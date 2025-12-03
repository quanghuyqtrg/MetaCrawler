import json
import logging
import os
from pathlib import Path
from typing import List, Tuple

import google.generativeai as genai
from dotenv import load_dotenv

from schemas import SearchResult  # NEW

log = logging.getLogger("metacrawler.gemini")

# 1) Load .env ở thư mục app/.env
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

masked_tail = GEMINI_API_KEY[-6:] if GEMINI_API_KEY else None
log.info(
    "[gemini] env loaded: has_key=%s tail=%s model=%s env_path=%s",
    bool(GEMINI_API_KEY),
    masked_tail,
    GEMINI_MODEL,
    ENV_PATH,
)

# Cấu hình cho bước rerank bằng LLM
RERANK_LLM_ENABLED = True           # bật/tắt rerank LLM
RERANK_LLM_MIN_SCORE = 0.35         # ngưỡng lọc: 0.0–1.0
RERANK_LLM_MAX_CANDIDATES = 20     # tối đa số bài gửi lên LLM để chấ

# 2) Khởi tạo model
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        _model = genai.GenerativeModel(GEMINI_MODEL)
        log.info("[gemini] init model=%s OK", GEMINI_MODEL)
    except Exception as e:
        log.error("[gemini] init model error: %s -> dùng fallback", e, exc_info=True)
        _model = None
else:
    _model = None
    log.warning("[gemini] GEMINI_API_KEY không có, luôn fallback")
    # Cấu hình cho bước rerank bằng LLM
    RERANK_LLM_ENABLED = True  # có thể tắt nếu cần
    RERANK_LLM_MIN_SCORE = 0.35  # 0.0–1.0, càng cao càng lọc gắt
    RERANK_LLM_MAX_CANDIDATES = 20  # tối đa số bài gửi lên LLM để chấm


def rerank_search_results_with_llm(
    name: str,
    object_type: str,
    short_description: str | None,
    language: str,
    search_query: str,
    results: List[SearchResult],
    max_results: int,
) -> List[SearchResult]:
    """
    Dùng Gemini để chấm điểm mức độ liên quan của từng kết quả search,
    sau đó sort + lọc lại, cắt còn tối đa max_results.

    Nếu có lỗi / model không sẵn sàng -> trả lại kết quả gốc (safety).
    """
    if not RERANK_LLM_ENABLED:
        return results[:max_results]

    if _model is None:
        log.warning("[gemini] rerank requested but _model is None -> skip")
        return results[:max_results]

    if not results:
        return []

    # Giới hạn số bài đưa lên LLM để đỡ tốn token
    max_candidates = min(len(results), RERANK_LLM_MAX_CANDIDATES)
    candidates = results[:max_candidates]

    # Chuẩn hóa dữ liệu đầu vào cho LLM
    items_payload = []
    for idx, item in enumerate(candidates):
        title = (getattr(item, "title", "") or "")
        desc = (getattr(item, "description", "") or "")
        items_payload.append(
            {
                "index": idx,                       # index trong danh sách candidates
                "title": title[:200],               # cắt ngắn cho đỡ tốn token
                "description": desc[:400],
            }
        )

    lang_label = "Tiếng Việt" if (language or "").startswith("vi") else (language or "English")

    if short_description:
        hint_block = f"- Mô tả ngắn của người dùng: {short_description.strip()}"
    else:
        hint_block = "- Mô tả ngắn của người dùng: (không có, hãy suy luận bối cảnh hợp lý từ tên và query)."

    items_json = json.dumps(items_payload, ensure_ascii=False)

    prompt = f"""
Bạn là trợ lý nghiên cứu, nhiệm vụ là CHẤM ĐIỂM MỨC ĐỘ LIÊN QUAN của các bài báo
đối với chủ đề sau và TRẢ VỀ DUY NHẤT MỘT ĐỐI TƯỢNG JSON HỢP LỆ.

Bối cảnh:
- Tên đối tượng: {name}
- Loại đối tượng: {object_type} (person, event, topic)
- Ngôn ngữ: {lang_label}
- Câu truy vấn tìm kiếm đã sử dụng: {search_query}
{hint_block}

Danh sách kết quả tìm kiếm (mỗi phần tử có 'index', 'title', 'description'):

{items_json}

Nhiệm vụ:
- Đánh giá mức độ liên quan của từng kết quả đến đúng đối tượng/chủ đề ở trên.
- Chỉ xem là "liên quan cao" nếu bài viết tập trung vào đối tượng/chủ đề này
  hoặc sự kiện/chủ đề trực tiếp liên quan.
- Các bài chỉ nhắc qua loa, hoặc nói về chủ đề khác, thì coi là liên quan thấp.

Yêu cầu JSON:
Trả về đúng cấu trúc:

{{
  "items": [
    {{
      "index": <số nguyên, giống index trong danh sách đầu vào>,
      "score": <một số từ 0.0 đến 1.0, càng cao càng liên quan>
    }},
    ...
  ]
}}

QUAN TRỌNG:
- Không thêm text ngoài JSON.
- Không bỏ sót bất kỳ index nào trong đầu vào.
- Không tạo index mới.
""".strip()

    try:
        resp = _model.generate_content(
            prompt,
            generation_config={
                "max_output_tokens": 512,
                "temperature": 0.2,
            },
        )
    except Exception as e:
        log.error("[gemini] rerank generate_content error: %s", e, exc_info=True)
        return results[:max_results]

    # Lấy text từ response
    try:
        raw_text = (getattr(resp, "text", "") or "").strip()
    except Exception as e:
        log.warning("[gemini] rerank resp.text error: %s", e)
        raw_text = ""

    if not raw_text:
        log.error("[gemini] rerank empty resp.text -> skip rerank")
        return results[:max_results]

    log.info("[gemini] rerank_raw_preview=%r", raw_text[:200].replace("\n", " "))

    # Cắt phần JSON trong text (phòng khi model thêm rác)
    try:
        start = raw_text.index("{")
        end = raw_text.rindex("}") + 1
        json_str = raw_text[start:end]
    except ValueError:
        json_str = raw_text

    try:
        data = json.loads(json_str)
    except Exception as e:
        log.error(
            "[gemini] rerank JSON parse error: %s, json_str_preview=%r",
            e,
            json_str[:200],
        )
        return results[:max_results]

    items_raw = data.get("items") or []
    if not isinstance(items_raw, list):
        log.error("[gemini] rerank 'items' không phải list -> skip rerank")
        return results[:max_results]

    # Map index -> score
    scored: dict[int, float] = {}
    for entry in items_raw:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        score = entry.get("score")
        try:
            idx_int = int(idx)
        except Exception:
            continue
        if idx_int < 0 or idx_int >= max_candidates:
            continue
        try:
            score_f = float(score)
        except Exception:
            continue

        # Clamp score về [0, 1]
        if score_f < 0.0:
            score_f = 0.0
        if score_f > 1.0:
            score_f = 1.0

        prev = scored.get(idx_int)
        if prev is None or score_f > prev:
            scored[idx_int] = score_f

    if not scored:
        log.warning("[gemini] rerank không tạo được score hợp lệ -> skip rerank")
        return results[:max_results]

    # Sắp xếp theo score giảm dần
    pairs = sorted(scored.items(), key=lambda x: x[1], reverse=True)

    filtered: List[SearchResult] = []
    for idx_int, score_f in pairs:
        if score_f < RERANK_LLM_MIN_SCORE:
            continue

        item = candidates[idx_int]

        # Gắn score vào SearchResult để trả ra ngoài
        try:
            item.score = score_f
        except Exception:
            # Trong trường hợp cực đoan (schema không có field) thì bỏ qua
            pass

        filtered.append(item)
        if len(filtered) >= max_results:
            break

    if not filtered:
        log.info(
            "[gemini] rerank: tất cả score < %.2f -> dùng kết quả gốc",
            RERANK_LLM_MIN_SCORE,
        )
        return results[:max_results]

    # Log chi tiết top N để debug
    try:
        top_detail = ", ".join(
            f"{idx}:{scored[idx]:.2f}"
            for idx, _ in pairs[: min(len(pairs), 10)]
        )
        log.info("[gemini] rerank_top detail=%s", top_detail)
    except Exception:
        pass

    log.info(
        "[gemini] rerank: used=%d/%d candidates, kept=%d, min_score=%.2f, max_score=%.2f",
        len(candidates),
        len(results),
        len(filtered),
        min(s for _, s in pairs),
        max(s for _, s in pairs),
    )
    return filtered


def _build_default_summary(
    name: str,
    object_type: str,
    language: str = "vi",
    short_description: str | None = None,
) -> Tuple[str, List[str], str]:
    """
    Tạo overview / key_points / search_query mặc định
    dùng khi:
    - Gemini không trả đủ field, hoặc
    - cần template fallback.

    Không log ở đây để tránh gây hiểu nhầm.
    """
    name = (name or "").strip()
    object_type = (object_type or "").strip().lower()
    language = (language or "vi").strip().lower()
    short_description = (short_description or "").strip()

    if language.startswith("vi"):
        # Vietnamese default
        if object_type == "person":
            overview = (
                f"{name} là một nhân vật đáng chú ý, được quan tâm trong bối cảnh truyền thông và công chúng. "
                f"Thông tin về tiểu sử, sự nghiệp và những điểm nổi bật liên quan đến {name} "
                "là cơ sở quan trọng để hiểu rõ hơn về ảnh hưởng và vị thế của họ."
            )
            key_points = [
                f"Thông tin cơ bản và tiểu sử của {name}",
                "Các cột mốc quan trọng trong sự nghiệp",
                "Những thành tựu, tranh cãi hoặc sự kiện nổi bật liên quan",
                "Bối cảnh đội bóng, tổ chức hoặc lĩnh vực hoạt động",
            ]
            search_query = f"{name} tiểu sử sự nghiệp thành tựu tranh cãi"
        elif object_type == "event":
            overview = (
                f"{name} là một sự kiện đáng chú ý, thu hút sự quan tâm của công chúng và truyền thông. "
                "Các thông tin liên quan đến bối cảnh, diễn biến chính và tác động của sự kiện là rất quan trọng."
            )
            key_points = [
                "Bối cảnh hình thành sự kiện",
                "Các diễn biến chính và mốc thời gian quan trọng",
                "Tác động đối với các bên liên quan",
                "Phản ứng của dư luận, truyền thông hoặc chuyên gia",
            ]
            search_query = f"{name} bối cảnh diễn biến tác động phản ứng"
        else:  # topic
            overview = (
                f"{name} là một chủ đề quan trọng, liên quan đến nhiều khía cạnh khác nhau. "
                "Việc nắm bắt các khái niệm cốt lõi, bối cảnh ứng dụng và tranh luận xung quanh chủ đề này "
                "giúp hiểu sâu hơn và tìm kiếm thông tin hiệu quả."
            )
            key_points = [
                "Định nghĩa và khái niệm cốt lõi",
                "Bối cảnh lịch sử hoặc thực tiễn liên quan",
                "Các quan điểm, trường phái hoặc tranh luận chính",
                "Ứng dụng thực tế và xu hướng phát triển",
            ]
            search_query = f"{name} định nghĩa bối cảnh ứng dụng tranh luận"

        # Nếu có short_description, gắn thêm vào overview cho sắc nét hơn
        if short_description:
            overview = f"{overview} Bối cảnh cụ thể: {short_description.strip()}."

    else:
        # English default
        if object_type == "person":
            overview = (
                f"{name} is a notable public figure whose background, career and key achievements "
                "are relevant for understanding their influence and public perception."
            )
            key_points = [
                f"Basic biographical information about {name}",
                "Key milestones in their career",
                "Major achievements, controversies or notable events",
                "Context of their team, organization or field",
            ]
            search_query = f"{name} biography career achievements controversies"
        elif object_type == "event":
            overview = (
                f"{name} is a noteworthy event that has attracted public and media attention. "
                "Understanding its context, main developments and impact is important."
            )
            key_points = [
                "Background and context of the event",
                "Key developments and timeline",
                "Impact on stakeholders",
                "Reactions from the public, media or experts",
            ]
            search_query = f"{name} background developments impact reactions"
        else:
            overview = (
                f"{name} is an important topic with multiple dimensions. "
                "Capturing its core concepts, context and debates helps to search and reason about it effectively."
            )
            key_points = [
                "Core definitions and concepts",
                "Historical or practical context",
                "Main perspectives, schools of thought or debates",
                "Real-world applications and emerging trends",
            ]
            search_query = f"{name} definition context applications debates"

        if short_description:
            overview = f"{overview} Specific context: {short_description.strip()}."

    return overview, key_points, search_query


def _fallback_summary(
    name: str,
    object_type: str,
    language: str = "vi",
    short_description: str | None = None,
) -> Tuple[str, List[str], str]:
    """
    HARD fallback: chỉ dùng khi Gemini lỗi/generate không dùng được.

    Có log rõ ràng để phân biệt với trường hợp chỉ dùng default template.
    """
    overview, key_points, search_query = _build_default_summary(
        name=name,
        object_type=object_type,
        language=language,
        short_description=short_description,
    )

    # Ưu tiên dùng short_description để làm rõ ngữ cảnh khi phải fallback
    user_hint = (short_description or "").strip()
    if user_hint:
        merged = f"{name} {user_hint}".strip()
        # Giới hạn độ dài query ở mức hợp lý, tránh quá dài
        if len(merged) <= 200:
            search_query = merged
        else:
            search_query = merged[:200]

    log.warning(
        "[gemini] HARD FALLBACK summary name=%s type=%s lang=%s search_query=%r",
        name,
        object_type,
        language,
        search_query,
    )
    return overview, key_points, search_query

def generate_topic_summary(
    name: str,
    object_type: str,
    short_description: str | None = None,
    language: str = "vi",
) -> Tuple[str, List[str], str]:
    """
    Trả về:
      - description: đoạn tóm tắt 2–3 câu (cho UI)
      - key_points: list bullet (3–5 mục)
      - search_query: câu truy vấn ngắn gọn dùng cho SearXNG
    """
    if _model is None:
        return _fallback_summary(name, object_type, language, short_description)

    lang_label = "Tiếng Việt" if language.startswith("vi") else language
    user_hint = (short_description or "").strip()

    if user_hint:
        hint_block = f"- Mô tả ngắn do người dùng cung cấp: {user_hint}"
    else:
        hint_block = (
            "- Mô tả ngắn do người dùng cung cấp: (không có, hãy suy luận bối cảnh hợp lý)."
        )

    prompt = f"""
    Bạn là trợ lý nghiên cứu. Hãy phân tích nhanh về đối tượng dưới đây và TRẢ VỀ DUY NHẤT MỘT ĐỐI TƯỢNG JSON HỢP LỆ.

    Đối tượng:
    - Tên: {name}
    - Loại: {object_type} (person, event, topic)
    {hint_block}

    Hướng dẫn sinh "search_query":
    - Luôn bám sát mục đích TÌM KIẾM TRÊN WEB.
    - Luôn chứa tên đối tượng (ví dụ: {name}).
    - Nếu có mô tả ngắn, hãy tận dụng để thêm các thực thể quan trọng (đối thủ, giải đấu, năm, địa điểm, lĩnh vực...).
    - Không dùng câu văn đầy đủ; tập trung 3–10 từ khóa quan trọng, dễ copy dán vào công cụ tìm kiếm.
    - Tránh các từ mơ hồ như "thông tin", "bài viết", "giới thiệu", "tổng hợp".

    Nếu object_type = "person":
    - Tập trung vào bối cảnh chính mà người dùng quan tâm: tiểu sử, sự nghiệp, thành tích, HOẶC sự kiện cụ thể liên quan tới mô tả ngắn (ví dụ một trận đấu, scandal, giải đấu).
    Nếu object_type = "event":
    - Tập trung vào tên sự kiện, mốc thời gian, địa điểm, bên liên quan và bối cảnh thực tế.
    Nếu object_type = "topic":
    - Tập trung vào khái niệm, lĩnh vực, bối cảnh ứng dụng và các từ khóa quan trọng liên quan.

    Yêu cầu JSON:

    {{
      "overview": "đoạn tóm tắt 2-3 câu, tối đa khoảng 400 ký tự, ngắn gọn, khách quan, ngôn ngữ: {lang_label}",
      "key_points": [
        "3-5 gạch đầu dòng chính, mỗi mục < 80 ký tự, mô tả các khía cạnh quan trọng",
        "Ví dụ: Điểm nổi bật chính, bối cảnh liên quan, tác động, các quan điểm đa chiều cần xem xét"
      ],
      "search_query": "câu truy vấn ngắn (<= 360 ký tự) dùng để tìm kiếm thông tin LIÊN QUAN NHẤT về đối tượng, tận dụng bối cảnh mô tả ngắn nếu có"
    }}

    QUAN TRỌNG:
    - Chỉ trả JSON, KHÔNG thêm giải thích, không thêm text bên ngoài.
    - Ngôn ngữ: {lang_label}.
    """

    log.info(
        "[gemini] generate_topic_summary name=%s type=%s lang=%s",
        name,
        object_type,
        language,
    )

    try:
        resp = _model.generate_content(
            prompt,
            generation_config={
                "max_output_tokens": 600,
                "temperature": 0.4,
            },
        )
    except Exception as e:
        log.error("[gemini] generate_content error: %s", e, exc_info=True)
        return _fallback_summary(name, object_type, language, short_description)

    # Lấy text (2.5 flash-lite hiện tại trả text bình thường)
    try:
        raw_text = (getattr(resp, "text", "") or "").strip()
    except Exception as e:
        log.warning("[gemini] resp.text error: %s", e)
        raw_text = ""

    if not raw_text:
        log.error("[gemini] empty resp.text, fallback")
        return _fallback_summary(name, object_type, language, short_description)

    log.info("[gemini] raw_text_preview=%r", raw_text[:200].replace("\n", " "))

    # Cố gắng cắt đoạn JSON từ text (phòng khi model lỡ thêm rác)
    try:
        start = raw_text.index("{")
        end = raw_text.rindex("}") + 1
        json_str = raw_text[start:end]
    except ValueError:
        json_str = raw_text

    try:
        data = json.loads(json_str)
    except Exception as e:
        log.error("[gemini] JSON parse error: %s, json_str_preview=%r", e, json_str[:200])
        return _fallback_summary(name, object_type, language, short_description)

    overview = (data.get("overview") or "").strip()
    overview_raw = overview  # Lưu lại mô tả gốc từ Gemini để log/debug
    key_points_raw = (data.get("key_points") or [])
    search_query = (data.get("search_query") or "").strip()

    if not isinstance(key_points_raw, list):
        key_points_raw = [str(key_points_raw)]

    key_points = [str(x).strip() for x in key_points_raw if str(x).strip()]



    # Bổ sung nếu thiếu field bằng default template (không phải hard fallback)
    fb_overview, fb_points, fb_query = _build_default_summary(
        name,
        object_type,
        language,
        short_description,
    )

    if not overview:
        overview = fb_overview
    if not key_points:
        key_points = fb_points
    if not search_query:
        search_query = fb_query

    # --- NEW: Ép short_description xuất hiện trong overview nếu chưa có ---
    if short_description:
        sd = short_description.strip()
        if sd and sd.lower() not in overview.lower():
            if language.startswith("vi"):
                suffix = f"\n\nBối cảnh cụ thể: {sd}."
            else:
                suffix = f"\n\nSpecific context: {sd}."
            overview = (overview.rstrip() + " " + suffix).strip()

    # --- NEW: Ép short_description dính vào search_query để tăng độ bám ngữ cảnh ---
    user_hint = (short_description or "").strip()
    base_query = (search_query or "").strip()

    if user_hint:
        # Nếu hint chưa nằm trong query thì gộp thêm
        if user_hint.lower() not in base_query.lower():
            merged = f"{base_query} {user_hint}".strip() if base_query else user_hint
            search_query = merged
        else:
            search_query = base_query
    else:
        search_query = base_query

    # Làm gọn search_query: bỏ xuống dòng, giới hạn độ dài
    search_query = " ".join(search_query.split())
    if len(search_query) > 220:
        search_query = search_query[:220]

    # Log info tổng quan
    log.info(
        "[gemini] summary_ready overview_len=%d key_points=%d search_query=%r",
        len(overview),
        len(key_points),
        search_query,
    )

    # Log mô tả gốc từ Gemini (không chỉnh sửa), bỏ xuống dòng cho dễ đọc log
    if overview_raw:
        log.info(
            "[gemini] overview_raw=%r",
            overview_raw.replace("\n", " "),
        )

    # Log mô tả cuối cùng sau khi đã ép short_description, fallback, v.v.
    if overview:
        log.info(
            "[gemini] overview_final=%r",
            overview.replace("\n", " "),
        )

    return overview, key_points, search_query


def summarize_crawled_data(
    name: str,
    object_type: str,
    crawled_contents: List[str],
    language: str = "vi",
) -> Tuple[str, List[str]]:
    """
    Dùng Gemini để tổng hợp thông tin từ nội dung đã crawl (RAG).
    Trả về: (overview, key_points)
    """
    if not crawled_contents or _model is None:
        return "", []

    # Giới hạn context: Lấy tối đa 5 bài, mỗi bài lấy 4000 ký tự đầu
    # Để tránh quá tải token và chi phí
    # Lọc bỏ các bài quá ngắn (< 200 ký tự) vì có thể là lỗi/rác
    valid_contents = [c for c in crawled_contents if c and len(c.strip()) > 200]
    limited_contents = [c[:4000] for c in valid_contents[:5]]
    
    if not limited_contents:
        log.warning("[gemini] summarize_crawled_data: no valid content > 200 chars")
        return "", []

    context_text = "\n\n---\n\n".join(limited_contents)
    
    lang_label = "Tiếng Việt" if language.startswith("vi") else language

    prompt = f"""
    Bạn là chuyên gia phân tích thông tin. Dựa vào các văn bản được cung cấp dưới đây, hãy viết một bản tóm tắt tổng quan về đối tượng:

    Đối tượng: {name} ({object_type})
    Ngôn ngữ đầu ra: {lang_label}

    Dữ liệu tham khảo (Context):
    {context_text}

    Yêu cầu đầu ra (JSON):
    {{
      "overview": "Đoạn văn tổng quan (khoảng 5-8 câu) đúc kết thông tin quan trọng nhất. Phải tuyệt đối trung thực với dữ liệu, kiểm chứng chéo các thông tin mâu thuẫn (chọn thông tin xuất hiện nhiều nhất hoặc từ nguồn uy tín). Tránh các câu văn sáo rỗng, khen ngợi chung chung (ví dụ: 'nguồn cảm hứng', 'tấm gương sáng') trừ khi có chi tiết cụ thể.",
      "key_points": [
        "5-7 điểm chính nổi bật nhất, ưu tiên các sự kiện, số liệu, mốc thời gian cụ thể. Tránh thông tin mơ hồ."
      ]
    }}
    
    Lưu ý:
    - Nếu dữ liệu tham khảo không đủ thông tin, hãy nói rõ trong overview.
    - Chỉ trả về JSON hợp lệ.
    """

    log.info("[gemini] summarize_crawled_data name=%s docs=%d", name, len(limited_contents))

    try:
        resp = _model.generate_content(
            prompt,
            generation_config={
                "max_output_tokens": 1024,
                "temperature": 0.2,
            },
        )
        raw_text = (getattr(resp, "text", "") or "").strip()
        
        # Extract JSON
        try:
            start = raw_text.index("{")
            end = raw_text.rindex("}") + 1
            json_str = raw_text[start:end]
            data = json.loads(json_str)
            
            overview = data.get("overview", "")
            key_points = data.get("key_points", [])
            
            return overview, key_points
        except Exception:
            log.warning("[gemini] summarize_crawled_data JSON parse fail, raw=%r", raw_text[:200])
            return "", []
            
    except Exception as e:
        log.error("[gemini] summarize_crawled_data error: %s", e)
        return "", []


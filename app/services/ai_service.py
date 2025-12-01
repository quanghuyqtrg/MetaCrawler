import json
import logging
import os
from pathlib import Path
from typing import List, Tuple

import google.generativeai as genai
from dotenv import load_dotenv

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
                "max_output_tokens": 400,
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
    if len(search_query) > 200:
        search_query = search_query[:300]

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

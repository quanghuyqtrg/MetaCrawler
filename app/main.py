import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from schemas import ResearchRequest, ResearchResponse
from services.ai_service import generate_topic_summary
from services.searxng_service import search_web_with_searxng

# Cấu hình log chung
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("metacrawler.api")

app = FastAPI(
    title="MetaCrawler AI Research",
    description="Service sinh mô tả bằng Gemini và tìm kiếm web qua SearXNG",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # production thì khóa lại domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/research", response_model=ResearchResponse)
def run_research(payload: ResearchRequest):
    """
    1. Từ name + object_type (+ short_description) -> Gemini sinh summary + key_points + search_query.
    2. Dùng search_query (ngắn) cho SearXNG.
    3. Trả về summary (cho UI) + kết quả search (cho crawler).
    """
    log.info(
        "[api] /api/research name=%s type=%s lang=%s max_results=%d",
        payload.name,
        payload.object_type,
        payload.language,
        payload.max_results,
    )
    if payload.short_description:
        log.info(
            "[api] short_description=%r",
            payload.short_description[:300],
        )

    # 1) Gemini: summary + key_points + search_query
    try:
        description, key_points, search_query = generate_topic_summary(
            name=payload.name,
            object_type=payload.object_type,
            short_description=payload.short_description,
            language=payload.language,
        )
        log.info(
            "[api] description_len=%d key_points=%d search_query=%r",
            len(description or ""),
            len(key_points),
            search_query,
        )
    except Exception as e:
        log.error("[api] Gemini error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Lỗi Gemini: {e}")

    # 2) SearXNG: chỉ dùng search_query
    try:
        results = search_web_with_searxng(
            query=search_query,
            language=payload.language,
            max_results=payload.max_results,
        )
        log.info("[api] searxng_results=%d", len(results))
    except Exception as e:
        log.error("[api] SearXNG error: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Lỗi gọi SearXNG: {e}")

    # 3) Trả về cho frontend + crawler
    return ResearchResponse(
        name=payload.name,
        object_type=payload.object_type,
        short_description=payload.short_description,
        description=description,
        key_points=key_points,
        search_query=search_query,
        search_results=results,
        crawler_payload=results,
    )

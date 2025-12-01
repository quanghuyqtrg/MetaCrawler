from typing import List
import logging
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from schemas import SearchResult

log = logging.getLogger("metacrawler.searxng")

# Load .env ở thư mục app/.env
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)

SEARXNG_BASE_URL = os.getenv("SEARXNG_BASE_URL", "http://localhost:9090")
SEARXNG_DEFAULT_LANGUAGE = os.getenv("SEARXNG_DEFAULT_LANGUAGE", "vi")
SEARXNG_DEFAULT_CATEGORIES = os.getenv("SEARXNG_DEFAULT_CATEGORIES", "general")
SEARXNG_TIMEOUT = int(os.getenv("SEARXNG_TIMEOUT", "20"))


def search_web_with_searxng(
    query: str,
    language: str,
    max_results: int,
    categories: str | None = None,
) -> List[SearchResult]:
    """
    Gọi SearXNG /search?format=json và chuẩn hóa kết quả.
    """
    base_url = SEARXNG_BASE_URL.rstrip("/")
    url = f"{base_url}/search"

    params = {
        "q": query,
        "format": "json",
        "language": language or SEARXNG_DEFAULT_LANGUAGE,
        "categories": categories or SEARXNG_DEFAULT_CATEGORIES,
    }

    log.info(
        "[searxng] search url=%s lang=%s max_results=%d q_preview=%r",
        url,
        params["language"],
        max_results,
        (query or "")[:80].replace("\n", " "),
    )

    resp = requests.get(url, params=params, timeout=SEARXNG_TIMEOUT)
    log.info("[searxng] http_status=%s", resp.status_code)
    resp.raise_for_status()

    data = resp.json()
    raw_results = data.get("results", []) or []

    normalized: List[SearchResult] = []

    for item in raw_results[: max_results]:
        title = item.get("title") or ""
        link = item.get("url") or ""
        description = item.get("content") or None
        published_date = item.get("publishedDate") or item.get("published") or None

        if not link:
            continue

        normalized.append(
            SearchResult(
                title=title,
                url=link,
                description=description,
                published_date=published_date,
            )
        )

    log.info(
        "[searxng] raw_results=%d normalized=%d",
        len(raw_results),
        len(normalized),
    )

    return normalized

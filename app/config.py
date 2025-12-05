from typing import Literal, List, Optional
from pydantic import BaseModel, Field, HttpUrl


class ResearchRequest(BaseModel):
    name: str = Field(..., description="Tên nhân vật / sự kiện / chủ đề")
    object_type: Literal["person", "event", "topic"] = Field(
        "topic", description="Loại đối tượng: person | event | topic"
    )
    language: str = Field(
        "vi",
        description="Mã ngôn ngữ ưu tiên khi tìm kiếm (vd: vi, en)",
    )
    max_results: int = Field(
        10, ge=1, le=50, description="Số kết quả tối đa lấy từ SearXNG"
    )


class SearchResult(BaseModel):
    title: str
    url: HttpUrl | str
    description: Optional[str] = None
    published_date: Optional[str] = None



# Jina AI API Key (optional, if not provided will fallback to local extraction)
import os
JINA_API_KEY = os.getenv("JINA_API_KEY", "")

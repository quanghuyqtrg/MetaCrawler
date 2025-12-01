from typing import Literal, List, Optional
from pydantic import BaseModel, Field, HttpUrl


class ResearchRequest(BaseModel):
    name: str = Field(..., description="Tên nhân vật / sự kiện / chủ đề")
    object_type: Literal["person", "event", "topic"] = Field(
        "topic",
        description="Loại đối tượng: person | event | topic",
    )
    short_description: Optional[str] = Field(
        None,
        description="Mô tả ngắn do người dùng nhập (tùy chọn, dùng làm bối cảnh cho LLM)",
    )
    language: str = Field(
        "vi",
        description="Mã ngôn ngữ ưu tiên khi tìm kiếm (vd: vi, en)",
    )
    max_results: int = Field(
        10,
        ge=1,
        le=50,
        description="Số kết quả tối đa lấy từ SearXNG",
    )


class SearchResult(BaseModel):
    title: str
    url: HttpUrl | str
    description: Optional[str] = None
    published_date: Optional[str] = None  # để string, crawler tự xử lý
    score: Optional[float] = Field(None, description="Điểm liên quan sau bước rerank (0.0–1.0); None nếu chưa rerank")
    content: Optional[str] = None         # nội dung bài viết (nếu crawl được)


class ResearchResponse(BaseModel):
    name: str
    object_type: str
    short_description: Optional[str] = None  # echo lại cho UI/crawler
    description: str                       # mô tả chi tiết (overview)
    key_points: List[str]                  # 3–5 bullet
    search_query: str                      # query ngắn cho SearXNG
    search_results: List[SearchResult]

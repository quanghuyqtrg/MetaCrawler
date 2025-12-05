import asyncio
import logging
import json
from typing import List, Optional, Dict, Any

import httpx
import trafilatura
from fake_useragent import UserAgent
from readability import Document
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from markdownify import markdownify as md

from schemas import CrawlResult

log = logging.getLogger(__name__)

# Cấu hình timeout và limit
TIMEOUT_SECONDS = 10

def get_user_agent_headers():
    """
    Safe UserAgent generation with fallback
    """
    try:
        from fake_useragent import UserAgent
        # Fallback string
        fallback = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ua = UserAgent(fallback=fallback)
        return {"User-Agent": ua.random}
    except Exception:
         # Hard fallback if library really fails
        return {"User-Agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}


import socket
from urllib.parse import urlparse
import ipaddress

def validate_url(url: str) -> None:
    """
    Kiểm tra tính hợp lệ và an toàn của URL (chống SSRF).
    1. Chỉ cho phép scheme http/https.
    2. Chặn private IP / loopback / link-local.
    3. Chặn localhost.
    Lưu ý: Cách này resolve DNS tại thời điểm check, vẫn có rủi ro DNS rebinding nhưng cơ bản là đủ cho nhu cầu.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid scheme: {parsed.scheme}")
    
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid hostname")
        
    try:
        # Resolve IP
        ip_str = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(ip_str)
        
        # Check IP ranges
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise ValueError(f"Blocked access to private/local IP: {ip_str} ({hostname})")
            
        # Optional: Chặn cụ thể các dải mây (aws metadata) nếu cần
        # if str(ip) == "169.254.169.254": raise ...
        
    except socket.gaierror:
        raise ValueError(f"Could not resolve hostname: {hostname}")
    except ValueError as e:
        raise e
    except Exception as e:
        raise ValueError(f"URL validation error: {e}")


@retry(
    stop=stop_after_attempt(2),
    wait=wait_fixed(1),
    retry=retry_if_exception_type((httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError)),
    reraise=True
)
async def fetch_html(client: httpx.AsyncClient, url: str) -> str:
    """
    Tải HTML từ URL với retry và fake user-agent.
    """
    headers = get_user_agent_headers()
    response = await client.get(url, headers=headers, follow_redirects=True)
    response.raise_for_status()
    
    # Kiểm tra content-type
    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type:
        raise ValueError(f"Skipped: Content-Type is {content_type}, not text/html")
        
    return response.text


def extract_content(html: str, url: str) -> Dict[str, Any]:
    """
    Trích xuất nội dung dùng trafilatura và readability.
    So sánh kết quả để chọn bản markdown có nhiều ảnh nhất (tốt cho AI sinh chart).
    """
    # 1. Trafilatura: Metadata, Clean Text, Markdown (include_images=True)
    # Lấy JSON để có metadata & clean text
    json_result = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        include_images=True, 
        output_format="json",
        with_metadata=True
    )
    
    data = {}
    if json_result:
        try:
            data = json.loads(json_result)
        except Exception:
            pass

    # Lấy Markdown riêng từ Trafilatura
    traf_markdown = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        include_images=True,
        output_format="markdown",
        with_metadata=False
    ) or ""

    # 2. Readability + Markdownify (Fallback/Alternative)
    doc = Document(html)
    summary_html = doc.summary() 
    title = doc.title()
    
    # Convert HTML -> Markdown
    # strip=["a"] -> giữ lại thẻ a nếu cần, nhưng user quan trọng ảnh
    rich_markdown = md(summary_html, heading_style="ATX") or ""
    
    # 3. Decision Logic: Chọn markdown nào?
    # Đếm số thẻ ảnh ![](...)
    traf_imgs = traf_markdown.count("![")
    rich_imgs = rich_markdown.count("![")
    
    # Mặc định ưu tiên Trafilatura vì structure tốt hơn
    # Nhưng nếu Readability lấy được nhiều ảnh hơn đáng kể (vd > 1) thì dùng Readability
    if rich_imgs > traf_imgs:
        final_markdown = rich_markdown
    else:
        final_markdown = traf_markdown
        
    # Nếu cả 2 đều rỗng text (lỗi extract), fallback sang cái còn lại có text
    if not final_markdown.strip():
        final_markdown = rich_markdown if rich_markdown.strip() else traf_markdown

    # Metadata & Clean Text
    final_title = data.get("title") or title
    clean_text = data.get("text")
    if not clean_text:
        # Fallback clean text từ Readability
        import lxml.html
        try:
             clean_text = lxml.html.fromstring(summary_html).text_content().strip()
        except:
             clean_text = ""
             
    # Format Header cho content_markdown theo yêu cầu user
    # Title: ...
    # URL Source: ...
    # Published Time: ...
    # Markdown Content: ...
    pub_date = data.get("date") or "Unknown"
    source_url = url
    
    header_info = (
        f"Title: {final_title}\n\n"
        f"URL Source: {source_url}\n\n"
        f"Published Time: {pub_date}\n\n"
        f"Markdown Content:\n"
    )
    
    final_markdown_with_header = header_info + final_markdown

    return {
        "title": final_title,
        "description": data.get("description"),
        "content": clean_text,  
        "content_markdown": final_markdown_with_header, 
        "metadata": {
            "author": data.get("author"),
            "date": data.get("date"),
            "sitename": data.get("sitename"),
            "categories": data.get("categories"),
            "tags": data.get("tags"),
            "image": data.get("image"), 
        }
    }


from config import JINA_API_KEY

@retry(
    stop=stop_after_attempt(2),
    wait=wait_fixed(1),
    retry=retry_if_exception_type((httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError)),
    reraise=True
)
async def fetch_with_jina(client: httpx.AsyncClient, url: str) -> str:
    """
    Gọi Jina AI Reader API để lấy markdown.
    """
    jina_url = f"https://r.jina.ai/{url}"
    headers = {
        "Authorization": f"Bearer {JINA_API_KEY}",
        "X-Return-Format": "markdown"
    }
    # Jina timeout có thể cần lâu hơn chút
    response = await client.get(jina_url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text


async def process_url(client: httpx.AsyncClient, url: str) -> CrawlResult:
    """
    Xử lý 1 URL: 
    1. Validate URL (Security).
    2. Thử Jina AI (nếu có key).
    3. Fallback: fetch -> extract (Trafilatura/Readability).
    """
    try:
        validate_url(url)
    except ValueError as e:
        return CrawlResult(url=url, status="error", error_message=str(e))

    # Cách 1: Jina AI
    if JINA_API_KEY:
        try:
            # log.info(f"Trying Jina for {url}")
            md_content = await fetch_with_jina(client, url)
            
            # Simple Title Extraction (First line # Title)
            lines = md_content.strip().split('\n')
            title = "Unknown"
            if lines and lines[0].startswith('# '):
                title = lines[0][2:].strip()
            
            # Format Header (Jina doesn't give Date in headers usually, so Unknown or parse??)
            # Để đơn giản ta để Unknown hoặc None
            header_info = (
                f"Title: {title}\n\n"
                f"URL Source: {url}\n\n"
                f"Published Time: Unknown\n\n"
                f"Markdown Content:\n"
            )
            final_md = header_info + md_content
            
            # Content text (clean) -> strip markdown? 
            # Dùng markdown to text đơn giản hoặc để nguyên markdown
            # Trafilatura extract text thì tốt hơn, nhưng ở đây dùng Jina là chính
            # Ta có thể dùng md_content làm content tạm
            
            return CrawlResult(
                url=url,
                status="ok",
                title=title,
                description=None,
                content=md_content, # Jina return markdown as content text too? Or keep html free.
                content_markdown=final_md,
                metadata={"source": "jina"}
            )
            
        except Exception as e:
            log.warning(f"Jina failed for {url}: {e}. Fallback to local extraction.")
            # Fallback continues below...

    # Cách 2: Local Extraction (Fallback)
    try:
        html = await fetch_html(client, url)
        data = extract_content(html, url)
        
        # Cắt ngắn nếu quá dài
        content = data.get("content") or ""
        if len(content) > MAX_CONTENT_LENGTH:
            content = content[:MAX_CONTENT_LENGTH] + "...(truncated)"
            
        return CrawlResult(
            url=url,
            status="ok",
            title=data.get("title"),
            description=data.get("description"),
            content=content,
            content_markdown=data.get("content_markdown"),
            metadata=data.get("metadata")
        )
        
    except ValueError as ve:
        # Lỗi logic (vd content type sai)
        return CrawlResult(url=url, status="skipped", error_message=str(ve))
    except Exception as e:
        # Lỗi network hoặc parse
        return CrawlResult(url=url, status="error", error_message=str(e))


async def crawl_urls(urls: List[str], max_workers: int = 5) -> List[CrawlResult]:
    """
    Hàm chính: crawl danh sách URL song song.
    """
    limits = httpx.Limits(max_keepalive_connections=max_workers, max_connections=max_workers)
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, limits=limits) as client:
        tasks = [process_url(client, str(url)) for url in urls]
        results = await asyncio.gather(*tasks)
        return results

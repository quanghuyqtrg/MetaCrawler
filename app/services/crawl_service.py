import asyncio
import logging
import json
from typing import List, Optional, Dict, Any

import httpx
import trafilatura
from readability import Document
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from markdownify import markdownify as md

from schemas import CrawlResult

log = logging.getLogger(__name__)

# Cấu hình timeout và limit
TIMEOUT_SECONDS = 15
# MAX_CONTENT_LENGTH = 30000 
MAX_DOWNLOAD_SIZE = 5 * 1024 * 1024  # 5MB limit for HTML download

import random

# Optimized Static User Agents & Headers
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0'
]

def get_user_agent_headers() -> Dict[str, str]:
    """
    Return optimized headers with random UA to avoid blocking
    """
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }


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
        # Resolve ALL addresses (IPv4/IPv6) and block any non-public range
        addrinfos = socket.getaddrinfo(hostname, parsed.port or 80, proto=socket.IPPROTO_TCP)
        if not addrinfos:
            raise ValueError(f"Could not resolve hostname: {hostname}")
        for ai in addrinfos:
            ip_str = ai[4][0]
            ip = ipaddress.ip_address(ip_str)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                raise ValueError(f"Blocked access to private/local IP: {ip_str} ({hostname})")
            # Optional: block other sensitive ranges if needed
            # if str(ip) == "169.254.169.254": ...
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
    Tải HTML từ URL với streaming, size limit và xử lý redirect thủ công để check SSRF.
    """
    current_url = url
    headers = get_user_agent_headers()
    
    # Manual redirect handling (max 5 redirects)
    for _ in range(5):
        # Validate Current URL Before Fetching
        validate_url(current_url)
        
        # Stream request to check headers and size
        request = client.build_request("GET", current_url, headers=headers)
        response = await client.send(request, stream=True)
        
        # Handle Redirects
        if response.is_redirect:
            await response.aclose()
            next_url = response.headers.get("location")
            if not next_url:
                break
            # Handle relative URLs if needed, but httpx usually handles parsing. 
            # We assume abs url or let library help if we used follow_redirects=True (but we can't here safely)
            # Simple resolve:
            from urllib.parse import urljoin
            current_url = urljoin(current_url, next_url)
            continue
            
        # If not redirect, check status
        response.raise_for_status()
        
        # Check Content-Type
        content_type = response.headers.get("content-type", "").lower()
        if "text/html" not in content_type and "text/plain" not in content_type:
             await response.aclose()
             raise ValueError(f"Skipped: Content-Type is {content_type}")

        # Download with Size Limit
        body = b""
        async for chunk in response.aiter_bytes():
            body += chunk
            if len(body) > MAX_DOWNLOAD_SIZE:
                await response.aclose()
                raise ValueError(f"Aborted: Content size exceeded {MAX_DOWNLOAD_SIZE} bytes")
        
        await response.aclose()
        # Decode manually or let helper
        # We need text. Attempt decode
        charset = response.encoding or "utf-8"
        try:
            return body.decode(charset, errors="replace")
        except:
             return body.decode("utf-8", errors="replace")
             
    raise ValueError("Too many redirects")


def extract_content(html: str, url: str) -> Dict[str, Any]:
    """
    Trích xuất nội dung dùng trafilatura và readability.
    - Title/Desc: Lấy chéo từ nhiều nguồn (Meta tags > Trafilatura > Readability).
    - Content: Pure text (không ảnh).
    - Content_Markdown: Rich text (có ảnh).
    """
    import lxml.html
    from lxml import etree

    # 0. Parse HTML bằng lxml để lấy raw metadata
    try:
        tree = lxml.html.fromstring(html)
        
        # Helper lấy meta
        def get_meta(props):
            for p in props:
                # support property="..." or name="..."
                # xpath: //meta[@property='p' or @name='p']/@content
                res = tree.xpath(f"//meta[@property='{p}' or @name='{p}']/@content")
                if res:
                    return str(res[0]).strip()
            return None

        meta_title = get_meta(["og:title", "twitter:title"])
        meta_desc = get_meta(["og:description", "twitter:description", "description"])
        meta_image = get_meta(["og:image", "twitter:image"])
    except Exception:
        meta_title = meta_desc = meta_image = None
        tree = None

    # 1. Trafilatura:
    # 1a. Pure text (NO images) -> cho field 'content'
    clean_text = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        include_images=False, # STRICTLY NO IMAGES
        output_format="txt",
        with_metadata=False
    )

    # 1b. Struct & XML -> để lấy metadata khác của Trafilatura
    # (Dùng json output để lấy full fields)
    traf_json_str = trafilatura.extract(
        html,
        url=url,
        include_comments=False, 
        include_images=False,
        output_format="json",
        with_metadata=True
    )
    traf_data = {}
    if traf_json_str:
        try:
            traf_data = json.loads(traf_json_str)
        except:
            pass
            
    # 1c. Markdown (Images INCLUDED) -> cho field 'content_markdown'
    traf_markdown = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        include_images=True, # KEEP IMAGES
        output_format="markdown",
        with_metadata=False
    ) or ""

    # 2. Readability + Markdownify (Fallback/Alternative)
    doc = Document(html)
    summary_html = doc.summary() 
    readability_title = doc.title()
    
    # 3. Tổng hợp Title / Description / Metadata
    # Priority: Meta Tags > Trafilatura > Readability
    final_title = meta_title or traf_data.get("title") or readability_title or "No Title"
    
    # Description: Meta Tags > Trafilatura
    final_desc = meta_desc or traf_data.get("description") or None
    
    # 4. Content Logic
    # Dùng clean_text của Trafilatura làm gốc. Nếu fail thì fallback sang Readability.
    final_pure_content = clean_text
    
    if not final_pure_content:
        # Fallback lấy text từ readability
        try:
             final_pure_content = lxml.html.fromstring(summary_html).text_content().strip()
        except:
             final_pure_content = ""

    # Cleaning artifacts (Published time, authors often leak into start of text)
    # Simple heuristic regex replacement can be added here if needed, 
    # but Trafilatura generally handles this well in 'txt' mode.
    
    # 5. Content Markdown Logic
    # Tương tự cũ: so sánh ảnh để chọn bản rich nhất
    # Convert Readability HTML -> Markdown
    rich_markdown = md(summary_html, heading_style="ATX") or ""
    
    traf_imgs = traf_markdown.count("![")
    rich_imgs = rich_markdown.count("![")
    
    if rich_imgs > traf_imgs:
        final_markdown_body = rich_markdown
    else:
        final_markdown_body = traf_markdown
        
    if not final_markdown_body.strip():
        final_markdown_body = rich_markdown if rich_markdown.strip() else (final_pure_content or "")

    # Format Header cho markdown
    pub_date = traf_data.get("date") or "Unknown"
    
    header_info = (
        f"Title: {final_title}\n"
        f"URL Source: {url}\n"
        f"Published Time: {pub_date}\n\n"
        f"Markdown Content:\n"
    )
    final_markdown_with_header = header_info + final_markdown_body

    return {
        "title": final_title,
        "description": final_desc,
        "content": final_pure_content,  # CLEAN TEXT ONLY
        "content_markdown": final_markdown_with_header, # RICH WITH IMAGES
        "metadata": {
            "author": traf_data.get("author"),
            "date": pub_date,
            "sitename": traf_data.get("sitename"),
            "categories": traf_data.get("categories"),
            "tags": traf_data.get("tags"),
            "image": meta_image or traf_data.get("image"), 
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
    Xử lý 1 URL theo chiến lược Hybrid:
    1. Local Extraction (Priority for Title, Desc, Pure Content, Metadata).
    2. Jina AI (Priority for Markdown Content).
    
    Chạy song song 2 luồng để tối ưu tốc độ.
    """
    try:
        validate_url(url)
    except ValueError as e:
        return CrawlResult(url=url, status="error", error_message=str(e))

    # Task 1: Jina AI (Markdown)
    async def task_jina():
        if not JINA_API_KEY:
            return None
        try:
            return await fetch_with_jina(client, url)
        except Exception as e:
            log.warning(f"Jina failed for {url}: {e}")
            return None

    # Task 2: Local Extraction (HTML -> Metadata, Clean Text, Fallback Markdown)
    async def task_local():
        try:
            html = await fetch_html(client, url)
            return extract_content(html, url)
        except Exception as e:
            # Nếu fetch HTML lỗi thì coi như task local fail
            log.warning(f"Local fetch/extract failed for {url}: {e}")
            return e # Trả về exception để check sau

    # Chạy song song
    # return_exceptions=True để 1 bên chết bên kia vẫn sống
    results = await asyncio.gather(task_jina(), task_local(), return_exceptions=True)
    
    jina_res = results[0]
    local_res = results[1]

    # Kiểm tra kêt quả Local
    # local_res có thể là Dict (success), Exception (error), hoặc None (unknown)
    if isinstance(local_res, Exception):
        # Nếu local fail, ta kiểm tra xem Jina có cứu được không?
        # Nếu Jina có trả về markdown, ta có thể tạo result tạm từ Jina
        if isinstance(jina_res, str) and jina_res:
             log.info(f"Local fail, fallback to Jina for {url}")
             # Parse sơ title từ Jina markdown
             lines = jina_res.strip().split('\n')
             title = "Unknown"
             if lines and lines[0].startswith('# '):
                 title = lines[0][2:].strip()
                 
             header_info = (
                f"Title: {title}\n"
                f"URL Source: {url}\n"
                f"Published Time: Unknown\n\n"
                f"Markdown Content:\n"
             )
             return CrawlResult(
                url=url,
                status="ok",
                title=title,
                description=None,
                content=jina_res, # Jina text as content
                # content_markdown=header_info + jina_res,
                metadata={"source": "jina_fallback_only"}
            )
        else:
             # Cả 2 đều fail
             return CrawlResult(url=url, status="error", error_message=str(local_res))

    # Nếu code chạy tới đây, Local thành công (trả về dict)
    local_data: Dict[str, Any] = local_res
    
    # Merge Logic
    # 1. Title/Desc/Metadata: Ưu tiên Local (vì lxml lấy từ meta tags chuẩn hơn Jina tự đoán)
    # 2. Content: Ưu tiên Local (Pure text config)
    # 3. Markdown: Ưu tiên Jina (Rich & Clean Layout)
    
    final_title = local_data.get("title")
    final_desc = local_data.get("description")
    final_content = local_data.get("content") # Pure text
    final_metadata = local_data.get("metadata", {})
    
    # Xử lý Markdown
    if isinstance(jina_res, str) and jina_res.strip():
        # Có kết quả từ Jina -> Dùng làm content_markdown chính
        # Vẫn wrap header thống nhất
        pub_date = final_metadata.get("date") or "Unknown"
        header_info = (
            f"Title: {final_title}\n"
            f"URL Source: {url}\n"
            f"Published Time: {pub_date}\n\n"
            f"Markdown Content:\n"
        )
        final_markdown = header_info + jina_res
        final_metadata["markdown_source"] = "jina"
    else:
        # Jina fail/empty -> Fallback về Markdown của Local (Trafilatura)
        final_markdown = local_data.get("content_markdown")
        final_metadata["markdown_source"] = "local"
        
    return CrawlResult(
        url=url,
        status="ok",
        title=final_title,
        description=final_desc,
        content=final_content,
        # content_markdown=final_markdown,
        metadata=final_metadata
    )


async def crawl_urls(urls: List[str], max_workers: int = 5) -> List[CrawlResult]:
    """
    Hàm chính: crawl danh sách URL song song.
    """
    limits = httpx.Limits(max_keepalive_connections=max_workers, max_connections=max_workers)
    
    # Sử dụng Semaphore để giới hạn số lượng task chạy thực sự cùng lúc (logic level)
    sem = asyncio.Semaphore(max_workers)

    async def sem_process(c, u):
        async with sem:
            return await process_url(c, str(u))

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, limits=limits) as client:
        tasks = [sem_process(client, url) for url in urls]
        results = await asyncio.gather(*tasks)
        return results

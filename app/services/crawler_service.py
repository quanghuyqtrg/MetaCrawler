import asyncio
import logging
from typing import List, Dict, Optional

import trafilatura

log = logging.getLogger("metacrawler.crawler")

from curl_cffi import requests
from urllib.parse import urlparse

# 1. Domain Blacklist
JUNK_DOMAINS = {
    # Social Media
    "facebook.com", "www.facebook.com",
    "twitter.com", "www.twitter.com", "x.com",
    "instagram.com", "www.instagram.com",
    "tiktok.com", "www.tiktok.com",
    "linkedin.com", "www.linkedin.com",
    "pinterest.com", "www.pinterest.com",
    "reddit.com", "www.reddit.com",
    
    # Video/Media
    "youtube.com", "www.youtube.com",
    "vimeo.com", "www.vimeo.com",
    "dailymotion.com", "www.dailymotion.com",
    
    # E-commerce
    "shopee.vn", "shopee.com",
    "lazada.vn", "lazada.com",
    "tiki.vn",
    "amazon.com", "www.amazon.com",
    "ebay.com", "www.ebay.com",
    
    # Tech/Code (unless specifically searching for code, these are usually not good for general summaries)
    "github.com", "www.github.com",
    "gitlab.com", "www.gitlab.com",
}

# 2. File Extension Filter
IGNORED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".7z", ".tar", ".gz",
    ".exe", ".apk", ".dmg", ".iso",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp3", ".mp4", ".wav", ".avi"
}

# 3. URL Pattern Filter
IGNORED_PATHS = [
    "/login", "/signin", "/signup", "/register",
    "/cart", "/checkout", "/basket",
    "/account", "/profile", "/user",
    "/search", "/find",
]

def is_valid_url(url: str) -> bool:
    """
    Kiểm tra xem URL có hợp lệ để crawl không.
    Lọc bỏ:
    - Domain rác (MXH, TMĐT...)
    - File không phải HTML (PDF, ZIP...)
    - Các trang chức năng (Login, Cart...)
    """
    if not url:
        return False
        
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        path = parsed.path.lower()
        
        # 1. Check Domain
        # Xử lý www. hoặc subdomain
        # Đơn giản nhất: check xem domain có kết thúc bằng junk domain không
        # VD: m.facebook.com ends with facebook.com -> True
        for junk in JUNK_DOMAINS:
            if domain == junk or domain.endswith("." + junk):
                return False
                
        # 2. Check Extension
        for ext in IGNORED_EXTENSIONS:
            if path.endswith(ext):
                return False
                
        # 3. Check Path Patterns
        for bad_path in IGNORED_PATHS:
            if bad_path in path:
                return False
                
        return True
        
    except Exception:
        return False

def _fetch_single_url(url: str) -> Optional[str]:
    """
    Hàm đồng bộ để tải và extract text từ 1 URL.
    Dùng curl_cffi để giả lập browser, tránh bị chặn (SSL/Anti-bot).
    """
    try:
        # impersonate="chrome" giúp vượt qua TLS fingerprinting
        resp = requests.get(
            url, 
            impersonate="chrome", 
            timeout=15,
            headers={
                "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7"
            }
        )
        
        if resp.status_code == 200:
            # Dùng trafilatura để extract text từ HTML
            text = trafilatura.extract(resp.text, include_comments=False, include_tables=False)
            return text
        else:
            log.warning(f"Error crawling {url}: status_code={resp.status_code}")
    except Exception as e:
        log.warning(f"Error crawling {url}: {e}")
    return None

async def crawl_urls(urls: List[str]) -> Dict[str, Optional[str]]:
    """
    Crawl song song danh sách URL.
    Trả về dict {url: content}.
    """
    loop = asyncio.get_running_loop()
    tasks = []
    
    for url in urls:
        # Trafilatura là thư viện đồng bộ, nên cần chạy trong executor
        tasks.append(loop.run_in_executor(None, _fetch_single_url, url))
        
    results = await asyncio.gather(*tasks)
    
    return {url: content for url, content in zip(urls, results)}

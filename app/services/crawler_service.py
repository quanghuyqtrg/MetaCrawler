import asyncio
import logging
from typing import List, Dict, Optional

import trafilatura

log = logging.getLogger("metacrawler.crawler")

import requests
import urllib3

# Tắt cảnh báo SSL không an toàn
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def _fetch_single_url(url: str) -> Optional[str]:
    """
    Hàm đồng bộ để tải và extract text từ 1 URL.
    Dùng requests để kiểm soát tốt hơn về SSL, Timeout và Headers.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    try:
        # verify=False để bỏ qua lỗi SSL trong môi trường Docker/Proxy
        resp = requests.get(url, headers=headers, timeout=30, verify=False)
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

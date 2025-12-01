import asyncio
import logging
from typing import List, Dict, Optional

import trafilatura

log = logging.getLogger("metacrawler.crawler")

def _fetch_single_url(url: str) -> Optional[str]:
    """
    Hàm đồng bộ để tải và extract text từ 1 URL.
    Chạy trong thread pool để không block event loop.
    """
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            return text
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

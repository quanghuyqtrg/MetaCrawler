import asyncio
import logging
import sys
import os

# Add current dir to sys.path to allow imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.crawl_service import process_url
import httpx

# Logging setup
logging.basicConfig(level=logging.INFO)

async def main():
    test_url = "https://vnexpress.net/chu-tich-quoc-hoi-tran-thanh-man-hoi-dam-voi-chu-tich-quoc-hoi-chinh-quyen-nhan-dan-cuba-4762310.html" 
    # Use a real news article URL or any URL expected to be crawled. 
    # Attempting a known site. If fails, user can suggest another.
    
    print(f"Crawling: {test_url}")
    
    async with httpx.AsyncClient(timeout=30) as client:
        result = await process_url(client, test_url)
        
    print("-" * 40)
    print(f"Status: {result.status}")
    if result.status == "ok":
        print(f"Title: {result.title}")
        print(f"Description: {result.description}")
        print(f"Content Length: {len(result.content) if result.content else 0}")
        print("-" * 20)
        print("CONTENT PREVIEW (Start):")
        print(result.content[:500] if result.content else "None")
        print("-" * 20)
        print("CONTENT PREVIEW (End):")
        print(result.content[-500:] if result.content else "None")
        print("-" * 20)
        print("METADATA:")
        print(result.metadata)
        
        # Check for images in content (should be pure text)
        if result.content and "![" in result.content:
             print("\n[!] Found markdown image syntax in content!")
        else:
             print("\n[OK] No markdown image syntax in content.")
             
        # Check for published time in content
        if result.content and "Published Time" in result.content:
             print("\n[!] Found 'Published Time' string in content!")
        
    else:
        print(f"Error: {result.error_message}")

if __name__ == "__main__":
    asyncio.run(main())

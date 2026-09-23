import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
import re

URL = "https://www.amazon.co.jp/s?k=%E3%82%AA%E3%82%B7%E3%83%A3%E3%83%AC+%E9%85%92%E5%99%A8"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    page.goto(URL, timeout=60000)
    page.wait_for_selector('div[data-asin]', timeout=30000)
    items = page.query_selector_all('div[data-asin]')
    results = []
    for it in items:
        asin = it.get_attribute('data-asin')
        if not asin:
            continue
        title_el = it.query_selector('h2 span') or it.query_selector('h2 a span')
        title = title_el.inner_text().strip() if title_el else None
        price_whole = it.query_selector('.a-price-whole')
        price = None
        if price_whole:
            txt = price_whole.inner_text().replace(',', '').replace('.', '')
            try:
                price = int(re.sub(r'\D', '', txt))
            except:
                price = None
        if title:
            results.append((asin, title, price))
    browser.close()

seen = set()
for asin, title, price in results:
    if asin in seen:
        continue
    seen.add(asin)
    print(f"{asin}\t{price}\t{title}")

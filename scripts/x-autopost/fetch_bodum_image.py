import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

url = sys.argv[1]

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(locale="ja-JP")
    page.goto(url, timeout=25000, wait_until="networkidle")
    og = page.locator('meta[property="og:image"]')
    if og.count() > 0:
        print("OG_IMAGE:", og.first.get_attribute("content"))
    imgs = page.locator("img").all()
    for img in imgs[:40]:
        src = img.get_attribute("src") or img.get_attribute("data-src") or ""
        if "12132" in src or "douro" in src.lower() or "product" in src.lower():
            print("IMG:", src)
    browser.close()

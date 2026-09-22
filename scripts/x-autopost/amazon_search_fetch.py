"""Fetch an Amazon.co.jp search results page and dump product cards (asin/title/price/url).

One-off helper for the recurring drink/sakeware blog job to find new candidate products.
"""

from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


def fetch_search_results(url: str, timeout_ms: int = 20000) -> list[dict]:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(
                locale="ja-JP",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            )
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            print(f"PAGE TITLE: {page.title()}", file=sys.stderr)
            try:
                page.wait_for_selector('div[data-component-type="s-search-result"]', timeout=timeout_ms)
            except Exception as e:
                page.screenshot(path="debug_search.png")
                print(f"SELECTOR WAIT FAILED: {e}", file=sys.stderr)
                print(f"BODY SNIPPET: {page.content()[:2000]}", file=sys.stderr)
                raise
            cards = page.locator('div[data-component-type="s-search-result"]').all()
            results = []
            for card in cards:
                asin = card.get_attribute("data-asin")
                if not asin:
                    continue
                try:
                    title = card.locator("h2").first.inner_text().strip()
                except Exception:
                    title = ""
                try:
                    price_whole = card.locator(".a-price-whole").first.inner_text().strip()
                    price = int(price_whole.replace(",", "").replace(".", ""))
                except Exception:
                    price = None
                try:
                    link = card.locator("h2 a").first.get_attribute("href")
                    full_url = f"https://www.amazon.co.jp{link}" if link and link.startswith("/") else link
                except Exception:
                    full_url = None
                results.append({"asin": asin, "title": title, "price": price, "url": full_url})
        finally:
            browser.close()
    return results


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python amazon_search_fetch.py <search-url>")
        raise SystemExit(1)
    data = fetch_search_results(sys.argv[1])
    print(json.dumps(data, ensure_ascii=False, indent=2))

"""Render a Hatena Blog entry page with Playwright and extract the article body text.

We render the real page (rather than trusting the RSS <description>) because
Hatena's RSS summary can be truncated or have its HTML mangled for long posts.
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

ENTRY_CONTENT_SELECTOR = ".entry-content.hatenablog-entry"


def fetch_article_body(url: str, timeout_ms: int = 30000) -> str:
    """Return the plain-text body of a Hatena Blog entry page."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_selector(ENTRY_CONTENT_SELECTOR, timeout=timeout_ms)
            body_text = page.locator(ENTRY_CONTENT_SELECTOR).inner_text()
        finally:
            browser.close()
    return body_text.strip()


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python scraper.py <hatena-entry-url>")
        raise SystemExit(1)
    text = fetch_article_body(sys.argv[1])
    print(text[:500])
    print(f"\n... ({len(text)} characters total)")

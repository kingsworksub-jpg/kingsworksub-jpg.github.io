"""Post the chosen tweet text (plus the article URL) to X via browser
automation (Playwright), reusing a saved login session -- no paid API.

X's API v2 dropped its free tier in Feb 2026 and now charges per post
($0.20/post for anything containing a URL), which conflicts with this
project's goal of a fully local, zero-cost pipeline. This module instead
drives the real x.com web UI with a session saved by x_login_setup.py.

Known tradeoff (accepted): this is browser automation against a service
that expects human use via its own official channels; it is a gray area
under X's terms and carries some account-risk if used at high volume or
in an obviously bot-like pattern. This project posts at most a few times
a week, matching normal human posting cadence.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

AUTH_STATE_PATH = Path(__file__).parent / ".." / ".." / ".secrets" / "x-auth-state.json"

COMPOSE_SELECTOR = '[data-testid="tweetTextarea_0"]'
POST_BUTTON_SELECTORS = ['[data-testid="tweetButtonInline"]', '[data-testid="tweetButton"]']


class PostingError(RuntimeError):
    pass


class SessionExpiredError(PostingError):
    pass


def post_tweet(text: str, url: str, timeout_ms: int = 30000) -> None:
    """Post `text` + the article URL to X via the logged-in web UI."""
    if not AUTH_STATE_PATH.exists():
        raise PostingError(
            f"No saved X login session at {AUTH_STATE_PATH.resolve()}. "
            "Run `python x_login_setup.py` once first."
        )

    full_text = f"{text}\n{url}"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(storage_state=str(AUTH_STATE_PATH))
            page = context.new_page()
            page.goto("https://x.com/compose/post", timeout=timeout_ms, wait_until="domcontentloaded")

            if "/login" in page.url:
                raise SessionExpiredError(
                    "X session has expired (redirected to login). "
                    "Run `python x_login_setup.py` again to re-authenticate."
                )

            page.wait_for_selector(COMPOSE_SELECTOR, timeout=timeout_ms)
            page.click(COMPOSE_SELECTOR)
            page.keyboard.type(full_text, delay=15)

            posted = False
            for selector in POST_BUTTON_SELECTORS:
                button = page.locator(selector)
                if button.count() > 0 and button.first.is_enabled():
                    button.first.click()
                    posted = True
                    break
            if not posted:
                raise PostingError("Could not find an enabled post button (X's UI may have changed).")

            # Give the post request time to complete before closing the browser.
            page.wait_for_timeout(3000)
        finally:
            browser.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python poster.py <text> <url>")
        raise SystemExit(1)
    post_tweet(sys.argv[1], sys.argv[2])
    print("Posted (check x.com to confirm -- this script does not capture the tweet URL/id).")

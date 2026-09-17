"""One-time interactive setup: log into X in a real (visible) browser window
and save the authenticated session so poster.py can reuse it headlessly.

We never store the X password anywhere -- the user types it into the actual
X login page themselves. Only the resulting session cookies/local storage
are saved, to ../../.secrets/x-auth-state.json (gitignored).

Run this once, and again any time poster.py reports the session has expired.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

AUTH_STATE_PATH = Path(__file__).parent / ".." / ".." / ".secrets" / "x-auth-state.json"


def main() -> None:
    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://x.com/login")

        print("=" * 70)
        print("ブラウザウィンドウでXにログインしてください。")
        print("2段階認証が求められた場合もそのまま画面上で完了してください。")
        print("ログインが終わってホームのタイムラインが表示されたら、")
        print("このターミナルに戻って Enter キーを押してください。")
        print("=" * 70)
        input("ログイン完了後、Enterを押してください... ")

        context.storage_state(path=str(AUTH_STATE_PATH))
        print(f"[x_login_setup] セッションを保存しました: {AUTH_STATE_PATH.resolve()}")

        browser.close()


if __name__ == "__main__":
    main()

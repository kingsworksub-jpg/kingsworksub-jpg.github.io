# -*- coding: utf-8 -*-
"""Google の手動ログイン用ブラウザを開き、セッションを専用プロファイルに保存する。

Google は自動ログインを拒否するため、表示されたウィンドウで一度だけ手動ログインする。
ログイン後は同じプロファイルを再利用して、以降の操作を自動化できる。

使い方:
    python scripts/google-login.py
"""
from __future__ import annotations

import os
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(ROOT, "data", "google_automation_profile")
SHOT = os.path.join(ROOT, "data", "google-login.png")
START = "https://console.cloud.google.com/"


def main() -> int:
    os.makedirs(os.path.dirname(PROFILE), exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE,
            headless=False,
            args=["--start-maximized"],
            viewport={"width": 1440, "height": 1000},
            locale="ja-JP",
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(START, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            print(f"WARN: 初期ページを開けませんでした ({exc})", flush=True)

        print("Google にログインしてください（最大10分待ちます）。", flush=True)
        deadline = time.time() + 600
        logged_in = False
        while time.time() < deadline:
            try:
                host = urlparse(page.url).hostname or ""
                title = page.title()
            except Exception:
                host, title = "", ""
            if "console.cloud.google.com" in host and "signin" not in title.lower():
                logged_in = True
                break
            page.wait_for_timeout(3000)

        try:
            page.screenshot(path=SHOT, full_page=False)
        except Exception:
            pass

        if logged_in:
            print(f"OK: ログインを検出しました / {page.url}", flush=True)
            print(f"    screenshot: {SHOT}", flush=True)
            ctx.close()
            return 0

        print("ログインを検出できませんでした。再実行してください。", flush=True)
        ctx.close()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

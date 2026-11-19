# -*- coding: utf-8 -*-
"""Amazonアソシエイトのログイン済みセッションを storage_state として書き出す（ローカル用・1回だけ）。

GitHub Actions は Windows の暗号化クッキー(DPAPI)を読めないため、
永続プロファイルではなく **平文の storage_state JSON** を Secrets に登録する。

使い方:
    python scripts/amazon-session-export.py --profile   # 既存プロファイルから（ログイン不要）
    python scripts/amazon-session-export.py             # 新規ログイン（ブラウザが開く）
    → data/amazon_storage_state.json と .b64 ができる
    → .b64 の中身を GitHub Secret `AMAZON_STORAGE_STATE_B64` に登録

認証情報はこのスクリプトに渡さない（パスワードは画面で入力する）。
"""
from __future__ import annotations

import argparse
import base64
import io
import os
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_JSON = os.path.join(ROOT, "data", "amazon_storage_state.json")
OUT_B64 = os.path.join(ROOT, "data", "amazon_storage_state.b64")
PROFILE = os.path.join(ROOT, "data", "amazon_associates_profile")
HOME = "https://affiliate.amazon.co.jp/home"


def is_associates(page) -> bool:
    host = urlparse(page.url).hostname or ""
    title = page.title()
    return host == "affiliate.amazon.co.jp" and "ログイン" not in title and "サインイン" not in title


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        action="store_true",
        help="既存のログイン済み永続プロファイルから storage_state を書き出す（ログイン不要）",
    )
    args = parser.parse_args()
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)

    with sync_playwright() as p:
        if args.profile:
            if not os.path.isdir(PROFILE):
                print(f"プロファイルが見つかりません: {PROFILE}", flush=True)
                return 1
            ctx = p.chromium.launch_persistent_context(
                PROFILE,
                headless=True,
                viewport={"width": 1440, "height": 1000},
                locale="ja-JP",
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            if not is_associates(page):
                print("保存済みセッションが切れています。--profile なしで再ログインしてください。", flush=True)
                ctx.close()
                return 1
            ctx.storage_state(path=OUT_JSON)
            ctx.close()
        else:
            browser = p.chromium.launch(headless=False, args=["--start-maximized"])
            ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="ja-JP")
            page = ctx.new_page()
            page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
            print("ブラウザで Amazon にログインしてください（最大10分待ちます）。", flush=True)
            deadline = time.time() + 600
            while time.time() < deadline and not is_associates(page):
                page.wait_for_timeout(3000)
            if not is_associates(page):
                print("ログインを検出できませんでした。再実行してください。", flush=True)
                browser.close()
                return 1
            page.wait_for_timeout(1500)
            ctx.storage_state(path=OUT_JSON)
            browser.close()

    with io.open(OUT_JSON, "rb") as fh:
        encoded = base64.b64encode(fh.read()).decode("ascii")
    with io.open(OUT_B64, "w", encoding="ascii", newline="") as fh:
        fh.write(encoded)
    print(f"OK: {OUT_JSON}", flush=True)
    print(f"OK: {OUT_B64}", flush=True)
    print("↑ の中身を GitHub Secret `AMAZON_STORAGE_STATE_B64` に登録してください。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

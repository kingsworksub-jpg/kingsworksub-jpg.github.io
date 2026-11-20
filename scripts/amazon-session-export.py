# -*- coding: utf-8 -*-
"""Amazonアソシエイトのログイン済みセッションを storage_state として書き出す（ローカル用・1回だけ）。

GitHub Actions は Windows の暗号化クッキー(DPAPI)を読めないため、
永続プロファイルではなく **平文の storage_state JSON** を Secrets に登録する。

使い方:
    python scripts/amazon-session-export.py --profile          # 既存プロファイルから（ログイン不要）
    python scripts/amazon-session-export.py                    # 新規ログイン（ブラウザが開く）
    python scripts/amazon-session-export.py --update-secret    # ログイン後に Secret も自動更新（推奨）
    python scripts/amazon-session-export.py --cdp --update-secret
        # デバッグポート付き Chrome にログイン済みなら、CDP 経由でセッションを取り出す
        # （→ 下記の CDP 起動コマンドを先に実行し、ブラウザでログインしておく）
    python scripts/amazon-session-export.py --chrome-profile --update-secret
        # 普段使っている Chrome の Cookie をコピーしてセッションを取り出す（GUI操作不要・非推奨）
        # 事前に Chrome を完全終了させ、Amazon にログイン済みにしておくこと
    → data/amazon_storage_state.json と .b64 ができる
    → --update-secret を付けると gh で `AMAZON_STORAGE_STATE_B64` を直接更新する

Secret の値は標準入力で gh に渡すため、引数・ログ・チャットには出ない。
認証情報はこのスクリプトに渡さない（パスワードは画面で入力する）。
"""
from __future__ import annotations

import argparse
import base64
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_JSON = os.path.join(ROOT, "data", "amazon_storage_state.json")
OUT_B64 = os.path.join(ROOT, "data", "amazon_storage_state.b64")
PROFILE = os.path.join(ROOT, "data", "amazon_associates_profile")
HOME = "https://affiliate.amazon.co.jp/home"
SECRET_NAME = "AMAZON_STORAGE_STATE_B64"
CHROME_USER_DATA = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data"
)


def is_associates(page) -> bool:
    host = urlparse(page.url).hostname or ""
    title = page.title()
    return host == "affiliate.amazon.co.jp" and "ログイン" not in title and "サインイン" not in title


def update_secret(encoded: str) -> tuple[bool, str]:
    """gh CLI で Secret を更新する（値は stdin で渡し、引数やログに出さない）。"""
    try:
        result = subprocess.run(
            ["gh", "secret", "set", SECRET_NAME],
            input=encoded + "\n",
            text=True,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip().splitlines()[-1:] or ["gh failed"]
    return True, ""


def secret_updated_at() -> str:
    """更新時刻だけを確認する（値は取得しない）。"""
    try:
        repo = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
            text=True, capture_output=True, timeout=30,
        ).stdout.strip()
        if not repo:
            return ""
        r = subprocess.run(
            ["gh", "api", f"repos/{repo}/actions/secrets/{SECRET_NAME}", "--jq", "updated_at"],
            text=True, capture_output=True, timeout=30,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def export_from_cdp() -> bool:
    """デバッグポート(9222)で起動した Chrome から storage_state を取り出す。"""
    endpoint = os.environ.get("AMAZON_CDP_ENDPOINT", "http://localhost:9222")
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(endpoint)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)
            if not is_associates(page):
                print(
                    f"CDP先のセッションが切れています (URL={page.url}, title={page.title()})。"
                    "ブラウザで Amazon にログインしてから再実行してください。",
                    flush=True,
                )
                return False
            ctx.storage_state(path=OUT_JSON)
            return True
    except Exception as exc:
        print(f"CDP に接続できませんでした ({endpoint}): {exc}", flush=True)
        return False


def export_from_chrome() -> bool:
    """Chrome のプロファイルを一時コピーし、ログイン済みセッションを storage_state に保存する。"""
    if not os.path.isdir(CHROME_USER_DATA):
        print(f"Chrome のプロファイルが見つかりません: {CHROME_USER_DATA}", flush=True)
        return False
    tmp = tempfile.mkdtemp(prefix="amazon-chrome-profile-")
    try:
        copies = [
            ("Local State", "Local State"),
            (os.path.join("Default", "Preferences"), os.path.join("Default", "Preferences")),
            (os.path.join("Default", "Network", "Cookies"), os.path.join("Default", "Network", "Cookies")),
        ]
        for src_rel, dst_rel in copies:
            src = os.path.join(CHROME_USER_DATA, src_rel)
            dst = os.path.join(tmp, dst_rel)
            if not os.path.exists(src):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with io.open(src, "rb") as f_in, io.open(dst, "wb") as f_out:
                f_out.write(f_in.read())
        if not os.path.exists(os.path.join(tmp, "Default", "Network", "Cookies")):
            print("Chrome の Cookie を読み取れませんでした。Chrome を完全に終了してください。", flush=True)
            return False

        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                tmp,
                channel="chrome",
                headless=True,
                viewport={"width": 1440, "height": 1000},
                locale="ja-JP",
            )
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
                if not is_associates(page):
                    print(
                        f"Chrome のセッションが切れています (URL={page.url}, title={page.title()})。"
                        "Chrome で Amazon にログインしてから再実行してください。",
                        flush=True,
                    )
                    return False
                ctx.storage_state(path=OUT_JSON)
                return True
            finally:
                ctx.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile", action="store_true",
        help="既存のログイン済み永続プロファイルから storage_state を書き出す（ログイン不要）",
    )
    parser.add_argument(
        "--update-secret", action="store_true",
        help="書き出した storage_state で GitHub Secret を自動更新する（gh CLI 認証が必要）",
    )
    parser.add_argument(
        "--chrome-profile", action="store_true",
        help="普段使っている Chrome の Cookie をコピーしてセッションを取り出す（要・Chrome終了）",
    )
    parser.add_argument(
        "--cdp", action="store_true",
        help="デバッグポート(9222)付き Chrome から CDP でセッションを取り出す",
    )
    args = parser.parse_args()
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)

    if args.cdp:
        if not export_from_cdp():
            return 1
    elif args.chrome_profile:
        if not export_from_chrome():
            return 1
    elif args.profile:
        if not os.path.isdir(PROFILE):
            print(f"プロファイルが見つかりません: {PROFILE}", flush=True)
            return 1
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                PROFILE, headless=True,
                viewport={"width": 1440, "height": 1000}, locale="ja-JP",
            )
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
                if not is_associates(page):
                    print("保存済みセッションが切れています。再ログインが必要です。", flush=True)
                    return 1
                ctx.storage_state(path=OUT_JSON)
            finally:
                ctx.close()
    else:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=["--start-maximized"])
            try:
                ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="ja-JP")
                page = ctx.new_page()
                page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
                print("ブラウザで Amazon にログインしてください（最大10分待ちます）。", flush=True)
                deadline = time.time() + 600
                while time.time() < deadline and not is_associates(page):
                    page.wait_for_timeout(3000)
                if not is_associates(page):
                    print("ログインを検出できませんでした。再実行してください。", flush=True)
                    return 1
                page.wait_for_timeout(1500)
                ctx.storage_state(path=OUT_JSON)
            finally:
                browser.close()

    with io.open(OUT_JSON, "rb") as fh:
        encoded = base64.b64encode(fh.read()).decode("ascii")
    with io.open(OUT_B64, "w", encoding="ascii", newline="") as fh:
        fh.write(encoded)
    print(f"OK: {OUT_JSON}", flush=True)
    print(f"OK: {OUT_B64}", flush=True)

    if args.update_secret:
        ok, error = update_secret(encoded)
        if not ok:
            print(f"WARN: GitHub Secret {SECRET_NAME} の更新に失敗しました ({error})", flush=True)
            print("      ローカルの storage_state は更新済みです。手動で登録してください。", flush=True)
            return 1
        print(f"OK: GitHub Secret {SECRET_NAME} を更新しました。", flush=True)
        when = secret_updated_at()
        if when:
            print(f"  updated_at: {when}", flush=True)
    else:
        print(f"↑ の中身を GitHub Secret `{SECRET_NAME}` に登録してください。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

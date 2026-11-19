# -*- coding: utf-8 -*-
"""Amazonアソシエイトのセッションを定期的に刷新し、GitHub Secret を更新する（ローカル用）。

GitHub Actions の GITHUB_TOKEN は Secrets を書き換えられないため、
刷新そのものはローカル（Windows タスクスケジューラ）で回す。
自宅 IP からアクセスさせることで、データセンター IP からのレポート取得が切れるのを防ぐ。

使い方:
    python scripts/amazon-session-keepalive.py                 # 1回刷新して Secret も更新
    python scripts/amazon-session-keepalive.py --no-secret     # ローカルの state だけ更新
    python scripts/amazon-session-keepalive.py --check-only    # 確認だけ（書き込みしない）
    python scripts/amazon-session-keepalive.py --strict        # 失敗時 exit 1

動作:
    1. data/amazon_storage_state.b64 を読む（無ければ env AMAZON_STORAGE_STATE_B64）
    2. headless Chromium で affiliate home → レポート画面を訪問
    3. 両方ともサインイン状態なら storage_state を刷新して .json / .b64 に保存
    4. 変更があれば `gh secret set AMAZON_STORAGE_STATE_B64` で Secret を更新
    5. サインイン画面に飛んだ場合は既存ファイル・Secret を一切触らず警告のみ

認証情報はチャットに出さない。パスワードはこのスクリプトに渡さない。
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
STATE_JSON = os.path.join(DATA_DIR, "amazon_storage_state.json")
STATE_B64 = os.path.join(DATA_DIR, "amazon_storage_state.b64")
STATUS_JSON = os.path.join(DATA_DIR, "amazon_keepalive_status.json")
LOG_FILE = os.path.join(DATA_DIR, "amazon-keepalive.log")
SECRET_NAME = "AMAZON_STORAGE_STATE_B64"
VISIT_URLS = (
    "https://affiliate.amazon.co.jp/home",
    "https://affiliate.amazon.co.jp/p/reporting/earnings",
)
JST = timezone(timedelta(hours=9))


def now_iso() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def log(message: str) -> None:
    line = f"{now_iso()} {message}"
    print(line, flush=True)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with io.open(LOG_FILE, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def is_associates(page) -> bool:
    host = urlparse(page.url).hostname or ""
    title = page.title()
    return host == "affiliate.amazon.co.jp" and "ログイン" not in title and "サインイン" not in title


def load_encoded() -> str | None:
    if os.path.exists(STATE_B64):
        with io.open(STATE_B64, "r", encoding="ascii") as fh:
            value = fh.read().strip()
        if value:
            return value
    return os.environ.get(SECRET_NAME, "").strip() or None


def save_status(status: dict) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with io.open(STATUS_JSON, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(status, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        log(f"WARN: ステータスファイルを書けませんでした ({exc})")


def update_secret(encoded: str) -> tuple[bool, str]:
    """gh の認証情報を使って Secret を更新する（値は process 引数に出さず stdin で渡す）。"""
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
        return False, (result.stderr or result.stdout).strip().splitlines()[-1:]
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-secret", action="store_true", help="GitHub Secret を更新しない")
    parser.add_argument("--check-only", action="store_true", help="ファイルも Secret も書き換えない")
    parser.add_argument("--strict", action="store_true", help="失敗時に exit 1 を返す")
    args = parser.parse_args()

    status = {
        "checked_at": now_iso(),
        "ok": False,
        "signed_in": False,
        "changed": False,
        "secret_updated": False,
        "reason": "",
    }

    encoded = load_encoded()
    if not encoded:
        status["reason"] = f"{STATE_B64} も {SECRET_NAME} も未設定です"
        log(f"SKIP: {status['reason']}")
        save_status(status)
        return 1 if args.strict else 0

    try:
        state = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        status["reason"] = f"storage_state のデコードに失敗しました ({exc})"
        log(f"WARN: {status['reason']}")
        save_status(status)
        return 1 if args.strict else 0

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        tf.write(state)
        state_path = tf.name
    refreshed_path = state_path + ".refreshed.json"

    signed_in = False
    reason = ""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(storage_state=state_path, locale="ja-JP")
            page = ctx.new_page()
            for url in VISIT_URLS:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(2500)
                except Exception as exc:
                    reason = f"ページを開けませんでした ({url}: {exc})"
                    break
                if not is_associates(page):
                    reason = f"サインイン画面にリダイレクトされました ({url})"
                    break
            else:
                signed_in = True

            if signed_in:
                ctx.storage_state(path=refreshed_path)
            browser.close()
    except Exception as exc:
        reason = f"ブラウザ実行に失敗しました ({exc})"
    finally:
        try:
            os.unlink(state_path)
        except OSError:
            pass

    status["signed_in"] = signed_in

    if not signed_in:
        try:
            os.unlink(refreshed_path)
        except OSError:
            pass
        status["reason"] = reason or "サインイン状態を確認できませんでした"
        log(f"WARN: {status['reason']}。既存の state / Secret は保持します。")
        save_status(status)
        return 1 if args.strict else 0

    try:
        with io.open(refreshed_path, "rb") as fh:
            refreshed_state = fh.read()
    finally:
        try:
            os.unlink(refreshed_path)
        except OSError:
            pass
    changed = refreshed_state != state
    status["changed"] = changed

    if args.check_only:
        status["ok"] = True
        status["reason"] = "check-only（書き込みなし）"
        log(f"OK: サインイン確認のみ（変更={'あり' if changed else 'なし'}）")
        save_status(status)
        return 0

    if not changed:
        status["ok"] = True
        status["reason"] = "変更なし"
        log("OK: セッション有効。storage_state に変更はありません。")
        save_status(status)
        return 0

    encoded_new = base64.b64encode(refreshed_state).decode("ascii")
    with io.open(STATE_JSON, "wb") as fh:
        fh.write(refreshed_state)
    with io.open(STATE_B64, "w", encoding="ascii", newline="") as fh:
        fh.write(encoded_new)
    log(f"OK: ローカルの storage_state を刷新しました ({STATE_B64})")

    if args.no_secret:
        status["ok"] = True
        status["reason"] = "--no-secret（ローカルのみ更新）"
        log("SKIP: --no-secret が指定されたため Secret は更新しません。")
        save_status(status)
        return 0

    updated, error = update_secret(encoded_new)
    status["secret_updated"] = updated
    if updated:
        status["ok"] = True
        status["reason"] = "Secret 更新完了"
        log(f"OK: GitHub Secret {SECRET_NAME} を更新しました。")
    else:
        status["reason"] = f"Secret の更新に失敗しました ({error})"
        log(f"WARN: {status['reason']}。ローカルの state は刷新済みです。")
    save_status(status)
    return 1 if (args.strict and not updated) else 0


if __name__ == "__main__":
    raise SystemExit(main())

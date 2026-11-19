# -*- coding: utf-8 -*-
"""Amazonアソシエイトのレポート数値を取得して scripts/p0-amazon.json を更新する（Actions用）。

認証情報はチャット/リポジトリに置かず、GitHub Secret から読む:

  AMAZON_STORAGE_STATE_B64 ... amazon-session-export.py が作った base64 文字列

未設定、セッション切れ、取得失敗の場合は既存の p0-amazon.json を保持して
警告だけ出し、ワークフロー全体を失敗させない（exit 0）。

必要ライブラリ:
  pip install playwright && python -m playwright install --with-deps chromium
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_JSON = os.path.join(ROOT, "scripts", "p0-amazon.json")
REPORT_URL = "https://affiliate.amazon.co.jp/p/reporting/earnings"


def load_existing() -> dict:
    if not os.path.exists(OUT_JSON):
        return {}
    with io.open(OUT_JSON, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def is_associates(page) -> bool:
    host = urlparse(page.url).hostname or ""
    title = page.title()
    return host == "affiliate.amazon.co.jp" and "ログイン" not in title and "サインイン" not in title


def _num(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text)
    return int(m.group(1).replace(",", "")) if m else None


def parse_summary(text: str) -> dict:
    out = {}
    m = re.search(
        r"([A-Z][a-z]{2}\s+\d+\s+\d{4})\s*-\s*([A-Z][a-z]{2}\s+\d+\s+\d{4})",
        text,
    )
    if m:
        out["period"] = f"{m.group(1)} 〜 {m.group(2)} / 過去30日間"
    m = re.search(r"最終更新日:\s*(.+?JST)", text)
    if m:
        out["last_updated"] = m.group(1).strip()

    out["clicks"] = _num(r"クリック数\s*\n\s*([\d,]+)\s*\n\s*注文済み商品", text)
    out["orders"] = _num(r"注文済み商品\s*\n\s*([\d,]+)\s*\n\s*コンバージョン率", text)
    m = re.search(r"コンバージョン率\s*\n\s*([\d.]+)%", text)
    if m:
        out["cvr"] = f"{float(m.group(1)):.2f}%"
    out["revenue"] = _num(r"注文商品売上\s*\n\s*¥([\d,]+)", text) or 0
    out["commission"] = _num(r"紹介料合計\s*\n\s*¥([\d,]+)", text) or 0
    out["shipped"] = _num(r"発送済み商品数\s*\n\s*([\d,]+)", text) or 0
    out["returned"] = _num(r"返品済み商品\s*\n\s*([\d,]+)", text) or 0
    return {k: v for k, v in out.items() if v is not None}


def main() -> int:
    encoded = os.environ.get("AMAZON_STORAGE_STATE_B64", "").strip()
    if not encoded:
        print("SKIP: AMAZON_STORAGE_STATE_B64 が未設定です", flush=True)
        return 0
    try:
        state = base64.b64decode(encoded)
    except Exception as exc:
        print(f"WARN: storage_state のデコードに失敗しました ({exc})", flush=True)
        return 0

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        tf.write(state)
        state_path = tf.name

    existing = load_existing()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(storage_state=state_path, locale="ja-JP")
            page = ctx.new_page()
            try:
                page.goto(REPORT_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
            except Exception as exc:
                print(f"WARN: レポート画面を開けませんでした ({exc})", flush=True)
                return 0
            if not is_associates(page):
                print("WARN: セッション切れの可能性があります（サインイン画面）。既存値を保持します。", flush=True)
                browser.close()
                return 0
            text = page.locator("body").inner_text(timeout=15000)
            browser.close()
    except Exception as exc:
        print(f"WARN: ブラウザ実行に失敗しました ({exc})", flush=True)
        return 0
    finally:
        try:
            os.unlink(state_path)
        except OSError:
            pass

    parsed = parse_summary(text)
    if "clicks" not in parsed:
        print("WARN: レポートから数値を抽出できませんでした。既存値を保持します。", flush=True)
        return 0

    existing.update(parsed)
    existing["_comment"] = "アソシエイト・セントラル レポートサマリーから自動回収した実数値。"
    existing["note"] = (
        "GitHub Actions が毎週自動取得。媒体別はUIフィルタ変更が必要。"
        "コード側 affiliate_tag.py の TAGS には5つ（X含む）を登録済み。"
    )
    existing["last_collected_at"] = datetime.now(
        timezone(timedelta(hours=9))
    ).isoformat(timespec="seconds")
    with io.open(OUT_JSON, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(existing, fh, ensure_ascii=False, indent=2)
    print(
        f"OK: {OUT_JSON} / clicks={parsed['clicks']} orders={parsed.get('orders')} "
        f"cvr={parsed.get('cvr')}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

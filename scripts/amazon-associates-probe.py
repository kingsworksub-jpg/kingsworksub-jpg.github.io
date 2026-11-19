# -*- coding: utf-8 -*-
"""Amazon アソシエイト管理画面を実ブラウザ(Playwright)で開き、ログイン後の画面を調査する。

通常の HTTP 取得はサインインへリダイレクト + bot 判定 503 で弾かれるため、
アソシエイト専用の永続プロファイル(実ブラウザ)を使う。検索用プロファイルとは分ける。
パスワードはスクリプトに渡さない。開いたウィンドウで手動ログインすること。

使い方:
    python scripts/amazon-associates-probe.py --wait 900

出力: data/amazon-associates-probe/ に txt / html / png / links.json / result.json
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

PROFILE = r"C:\Users\norio\my-github-blog\data\amazon_associates_profile"
OUT = r"C:\Users\norio\my-github-blog\data\amazon-associates-probe"
HOME = "https://affiliate.amazon.co.jp/home"


def stamp() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d-%H%M%S")


def is_associates(page) -> bool:
    """サインインURLの return_to に affiliate.amazon.co.jp が入っていても誤判定しない。"""
    host = urlparse(page.url).hostname or ""
    title = page.title()
    return (
        host == "affiliate.amazon.co.jp"
        and "ログイン" not in title
        and "サインイン" not in title
    )


def dump(page, prefix: str) -> dict:
    info = {"url": page.url, "title": page.title(), "prefix": prefix}
    try:
        text = page.locator("body").inner_text(timeout=10000)
    except Exception as exc:
        text = f"(inner_text failed: {exc})"
    with io.open(os.path.join(OUT, f"{prefix}.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text[:60000])
    try:
        with io.open(os.path.join(OUT, f"{prefix}.html"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(page.content()[:300000])
    except Exception as exc:
        info["html_error"] = str(exc)
    try:
        page.screenshot(path=os.path.join(OUT, f"{prefix}.png"), full_page=True, timeout=15000)
    except Exception as exc:
        info["png_error"] = str(exc)
    info["text_chars"] = len(text)
    info["text_head"] = text[:400]
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=900, help="ログイン待ち秒数 (既定900)")
    ap.add_argument("--collect-only", action="store_true", help="ログイン待ちをせず、保存済みセッションで回収だけ行う")
    ap.add_argument("--profile", default=PROFILE, help="永続ブラウザプロファイルのパス")
    ap.add_argument("--extra-url", default=None, help="回収後に追加で開いてダンプするURL")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    run_id = stamp()
    print(f"[{run_id}] ブラウザを開きます。表示されたウィンドウで Amazon にログインしてください。", flush=True)

    result = {"started_at": run_id, "dumps": []}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            args.profile,
            headless=False,
            args=["--start-maximized"],
            viewport={"width": 1440, "height": 1000},
            locale="ja-JP",
        )
        page = ctx.new_page()
        try:
            page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            print(f"goto error: {exc}", flush=True)
            result["goto_error"] = str(exc)

        deadline = time.time() + args.wait
        logged_in = is_associates(page)
        last_report = 0
        if not args.collect_only:
            while time.time() < deadline and not logged_in:
                logged_in = is_associates(page)
                if logged_in:
                    break
                if time.time() - last_report >= 20:
                    print(f"  ログイン待機中... ({int(deadline - time.time())}s残) url={page.url[:80]}", flush=True)
                    last_report = time.time()
                page.wait_for_timeout(3000)

        result["logged_in"] = is_associates(page)
        if not result["logged_in"]:
            print("ログイン未検出: 現在の画面をダンプします。サインインページならログイン後に --collect-only で再実行してください。", flush=True)
        page.wait_for_timeout(1500)

        result["dumps"].append(dump(page, f"{run_id}-home"))

        links = []
        try:
            links = page.eval_on_selector_all(
                "a",
                """els => els.map(e => ({text: (e.innerText||'').trim(), href: e.href}))
                     .filter(x => /report|レポート|earnings|クリック|売上/i.test(x.text + ' ' + x.href))
                     .slice(0, 50)""",
            )
        except Exception as exc:
            result["links_error"] = str(exc)
        with io.open(os.path.join(OUT, f"{run_id}-links.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(links, fh, ensure_ascii=False, indent=2)
        result["report_links"] = links
        print(f"レポート候補リンク: {len(links)} 件", flush=True)

        candidates = []
        for link in links:
            href = link.get("href", "")
            if "affiliate.amazon.co.jp" in href and "report" in href.lower() and href not in candidates:
                candidates.append(href)
        for i, href in enumerate(candidates[:3], 1):
            try:
                page.goto(href, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2000)
                result["dumps"].append(dump(page, f"{run_id}-report-{i}"))
                print(f"  report-{i}: {href}", flush=True)
            except Exception as exc:
                print(f"  report-{i} failed: {exc}", flush=True)

        if args.extra_url:
            try:
                page.goto(args.extra_url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2000)
                result["dumps"].append(dump(page, f"{run_id}-extra"))
                print(f"  extra: {args.extra_url}", flush=True)
            except Exception as exc:
                print(f"  extra failed: {exc}", flush=True)

        ctx.close()

    with io.open(os.path.join(OUT, f"{run_id}-result.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(f"完了: {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

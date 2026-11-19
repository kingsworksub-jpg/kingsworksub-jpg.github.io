# -*- coding: utf-8 -*-
"""Google Search Console の検索パフォーマンスを実ブラウザで開き、CSVをダウンロードする。

使い方:
    python scripts/search-console-probe.py --wait 900

ログインは開いたウィンドウで手動で行う（パスワードはスクリプトに渡さない）。
セッションは専用プロファイルに保存されるので、次回以降は --collect-only で再実行できる。

出力:
    scripts/p0-sc.csv                      ... ダウンロードしたCSV（成功時）
    data/search-console-probe/*.txt/.html/.png ... 画面ダンプ（失敗時の調査用）
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

PROFILE = r"C:\Users\norio\my-github-blog\data\google_sc_profile"
OUT = r"C:\Users\norio\my-github-blog\data\search-console-probe"
SC_URL = "https://search.google.com/search-console"
CSV_OUT = r"C:\Users\norio\my-github-blog\scripts\p0-sc.csv"

# Google は Playwright の自動化フラグを検出するとサインインを拒否する
# (accounts.google.com/v3/signin/rejected)。既存の Ameba 投稿スクリプトと同じ対策。
INIT_SCRIPT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"

CANDIDATES = [
    "https://search.google.com/search-console/performance/search-analytics?resource_id=sc-domain%3Akingsworksub-jpg.github.io",
    "https://search.google.com/search-console/performance/search-analytics?resource_id=https%3A%2F%2Fkingsworksub-jpg.github.io%2F",
]


def stamp() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d-%H%M%S")


def is_console(page) -> bool:
    """未ログインでも見える about ページとサインイン画面をログイン済みと誤判定しない。"""
    host = urlparse(page.url).hostname or ""
    path = urlparse(page.url).path
    if host != "search.google.com" or not path.startswith("/search-console"):
        return False
    try:
        text = page.locator("body").inner_text(timeout=3000)
    except Exception:
        return False
    if "ログインしてください" in text or "メールアドレスまたは電話番号" in text:
        return False
    if "Google 検索での掲載順位を改善する" in text:  # /about の公開ページ
        return False
    return True


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
    info["text_head"] = text[:500]
    return info


def click_text(page, *labels: str) -> bool:
    for label in labels:
        try:
            loc = page.get_by_text(label, exact=False).first
            loc.click(timeout=4000)
            print(f"  clicked: {label}", flush=True)
            return True
        except Exception:
            continue
    return False


def try_export(page, result: dict) -> bool:
    """エクスポート → CSVダウンロード を試す。成功したら p0-sc.csv に保存する。"""
    try:
        with page.expect_download(timeout=20000) as handle:
            opened = False
            for label in ("エクスポート", "ダウンロード", "Export", "Download"):
                if click_text(page, label):
                    opened = True
                    break
            try:
                page.locator('[aria-label*="エクスポート"], [aria-label*="Export"]').first.click(timeout=3000)
                opened = True
            except Exception:
                pass
            if not opened:
                result["export_error"] = "エクスポートボタンが見つからない"
                return False
            page.wait_for_timeout(800)
            for label in ("CSVをダウンロード", "CSVをダウンロードする", "CSV形式でダウンロード", "CSV", "Download CSV"):
                if click_text(page, label):
                    break
            else:
                result["export_error"] = "CSVメニュー項目が見つからない"
                return False
        download = handle.value
        download.save_as(CSV_OUT)
        result["csv_saved"] = CSV_OUT
        result["csv_filename"] = download.suggested_filename
        print(f"  CSV保存: {CSV_OUT} ({download.suggested_filename})", flush=True)
        return True
    except Exception as exc:
        result["export_error"] = str(exc)
        print(f"  export failed: {exc}", flush=True)
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=900, help="ログイン待ち秒数")
    ap.add_argument("--collect-only", action="store_true", help="ログイン待ちをせず回収だけ行う")
    ap.add_argument("--profile", default=PROFILE, help="永続ブラウザプロファイル")
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    run_id = stamp()
    print(f"[{run_id}] Search Console を開きます。Googleにログインしてください。", flush=True)

    result = {"started_at": run_id, "dumps": []}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            args.profile,
            headless=False,
            channel="msedge",
            ignore_default_args=["--enable-automation"],
            accept_downloads=True,
            args=["--start-maximized"],
            viewport={"width": 1440, "height": 1000},
            locale="ja-JP",
        )
        ctx.add_init_script(INIT_SCRIPT)
        page = ctx.new_page()
        try:
            page.goto(SC_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            result["goto_error"] = str(exc)
            print(f"goto error: {exc}", flush=True)

        deadline = time.time() + args.wait
        logged_in = is_console(page)
        last_report = 0
        if not args.collect_only:
            while time.time() < deadline and not logged_in:
                logged_in = is_console(page)
                if logged_in:
                    break
                if time.time() - last_report >= 20:
                    print(f"  ログイン待機中... ({int(deadline - time.time())}s残) url={page.url[:80]}", flush=True)
                    last_report = time.time()
                page.wait_for_timeout(3000)

        result["logged_in"] = is_console(page)
        if not result["logged_in"]:
            print("ログイン未検出: 現在の画面をダンプします。", flush=True)
        page.wait_for_timeout(1500)
        result["dumps"].append(dump(page, f"{run_id}-console"))

        # 検索パフォーマンス画面へ。既知URLを優先し、ダメならページ内のリンクを探す。
        found = False
        for url in CANDIDATES:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                text = page.locator("body").inner_text(timeout=8000)
                if "検索パフォーマンス" in text or "Search performance" in text:
                    found = True
                    print(f"  performance: {url}", flush=True)
                    break
            except Exception as exc:
                print(f"  candidate failed: {exc}", flush=True)

        if not found:
            links = []
            try:
                links = page.eval_on_selector_all(
                    "a",
                    """els => els.map(e => ({text: (e.innerText||'').trim(), href: e.href}))
                         .filter(x => /performance|パフォーマンス/i.test(x.text + ' ' + x.href))
                         .slice(0, 20)""",
                )
            except Exception as exc:
                result["links_error"] = str(exc)
            result["performance_links"] = links
            for link in links:
                href = link.get("href", "")
                if "search.google.com" in href and "performance" in href:
                    try:
                        page.goto(href, wait_until="domcontentloaded", timeout=45000)
                        page.wait_for_timeout(2500)
                        found = True
                        print(f"  performance(link): {href}", flush=True)
                        break
                    except Exception as exc:
                        print(f"  link failed: {exc}", flush=True)

        page.wait_for_timeout(1000)
        result["dumps"].append(dump(page, f"{run_id}-performance"))

        if found:
            # 期間を「過去3か月」に広げる（既定は28日）
            if click_text(page, "過去28日間", "過去28日", "Last 28 days"):
                page.wait_for_timeout(800)
                click_text(page, "過去3か月", "過去3ヶ月", "Last 3 months")
                page.wait_for_timeout(1500)
            result["csv_saved"] = False
            try_export(page, result)
            result["dumps"].append(dump(page, f"{run_id}-after-export"))

        ctx.close()

    with io.open(os.path.join(OUT, f"{run_id}-result.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(f"完了: {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""Amazon.co.jp を実ブラウザ(Playwright)で検索し、候補商品のASIN・商品名・価格を返す。

WebFetch/WebSearch経由だとAmazonがbot判定で503を返すため使えない(2026-10-23実測)。
実ブラウザでのアクセスはこれまでのAmeba/note自動化と同様にブロックされないため、
新規アフィリエイトリンク付与プロジェクトのASIN調査にはこちらを使う。

使い方(1クエリ):
    python amazon_search.py "製品名やキーワード"

使い方(複数クエリを一括、結果をJSONに保存):
    python amazon_search.py --batch queries.json --out results.json
    (queries.json は ["クエリ1", "クエリ2", ...] の配列)
"""
import io
import json
import sys
import time

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")


def search_amazon(page, query, limit=6):
    url = f"https://www.amazon.co.jp/s?k={query}"
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1800)
    try:
        page.wait_for_selector('div[data-component-type="s-search-result"]', timeout=8000)
    except Exception:
        return []
    items = page.eval_on_selector_all(
        'div[data-component-type="s-search-result"][data-asin]',
        """els => els.slice(0, 12).map(e => {
            const asin = e.getAttribute('data-asin');
            const titleEl = e.querySelector('h2 span, h2 a span');
            const priceEl = e.querySelector('.a-price .a-offscreen');
            const imgEl = e.querySelector('img.s-image');
            return {
                asin: asin,
                title: titleEl ? titleEl.innerText.trim() : null,
                price: priceEl ? priceEl.innerText.trim() : null,
                image: imgEl ? imgEl.src : null,
            };
        })""",
    )
    out = [it for it in items if it["asin"] and it["title"]]
    return out[:limit]


def main():
    args = sys.argv[1:]
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            r"C:\Users\norio\my-github-blog\data\amazon_search_profile",
            headless=False,
            args=["--start-maximized"],
            viewport={"width": 1280, "height": 900},
            locale="ja-JP",
        )
        page = ctx.new_page()

        if args and args[0] == "--batch":
            qfile = args[1]
            outfile = args[args.index("--out") + 1] if "--out" in args else "amazon_search_results.json"
            with io.open(qfile, encoding="utf-8") as f:
                queries = json.load(f)
            results = {}
            for i, q in enumerate(queries, 1):
                print(f"[{i}/{len(queries)}] {q}", flush=True)
                try:
                    results[q] = search_amazon(page, q)
                except Exception as e:
                    print("  error:", e)
                    results[q] = []
                time.sleep(1.5)
            with io.open(outfile, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print("saved:", outfile)
        else:
            query = " ".join(args) if args else input("検索語: ")
            res = search_amazon(page, query)
            print(json.dumps(res, ensure_ascii=False, indent=2))

        ctx.close()


if __name__ == "__main__":
    main()

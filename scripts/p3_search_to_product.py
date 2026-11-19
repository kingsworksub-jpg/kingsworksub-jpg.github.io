# -*- coding: utf-8 -*-
"""P3: 検索リンク(/s?k=)を、確認済みASINの商品リンク(/dp/)へ置換する。

マッピングは scripts/p3-search-asins.json（実ブラウザで確認した日付・商品名つき）。
確認できていないクエリは一切置換しない（誤商品リンクは検索リンクより有害）。

    target="_blank" / rel / アンカーテキスト / 画像 / タグ値は保持する。
    tag= は元の記事の値をそのまま使う。

使い方:
    python scripts/p3_search_to_product.py            # dry-run
    python scripts/p3_search_to_product.py --apply    # 書き込み
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import urllib.parse

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTS = os.path.join(ROOT, "content", "posts")
MAP = os.path.join(ROOT, "scripts", "p3-search-asins.json")

# href="..." と Markdown の (...) の両方に現れる検索URLを対象にする
SEARCH_URL_RE = re.compile(r'https://www\.amazon\.co\.jp/s\?k=[^"\'<>\s)]+')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    with io.open(MAP, "r", encoding="utf-8-sig") as fh:
        mapping = json.load(fh)
    by_slug: dict[str, dict[str, str]] = {}
    for m in mapping["mappings"]:
        by_slug.setdefault(m["slug"], {})[m["query"]] = m["asin"]

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== P3 search links -> product links ({mode}) ===", flush=True)
    total = 0
    for slug, queries in by_slug.items():
        path = os.path.join(POSTS, slug + ".md")
        if not os.path.exists(path):
            print(f"  [SKIP] {slug}: ファイルなし", flush=True)
            continue
        with io.open(path, "r", encoding="utf-8-sig", newline="") as fh:
            original = fh.read()
        count = 0

        def repl(m: re.Match) -> str:
            nonlocal count
            url = m.group(0)
            parsed = urllib.parse.urlparse(url)
            q = urllib.parse.parse_qs(parsed.query)
            keyword = q.get("k", [""])[0]
            asin = queries.get(keyword)
            if not asin:
                return url
            tag = q.get("tag", ["nakimoto1-22"])[0]
            count += 1
            return f"https://www.amazon.co.jp/dp/{asin}?tag={tag}"

        new = SEARCH_URL_RE.sub(repl, original)
        if not count:
            print(f"  [SKIP] {slug}: 置換対象なし", flush=True)
            continue
        total += count
        print(f"  {slug}: {count}件を商品リンクへ置換", flush=True)
        for q, asin in queries.items():
            print(f"      {q} -> {asin}", flush=True)
        if args.apply:
            with io.open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(new)

    print(f"完了: {total}件" + ("（書き込み済み）" if args.apply else "（dry-run）"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

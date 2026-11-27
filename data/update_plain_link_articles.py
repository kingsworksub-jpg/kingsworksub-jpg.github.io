# -*- coding: utf-8 -*-
"""ASIN無しで公開時にリンクが外れたAmazon導線を修正した記事を検証・再公開する。

使い方:
    python data/update_plain_link_articles.py --check
    python data/update_plain_link_articles.py --update
"""
import argparse
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_module(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BASE, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pa = load_module("pa", "scripts/post-to-ameba.py")

TARGETS = [
    {"slug": "ardbeg-trudernish-15yo", "entry_id": "12985467222", "asins": ["B08148ZT4L", "B075MNCHS5", "B0GV29QWJD"]},
    {"slug": "whisky-year-end-gift-guide-2026", "entry_id": "12982392866", "asins": ["B004BE5WGS"]},
    {"slug": "nanbu-tetsubin-kanzake-yusen", "entry_id": "12982392252", "asins": ["B08M5PTJHY"]},
    {"slug": "urushi-sakazuki-shu-kuro", "entry_id": "12982392138", "asins": ["B0F3W55MMP"]},
    {"slug": "shigaraki-guinomi-hiiro", "entry_id": "12982391957", "asins": ["B087M16VF5"]},
    {"slug": "islay-malt-5choice-2026", "entry_id": "12982393451", "asins": ["B0029ZFVVW", "B002VZY62K"]},
    {"slug": "sherry-cask-5choice-2026", "entry_id": "12982393102", "asins": ["B0H996NSHG", "B08GCN2JB6"]},
    {"slug": "canadian-whisky-rye-4choice-2026", "entry_id": "12982217341", "asins": ["B07P6ZPZ6C", "B0918YX5JQ"]},
]

PHRASES = ["Amazonで価格とレビューを見る", "Amazonで見る", "Amazonでも", "Amazonで確認", "在庫をチェック"]
_BUILD = None


def ensure_build():
    global _BUILD
    if _BUILD is None:
        _BUILD = tempfile.mkdtemp(prefix="ameba-build-once-")
        print("Hugo build (1回のみ)...", flush=True)
        subprocess.run(["hugo", "--destination", _BUILD], cwd=BASE, check=True, capture_output=True)
    return _BUILD


def render_cached(slug, cvr=True):
    build = ensure_build()
    post = os.path.join(build, "posts", slug, "index.html")
    if not os.path.exists(post):
        raise RuntimeError(f"rendered post not found: {post}")
    body = pa.extract_post_content(post)
    if cvr:
        body, changes = pa.cvr_optimize(body, platform="ameba")
        for c in changes:
            print(f"  CVR: {c}")
    py = os.path.join(BASE, "scripts", ".venv", "Scripts", "python.exe")
    if not os.path.exists(py):
        py = sys.executable
    for helper in ("hatena_banner.py", "hatena_figures.py"):
        body = subprocess.run(
            [py, os.path.join(BASE, "scripts", helper)],
            input=body.encode("utf-8"), capture_output=True, check=True,
        ).stdout.decode("utf-8")
    body = pa.shrink_figure_img_attrs(body)
    return pa.rewrite_for(body, "ameba")


pa.render_body_html = render_cached

rows = json.load(io.open(os.path.join(BASE, "data/ameba-all-entries.json"), encoding="utf-8"))
by_id = {}
for r in rows:
    by_id.setdefault(r["id"], r)


def check(rows_to_check):
    from bs4 import BeautifulSoup, NavigableString

    problems = []
    for r in rows_to_check:
        body = render_cached(r["slug"], cvr=True)
        soup = BeautifulSoup(body, "html.parser")
        plain = []
        for node in soup.find_all(string=True):
            if not isinstance(node, NavigableString) or node.find_parent("a"):
                continue
            text = " ".join(str(node).split())
            for phrase in PHRASES:
                if phrase in text:
                    plain.append(f"{phrase}: {text[:60]}")
        # hatena_figures.py が付ける ameba-img-sub-22 の検索リンクは公開時に外れるため無視する。
        asinless = [
            u for u in re.findall(r'https://www\.amazon\.co\.jp/[^"\')\s]+', body)
            if "/dp/" not in u and "ameba-img-sub-22" not in u
        ]
        nested = len(re.findall(r"<p><p ", body))
        ol_ok = body.count("<ol") == body.count("</ol>")
        leftovers = re.findall(r"\[[A-Z_]+:[^\]]+\]", body)
        missing = [a for a in r["asins"] if a not in body]
        risky_figs = []
        for fig in soup.select("figure.photo"):
            if fig.get("data-pick-skip") == "1":
                continue
            if fig.select_one('a[href*="amazon.co.jp/dp/"]'):
                continue
            # 既存の非Amazonリンクがあれば convert_amazon_links_to_pick() はASINを付けない。
            if fig.select_one("a"):
                continue
            # ASIN無しAmazonリンクは公開時に外れ、そのfigureに data-pick-skip が付く。
            if fig.select_one('a[href*="amazon.co.jp/s?k="]'):
                continue
            risky_figs.append(" ".join(fig.get_text(" ", strip=True).split())[:50])
        ok = not plain and not asinless and not nested and ol_ok and not leftovers and not missing and not risky_figs
        print(
            f"{'OK' if ok else 'NG':2s} {r['slug']:44s} plain={len(plain)} asinless={len(asinless)} "
            f"nested={nested} ol={ol_ok} leftovers={len(leftovers)} missing={missing} risky_figs={len(risky_figs)}",
            flush=True,
        )
        for label, items in (("plain", plain), ("asinless", asinless), ("risky_fig", risky_figs)):
            for item in items[:5]:
                print(f"   {label}: {item}")
        if not ok:
            problems.append(r)
    return problems


def update(rows_to_update, retries=3, delay=12):
    failed = []
    for i, r in enumerate(rows_to_update, 1):
        entry = by_id[r["entry_id"]]
        title = entry["title"]
        for attempt in range(1, retries + 1):
            print(f"\n[{i}/{len(rows_to_update)}] {r['slug']} ({r['entry_id']}) attempt={attempt}", flush=True)
            try:
                pa.update_existing_entry(r["entry_id"], r["slug"], title, cvr=True)
                break
            except SystemExit as e:
                reason = f"SystemExit {e.code}"
            except Exception as e:  # noqa: BLE001
                reason = f"{type(e).__name__}: {str(e)[:160]}"
            else:
                reason = ""
            if reason:
                print(f"  公開失敗 ({reason})", flush=True)
                if attempt == retries:
                    failed.append(r["slug"])
                    break
                wait = 45 * attempt
                print(f"  {wait}秒待って再試行します...", flush=True)
                time.sleep(wait)
        if i < len(rows_to_update):
            print(f"  次の記事まで {delay}秒待機", flush=True)
            time.sleep(delay)
    print(f"\n失敗: {len(failed)} 件 {failed}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--update", action="store_true")
    args = ap.parse_args()
    try:
        if args.check:
            problems = check(TARGETS)
            print(f"\n問題あり: {len(problems)} 件")
            if problems:
                sys.exit(1)
        elif args.update:
            update(TARGETS)
        else:
            print("--check または --update を指定してください。")
    finally:
        if _BUILD:
            shutil.rmtree(_BUILD, ignore_errors=True)


if __name__ == "__main__":
    main()

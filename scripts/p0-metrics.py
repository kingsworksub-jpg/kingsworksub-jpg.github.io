# -*- coding: utf-8 -*-
"""P0: 「数値を1枚にする」ための集計スクリプト。

Search Console の「検索結果」レポートを CSV でエクスポートして読み込み、
記事 slug をキーにして以下を 1 枚の Markdown / JSON にまとめる。

  - 記事別: インプレッENSION / クリック / CTR / 平均順位 / ASIN 数 / 検索リンク数
  - クエリ別: インプレッション / クリック / 平均順位 (Top 30)
  - サイト全体: Amazon アソシエイトのクリック / 注文 / 売上 / CVR (手入力 or JSON)

使い方:
    python scripts/p0-metrics.py --sc scripts/p0-sc.csv
    python scripts/p0-metrics.py --sc scripts/p0-sc.csv --amazon scripts/p0-amazon.json

CSV は日本語ヘッダ (ページ/クエリ/インプレッション数/クリック数/CTR/平均順位)
と英語ヘッダ (Page/Query/Impressions/Clicks/CTR/Average position) の両方を扱う。
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTS_DIR = os.path.join(ROOT, "content", "posts")
OUT_MD = os.path.join(ROOT, "scripts", "p0-metrics.md")
OUT_JSON = os.path.join(ROOT, "scripts", "p0-metrics.json")

TAGS = {
    "GitHub Pages": "nakimoto1-22",
    "はてな": "hatena-img-sub-22",
    "note": "note-img-sub-22",
    "Ameba": "ameba-img-sub-22",
    "X": "x-img-22",
}

PAGE_RE = re.compile(r"https?://[^/]+/posts/([^/?#]+)/?")
ASIN_RE = re.compile(r"amazon\.co\.jp/(?:dp|gp/product)/([A-Z0-9]{10})")
SEARCH_LINK_RE = re.compile(r"amazon\.co\.jp/s\?k=")

HEADER_ALIASES = {
    "ページ": "page", "page": "page", "url": "page",
    "クエリ": "query", "query": "query", "検索語": "query",
    "インプレッション数": "impressions", "impressions": "impressions",
    "クリック数": "clicks", "clicks": "clicks",
    "ctr": "ctr",
    "平均順位": "position", "average position": "position", "position": "position",
}


def _to_int(value) -> int:
    try:
        return int(float(str(value).replace(",", "").replace("%", "").strip()))
    except (ValueError, TypeError):
        return 0


def _to_float(value) -> float:
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (ValueError, TypeError):
        return 0.0


def read_csv(path: str):
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            with io.open(path, "r", encoding=enc, newline="") as fh:
                sample = fh.read(4096)
                fh.seek(0)
                rows = list(csv.DictReader(fh))
            if rows:
                return rows, enc
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"CSV を読み込めませんでした: {path}")


def _frontmatter(path: str) -> dict:
    out = {}
    with io.open(path, "r", encoding="utf-8-sig") as fh:
        lines = fh.readlines()
    if not lines or lines[0].strip() != "---":
        return out
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*?)\s*$", line)
        if m:
            value = m.group(2).strip().strip('"').strip("'")
            out[m.group(1)] = value
    return out


def _article_stats(path: str) -> dict:
    with io.open(path, "r", encoding="utf-8-sig") as fh:
        body = fh.read()
    asins = set(ASIN_RE.findall(body))
    return {
        "asins": len(asins),
        "search_links": len(SEARCH_LINK_RE.findall(body)),
        "amazon_links": len(asins) + len(SEARCH_LINK_RE.findall(body)),
    }


def collect_articles() -> dict:
    articles = {}
    for name in os.listdir(POSTS_DIR):
        if not name.endswith(".md"):
            continue
        path = os.path.join(POSTS_DIR, name)
        slug = name[:-3]
        fm = _frontmatter(path)
        if fm.get("draft", "").lower() == "true":
            continue
        articles[slug] = {
            "slug": slug,
            "title": fm.get("title", slug),
            "date": fm.get("date", ""),
            "description": fm.get("description", ""),
            **_article_stats(path),
        }
    return articles


def aggregate(rows) -> tuple:
    per_page = defaultdict(lambda: {"impressions": 0, "clicks": 0, "pos_sum": 0.0})
    per_query = defaultdict(lambda: {"impressions": 0, "clicks": 0, "pos_sum": 0.0})
    normalized = []
    for row in rows:
        item = {}
        for key, value in row.items():
            if key is None:
                continue
            name = HEADER_ALIASES.get(key.strip().lower())
            if name:
                item[name] = value
        normalized.append(item)
        imp = _to_int(item.get("impressions", 0))
        clk = _to_int(item.get("clicks", 0))
        pos = _to_float(item.get("position", 0))
        page = item.get("page", "") or ""
        query = item.get("query", "") or ""
        m = PAGE_RE.search(page)
        if m:
            d = per_page[m.group(1)]
            d["impressions"] += imp
            d["clicks"] += clk
            d["pos_sum"] += pos * imp
        if query and not query.startswith("#"):
            d = per_query[query]
            d["impressions"] += imp
            d["clicks"] += clk
            d["pos_sum"] += pos * imp
    return per_page, per_query


def _finalize(d: dict) -> dict:
    imp = d["impressions"]
    return {
        "impressions": imp,
        "clicks": d["clicks"],
        "ctr": round(d["clicks"] / imp * 100, 2) if imp else 0.0,
        "position": round(d["pos_sum"] / imp, 1) if imp else 0.0,
    }


def priority_note(row: dict) -> str:
    notes = []
    imp = row["impressions"]
    pos = row["position"]
    if imp >= 3000:
        notes.append("P1候補")
    if 10.0 <= pos <= 30.0:
        notes.append("P2候補")
    if "choice" in row["slug"] and row["asins"] >= 3:
        notes.append("比較ハブ")
    if row["asins"] == 0 and row["search_links"] == 0:
        notes.append("商品リンクなし")
    return " / ".join(notes) if notes else "-"


def render(sc_path: str, per_page: dict, per_query: dict, articles: dict, amazon: dict) -> str:
    now = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST")
    merged = []
    for slug, d in per_page.items():
        row = {"slug": slug, **_finalize(d), **articles.get(slug, {
            "title": "(記事ファイルなし)", "date": "", "description": "",
            "asins": 0, "search_links": 0, "amazon_links": 0,
        })}
        row["memo"] = priority_note(row)
        merged.append(row)
    merged.sort(key=lambda r: r["impressions"], reverse=True)

    total_imp = sum(r["impressions"] for r in merged)
    total_clk = sum(r["clicks"] for r in merged)
    covered = sum(1 for r in merged if r["impressions"] > 0 and r["slug"] in articles)

    lines = [
        "# P0 数値サマリ（Search Console × 記事 × Amazon）",
        "",
        f"- 生成: {now}",
        f"- 入力CSV: `{sc_path}`",
        f"- 検索結果に出た記事: **{covered}本** / 公開記事 {len(articles)}本（CSVに無い記事はインプレッション0扱い）",
        f"- 合計インプレッション: **{total_imp:,}** / 合計クリック: **{total_clk:,}**",
        "",
        "## 記事別（インプレッション順）",
        "",
        "| slug | タイトル | IMP | クリック | CTR | 平均順位 | ASIN | 検索リンク | メモ |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in merged[:120]:
        title = r["title"].replace("|", "\\|")[:42]
        lines.append(
            f"| `{r['slug']}` | {title} | {r['impressions']:,} | {r['clicks']:,} | "
            f"{r['ctr']}% | {r['position']} | {r['asins']} | {r['search_links']} | {r['memo']} |"
        )

    lines += [
        "",
        "## 上位クエリ Top 30",
        "",
        "| クエリ | IMP | クリック | 平均順位 |",
        "|---|---:|---:|---:|",
    ]
    queries = sorted(per_query.items(), key=lambda kv: kv[1]["impressions"], reverse=True)[:30]
    for query, d in queries:
        f = _finalize(d)
        lines.append(f"| {query.replace('|', '\\\\|')[:60]} | {f['impressions']:,} | {f['clicks']:,} | {f['position']} |")

    lines += [
        "",
        "## Amazon アソシエイト（サイト全体）",
        "",
    ]
    if amazon:
        for key in ("period", "clicks", "orders", "revenue", "cvr", "approval_status"):
            if key in amazon:
                lines.append(f"- {key}: {amazon[key]}")
        by_tag = amazon.get("by_tracking_id")
        if by_tag:
            lines += ["", "| トラッキングID | 媒体 | クリック | 注文 | 売上 | CVR |", "|---|---|---:|---:|---:|---:|"]
            for tag, d in by_tag.items():
                media = next((k for k, v in TAGS.items() if v == tag), "-")
                lines.append(
                    f"| `{tag}` | {media} | {d.get('clicks', '-')} | {d.get('orders', '-')} | "
                    f"{d.get('revenue', '-')} | {d.get('cvr', '-')} |"
                )
    else:
        lines += [
            "**未入力**（アソシエイト管理画面のレポートから転記するか、 `--amazon <json>` で渡す）",
            "",
            "- period: ",
            "- clicks: ",
            "- orders: ",
            "- revenue: ",
            "- cvr: ",
            "- approval_status: （180日以内3件の本承認）",
            "",
            "既存トラッキングID: " + ", ".join(f"`{v}` ({k})" for k, v in TAGS.items()),
            "※ 現状は**媒体別**まで。記事別の注文は `ascsubtag` または GA4 `affiliate_click` イベント（P4）で紐づける。",
        ]

    lines += [
        "",
        "## 次のアクション",
        "",
        "1. `P1候補` の記事（上位20〜30本）にプランAのCTA/テキストリンク/価格注記/不安解消をバックフィル",
        "2. `P2候補`（順位11〜30）のタイトル・description・h2を修正",
        "3. P4で `affiliate_click` イベントを追加し、記事別CVRを計測可能にする",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="P0 数値サマリを生成する")
    ap.add_argument("--sc", default="scripts/p0-sc.csv", help="Search Console のCSV")
    ap.add_argument("--amazon", default=None, help="アソシエイト数値のJSON（任意）")
    ap.add_argument("--out", default=OUT_MD, help="出力 Markdown")
    args = ap.parse_args()

    sc_path = args.sc if os.path.isabs(args.sc) else os.path.join(ROOT, args.sc)
    if not os.path.exists(sc_path):
        print(f"CSV がありません: {sc_path}\nSearch Console → 検索結果 → エクスポート → CSV を置いてください。", file=sys.stderr)
        return 1

    rows, enc = read_csv(sc_path)
    per_page, per_query = aggregate(rows)
    articles = collect_articles()
    amazon = {}
    if args.amazon:
        a_path = args.amazon if os.path.isabs(args.amazon) else os.path.join(ROOT, args.amazon)
        with io.open(a_path, "r", encoding="utf-8-sig") as fh:
            amazon = json.load(fh)

    md = render(args.sc, per_page, per_query, articles, amazon)
    with io.open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(md)

    payload = {
        "generated_at": datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds"),
        "source_csv": args.sc,
        "encoding": enc,
        "per_page": {k: _finalize(v) for k, v in per_page.items()},
        "per_query": {k: _finalize(v) for k, v in per_query.items()},
        "articles": articles,
        "amazon": amazon,
    }
    with io.open(OUT_JSON, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print(f"OK: {args.out} (CSV {len(rows)} 行 / 記事 {len(per_page)} / エンコーディング {enc})")
    print(f"OK: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

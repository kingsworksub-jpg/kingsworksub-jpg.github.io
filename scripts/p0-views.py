# -*- coding: utf-8 -*-
"""P0 代替: Search Console の代わりに、サイト自身のビュー数(countapi)で記事を並べる。

Google ログインが自動ブラウザで拒否されるため、Search Console CSV が無い場合でも
「どの記事が読まれているか」を把握し、P1 の CVR バックフィル対象を決めるためのスクリプト。

使い方:
    python scripts/p0-views.py

取得元:
    https://countapi.mileshilliard.com/api/v1/get/<key>
    key = kingsworksub-jpg-studionotes-<slug>
    ※ hit エンドポイントはインクリメントするので絶対に使わないこと。

出力:
    scripts/p0-views.md
    scripts/p0-views.json
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTS_DIR = os.path.join(ROOT, "content", "posts")
AMAZON_JSON = os.path.join(ROOT, "scripts", "p0-amazon.json")
OUT_MD = os.path.join(ROOT, "scripts", "p0-views.md")
OUT_JSON = os.path.join(ROOT, "scripts", "p0-views.json")

COUNT_BASE = "https://countapi.mileshilliard.com/api/v1/get/"
KEY_PREFIX = "kingsworksub-jpg-studionotes-"
WORKERS = 8

ASIN_RE = re.compile(r"amazon\.co\.jp/(?:dp|gp/product)/([A-Z0-9]{10})")
SEARCH_LINK_RE = re.compile(r"amazon\.co\.jp/s\?k=")


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
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def collect_articles() -> dict:
    articles = {}
    for name in sorted(os.listdir(POSTS_DIR)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(POSTS_DIR, name)
        slug = name[:-3]
        fm = _frontmatter(path)
        if fm.get("draft", "").lower() == "true":
            continue
        with io.open(path, "r", encoding="utf-8-sig") as fh:
            body = fh.read()
        asins = set(ASIN_RE.findall(body))
        search_links = len(SEARCH_LINK_RE.findall(body))
        articles[slug] = {
            "slug": slug,
            "title": fm.get("title", slug),
            "date": fm.get("date", ""),
            "views": None,
            "asins": len(asins),
            "search_links": search_links,
            "amazon_links": len(asins) + search_links,
        }
    return articles


def fetch_views(slug: str) -> tuple[str, int | None, str | None]:
    key = KEY_PREFIX + slug
    url = COUNT_BASE + urllib.parse.quote(key, safe="")
    last_error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "StudioNotesMetrics/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            value = data.get("value")
            return slug, int(value) if value is not None else None, None
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                # まだ一度も閲覧されていない記事はキーが作られていない → ビュー0扱い
                return slug, 0, None
            last_error = str(exc)
            time.sleep(0.5 * (attempt + 1))
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.5 * (attempt + 1))
    return slug, None, last_error


def load_amazon() -> dict:
    if not os.path.exists(AMAZON_JSON):
        return {}
    with io.open(AMAZON_JSON, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def memo(row: dict) -> str:
    notes = []
    if row["views"] is not None and row["views"] >= 30:
        notes.append("P1候補")
    if row["amazon_links"] == 0:
        notes.append("商品リンクなし")
    elif row["asins"] == 0:
        notes.append("検索リンクのみ")
    return " / ".join(notes) if notes else "-"


def render(articles: dict, amazon: dict, errors: int) -> str:
    now = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST")
    rows = list(articles.values())
    rows.sort(key=lambda r: (r["views"] if r["views"] is not None else -1), reverse=True)
    ranked = [r for r in rows if r["views"] is not None]
    total_views = sum(r["views"] for r in ranked)
    with_links = [r for r in ranked if r["amazon_links"] > 0]

    lines = [
        "# P0 数値サマリ（サイト内ビュー × Amazon）",
        "",
        f"- 生成: {now}",
        f"- ビュー取得元: countapi `kingsworksub-jpg-studionotes-<slug>`（累計・公開後通し）",
        f"- 対象記事: **{len(ranked)}本** / 公開Markdown {len(articles)}本（取得失敗 {errors}本・未閲覧=0含む）",
        f"- 合計ビュー: **{total_views:,}** / Amazonリンクあり記事: **{len(with_links)}本**",
        "",
        "> Search Console は初期設定直後で過去データが無いため、記事別の並びはサイト自身のビュー数を使用。",
        "> インプレッション／検索クエリ／平均順位はSCにデータが溜まってから追加する。",
        "",
        "## Amazon アソシエイト（サイト全体・実数値）",
        "",
    ]
    if amazon:
        for key in ("period", "clicks", "orders", "cvr", "revenue", "commission", "shipped", "returned", "approval_status"):
            if key in amazon:
                lines.append(f"- {key}: {amazon[key]}")
    else:
        lines.append("- **未入力**（`scripts/p0-amazon.json` を確認）")

    lines += [
        "",
        "## 記事別（ビュー順・上位120本）",
        "",
        "| slug | タイトル | ビュー | ASIN | 検索リンク | Amazonリンク | メモ |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for r in rows[:120]:
        title = r["title"].replace("|", "\\|")[:44]
        views = f"{r['views']:,}" if r["views"] is not None else "-"
        lines.append(
            f"| `{r['slug']}` | {title} | {views} | {r['asins']} | {r['search_links']} | "
            f"{r['amazon_links']} | {memo(r)} |"
        )

    lines += [
        "",
        "## P1 候補（ビュー上位 × Amazonリンクあり・最大30本）",
        "",
        "| # | slug | ビュー | Amazonリンク | メモ |",
        "|---:|---|---:|---:|---|",
    ]
    for i, r in enumerate(with_links[:30], 1):
        lines.append(
            f"| {i} | `{r['slug']}` | {r['views']:,} | {r['amazon_links']} | {memo(r)} |"
        )

    lines += [
        "",
        "## 読み込まれているが商品リンクがない記事（上位20本）",
        "",
        "| slug | ビュー |",
        "|---|---:|",
    ]
    for r in [r for r in ranked if r["amazon_links"] == 0][:20]:
        lines.append(f"| `{r['slug']}` | {r['views']:,} |")

    lines += [
        "",
        "## 次のアクション",
        "",
        "1. 上記 P1 候補へ CTA / テキストリンク / 価格注記 / 不安解消をバックフィル",
        "2. 商品リンクなしの高ビュー記事には、まず商品紹介を1つ追加するか、P1対象から外すか判断",
        "3. Search Console にデータが溜まったら `p0-metrics.py --sc scripts/p0-sc.csv` で IMP/順位/クエリを統合",
        "4. P4 で `affiliate_click` イベントを追加し、記事別CVRを計測可能にする",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    articles = collect_articles()
    print(f"公開記事: {len(articles)}本。ビューを取得します...", flush=True)
    errors = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch_views, slug): slug for slug in articles}
        for i, future in enumerate(as_completed(futures), 1):
            slug, views, error = future.result()
            articles[slug]["views"] = views
            if error:
                errors += 1
            if i % 50 == 0:
                print(f"  {i}/{len(articles)}", flush=True)

    amazon = load_amazon()
    md = render(articles, amazon, errors)
    with io.open(OUT_MD, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(md)

    payload = {
        "generated_at": datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds"),
        "source": "countapi (cumulative post views)",
        "articles": articles,
        "amazon": amazon,
        "errors": errors,
    }
    with io.open(OUT_JSON, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    ranked = [r for r in articles.values() if r["views"] is not None]
    print(f"OK: {OUT_MD}")
    print(f"OK: {OUT_JSON}")
    print(f"ビュー取得: {len(ranked)}/{len(articles)}本 / 合計 {sum(r['views'] for r in ranked):,} / 失敗 {errors}本")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""ゼロIMP記事を分類し、内部リンク＋URL検査送信の計画を出す。

入力:
  scripts/p0-sc.csv                    ... page単位のIMP（分母）
  data/sc-inspection-results.json      ... sc-inspect-articles.py の URL検査結果
  content/posts/*.md                   ... 記事メタデータ

出力:
  scripts/zero-imp-plan.md / .json
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTS_DIR = os.path.join(ROOT, "content", "posts")
ASIN_RE = re.compile(r"amazon\.co\.jp/(?:dp|gp/product)/([A-Z0-9]{10})")
SEARCH_LINK_RE = re.compile(r"amazon\.co\.jp/s\?k=")


def collect_articles() -> dict:
    out = {}
    for name in os.listdir(POSTS_DIR):
        if not name.endswith(".md"):
            continue
        path = os.path.join(POSTS_DIR, name)
        with io.open(path, "r", encoding="utf-8-sig") as fh:
            lines = fh.readlines()
        if not lines or lines[0].strip() != "---":
            continue
        fm = {}
        for line in lines[1:]:
            if line.strip() == "---":
                break
            m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*?)\s*$", line)
            if m:
                fm[m.group(1)] = m.group(2).strip().strip('"').strip("'")
        if fm.get("draft", "").lower() == "true":
            continue
        slug = name[:-3]
        out[slug] = {"slug": slug, "title": fm.get("title", slug), "date": fm.get("date", "")}
    # ローカルの未追跡記事は公開対象外なので集計から除く（CIと母集団を合わせる）
    tracked = subprocess.check_output(
        ["git", "ls-files", "content/posts"], cwd=ROOT, text=True, encoding="utf-8"
    ).splitlines()
    tracked_slugs = {os.path.basename(p)[:-3] for p in tracked if p.endswith(".md")}
    return {s: v for s, v in out.items() if s in tracked_slugs}


INSPECTION = os.path.join(ROOT, "data", "sc-inspection-results.json")
OUT_MD = os.path.join(ROOT, "scripts", "zero-imp-plan.md")
OUT_JSON = os.path.join(ROOT, "scripts", "zero-imp-plan.json")

STOP = {
    "2026", "2025", "guide", "deep", "dive", "choice", "choices", "the", "and",
    "for", "with", "into", "from", "how", "why", "what", "best", "new", "all",
    "intro", "guidebook", "complete", "ver", "vol", "mk", "mk2", "mk3", "pro",
    "revival", "deep", "dive", "choice", "5choice", "10choice", "4choice", "3choice",
    "comparison", "review", "basics", "guide",
}

PAGE_RE = re.compile(r"/posts/([^/?#]+)/?")


def sitemap_urls() -> set[str] | None:
    try:
        import urllib.request
        with urllib.request.urlopen("https://kingsworksub-jpg.github.io/sitemap.xml", timeout=20) as r:
            return set(re.findall(r"<loc>([^<]+)</loc>", r.read().decode("utf-8")))
    except Exception:
        return None


def imp_pages() -> dict[str, int]:
    import csv
    out = {}
    with io.open(os.path.join(ROOT, "scripts", "p0-sc.csv"), "r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            page = row.get("ページ", "") or next(iter(row.values()), "")
            m = PAGE_RE.search(page)
            if m:
                out[m.group(1)] = int(float(str(row.get("インプレッション数", 0)).replace(",", "")))
    return out


def tokens(slug: str) -> set[str]:
    out = set()
    for raw in slug.split("-"):
        t = re.sub(r"^\d+", "", raw)  # 5choice -> choice, 10choice -> choice
        if len(t) >= 3 and t not in STOP and not t.isdigit():
            out.add(t)
    return out


def classify(rec: dict | None) -> str:
    if not rec:
        return "未検査"
    if rec.get("error"):
        return "検査失敗"
    cov = rec.get("coverage", "")
    verdict = rec.get("verdict", "")
    if "noindex" in cov.lower() or "redirect" in cov.lower() or "not found" in cov.lower() or verdict == "FAIL":
        return "対象外"
    if "unknown to google" in cov.lower():
        return "未インデックス（未検出）"
    if "not indexed" in cov.lower() or "discovered" in cov.lower():
        return "未インデックス（クロール済み）"
    if verdict == "PASS":
        return "インデックス済み・クエリ無し"
    return f"その他（{verdict} / {cov}）"


def main() -> int:
    articles = collect_articles()
    imp = imp_pages()
    with io.open(INSPECTION, "r", encoding="utf-8") as fh:
        inspected = json.load(fh)
    if not inspected:
        print(f"SKIP: {INSPECTION} が空です。先に sc-inspect-articles.py を実行してください。")
        return 1

    zero = [s for s in articles if s not in imp]
    by_class = defaultdict(list)
    for slug in zero:
        by_class[classify(inspected.get(slug))].append(slug)

    # 内部リンク候補: IMPのある記事とトークンを共有する。共有トークン数×IMPでスコア化。
    imp_tokens = {s: tokens(s) for s in imp}
    link_sources = defaultdict(list)
    for slug in zero:
        ts = tokens(slug)
        scores = []
        for src, st in imp_tokens.items():
            shared = ts & st
            if len(shared) >= 2 or (len(shared) == 1 and len(next(iter(shared))) >= 3):
                score = len(shared) * 10 + min(imp[src], 30) / 3
                scores.append((round(score, 1), src, sorted(shared), imp[src]))
        scores.sort(reverse=True)
        link_sources[slug] = scores[:5]

    rows = []
    for slug in zero:
        rec = inspected.get(slug, {})
        cls = classify(rec if rec else None)
        a = articles[slug]
        with io.open(os.path.join(POSTS_DIR, slug + ".md"), "r", encoding="utf-8-sig") as fh:
            body = fh.read()
        asins = len(ASIN_RE.findall(body))
        searches = len(SEARCH_LINK_RE.findall(body))
        sources = link_sources[slug]
        if cls.startswith("未インデックス") and sources and (asins or searches):
            prio = "P1"
        elif cls.startswith("未インデックス") and sources:
            prio = "P2"
        elif cls == "インデックス済み・クエリ無し":
            prio = "P3"
        elif cls in ("対象外",):
            prio = "P4"
        else:
            prio = "保留"
        rows.append({
            "slug": slug, "title": a["title"], "date": a["date"],
            "class": cls, "priority": prio,
            "asin": asins, "search_link": searches,
            "verdict": rec.get("verdict", ""), "coverage": rec.get("coverage", ""),
            "last_crawl": rec.get("last_crawl", ""),
            "link_sources": [{"slug": s, "shared": sh, "imp": i, "score": sc} for sc, s, sh, i in sources],
        })
    prio_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3, "保留": 4}
    rows.sort(key=lambda r: (prio_order[r["priority"]], -len(r["link_sources"]), r["slug"]))

    counts = defaultdict(int)
    for r in rows:
        counts[r["class"]] += 1
    pc = defaultdict(int)
    for r in rows:
        pc[r["priority"]] += 1

    md = [
        "# ゼロIMP記事 分類と内部リンク／URL検査計画",
        "",
        f"- 生成: {datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M JST')}",
        "- 基準: 直近30日 page単位 SC（`scripts/p0-sc.csv`）に載らない公開記事",
        f"- 対象: **{len(rows)}本** / 公開記事 {len(articles)}本（IMPあり {len(imp)}本）",
        "- URL検査: `scripts/sc-inspect-articles.py` / 結果 `data/sc-inspection-results.json`",
    ]
    sm = sitemap_urls()
    if sm is not None:
        in_sm = sum(1 for s in articles if f"https://kingsworksub-jpg.github.io/posts/{s}/" in sm)
        md.append(f"- sitemap.xml 収録: {in_sm}/{len(articles)}件（未収録でも検索に出ない原因にはならない）")
    md += [
        "",
        "## 分類内訳",
        "",
        "| 分類 | 件数 |",
        "|---|---:|",
    ]
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        md.append(f"| {k} | {v} |")
    md += [
        "",
        "| 優先度 | 件数 | 意味 |",
        "|---|---:|---|",
        f"| P1 | {pc['P1']} | 未インデックス＋内部リンク候補＋商品リンクあり（最初に対応） |",
        f"| P2 | {pc['P2']} | 未インデックス＋内部リンク候補あり |",
        f"| P3 | {pc['P3']} | インデックス済みだがクエリ無し（内部リンクで再活性化） |",
        f"| P4 | {pc['P4']} | 対象外（noindex / リダイレクト / 404） |",
        f"| 保留 | {pc['保留']} | 未インデックスだが関連リンク元候補なし（別途カテゴリ導線が必要） |",
        "",
        "## 対応方針",
        "",
        "1. P1/P2 の記事へ、IMPのある上位記事から内部リンクを1〜2本追加する（下表の `link_sources` を参照）。",
        "2. 内部リンク追加後、Search Console のURL検査で「インデックスに送信」を手動実行する。",
        "   - Indexing API は `GOOGLE_INDEXING_CREDENTIALS` 未登録のため自動通知は無効。",
        "3. P3 はタイトル／description を page 単位の近縁記事に寄せてから内部リンクを追加する。",
        "4. P4 は sitemap と `aliases` を見直し、必要なら noindex を外す。",
        "",
        "## 内部リンク追加計画（P1/P2 上位30件）",
        "",
        "| 追加先（ゼロIMP） | 追加元（IMPあり） | 共通トークン | 追加元IMP |",
        "|---|---|---|---:|",
    ]
    for r in [x for x in rows if x["priority"] in ("P1", "P2")][:30]:
        if not r["link_sources"]:
            continue
        for i, src in enumerate(r["link_sources"][:2]):
            target = f"`{r['slug']}`" if i == 0 else ""
            md.append(
                f"| {target} | `{src['slug']}` | {', '.join(src['shared'])} | {src['imp']} |"
            )
    md += [
        "",
        "## URL検査送信計画（P1/P2 上位30件）",
        "",
        "1. 上記の内部リンクを追加して公開を待つ。",
        "2. Search Console → URL検査 に以下のURLを1件ずつ入力し、「インデックスに送信」を実行する。",
        "",
        "| # | URL | 分類 |",
        "|---:|---|---|",
    ]
    for i, r in enumerate([x for x in rows if x["priority"] in ("P1", "P2")][:30], 1):
        md.append(f"| {i} | https://kingsworksub-jpg.github.io/posts/{r['slug']}/ | {r['class']} |")
    md += [
        "",
        "## 優先記事一覧（上位80件）",
        "",
        "| 優先度 | slug | 分類 | 内部リンク元候補（IMP） | ASIN/検索 |",
        "|---|---|---|---|---|",
    ]
    for r in rows[:80]:
        src = ", ".join(f"`{x['slug']}`({x['imp']})" for x in r["link_sources"][:2]) or "-"
        title = r["title"].replace("|", "\\|")[:28]
        md.append(
            f"| {r['priority']} | `{r['slug']}` / {title} | {r['class']} | {src} | "
            f"{r['asin']}/{r['search_link']} |"
        )
    md += ["", "全件の詳細は `scripts/zero-imp-plan.json` を参照。", ""]

    with io.open(OUT_MD, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(md))
    with io.open(OUT_JSON, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({
            "total_zero_imp": len(rows),
            "counts_by_class": dict(counts),
            "counts_by_priority": dict(pc),
            "rows": rows,
        }, fh, ensure_ascii=False, indent=2)
    print(f"OK: {OUT_MD} / {OUT_JSON} ({len(rows)}本)")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

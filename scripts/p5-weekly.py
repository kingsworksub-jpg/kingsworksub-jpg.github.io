# -*- coding: utf-8 -*-
"""P5: 週次SEOレポートを生成する。

やること:
  1. p0-views.py を実行して記事別ビューを最新化
  2. 前回スナップショットとの差分を計算
  3. 未バックフィルの高ビュー記事を「次のP1候補」として提示
  4. Amazon数値(p0-amazon.json)とGA4数値(p0-ga4.json)、P4計測チェックを1枚にまとめる

使い方:
    python scripts/p5-weekly.py

出力:
    scripts/p5-weekly.md        ... 週次レポート
    scripts/p5-weekly.json      ... 同上の構造化データ
    scripts/p5-snapshot.json    ... 次回の比較用スナップショット
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
VIEWS_JSON = os.path.join(SCRIPTS, "p0-views.json")
AMAZON_JSON = os.path.join(SCRIPTS, "p0-amazon.json")
GA4_JSON = os.path.join(SCRIPTS, "p0-ga4.json")
SNAPSHOT = os.path.join(SCRIPTS, "p5-snapshot.json")
OUT_MD = os.path.join(SCRIPTS, "p5-weekly.md")
OUT_JSON = os.path.join(SCRIPTS, "p5-weekly.json")

# P1で既にCVRパーツを入れた19本（cvr_backfill_md.py の既定対象）
BACKFILLED = {
    "piano-practice-apps-3choice-2026", "sony-pslx3bt-deep-dive-2026",
    "bodum-douro-carafe-deep-dive-2026", "odate-akita-sugi-sake-set-deep-dive-2026",
    "budget-whisky-10choice-2026", "canned-coffee-5choice-2026",
    "sodastream-terra-carbonation-guide-2026", "turntable-5choice-2026",
    "record-stylus-lifespan-guide-2026", "modal-jazz-challenge",
    "condenser-mic-5choice-2026", "sampler-5choice-2026",
    "statement-hat-trends-autumn-2026", "jazz-style-fashion-revival-2026",
    "daw-5choice-2026", "dtm-school-or-self-study-2026",
    "midi-keyboard-5choice-2026", "adult-piano-learning-2026", "anime-and-jazz",
}


def _load(path: str, default=None):
    if not os.path.exists(path):
        return default
    with io.open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def refresh_views() -> dict:
    subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "p0-views.py")],
        check=True,
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
    )
    return _load(VIEWS_JSON, {})


def render(views: dict, prev: dict, amazon: dict, now: str, ga4: dict | None = None) -> tuple[str, dict]:
    articles = views.get("articles", {})
    rows = []
    for slug, a in articles.items():
        views_now = a.get("views") or 0
        views_before = prev.get(slug, 0)
        rows.append({
            "slug": slug,
            "title": a.get("title", slug),
            "views": views_now,
            "delta": views_now - views_before,
            "amazon_links": a.get("amazon_links", 0),
        })
    rows.sort(key=lambda r: r["views"], reverse=True)

    total = sum(r["views"] for r in rows)
    total_prev = sum(v for k, v in prev.items() if k != "_date") if prev else 0
    gainers = sorted(rows, key=lambda r: r["delta"], reverse=True)[:10]

    next_candidates = [
        r for r in rows
        if r["slug"] not in BACKFILLED and r["amazon_links"] > 0 and r["views"] >= 15
    ][:20]
    no_link = [r for r in rows if r["amazon_links"] == 0 and r["views"] >= 5][:10]

    lines = [
        "# P5 週次SEOレポート",
        "",
        f"- 生成: {now}",
        f"- 記事数: **{len(rows)}本** / 合計ビュー: **{total:,}**"
        + (f"（前回比 **{total - total_prev:+,}**）" if prev else "（初回スナップショット）"),
        f"- 比較元: {prev.get('_date', 'なし')}",
        "",
        "## Amazon アソシエイト（前回回収値のまま）",
        "",
    ]
    if amazon:
        for key in ("period", "clicks", "orders", "cvr", "revenue", "approval_status"):
            if key in amazon:
                lines.append(f"- {key}: {amazon[key]}")
        lines.append("- 更新: `python scripts/amazon-associates-probe.py --collect-only`（ローカルのみ）")
    else:
        lines.append("- `scripts/p0-amazon.json` がありません")

    lines += ["", "## GA4（Data API 実数値・直近30日）", ""]
    if ga4 and ga4.get("totals"):
        t = ga4["totals"]
        for key in ("screenPageViews", "activeUsers", "eventCount", "sessions", "keyEvents"):
            if key in t:
                lines.append(f"- {key}: **{t[key]}**")
        pt = ga4.get("posts_totals", {})
        if pt:
            lines.append(
                "- ブログ記事のみ (`/posts/`): pageviews **" + pt.get("screenPageViews", "-")
                + "** / activeUsers **" + pt.get("activeUsers", "-") + "**"
            )
        clicks = ga4.get("affiliate_clicks", [])
        lines.append(f"- affiliate_click イベント: {sum(int(x.get('count', 0)) for x in clicks):,} 件")
        pages = ga4.get("top_pages", [])[:10]
        if pages:
            lines += ["", "| pagePath | pageviews | activeUsers |", "|---|---:|---:|"]
            for p in pages:
                lines.append(
                    f"| `{p.get('page', '')}` | {p.get('screenPageViews', '-')} | {p.get('activeUsers', '-')} |"
                )
        if ga4.get("errors"):
            lines += ["", "- WARN: " + " / ".join(ga4["errors"][:3])]
    else:
        lines.append("- `scripts/p0-ga4.json` がありません（GA4 Data API が無効の可能性）")

    lines += [
        "",
        "## P4 計測の確認チェック",
        "",
        "- [ ] GA4 カスタム定義に `article_slug` / `link_source` / `asin` / `ascsubtag` を登録済みか",
        "- [ ] 「探索」で `affiliate_click` × `記事Slug` が見えているか",
        "- [ ] Amazonリンクの `ascsubtag=kingsworksub-jpg-<slug>` を1件確認したか",
        "",
        "## 先週比で伸びた記事 Top10",
        "",
        "| slug | ビュー | 増分 |",
        "|---|---:|---:|",
    ]
    for r in gainers:
        lines.append(f"| `{r['slug']}` | {r['views']:,} | {r['delta']:+,} |")

    lines += [
        "",
        "## 次のP1候補（未バックフィル・ビュー順 Top20）",
        "",
        "| slug | ビュー | Amazonリンク |",
        "|---|---:|---:|",
    ]
    for r in next_candidates:
        lines.append(f"| `{r['slug']}` | {r['views']:,} | {r['amazon_links']} |")

    lines += [
        "",
        "## 商品リンクなしの高ビュー記事 Top10",
        "",
        "| slug | ビュー |",
        "|---|---:|",
    ]
    for r in no_link:
        lines.append(f"| `{r['slug']}` | {r['views']:,} |")

    slugs_arg = ",".join(r["slug"] for r in next_candidates[:10])
    lines += [
        "",
        "## 今週のアクション",
        "",
        "1. Amazon数値を更新する（上記コマンド）",
        "2. P1候補の上位10本へCVRパーツを適用する:",
        "",
        "   ```bash",
        f"   python scripts/cvr_backfill_md.py --apply --slugs {slugs_arg}",
        "   ```",
        "",
        "3. Search Consoleにデータが溜まってきたら `p0-metrics.py --sc scripts/p0-sc.csv` で順位/クエリを統合",
        "",
    ]
    payload = {
        "generated_at": now,
        "total_views": total,
        "previous_total": total_prev if prev else None,
        "gainers": gainers,
        "next_candidates": next_candidates,
        "no_link_high_views": no_link,
        "amazon": amazon,
        "ga4": ga4 or {},
    }
    return "\n".join(lines), payload


def main() -> int:
    now = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST")
    today = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    prev = _load(SNAPSHOT, {})
    views = refresh_views()
    amazon = _load(AMAZON_JSON, {})
    ga4 = _load(GA4_JSON, {})
    md, payload = render(views, prev, amazon, now, ga4)

    with io.open(OUT_MD, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(md)
    with io.open(OUT_JSON, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    snapshot = {"_date": today}
    for slug, a in views.get("articles", {}).items():
        snapshot[slug] = a.get("views") or 0
    with io.open(SNAPSHOT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=2)

    print(f"OK: {OUT_MD}")
    print(f"OK: {OUT_JSON}")
    print(f"OK: {SNAPSHOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""4つのブログ（GitHub / Hatena / Ameba / note）の日次解析レポートを生成する。

X アカウント解析（scripts/x_consultant.py）と同じ流れで、
日付付きスナップショット -> 指標 -> 相対比較 -> LLM診断 -> 提案 -> Markdown/HTML を残す。
生成した HTML は X タブと一緒に、xaccounting-reports.html のタブとして公開する。

使い方:
    python scripts/blog_consultant.py                 # 通常（note はログイン済みプロファイルから実PVを取得）
    python scripts/blog_consultant.py --skip-llm      # LLM診断をスキップ（ルールベース診断）
    python scripts/blog_consultant.py --no-live       # note の実PV取得をやめローカル索引を使う
    python scripts/blog_consultant.py --only note     # 特定プラットフォームだけ更新
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from x_consultant import parse_json_object, run_opencode
from data_freshness import check as check_freshness

try:
    from blog_prompt_config import PROMPT_SPECS, enum_step, get_all_rules, validate_value
except Exception:  # pragma: no cover - scripts dir is normally on sys.path
    PROMPT_SPECS = {}
    get_all_rules = lambda platform: {}  # type: ignore
    enum_step = lambda key, current, direction: current  # type: ignore
    validate_value = lambda key, value, current=None: (False, "prompt_config_unavailable", None)  # type: ignore

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
OUT = DATA / "blog-consulting"
# タブHTMLはルート直下に置き、file:// で開いたときも相対パスが解決するようにする。
TAB_DIR = BASE / "tabs"
HISTORY_DIR = OUT / "history"
STATE_PATH = OUT / "state.json"
DASHBOARD_PATH = BASE / "xaccounting-reports.html"
X_TAB_PATH = TAB_DIR / "x.html"
MODEL = os.environ.get("BLOG_CONSULT_MODEL", "google/gemini-3.5-flash-lite")
JST = timezone(timedelta(hours=9))
CHART_CDN = "https://cdn.jsdelivr.net/npm/chart.js"

# ---------------------------------------------------------------------------
# プラットフォームごとの指標定義。X と同じく「絶対値＋前期/中央値比」で見る。
# good: 1=大きいほど良い / -1=小さいほど良い / 0=方向中性
# ---------------------------------------------------------------------------
PLATFORMS: dict[str, dict[str, Any]] = {
    "github": {
        "label": "GitHub Pages（メインブログ）",
        "short": "GitHub",
        "url": "https://kingsworksub-jpg.github.io/",
        "source": "GA4（プロパティ全体 + /posts/ 抽出）/ Search Console サンプルCSV / countapi / 記事frontmatter",
        "focus": "検索流入と収益化（表示→クリック→記事PV→アフィリエイト導線）",
        "kpis": ["ga4_pageviews", "github_pageviews", "post_pageviews", "post_view_share_pct",
                 "gsc_impressions", "gsc_clicks", "gsc_ctr_pct", "gsc_sample_pages",
                 "countapi_views_total", "published_articles", "countapi_articles",
                 "affiliate_coverage_pct"],
        "metrics": {
            "ga4_pageviews": ("GA4 PV（30日・全体）", "", 0, 1, "Ameba等を含むGA4プロパティ全体のPV"),
            "github_pageviews": ("GA4 PV（GitHubのみ）", "", 0, 1, "hostName=kingsworksub-jpg.github.io のPV"),
            "ga4_active_users": ("GA4 ユーザー（全体）", "人", 0, 1, "プロパティ全体の30日間ユニーク数"),
            "ga4_sessions": ("GA4 セッション（全体）", "", 0, 1, "プロパティ全体の30日間セッション数"),
            "post_pageviews": ("GitHub記事PV（/posts/）", "", 0, 1, "/posts/ 配下のみ。GitHub記事のPV"),
            "post_view_share_pct": ("記事PVシェア（GitHub比）", "%", 1, 1, "/posts/ PV÷GitHub全体PV"),
            "gsc_impressions": ("SC 表示（サンプル）", "回", 0, 1, "p0-sc.csv に載ったページのみ。全体値ではない"),
            "gsc_clicks": ("SC クリック（サンプル）", "回", 0, 1, "サンプルページの検索流入クリック"),
            "gsc_ctr_pct": ("検索CTR（サンプル）", "%", 2, 1, "サンプルページのクリック÷表示"),
            "gsc_position": ("検索平均順位（サンプル）", "位", 1, -1, "小さいほど上位。サンプルページのみ"),
            "gsc_sample_pages": ("SC サンプルページ数", "ページ", 0, 0, "Search Console母集団のページ数"),
            "countapi_views_total": ("累計記事ビュー（countapi）", "", 0, 1, "countapi が記録した記事別ビューの合計"),
            "views_weekly_delta": ("週次ビュー増分", "", 0, 1, "直近週の合計ビュー増分（p5-weekly）"),
            "affiliate_coverage_pct": ("アフィリリンク率（countapi対象）", "%", 1, 1, "countapi対象記事のうちAmazonリンクありの割合"),
            "published_articles": ("公開記事数（frontmatter）", "本", 0, 0, "draft:true を除く content/posts の記事数"),
            "countapi_articles": ("countapi追跡記事数", "本", 0, 0, "countapi が記事別ビューを記録している数"),
        },
        "charts": [
            ("検索流入（サンプルページ）: 表示 / クリック / CTR",
             ["gsc_impressions", "gsc_clicks", "gsc_ctr_pct"],
             "p0-sc.csv のページのみ。CTRは同軸（%）。表示とクリックの桁差に注意。"),
            ("GA4: 全体 / GitHub / ユーザー", ["ga4_pageviews", "github_pageviews", "ga4_active_users"],
             "全体はAmeba等を含む。GitHubのみ(hostName抽出)と比べて混在の影響を見る。"),
            ("記事の_read_効率", ["post_pageviews", "post_view_share_pct", "countapi_views_total"],
             "記事PVシェア（%）は右上がりだとトップ依存からの脱却を示す。"),
        ],
        "item_title": "代表ページ / 記事（GA4 PV または countapi ビュー順）",
        "item_columns": [("対象", "title"), ("値", "value"), ("補足", "detail")],
    },
    "hatena": {
        "label": "はてなブログ",
        "short": "Hatena",
        "url": "https://kinbro.hatenablog.com/",
        "source": "post-platforms.json / content/posts / category-plan.json（公式PV APIは未接続）",
        "focus": "SEOハブとしての更新継続・比較/深掘り記事の厚み・転載カバレッジ",
        "kpis": ["published_entries", "entries_last_7d", "entries_last_30d", "freshness_days",
                 "hub_ratio_pct", "affiliate_coverage_pct", "avg_body_chars", "cross_post_ratio_pct"],
        "metrics": {
            "published_entries": ("公開エントリ数", "件", 0, 0, "Hatenaへ転載された記事数"),
            "entries_last_7d": ("直近7日投稿", "件", 0, 1, "投稿 cadence（直近7日）"),
            "entries_last_30d": ("直近30日投稿", "件", 0, 1, "投稿 cadence（直近30日）"),
            "freshness_days": ("最終投稿からの日数", "日", 0, -1, "小さいほど新鮮。更新停止の検知"),
            "hub_ratio_pct": ("ハブ/深掘り記事率", "%", 1, 1, "比較・深掘り系記事の割合。SEOハブの柱"),
            "affiliate_coverage_pct": ("アフィリエイトリンク付与率", "%", 1, 1, "Amazonリンクのある記事の割合"),
            "avg_body_chars": ("平均本文文字数", "文字", 0, 1, "本文の厚み。検索意図との一致を推定"),
            "cross_post_ratio_pct": ("全記事との転載カバレッジ", "%", 1, 1, "GitHub記事のうちHatenaにも出ている割合"),
        },
        "charts": [
            ("投稿cadence", ["entries_last_7d", "entries_last_30d"], "日次の積み上げではありません。source更新時に段差が出ます。"),
            ("コンテンツ品質", ["hub_ratio_pct", "affiliate_coverage_pct", "cross_post_ratio_pct"],
             "いずれも%です。高いほどSEOハブ/収益導線として充実。"),
            ("新鮮度と記事の厚み", ["freshness_days", "avg_body_chars"],
             "freshnessは低いほど良い（左軸）。"),
        ],
        "item_title": "最近のエントリ",
        "item_columns": [("タイトル", "title"), ("公開日", "value"), ("slug / entry id", "detail")],
    },
    "ameba": {
        "label": "Ameba",
        "short": "Ameba",
        "url": "https://ameblo.jp/sfd0501/",
        "source": "post-platforms.json / ameba-engage-state.json / content/posts（公式PV APIは未接続）",
        "focus": "投稿継続と他ブログへの交流活動（自動エンゲージの実績を含む）",
        "kpis": ["published_entries", "entries_last_7d", "entries_last_30d", "freshness_days",
                 "outbound_likes_7d", "outbound_follows_7d", "active_days_ratio_30d",
                 "affiliate_coverage_pct"],
        "metrics": {
            "published_entries": ("公開エントリ数", "件", 0, 0, "Amebaへ転載された記事数"),
            "entries_last_7d": ("直近7日投稿", "件", 0, 1, "投稿 cadence（直近7日）"),
            "entries_last_30d": ("直近30日投稿", "件", 0, 1, "投稿 cadence（直近30日）"),
            "freshness_days": ("最終投稿からの日数", "日", 0, -1, "小さいほど新鮮"),
            "outbound_likes_7d": ("いいね（7日）", "件", 0, 1, "自動化が他ブログ記事へ押したいいね数"),
            "outbound_follows_7d": ("フォロー（7日）", "件", 0, 1, "自動化が他ブログをフォローした数"),
            "outbound_likes_30d": ("いいね（30日）", "件", 0, 1, "同上・30日累計"),
            "outbound_follows_30d": ("フォロー（30日）", "件", 0, 1, "同上・30日累計"),
            "active_days_ratio_30d": ("交流実施日率", "%", 1, 1, "30日のうちいいね/フォローがあった日の割合"),
            "affiliate_coverage_pct": ("アフィリエイトリンク付与率", "%", 1, 1, "Amazonリンクのある記事の割合"),
            "avg_body_chars": ("平均本文文字数", "文字", 0, 1, "本文の厚み"),
        },
        "charts": [
            ("交流活動（日次）", ["outbound_likes_7d", "outbound_follows_7d"],
             "直近7日累計。毎日の内訳は下の日次テーブルを参照。"),
            ("投稿cadence", ["entries_last_7d", "entries_last_30d"], "直近7日/30日の投稿件数。"),
            ("継続性と導線", ["freshness_days", "active_days_ratio_30d", "affiliate_coverage_pct"],
             "freshnessは低いほど良い。他は高いほど良い。"),
        ],
        "item_title": "最近のエントリ / 交流の日次内訳",
        "item_columns": [("対象", "title"), ("値", "value"), ("補足", "detail")],
    },
    "note": {
        "label": "note",
        "short": "note",
        "url": "https://note.com/shining_finger01/",
        "source": "note ログインセッションの stats/pv API（実PV）+ note-index.json",
        "focus": "読まれる記事の特定と、エンゲージ（スキ/コメント）率の改善",
        "kpis": ["notes_published", "excluded_deleted_notes", "total_reads", "total_likes",
                 "avg_reads_per_note", "like_rate_pct", "comment_rate_pct",
                 "longform_ratio_pct", "freshness_days"],
        "metrics": {
            "notes_published": ("公開ノート数", "件", 0, 0, "stats API の status=published のみ"),
            "stats_rows_total": ("stats API 生行数", "件", 0, 0, "filter=all の生行数（削除ノート含む）"),
            "excluded_deleted_notes": ("除外: 削除ノート", "件", 0, 0, "status=deleted は集計から除外"),
            "total_reads": ("総読者数（読み）", "", 0, 1, "公開ノートの read_count 合計"),
            "total_likes": ("総スキ数", "", 0, 1, "公開ノートの like_count 合計"),
            "total_comments": ("総コメント数", "", 0, 1, "公開ノートの comment_count 合計"),
            "avg_reads_per_note": ("1 note あたり読者", "", 1, 1, "総読者÷公開ノート数"),
            "like_rate_pct": ("スキ率", "%", 2, 1, "スキ÷読者。記事の共感度"),
            "comment_rate_pct": ("コメント率", "%", 2, 1, "コメント÷読者。議論の生まれやすさ"),
            "paid_ratio_pct": ("有料ノート率", "%", 1, 0, "価格>0 のノート割合（方針によるため方向中性）"),
            "avg_body_chars": ("平均本文文字数", "文字", 0, 1, "note-index の本文文字数平均"),
            "longform_ratio_pct": ("ロングフォーム率", "%", 1, 1, "3000文字以上のノート割合"),
            "freshness_days": ("最終投稿からの日数", "日", 0, -1, "小さいほど新鮮"),
            "notes_last_7d": ("直近7日投稿", "件", 0, 1, "publish_at 基準の投稿件数"),
            "notes_last_30d": ("直近30日投稿", "件", 0, 1, "同上・30日"),
        },
        "charts": [
            ("読者とスキ（実PV）", ["total_reads", "total_likes"], "note stats API の累計値。"),
            ("エンゲージ率", ["like_rate_pct", "comment_rate_pct"], "読みあたりのスキ/コメント率（%）。"),
            ("コンテンツ構造", ["longform_ratio_pct", "paid_ratio_pct", "avg_body_chars"],
             "文字数轴が桁違いなので主に比率の推移を見る。"),
        ],
        "item_title": "読まれているノート",
        "item_columns": [("タイトル", "title"), ("読者", "value"), ("スキ / コメント", "detail")],
    },
}

# 全ブログ共通の「日時」指標。投稿時刻の分布は各タブの時間帯グラフにも出る。
for _spec in PLATFORMS.values():
    _spec["metrics"]["peak_hour"] = ("最多投稿時（JST）", "時", 0, 0,
                                     "直近30日の記事/ノート投稿が最も多い時間帯")
    _spec["kpis"].append("peak_hour")


# ---------------------------------------------------------------------------
# 基本ユーティリティ
# ---------------------------------------------------------------------------
def now_jst() -> datetime:
    return datetime.now(JST)


def date_str(dt: datetime | None = None) -> str:
    return (dt or now_jst()).strftime("%Y-%m-%d")


def ensure_dirs() -> None:
    for p in (OUT, TAB_DIR, HISTORY_DIR):
        p.mkdir(parents=True, exist_ok=True)
    for name in PLATFORMS:
        for sub in ("snapshots", "analyses", "reports", "proposals"):
            (OUT / name / sub).mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else "N/A"), quote=True)


def to_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        f = float(str(value).replace(",", ""))
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def safe_div(a: Any, b: Any, scale: float = 1.0, digits: int = 2) -> float | None:
    av, bv = to_float(a), to_float(b)
    if av is None or bv is None or bv == 0:
        return None
    return round(av / bv * scale, digits)


def parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    if len(s) == 10 and re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        s += "T00:00:00+09:00"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        return dt.astimezone(JST)
    except (ValueError, TypeError):
        return None


def days_since(value: Any, today: datetime | None = None) -> float | None:
    dt = parse_date(value)
    if not dt:
        return None
    base = today or now_jst()
    return round((base - dt).total_seconds() / 86400, 1)


def within_days(value: Any, days: int, today: datetime | None = None) -> bool:
    """直近N日を「今日とその前N-1日」のカレンダー日で判定する。

    時刻を含む 168時間ローリングだと、N日前の早朝投稿が除外されて
    note の管理画面の「直近7日」などとズレるため、日付単位に揃える。
    """
    dt = parse_date(value)
    if not dt:
        return False
    base = (today or now_jst()).date()
    delta = (base - dt.date()).days
    return 0 <= delta < days


def hour_distribution(dates: list[Any]) -> list[int]:
    """直近30日の投稿を JST の時間帯（0-23時）に振り分ける。"""
    buckets = [0] * 24
    for value in dates:
        dt = parse_date(value)
        if dt and within_days(dt, 30):
            buckets[dt.hour] += 1
    return buckets


def peak_of(buckets: list[int]) -> int | None:
    if not buckets or max(buckets) == 0:
        return None
    return buckets.index(max(buckets))


def fmt_value(key: str, value: Any) -> str:
    spec = PLATFORM_METRIC_INDEX.get(key)
    digits = spec[2] if spec else 1
    unit = spec[1] if spec else ""
    if value is None:
        return "N/A"
    if isinstance(value, float):
        text = f"{value:,.{digits}f}"
    elif isinstance(value, int):
        text = f"{value:,}"
    else:
        text = str(value)
    return f"{text}{unit}"


#  Metric metadata flattened for formatting.
PLATFORM_METRIC_INDEX: dict[str, tuple[str, str, int, int, str]] = {}
for _spec in PLATFORMS.values():
    PLATFORM_METRIC_INDEX.update(_spec["metrics"])


def judgment(change_pct: float | None, good: int) -> str:
    if change_pct is None:
        return "比較不可"
    if abs(change_pct) < 5:
        return "横ばい"
    if good == 0:
        return "上昇" if change_pct > 0 else "下降"
    improving = change_pct > 0 if good > 0 else change_pct < 0
    return "改善" if improving else "悪化"


def relative_rows(values: dict[str, Any], history: list[dict[str, Any]], date: str,
                  spec: dict[str, Any]) -> list[dict[str, Any]]:
    past = [h for h in history if h.get("date") != date]
    prev = past[-1].get("values", {}) if past else {}
    rows = []
    for key in spec["metrics"]:
        cur = values.get(key)
        label, unit, digits, good, desc = spec["metrics"][key]
        old = prev.get(key)
        change = safe_div((cur or 0) - (old or 0), old, 100, 1) if isinstance(cur, (int, float)) \
            and isinstance(old, (int, float)) and old else None
        window = [h["values"].get(key) for h in past[-7:]]
        window = [v for v in window if isinstance(v, (int, float))]
        med = round(statistics.median(window), digits) if window else None
        med_change = safe_div((cur or 0) - med, med, 100, 1) if med and isinstance(cur, (int, float)) else None
        rows.append({
            "key": key, "label": label, "current": cur, "change_pct": change,
            "median": med, "median_change_pct": med_change,
            "judgment": judgment(change, good), "desc": desc,
        })
    return rows


# ---------------------------------------------------------------------------
# 記事メタデータ
# ---------------------------------------------------------------------------
def article_meta(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    fm = m.group(1) if m else ""
    body = m.group(2) if m else text

    def get(name: str) -> str:
        hit = re.search(rf"(?m)^{re.escape(name)}:\s*(.*)$", fm)
        if not hit:
            return ""
        return hit.group(1).strip().strip("\"'")

    date_full = get("date")
    date = date_full[:10]
    title = get("title") or path.stem
    amazon_links = len(re.findall(r"https?://(?:www\.)?amazon\.co\.jp/(?:dp|gp/product)/", body))
    draft = get("draft").strip().lower() in ("true", "1", "yes")
    return {"slug": path.stem, "title": title, "date": date, "date_full": date_full,
            "body_chars": len(body), "amazon_links": amazon_links, "draft": draft}


def load_articles() -> dict[str, dict[str, Any]]:
    out = {}
    for path in (BASE / "content" / "posts").glob("*.md"):
        out[path.stem] = article_meta(path)
    return out


def published_article_count(articles: dict[str, dict[str, Any]]) -> int:
    """Hugo のデフォルトに合わせ、draft:true のみを unpublished として扱う。"""
    return sum(1 for a in articles.values() if not a.get("draft"))


def platform_entries(articles: dict[str, dict[str, Any]], id_key: str) -> list[dict[str, Any]]:
    registry = load_json(BASE / "scripts" / "post-platforms.json", {})
    entries = []
    for slug, rec in registry.items():
        entry_id = rec.get(id_key) if isinstance(rec, dict) else None
        if not entry_id:
            continue
        meta = articles.get(slug, {})
        entries.append({
            "slug": slug,
            "title": meta.get("title") or rec.get("title") or slug,
            "date": meta.get("date") or str(rec.get("updated_at") or "")[:10],
            "date_full": meta.get("date_full") or str(rec.get("updated_at") or ""),
            "entry_id": str(entry_id),
            "body_chars": meta.get("body_chars", 0),
            "amazon_links": meta.get("amazon_links", 0),
        })
    entries.sort(key=lambda e: e["date"] or "", reverse=True)
    return entries


def content_values(entries: list[dict[str, Any]], total_articles: int) -> dict[str, Any]:
    recent7 = sum(1 for e in entries if within_days(e["date"], 7))
    recent30 = sum(1 for e in entries if within_days(e["date"], 30))
    dates = [e["date"] for e in entries if e["date"]]
    fresh = min([days_since(d) for d in dates], default=None)
    with_link = sum(1 for e in entries if e["amazon_links"] > 0)
    avg_chars = round(statistics.mean([e["body_chars"] for e in entries if e["body_chars"]]), 1) \
        if entries else None
    hub = sum(1 for e in entries if re.search(r"choice|deep.dive|深掘り|10選|5選|比較",
                                              e["slug"] + " " + e["title"], re.I))
    return {
        "published_entries": len(entries),
        "entries_last_7d": recent7,
        "entries_last_30d": recent30,
        "freshness_days": fresh,
        "affiliate_coverage_pct": safe_div(with_link, len(entries), 100, 1),
        "avg_body_chars": avg_chars,
        "hub_ratio_pct": safe_div(hub, len(entries), 100, 1),
        "cross_post_ratio_pct": safe_div(len(entries), total_articles, 100, 1),
    }


# ---------------------------------------------------------------------------
# プラットフォーム別のスナップショット収集
# ---------------------------------------------------------------------------
def collect_github() -> dict[str, Any]:
    ga4 = load_json(BASE / "scripts" / "p0-ga4.json", {})
    views = load_json(BASE / "scripts" / "p0-views.json", {})
    metrics = load_json(BASE / "scripts" / "p0-metrics.json", {})
    weekly = load_json(BASE / "scripts" / "p5-weekly.json", {})
    totals = ga4.get("totals") or {}
    posts = ga4.get("posts_totals") or {}
    per_page = metrics.get("per_page") or {}
    articles = views.get("articles") or {}
    published = published_article_count(load_articles())

    pv = to_int(totals.get("screenPageViews"))
    github = ga4.get("github_totals") or {}
    if not github:
        github = next((h for h in (ga4.get("host_totals") or [])
                       if h.get("host") == "kingsworksub-jpg.github.io"), {})
    github_pv = to_int(github.get("screenPageViews")) or pv
    post_pv = to_int(posts.get("screenPageViews"))
    impressions = sum(to_int(v.get("impressions")) for v in per_page.values() if isinstance(v, dict))
    clicks = sum(to_int(v.get("clicks")) for v in per_page.values() if isinstance(v, dict))
    positions = [to_float(v.get("position")) for v in per_page.values() if isinstance(v, dict)]
    positions = [p for p in positions if p is not None]
    view_total = sum(to_int(v.get("views")) for v in articles.values() if isinstance(v, dict))
    with_link = sum(1 for v in articles.values() if isinstance(v, dict) and to_int(v.get("amazon_links")) > 0)
    weekly_delta = to_int(weekly.get("total_views")) - to_int(weekly.get("previous_total"))

    # GA4トップページには Ameba（/sfd0501/）等も混ざるため、GitHub記事は /posts/ だけを出す。
    pages = sorted([p for p in (ga4.get("top_pages") or [])
                    if str(p.get("page") or "").startswith("/posts/")],
                   key=lambda x: -to_int(x.get("screenPageViews")))[:5]
    top_articles = sorted(articles.items(), key=lambda kv: -to_int(kv[1].get("views")))[:5]
    items = []
    for row in pages:
        items.append({"title": str(row.get("page") or "/"), "value": to_int(row.get("screenPageViews")),
                      "detail": f"activeUsers {to_int(row.get('activeUsers'))}"})
    for slug, row in top_articles:
        items.append({"title": str(row.get("title") or slug)[:70], "value": to_int(row.get("views")),
                      "detail": f"slug: {slug}"})

    values = {
        "ga4_pageviews": pv,
        "github_pageviews": github_pv,
        "ga4_active_users": to_int(totals.get("activeUsers")),
        "ga4_sessions": to_int(totals.get("sessions")),
        "post_pageviews": post_pv,
        "post_view_share_pct": safe_div(post_pv, github_pv, 100, 1),
        "gsc_impressions": impressions,
        "gsc_clicks": clicks,
        "gsc_ctr_pct": safe_div(clicks, impressions, 100, 2),
        "gsc_position": round(statistics.mean(positions), 1) if positions else None,
        "gsc_sample_pages": len(per_page),
        "countapi_views_total": view_total,
        "views_weekly_delta": weekly_delta,
        "affiliate_coverage_pct": safe_div(with_link, len(articles), 100, 1),
        "published_articles": published,
        "countapi_articles": len(articles),
    }
    hours = hour_distribution([v.get("date") for v in articles.values() if isinstance(v, dict)])
    values["peak_hour"] = peak_of(hours)
    return {
        "platform": "github", "collected_at": now_jst().isoformat(timespec="seconds"),
        "hour_buckets": hours,
        "sources": {
            "ga4": ga4.get("generated_at") or ga4.get("date_range"),
            "ga4_property": ga4.get("property_id"),
            "views": views.get("generated_at"), "metrics": metrics.get("generated_at"),
            "weekly": weekly.get("generated_at"),
            "freshness": check_freshness([
                str(BASE / "scripts" / "p0-ga4.json"),
                str(BASE / "scripts" / "p0-sc.csv"),
                str(BASE / "scripts" / "p0-views.json"),
            ], max_days=7),
        },
        "values": values, "items": items,
        "source_notes": [
            f"GA4: {ga4.get('date_range', 'N/A')}（プロパティ {ga4.get('property_id', 'N/A')} 全体）",
            "GA4全体値には Ameba /sfd0501/ 等も含まれる。GitHub分を hostName で分離し、記事は /posts/ 抽出値を見る",
            f"Search Consoleは p0-sc.csv の {len(per_page)} ページのみ。サイト全体の検索流入ではない",
            f"公開記事数は frontmatter 基準で {published} 本（draft:true 除外）。countapi追跡は {len(articles)} 本",
            "countapi / Search Console / 週次増分は週次Workflowの最新生成物を使用",
            *[f"鮮度: {r['message']}" for r in check_freshness([
                str(BASE / "scripts" / "p0-ga4.json"),
                str(BASE / "scripts" / "p0-sc.csv"),
            ], max_days=7) if r["level"] != "ok"],
        ],
    }


def collect_hatena() -> dict[str, Any]:
    articles = load_articles()
    entries = platform_entries(articles, "hatena_entry")
    published = published_article_count(articles)
    values = content_values(entries, published)
    hours = hour_distribution([e["date_full"] for e in entries])
    values["peak_hour"] = peak_of(hours)
    return {
        "platform": "hatena", "collected_at": now_jst().isoformat(timespec="seconds"),
        "hour_buckets": hours,
        "sources": {"post-platforms": "scripts/post-platforms.json",
                    "articles_published": published},
        "values": values,
        "items": [{"title": e["title"][:70], "value": e["date"] or "日付不明",
                   "detail": f"{e['slug']} / entry {e['entry_id']}"} for e in entries[:8]],
        "source_notes": ["はてなの公式PV/検索レポートAPIは未接続のため、公開・コンテンツ指標で代用",
                         "公開エントリ数は post-platforms.json に記録された転載済み件数（管理画面の記事数とは別）",
                         "転載カバレッジの分母は frontmatter 基準の公開記事数（draft:true 除外）",
                         "entry ID と記事日付は post-platforms.json + frontmatter から取得"],
    }


def collect_ameba() -> dict[str, Any]:
    articles = load_articles()
    entries = platform_entries(articles, "ameba_entry")
    published = published_article_count(articles)
    values = content_values(entries, published)
    engage = load_json(DATA / "ameba-engage-state.json", {})
    daily = engage.get("daily_counts") or {}
    today = now_jst()

    def sum_days(days: int) -> tuple[int, int]:
        likes = follows = 0
        for day, counts in daily.items():
            if within_days(day, days, today) and isinstance(counts, dict):
                likes += to_int(counts.get("likes"))
                follows += to_int(counts.get("follows"))
        return likes, follows

    likes7, follows7 = sum_days(7)
    likes30, follows30 = sum_days(30)
    active = 0
    for day, counts in daily.items():
        if within_days(day, 30, today) and isinstance(counts, dict) and \
                (to_int(counts.get("likes")) + to_int(counts.get("follows"))) > 0:
            active += 1
    values.update({
        "outbound_likes_7d": likes7, "outbound_follows_7d": follows7,
        "outbound_likes_30d": likes30, "outbound_follows_30d": follows30,
        "active_days_ratio_30d": safe_div(active, 30, 100, 1),
    })
    hours = hour_distribution([e["date_full"] for e in entries])
    values["peak_hour"] = peak_of(hours)
    daily_rows = []
    for day in sorted(daily, reverse=True)[:8]:
        counts = daily.get(day) or {}
        daily_rows.append({"title": f"交流 {day}",
                           "value": f"いいね {to_int(counts.get('likes'))}",
                           "detail": f"フォロー {to_int(counts.get('follows'))}"})
    items = [{"title": e["title"][:70], "value": e["date"] or "日付不明",
              "detail": f"{e['slug']} / entry {e['entry_id']}"} for e in entries[:6]] + daily_rows
    return {
        "platform": "ameba", "collected_at": now_jst().isoformat(timespec="seconds"),
        "hour_buckets": hours,
        "sources": {"post-platforms": "scripts/post-platforms.json",
                    "articles_published": published,
                    "engage": "data/ameba-engage-state.json"},
        "values": values, "items": items,
        "source_notes": ["Ameba公式PVは未接続。投稿継続 + 自動交流の実績を指標化",
                         "公開エントリ数は post-platforms.json に記録された転載済み件数（管理画面の記事数とは別）",
                         "転載カバレッジの分母は frontmatter 基準の公開記事数（draft:true 除外）",
                         "交流値はこのPCの ameba-auto-engage.py が記録したいいね/フォロー"],
    }


JS_NOTE_STATS = """async (pg) => {
  const r = await fetch('https://note.com/api/v1/stats/pv?filter=all&page=' + pg,
                        {credentials: 'include'});
  if (r.status !== 200) return {status: r.status};
  const j = await r.json();
  return j.data || {};
}"""


def fetch_note_stats() -> list[dict[str, Any]]:
    """ログイン済みプロファイルで note の実PV/スキ/コメントを取得する。"""
    from playwright.sync_api import sync_playwright

    profile = DATA / "note_user_data"
    if not profile.exists():
        raise RuntimeError(f"note profile not found: {profile}")
    out: list[dict[str, Any]] = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(profile), headless=True,
            args=["--disable-blink-features=AutomationControlled"],
            locale="ja-JP", timezone_id="Asia/Tokyo", ignore_https_errors=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://note.com/", wait_until="domcontentloaded", timeout=60000)
        pg = 1
        while True:
            data = page.evaluate(JS_NOTE_STATS, pg)
            if not isinstance(data, dict) or "note_stats" not in data:
                raise RuntimeError(f"note stats API failed: {str(data)[:200]}")
            rows = data.get("note_stats") or []
            out.extend(rows)
            if data.get("last_page") or not rows or pg > 30:
                break
            pg += 1
        ctx.close()
    return out


def collect_note(live: bool) -> dict[str, Any]:
    index = load_json(BASE / "scripts" / "note-index.json", {})
    notes = index.get("notes") or []
    by_key = {str(n.get("key")): n for n in notes if isinstance(n, dict)}
    stats: list[dict[str, Any]] = []
    notes_used = "note-index.json (ローカル索引)"
    if live:
        try:
            stats = fetch_note_stats()
            notes_used = "note stats API (ログイン済みブラウザ・実PV)"
        except Exception as exc:
            notes_used = f"note-index.json (実PV取得失敗: {str(exc)[:120]})"
    if not stats:
        stats = [{"key": k, "name": n.get("title") or k, "read_count": 0,
                  "like_count": 0, "comment_count": 0} for k, n in by_key.items()]
    # stats/pv?filter=all には deleted も混ざる。note 管理画面の記事数は published のみ。
    raw_count = len(stats)
    published_stats = [r for r in stats
                       if str(r.get("status") or "published").strip().lower() == "published"]
    excluded = raw_count - len(published_stats)
    stats = published_stats

    seen: set[str] = set()
    items = []
    for row in stats:
        key = str(row.get("key") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        meta = by_key.get(key, {})
        items.append({
            "key": key,
            "title": str(row.get("name") or meta.get("title") or key)[:70],
            "reads": to_int(row.get("read_count")),
            "likes": to_int(row.get("like_count")),
            "comments": to_int(row.get("comment_count")),
            "price": to_float(meta.get("price")) or 0.0,
            "body_chars": to_int(meta.get("free_chars")) + to_int(meta.get("paid_chars")),
            "publish_at": meta.get("publish_at") or "",
        })
    items.sort(key=lambda x: -x["reads"])
    total_reads = sum(x["reads"] for x in items)
    total_likes = sum(x["likes"] for x in items)
    total_comments = sum(x["comments"] for x in items)
    paid = sum(1 for x in items if x["price"] > 0)
    longform = sum(1 for x in items if x["body_chars"] >= 3000)
    values = {
        "notes_published": len(items),
        "stats_rows_total": raw_count,
        "excluded_deleted_notes": excluded,
        "total_reads": total_reads,
        "total_likes": total_likes,
        "total_comments": total_comments,
        "avg_reads_per_note": round(total_reads / len(items), 1) if items else None,
        "like_rate_pct": safe_div(total_likes, total_reads, 100, 2),
        "comment_rate_pct": safe_div(total_comments, total_reads, 100, 2),
        "paid_ratio_pct": safe_div(paid, len(items), 100, 1),
        "avg_body_chars": round(statistics.mean([x["body_chars"] for x in items if x["body_chars"]]), 1)
        if items else None,
        "longform_ratio_pct": safe_div(longform, len(items), 100, 1),
        "freshness_days": min([days_since(x["publish_at"]) for x in items
                               if days_since(x["publish_at"]) is not None], default=None),
        "notes_last_7d": sum(1 for x in items if within_days(x["publish_at"], 7)),
        "notes_last_30d": sum(1 for x in items if within_days(x["publish_at"], 30)),
    }
    hours = hour_distribution([x["publish_at"] for x in items])
    values["peak_hour"] = peak_of(hours)
    return {
        "platform": "note", "collected_at": now_jst().isoformat(timespec="seconds"),
        "hour_buckets": hours,
        "sources": {"stats": notes_used, "index_at": index.get("generated_at")},
        "values": values,
        "items": [{"title": x["title"], "value": x["reads"],
                   "detail": f"スキ {x['likes']} / コメント {x['comments']}"} for x in items[:8]],
        "source_notes": [
            notes_used,
            f"stats/pv?filter=all の生 {raw_count} 行のうち status=deleted の {excluded} 行を除外",
            f"集計対象は published {len(published_stats)} 件（管理画面の記事数と同じ口径）",
            "削除済みノートの read_count / like_count / comment_count は合計に含めない",
            "本文文字数/有料率/投稿時刻は note-index.json 由来（note_sync の同期タイミング依存）",
            "取得失敗時の note-index.json は参考値で、管理画面の記事数と一致しない場合がある",
        ],
    }


COLLECTORS = {"github": collect_github, "hatena": collect_hatena,
              "ameba": collect_ameba, "note": collect_note}


# ---------------------------------------------------------------------------
# LLM診断（X と同じ opencode ランナーを使う）
# ---------------------------------------------------------------------------
def fallback_diagnosis(spec: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    bad = [r for r in rows if r["judgment"] == "悪化"]
    good = [r for r in rows if r["judgment"] == "改善"]
    summary = (f"{spec['label']}では {len(good)} 指標が改善、{len(bad)} 指標が悪化。"
               f"注力領域は{spec['focus']}。")
    issues = [f"{r['label']}が前期比 {r['change_pct']:+.1f}%（{r['desc']}）" for r in bad[:4]] or \
             ["明確な悪化はなし。標本が少ないため継続観測が必要。"]
    actions = []
    for r in (bad or rows)[:3]:
        actions.append({
            "title": f"{r['label']}の改善",
            "reason": r["desc"],
            "metric": r["key"],
            "horizon_days": 14,
            "risk": "データ源の更新頻度に注意（即時の変化ではない）",
        })
    return {"summary": summary, "issues": issues, "actions": actions,
            "confidence": "low", "_model": "rule-based"}


def llm_diagnose_all(results: dict[str, dict[str, Any]], relative: dict[str, list[dict[str, Any]]],
                     attempts: list[str]) -> dict[str, dict[str, Any]]:
    payload = {}
    for name, result in results.items():
        spec = PLATFORMS[name]
        payload[name] = {
            "label": spec["label"], "focus": spec["focus"],
            "values": result["snapshot"]["values"],
            "relative": [{k: r[k] for k in ("label", "current", "change_pct", "median_change_pct",
                                           "judgment", "desc")} for r in relative[name]],
            "top_items": result["snapshot"].get("items", [])[:5],
            "source_notes": result["snapshot"].get("source_notes", []),
        }
    prompt = (
        "You are a Japanese content analyst. Analyze the daily metrics of 4 blogs and "
        "return ONLY one JSON object keyed by platform names (github, hatena, ameba, note). "
        "Each value must be an object with: summary (string, <=180 Japanese chars), "
        "issues (array of <=4 short Japanese strings), actions (array of <=3 objects with "
        "title, reason, metric, horizon_days, risk), confidence (high/medium/low). "
        "Use only the given numbers, avoid unsupported claims, and note when a platform has "
        "no native PV data. Do not output markdown fences.\n\nDATA:\n"
        + json.dumps(payload, ensure_ascii=False)[:24000]
    )
    ok, text = run_opencode(prompt, MODEL, timeout=300)
    attempts.append(f"{MODEL}: ok={ok}")
    parsed = parse_json_object(text) if ok else None
    if not isinstance(parsed, dict):
        attempts.append("fallback: rule-based diagnosis")
        return {}
    return {name: parsed[name] for name in results if isinstance(parsed.get(name), dict)}


# ---------------------------------------------------------------------------
# 自動プロンプト調整（レポート -> deploy -> ブログ記事生成LLM）
# LLMの自由文ではなく、blog_prompt_config.py の allowlist ノブだけを動かす。
# ---------------------------------------------------------------------------
PROMPT_SAMPLE_MIN = 5


def _as_num(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _prompt_arrow(hint: dict[str, Any]) -> str:
    before, after = hint.get("before"), hint.get("value")
    try:
        return "↑" if float(after) > float(before) else "↓"
    except Exception:
        spec = PROMPT_SPECS.get(str(hint.get("key"))) or {}
        allowed = list(spec.get("allowed") or [])
        if before in allowed and after in allowed:
            return "↑" if allowed.index(after) > allowed.index(before) else "↓"
    return "→"


def _prompt_sample_size(name: str, values: dict[str, Any]) -> int:
    keys = {
        "github": ("gsc_sample_pages", "countapi_articles", "published_articles"),
        "hatena": ("entries_last_30d", "published_entries"),
        "ameba": ("entries_last_30d", "published_entries"),
        "note": ("notes_last_30d", "notes_published"),
    }.get(name, ())
    for key in keys:
        n = _as_num(values.get(key))
        if n is not None and n >= PROMPT_SAMPLE_MIN:
            return int(n)
    return 0


def _row_judgment(rows: list[dict[str, Any]], key: str) -> str:
    for row in rows:
        if row.get("key") == key:
            return str(row.get("judgment") or "")
    return ""


def _suggest_prompt_hints(name: str, values: dict[str, Any],
                          rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """指標のみから prompt_set を決める決定論ルール。LLM出力は使わない。"""
    if not PROMPT_SPECS:
        return []
    sample = _prompt_sample_size(name, values)
    if sample < PROMPT_SAMPLE_MIN:
        # 標本が少ないときはプロンプトを動かさない（X の deploy hint と同じ方針）。
        return []

    effective = get_all_rules(name)
    hints: list[dict[str, Any]] = []

    def add(key: str, target: Any, rule: str, reason: str) -> None:
        before = effective.get(key)
        ok, _why, value = validate_value(key, target, before)
        if not ok or value == before:
            return
        hints.append({
            "type": "prompt_set",
            "key": key,
            "value": value,
            "before": before,
            "platform": name,
            "auto_safe": True,
            "rule": rule,
            "reason": f"sample={sample} {reason}",
        })

    body = _as_num(values.get("avg_body_chars"))
    longform = _as_num(values.get("longform_ratio_pct"))
    like_rate = _as_num(values.get("like_rate_pct"))
    comment_rate = _as_num(values.get("comment_rate_pct"))
    ctr = _as_num(values.get("gsc_ctr_pct"))
    position = _as_num(values.get("gsc_position"))

    thin = (body is not None and body < 2600) or (longform is not None and longform < 30)
    thick = (body is not None and body >= 6500) or (longform is not None and longform >= 70)
    worse = any(_row_judgment(rows, k) == "悪化"
                for k in ("gsc_ctr_pct", "like_rate_pct", "comment_rate_pct", "avg_reads_per_note"))
    improved = any(_row_judgment(rows, k) == "改善"
                   for k in ("gsc_ctr_pct", "like_rate_pct", "comment_rate_pct", "avg_reads_per_note"))
    cta_weak = ((like_rate is not None and like_rate <= 1.0)
                or (comment_rate is not None and comment_rate <= 0.2)
                or (ctr is not None and ctr <= 2.0)
                or (position is not None and position >= 15))
    cta_strong = ((like_rate is not None and like_rate >= 3.0)
                  or (comment_rate is not None and comment_rate >= 0.5)
                  or (ctr is not None and ctr >= 4.0))

    # 厚みが足りない -> 文字数下限と見出し数を1段だけ上げる。逆に長期化＋CTR悪化なら戻す。
    if thin:
        spec = PROMPT_SPECS.get("BLOG_MIN_BODY_CHARS") or {}
        add("BLOG_MIN_BODY_CHARS",
            int(effective.get("BLOG_MIN_BODY_CHARS", spec.get("default", 5000))) + int(spec.get("step", 500)),
            "R_PROMPT_THIN_CONTENT", "avg_body_chars/longform_ratio が下限近く")
        add("BLOG_HEADING_MIN",
            int(effective.get("BLOG_HEADING_MIN", 7)) + 1,
            "R_PROMPT_THIN_CONTENT", "情報量を増やすため見出しを1つ増やす")
    elif thick and worse:
        spec = PROMPT_SPECS.get("BLOG_MIN_BODY_CHARS") or {}
        add("BLOG_MIN_BODY_CHARS",
            int(effective.get("BLOG_MIN_BODY_CHARS", spec.get("default", 5000))) - int(spec.get("step", 500)),
            "R_PROMPT_TOO_LONG", "長文かつエンゲージ悪化")
        add("BLOG_HEADING_MIN", int(effective.get("BLOG_HEADING_MIN", 7)) - 1,
            "R_PROMPT_TOO_LONG", "冗長な章を減らす")

    # CTA / 読後アクションの強弱。強い反応が出たら段階的に既定へ戻す。
    if cta_weak:
        add("BLOG_CTA_LEVEL", enum_step("BLOG_CTA_LEVEL", effective.get("BLOG_CTA_LEVEL"), +1),
            "R_PROMPT_CTA_WEAK", "スキ/コメント率・検索CTR が低い")
    elif cta_strong and improved and effective.get("BLOG_CTA_LEVEL") != "standard":
        add("BLOG_CTA_LEVEL", enum_step("BLOG_CTA_LEVEL", effective.get("BLOG_CTA_LEVEL"), -1),
            "R_PROMPT_CTA_RECOVERED", "反応が改善したため既定の導線へ戻す")

    # 比較表 / 実践寄りに寄せる。改善が出たら段階的に既定へ戻す。
    if thin or (comment_rate is not None and comment_rate <= 0.2) or (position is not None and position >= 15):
        add("BLOG_DEPTH_STYLE", enum_step("BLOG_DEPTH_STYLE", effective.get("BLOG_DEPTH_STYLE"), +1),
            "R_PROMPT_DEPTH_WEAK", "厚み・コメント・検索順位のいずれかが弱い")
    elif improved and effective.get("BLOG_DEPTH_STYLE") != "standard":
        add("BLOG_DEPTH_STYLE", enum_step("BLOG_DEPTH_STYLE", effective.get("BLOG_DEPTH_STYLE"), -1),
            "R_PROMPT_DEPTH_RECOVERED", "指標が改善したため既定の構成へ戻す")

    return hints[:4]


# ---------------------------------------------------------------------------
# 提案・Markdown
# ---------------------------------------------------------------------------
def build_proposal(name: str, date: str, diagnosis: dict[str, Any],
                   rows: list[dict[str, Any]]) -> dict[str, Any]:
    spec = PLATFORMS[name]
    values = {r.get("key"): r.get("current") for r in rows if isinstance(r, dict)}
    prompt_hints = _suggest_prompt_hints(name, values, rows or [])
    actions = []
    for idx, raw in enumerate(diagnosis.get("actions") or [], start=1):
        if not isinstance(raw, dict):
            continue
        actions.append({
            "id": f"{name}-{date}-{idx:02d}",
            "title": str(raw.get("title") or "改善アクション"),
            "reason": str(raw.get("reason") or ""),
            "metric": str(raw.get("metric") or ""),
            "horizon_days": to_int(raw.get("horizon_days")) or 14,
            "risk": str(raw.get("risk") or "なし"),
            "status": "proposed",
            "auto_apply": False,
        })
    for hint in prompt_hints:
        arrow = _prompt_arrow(hint)
        actions.append({
            "id": f"{name}-{date}-prompt-{len(actions) + 1:02d}",
            "title": f"自動プロンプト調整: {hint['key']} {hint.get('before')} {arrow} {hint.get('value')}",
            "reason": hint.get("reason", ""),
            "metric": hint.get("rule", ""),
            "horizon_days": 7,
            "risk": "low",
            "status": "proposed",
            "requires_approval": False,
            "auto_apply": True,
            "deploy": hint,
        })
    return {
        "date": date, "platform": name, "label": spec["label"],
        "generated_at": now_jst().isoformat(timespec="seconds"),
        "model": diagnosis.get("_model", MODEL),
        "confidence": diagnosis.get("confidence", "n/a"),
        "summary": diagnosis.get("summary", ""),
        "issues": diagnosis.get("issues") or [],
        "actions": actions,
        "prompt_changes": prompt_hints,
        "prompt_changes_auto_safe": bool(prompt_hints),
        "guardrails": [
            "プラットフォームへの自動投稿/自動削除は行わない（外部操作は提案のみ。プロンプトノブのみ自動適用）",
            "数値は日次スナップショット。sourceが週次更新のため短期の変化は慎重に読む",
            "GA4全体値には他ブログを含む。GSCはサンプルページのみ。noteは削除済みを除外",
            "プロンプト調整は allowlist ノブのみ。LLMによる本文書き換えは行わない",
        ],
        "phase": "proposal-plus-auto-prompt",
    }


def render_markdown(name: str, date: str, result: dict[str, Any],
                    rows: list[dict[str, Any]], diagnosis: dict[str, Any],
                    proposal: dict[str, Any]) -> str:
    spec = PLATFORMS[name]
    lines = [
        f"# {spec['label']} 日次解析レポート（{date}）", "",
        f"- 対象: {spec['url']}",
        f"- 注力領域: {spec['focus']}",
        f"- データ源: {spec['source']}",
        f"- 収集時刻: {result['snapshot']['collected_at']}", "",
        "## 指標（現在値と前期比）", "",
        "| 指標 | 現在値 | 前期比 | 中央値比 | 判定 | 内容 |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    for r in rows:
        lines.append(f"| {r['label']} | {fmt_value(r['key'], r['current'])} | "
                     f"{_pct(r['change_pct'])} | {_pct(r['median_change_pct'])} | "
                     f"{r['judgment']} | {r['desc']} |")
    lines += ["", "## LLM診断", "", str(diagnosis.get("summary") or "N/A"), "", "### 課題", ""]
    lines += [f"- {x}" for x in diagnosis.get("issues") or []] or ["- N/A"]
    lines += ["", "### 次アクション", ""]
    for action in proposal["actions"]:
        lines.append(f"- **{action['title']}** — 指標: `{action['metric']}` / "
                     f"horizon: {action['horizon_days']}d / risk: {action['risk']}")
    lines += ["", "## 自動プロンプト調整（レポート→実運用）", ""]
    prompt_hints = proposal.get("prompt_changes") or []
    if prompt_hints:
        for hint in prompt_hints:
            lines.append(f"- **{hint.get('key')}**: {hint.get('before')} "
                         f"{_prompt_arrow(hint)} {hint.get('value')} "
                         f"(rule: `{hint.get('rule')}` / {hint.get('reason')})")
    else:
        lines.append("- 今回の調整はなし（標本不足または既に安全な範囲）")
    lines += [
        "- allowlist / min / cap / step / cooldown の範囲で `x_deploy.py --auto-safe` が自動適用し、"
        "`oc_generate.py` が次回記事生成から読み込む。",
        "- KPI悪化時は `x_verify.py --apply-rollbacks` が自動で巻き戻す（前値を復元）。",
        "- LLMにプロンプト本文の自由記述はさせず、許可されたノブだけを切り替える。",
    ]
    lines += ["", "## データ出典", ""]
    lines += [f"- {n}" for n in result["snapshot"].get("source_notes", [])]
    lines.append("")
    return "\n".join(lines)


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:+.1f}%"


# ---------------------------------------------------------------------------
# HTML（各タブ）
# ---------------------------------------------------------------------------
TAB_CSS = """
:root{--bg:#f4f7fb;--card:#fff;--text:#182230;--muted:#5b6b7f;--line:#dbe5f0;--good:#1a7f37;--warn:#b54708}
*,*::before,*::after{box-sizing:border-box}
html,body{max-width:100%;overflow-x:hidden}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Kaku Gothic ProN",Meiryo,sans-serif;background:var(--bg);color:var(--text);line-height:1.65}
.wrap{width:100%;max-width:1280px;margin:0 auto;padding:14px}
@media(min-width:768px){.wrap{padding:24px}}
h1{margin:0 0 6px;font-size:clamp(20px,4.5vw,27px);overflow-wrap:anywhere}
h2{font-size:16px;margin:0 0 12px;overflow-wrap:anywhere}
.sub{color:var(--muted);margin-bottom:18px;font-size:13px;overflow-wrap:anywhere}
.grid{display:grid;gap:14px;min-width:0}
.kpis{grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));margin-bottom:14px}
.charts{grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));margin-bottom:14px}
.two{grid-template-columns:repeat(auto-fit,minmax(min(100%,400px),1fr));margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;box-shadow:0 1px 2px rgba(0,0,0,.03);min-width:0;overflow-wrap:anywhere}
.kpi .label{color:var(--muted);font-size:12px}
.kpi .value{font-size:clamp(20px,5vw,27px);font-weight:700;margin-top:6px}
.kpi .delta{font-size:12px;color:var(--muted);margin-top:4px;overflow-wrap:anywhere}
.table-wrap{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:13px;table-layout:auto}
th,td{padding:8px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left;overflow-wrap:anywhere;word-break:break-word}
th{color:var(--muted);font-weight:600}
.chart-box{position:relative;width:100%;height:250px}
@media(min-width:768px){.chart-box{height:300px}}
canvas{max-width:100%!important;max-height:100%!important}
ul{margin:0;padding-left:18px}li{margin:6px 0;overflow-wrap:anywhere}
.muted{color:var(--muted)}
.pill{display:inline-block;background:#eef6ff;color:#0b5cad;border-radius:999px;padding:2px 8px;font-size:11px;margin:2px 4px 2px 0}
.good{color:var(--good)}.warn{color:var(--warn)}
@media(max-width:640px){
 table.responsive thead{display:none}
 table.responsive,table.responsive tbody,table.responsive tr,table.responsive td{display:block;width:100%}
 table.responsive tr{border:1px solid var(--line);border-radius:10px;margin-bottom:10px;padding:4px}
 table.responsive td{border-bottom:1px dotted var(--line);padding:6px 8px}
 table.responsive td:last-child{border-bottom:0}
 table.responsive td::before{content:attr(data-label);display:block;color:var(--muted);font-size:11px;font-weight:600}
 .chart-box{height:220px}
}
"""


def render_tab_html(name: str, date: str, result: dict[str, Any],
                    rows: list[dict[str, Any]], diagnosis: dict[str, Any],
                    proposal: dict[str, Any], history: list[dict[str, Any]]) -> str:
    spec = PLATFORMS[name]
    values = result["snapshot"]["values"]
    by_key = {r["key"]: r for r in rows}

    kpi_cards = []
    for key in spec["kpis"]:
        row = by_key.get(key)
        delta = _pct(row["change_pct"] if row else None)
        label = spec["metrics"][key][0]
        kpi_cards.append(
            f'<div class="card kpi"><div class="label">{esc(label)}</div>'
            f'<div class="value">{esc(fmt_value(key, values.get(key)))}</div>'
            f'<div class="delta">前期比 {esc(delta)} / 中央値比 '
            f'{esc(_pct(row["median_change_pct"] if row else None))}</div></div>')

    rel_rows = []
    for r in rows:
        cls = "good" if r["judgment"] == "改善" else ("warn" if r["judgment"] == "悪化" else "muted")
        rel_rows.append(
            "<tr>"
            f"<td data-label='指標:'>{esc(r['label'])}</td>"
            f"<td data-label='現在値:'>{esc(fmt_value(r['key'], r['current']))}</td>"
            f"<td data-label='前期比:'>{esc(_pct(r['change_pct']))}</td>"
            f"<td data-label='中央値比:'>{esc(_pct(r['median_change_pct']))}</td>"
            f"<td data-label='判定:' class='{cls}'>{esc(r['judgment'])}</td>"
            f"<td data-label='内容:'>{esc(r['desc'])}</td></tr>")

    item_rows = []
    for item in result["snapshot"].get("items", [])[:10]:
        cells = "".join(
            f"<td data-label='{esc(label)}:'>{esc(item.get(key))}</td>"
            for label, key in spec["item_columns"])
        item_rows.append("<tr>" + cells + "</tr>")
    item_head = "".join(f"<th>{esc(label)}</th>" for label, _ in spec["item_columns"])

    issues = "".join(f"<li>{esc(x)}</li>" for x in diagnosis.get("issues") or []) or "<li>N/A</li>"
    actions = []
    for action in proposal["actions"]:
        actions.append(
            f"<li><b>{esc(action['title'])}</b><br>"
            f"<span class='muted'>{esc(action['reason'])}</span><br>"
            f"<span class='pill'>metric: {esc(action['metric'])}</span>"
            f"<span class='pill'>horizon: {action['horizon_days']}d</span>"
            f"<span class='pill'>risk: {esc(action['risk'])}</span></li>")
    actions_html = "".join(actions) or "<li>提案なし</li>"

    prompt_items = []
    for hint in proposal.get("prompt_changes") or []:
        prompt_items.append(
            "<li><b>" + esc(hint.get("key")) + "</b>: "
            + esc(hint.get("before")) + " " + esc(_prompt_arrow(hint)) + " " + esc(hint.get("value"))
            + "<br><span class='muted'>rule: " + esc(hint.get("rule"))
            + " / " + esc(hint.get("reason")) + "</span></li>")
    prompt_html = (
        '<div class="card" style="margin-top:16px"><h2>自動プロンプト調整（レポート→実運用）</h2><ul>'
        + ("".join(prompt_items) or "<li>今回の調整はなし（標本不足または既に安全な範囲）</li>")
        + "</ul><p class='muted'>allowlist / min / cap / step / cooldown の範囲で "
          "<code>x_deploy.py --auto-safe</code> が適用し、<code>oc_generate.py</code> が次回記事生成から読み込みます。"
          "KPI悪化時は <code>x_verify.py --apply-rollbacks</code> が前値へ戻します。"
          "LLMにプロンプト本文の自由記述はさせません。</p></div>")

    labels = [h["date"] for h in history]
    series = {}
    for chart in spec["charts"]:
        for key in chart[1]:
            series[key] = [h["values"].get(key) for h in history]
    charts_html, scripts = [], []
    for idx, (title, keys, note) in enumerate(spec["charts"]):
        cid = f"chart{idx}"
        datasets = []
        for j, key in enumerate(keys):
            label = spec["metrics"][key][0]
            color = ["#1d9bf0", "#ef4444", "#10b981"][j % 3]
            datasets.append({"label": label, "data": series.get(key, []),
                             "borderColor": color, "backgroundColor": color + "55",
                             "tension": 0.2, "fill": False})
        charts_html.append(
            f'<div class="card"><h2>{esc(title)}</h2><div class="chart-box">'
            f'<canvas id="{cid}"></canvas></div><p class="muted">{esc(note)}</p></div>')
        config = {"type": "line", "data": {"labels": labels, "datasets": datasets},
                  "options": {"responsive": True, "maintainAspectRatio": False,
                              "interaction": {"mode": "index", "intersect": False},
                              "plugins": {"legend": {"position": "bottom"}}}}
        scripts.append(f"new Chart(document.getElementById('{cid}'), {json.dumps(config, ensure_ascii=False)});")

    # 日時帯（JST）の投稿分布。X のレポートには無い、ブログ特有の「いつ投稿しているか」指標。
    hour_buckets = result["snapshot"].get("hour_buckets")
    if hour_buckets:
        charts_html.append(
            '<div class="card"><h2>投稿時間帯（JST / 直近30日）</h2>'
            '<div class="chart-box"><canvas id="chartHour"></canvas></div>'
            '<p class="muted">記事/ノートの公開時刻を0-23時に集計。投稿スケジュールの偏りを確認する。</p></div>')
        hour_config = {
            "type": "bar",
            "data": {"labels": [f"{h:02d}:00" for h in range(24)],
                     "datasets": [{"label": "投稿数", "data": hour_buckets,
                                   "backgroundColor": "rgba(29,155,240,.55)",
                                   "borderColor": "#1d9bf0"}]},
            "options": {"responsive": True, "maintainAspectRatio": False,
                        "plugins": {"legend": {"display": False}}},
        }
        scripts.append("new Chart(document.getElementById('chartHour'), "
                       + json.dumps(hour_config, ensure_ascii=False) + ");")

    notes_html = "".join(f"<li>{esc(x)}</li>" for x in result["snapshot"].get("source_notes", []))
    attempts = "".join(f"<li>{esc(x)}</li>" for x in diagnosis.get("_attempts", [])) or "<li>N/A</li>"

    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(spec['label'])} 日次解析レポート</title>
<script src="{CHART_CDN}"></script>
<style>{TAB_CSS}</style></head><body><div class="wrap">
<h1>{esc(spec['label'])} 日次解析</h1>
<div class="sub">{esc(spec['url'])} / 最終更新: {esc(now_jst().strftime('%Y-%m-%d %H:%M JST'))} / 対象日: {esc(date)} / 注力領域: {esc(spec['focus'])}</div>
<div class="grid kpis">{''.join(kpi_cards)}</div>
<div class="card" style="margin-bottom:14px"><h2>全パラメータの相対比較（客観判定）</h2>
<p class="muted">前期比±5%以上で改善/悪化、±5%未満は横ばい。中央値比は直近7観測の中央値との差。判定の向きは指標ごとに設定。</p>
<div class="table-wrap"><table class="responsive"><thead><tr><th>指標</th><th>現在値</th><th>前期比</th><th>中央値比</th><th>判定</th><th>内容</th></tr></thead>
<tbody>{''.join(rel_rows)}</tbody></table></div></div>
<div class="grid charts">{''.join(charts_html)}</div>
<div class="grid two">
 <div class="card"><h2>LLM診断サマリー</h2><p><b>model:</b> {esc(diagnosis.get('_model', MODEL))} / <b>confidence:</b> {esc(diagnosis.get('confidence', 'n/a'))}</p>
  <p>{esc(diagnosis.get('summary') or 'N/A')}</p><h2>課題</h2><ul>{issues}</ul></div>
 <div class="card"><h2>次アクション（LLM提案）</h2><ul>{actions_html}</ul>
  <h2>LLM試行ログ</h2><ul>{attempts}</ul></div>
</div>
{prompt_html}
<div class="card" style="margin-top:16px"><h2>{esc(spec['item_title'])}</h2>
 <div class="table-wrap"><table class="responsive"><thead><tr>{item_head}</tr></thead><tbody>{''.join(item_rows)}</tbody></table></div></div>
<div class="card" style="margin-top:16px"><h2>データ出典と注意</h2><ul>{notes_html}</ul>
 <p class="muted">X と同じく日付付きスナップショットを蓄積して推移を作ります。sourceごとの更新頻度の違いに注意してください。</p></div>
</div><script>
{''.join(scripts)}
</script></body></html>
"""


DASHBOARD_CSS = """
:root{--bg:#f4f7fb;--card:#fff;--text:#182230;--muted:#5b6b7f;--line:#dbe5f0;--accent:#1d9bf0}
*,*::before,*::after{box-sizing:border-box}
html,body{max-width:100%;overflow-x:hidden}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Kaku Gothic ProN",Meiryo,sans-serif;background:var(--bg);color:var(--text)}
.wrap{width:100%;max-width:1320px;margin:0 auto;padding:12px}
@media(min-width:768px){.wrap{padding:20px}}
h1{margin:0 0 4px;font-size:clamp(19px,4.4vw,27px);overflow-wrap:anywhere}
.sub{color:var(--muted);font-size:13px;margin-bottom:14px;overflow-wrap:anywhere}
.tabs{display:flex;gap:6px;overflow-x:auto;-webkit-overflow-scrolling:touch;padding-bottom:6px;margin-bottom:10px}
.tab{flex:0 0 auto;border:1px solid var(--line);background:var(--card);color:var(--muted);border-radius:999px;padding:7px 14px;font-size:13px;cursor:pointer;white-space:nowrap}
.tab[aria-selected="true"]{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:700}
iframe{display:none;width:100%;height:1600px;min-height:600px;border:1px solid var(--line);border-radius:14px;background:var(--card)}
iframe.active{display:block}
"""


def render_dashboard(date: str, updated: list[str]) -> str:
    tabs = [("x", "X @100labjtvn"), ("github", "GitHub Pages"),
            ("hatena", "はてなブログ"), ("ameba", "Ameba"), ("note", "note")]
    buttons = "".join(
        f'<button class="tab" role="tab" aria-selected="false" data-tab="{key}" '
        f'type="button">{esc(label)}</button>' for key, label in tabs)
    frames = "".join(
        f'<iframe id="tab-{key}" title="{esc(label)}" src="tabs/{key}.html" '
        f'loading="lazy"></iframe>' for key, label in tabs)
    updated_text = " / ".join(updated) or "N/A"
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>コンテンツ / アカウント分析レポート</title>
<style>{DASHBOARD_CSS}</style></head><body><div class="wrap">
<h1>コンテンツ / アカウント分析レポート</h1>
<div class="sub">対象日 {esc(date)} / 更新: {esc(updated_text)} / X + 4ブログを同じ指標比較フォーマットで日次更新</div>
<nav class="tabs" role="tablist" aria-label="レポート選択">{buttons}</nav>
{frames}
</div><script>
(function(){{
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.tab'));
  var frames = Array.prototype.slice.call(document.querySelectorAll('iframe'));
  function fit(frame){{
    try {{
      var h = frame.contentDocument.documentElement.scrollHeight;
      frame.style.height = Math.max(600, h + 24) + 'px';
    }} catch (e) {{ /* file:// 等で参照できない場合は既定高さを使う */ }}
  }}
  function activate(key, push){{
    tabs.forEach(function(t){{ t.setAttribute('aria-selected', String(t.dataset.tab === key)); }});
    frames.forEach(function(f){{ f.classList.toggle('active', f.id === 'tab-' + key); }});
    var active = document.getElementById('tab-' + key);
    if (active) fit(active);
    if (push && history.replaceState) history.replaceState(null, '', '#' + key);
  }}
  tabs.forEach(function(t){{ t.addEventListener('click', function(){{ activate(t.dataset.tab, true); }}); }});
  frames.forEach(function(f){{ f.addEventListener('load', function(){{ fit(f); }}); }});
  window.addEventListener('resize', function(){{ frames.forEach(fit); }});
  var initial = (location.hash || '').replace('#', '');
  activate(initial || 'x', false);
}})();
</script></body></html>
"""


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date_str())
    ap.add_argument("--skip-llm", action="store_true")
    ap.add_argument("--no-live", action="store_true", help="note の実PV取得をスキップ")
    ap.add_argument("--only", choices=list(PLATFORMS), default="",
                    help="指定したプラットフォームのみ更新（dashboard は全タブで作り直す）")
    args = ap.parse_args()
    ensure_dirs()

    names = [args.only] if args.only else list(PLATFORMS)
    results: dict[str, dict[str, Any]] = {}
    for name in names:
        collector = COLLECTORS[name]
        snapshot = collector() if name != "note" else collector(not args.no_live)
        history_path = HISTORY_DIR / f"{name}.json"
        history = load_json(history_path, [])
        if not isinstance(history, list):
            history = []
        history = [h for h in history if isinstance(h, dict) and h.get("date") != args.date]
        current = {"date": args.date, "values": snapshot["values"]}
        chart_history = history + [current]
        chart_history.sort(key=lambda h: h.get("date", ""))
        results[name] = {"snapshot": snapshot, "history": history,
                         "chart_history": chart_history[-90:], "history_path": history_path}

    relative = {name: relative_rows(results[name]["snapshot"]["values"],
                                    results[name]["chart_history"], args.date, PLATFORMS[name])
                for name in names}

    attempts: list[str] = []
    diagnoses = {} if args.skip_llm else llm_diagnose_all(results, relative, attempts)
    updated: list[str] = []
    for name in names:
        spec = PLATFORMS[name]
        result = results[name]
        diagnosis = diagnoses.get(name) or fallback_diagnosis(spec, relative[name])
        diagnosis = dict(diagnosis)
        diagnosis.setdefault("_model", MODEL)
        diagnosis["_attempts"] = attempts
        if "summary" not in diagnosis:
            diagnosis["summary"] = f"{spec['label']}の分析結果（LLM出力に不備があったためルール診断に切り替え）"
        proposal = build_proposal(name, args.date, diagnosis, relative[name])

        save_json(OUT / name / "snapshots" / f"{args.date}.json", result["snapshot"])
        save_json(OUT / name / "analyses" / f"{args.date}.json", {
            "date": args.date, "platform": name, "values": result["snapshot"]["values"],
            "relative": relative[name], "diagnosis": diagnosis,
        })
        proposal_path = OUT / name / "proposals" / f"{args.date}.json"
        save_json(proposal_path, proposal)
        md_path = OUT / name / "reports" / f"{args.date}.md"
        md_path.write_text(render_markdown(name, args.date, result, relative[name],
                                           diagnosis, proposal), encoding="utf-8")
        tab_path = TAB_DIR / f"{name}.html"
        tab_path.write_text(render_tab_html(name, args.date, result, relative[name],
                                            diagnosis, proposal, result["chart_history"]),
                            encoding="utf-8")
        save_json(result["history_path"], result["chart_history"][-90:])
        updated.append(f"{spec['short']} {result['snapshot']['collected_at'][11:16]}")
        print(f"[ok] {name}: {md_path}")

    # X タブは x_consultant.py が生成したものを使う。初回だけ旧ルートHTMLを流用する。
    # ルートがすでにダッシュボードになっている場合は再帰 iframe を避けてプレースホルダにする。
    TAB_DIR.mkdir(parents=True, exist_ok=True)
    if not X_TAB_PATH.is_file() and DASHBOARD_PATH.is_file():
        old = DASHBOARD_PATH.read_text(encoding="utf-8")
        if 'id="tab-x"' not in old:
            X_TAB_PATH.write_text(old, encoding="utf-8")
    if not X_TAB_PATH.is_file():
        X_TAB_PATH.write_text(
            "<!doctype html><html lang='ja'><meta charset='utf-8'><body>"
            "<p>X レポートがまだ生成されていません。python scripts/x_consultant.py を実行してください。</p>"
            "</body></html>", encoding="utf-8")

    DASHBOARD_PATH.write_text(render_dashboard(args.date, updated), encoding="utf-8")
    state = load_json(STATE_PATH, {})
    state["last_run_at"] = now_jst().isoformat(timespec="seconds")
    state["last_date"] = args.date
    state["dashboard"] = DASHBOARD_PATH.relative_to(BASE).as_posix()
    state["tabs"] = {name: (TAB_DIR / f"{name}.html").relative_to(BASE).as_posix()
                     for name in PLATFORMS}
    state["last_report"] = {name: (OUT / name / "reports" / f"{args.date}.md")
                            .relative_to(BASE).as_posix() for name in names}
    save_json(STATE_PATH, state)
    print(f"[ok] dashboard: {DASHBOARD_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

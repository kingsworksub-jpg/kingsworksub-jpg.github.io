# -*- coding: utf-8 -*-
"""投稿・返信の文脈に合う外部リンクを、実行時に解決する。

ユーザー指示（2026-11-23）:
- リンクの「キュー」や「RSS」は使わない。
- 投稿文・返信文脈に関連するキーワードがあり、リンクを貼ったほうが
  インプレッションが伸びるとLLMが判断したときだけ、関連リンクを貼る。

取得元:
- 自分のブログ記事（content/posts/*.md の front matter からURLを組み立て）
- YouTube（検索結果HTMLを解析。APIキー不要）

安全策:
- 返すURLは「自分のブログのbaseURL」または「youtube.com/watch / youtu.be」だけ。
- YouTubeは oEmbed で実在確認し、LIVE/予定/短すぎる動画/明らかなNG語を除外。
- 信頼チャンネルの指定（data/x-consulting/link-sources.json）があればそれ優先。
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
POSTS_DIR = BASE / "content" / "posts"
SOURCES_PATH = BASE / "data" / "x-consulting" / "link-sources.json"

DEFAULT_BLOG_BASE = "https://kingsworksub-jpg.github.io"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
BLOCKED_KEYWORDS = [
    "炎上", "暴露", "裏垢", "パクリ", "殺人", "事故", "事件", "訃報",
    "ギャンブル", "カジノ", "仮想通貨", "副業", "稼げる", "儲かる",
    "出会い", "アダルト", "エロ", "グロ", "ホラー", "porn", "gore", "scam",
]


def _load_sources() -> dict[str, Any]:
    try:
        obj = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _http_get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept-Language": "ja,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _is_blocked(text: str) -> bool:
    low = (text or "").lower()
    return any(k.lower() in low for k in BLOCKED_KEYWORDS)


# ---------------------------------------------------------------------------
# Blog (own site)
# ---------------------------------------------------------------------------

def _parse_front_matter(path: Path) -> dict[str, str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    if not raw.startswith("---"):
        return {}
    end = raw.find("\n---", 3)
    if end < 0:
        return {}
    meta: dict[str, str] = {}
    for line in raw[3:end].splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        meta[key.strip().lower()] = val.strip().strip('"').strip("'")
    return meta


def blog_candidates() -> list[dict[str, Any]]:
    sources = _load_sources()
    base = str(sources.get("blog_base_url") or DEFAULT_BLOG_BASE).rstrip("/")
    out: list[dict[str, Any]] = []
    if not POSTS_DIR.exists():
        return out
    for p in sorted(POSTS_DIR.glob("*.md")):
        meta = _parse_front_matter(p)
        title = meta.get("title") or p.stem
        if not title:
            continue
        slug = meta.get("slug") or p.stem
        url = f"{base}/posts/{urllib.parse.quote(slug)}/"
        out.append({
            "url": url,
            "title": title,
            "description": meta.get("description", ""),
            "tags": f"{meta.get('tags','')} {meta.get('categories','')}",
            "source": "blog",
        })
    return out


def _keyword_score(keywords: list[str], item: dict[str, Any]) -> int:
    title = (item.get("title") or "").lower()
    desc = (item.get("description") or "").lower()
    tags = (item.get("tags") or "").lower()
    score = 0
    for kw in keywords:
        k = (kw or "").strip().lower()
        if len(k) < 2:
            continue
        if k in title:
            score += 3
        if k in tags:
            score += 2
        if k in desc:
            score += 1
    return score


def choose_blog_link(keywords: list[str], min_score: int = 3) -> dict[str, Any] | None:
    best = None
    best_score = 0
    for item in blog_candidates():
        if _is_blocked(item.get("title", "")):
            continue
        sc = _keyword_score(keywords, item)
        if sc > best_score:
            best, best_score = item, sc
    if best is None or best_score < min_score:
        return None
    return {**best, "score": best_score, "reason": f"keyword_score={best_score}"}


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------

def _extract_yt_initial_data(html: str) -> dict[str, Any] | None:
    # ytInitialData = {...}; / window["ytInitialData"] = {...};
    m = re.search(r'(?:window\["ytInitialData"\]|ytInitialData)\s*=\s*', html)
    if not m:
        return None
    start = html.find("{", m.end())
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(html)):
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start : i + 1])
                except Exception:
                    return None
    return None


def _txt(node: Any) -> str:
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    if isinstance(node.get("simpleText"), str):
        return node["simpleText"]
    runs = node.get("runs")
    if isinstance(runs, list):
        return "".join(str(r.get("text", "")) for r in runs if isinstance(r, dict))
    return ""


def _duration_seconds(text: str) -> int | None:
    if not text:
        return None
    parts = text.split(":")
    try:
        parts = [int(x) for x in parts]
    except Exception:
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def _walk_video_renderers(node: Any, out: list[dict[str, Any]], depth: int = 0) -> None:
    if depth > 40:
        return
    if isinstance(node, dict):
        v = node.get("videoRenderer")
        if isinstance(v, dict):
            vid = v.get("videoId")
            title = _txt(v.get("title"))
            if vid and title:
                badges = v.get("badges") or []
                badge_text = " ".join(
                    _txt(b.get("metadataBadgeRenderer", {}).get("label"))
                    for b in badges if isinstance(b, dict)
                )
                length = _txt(v.get("lengthText"))
                owner = _txt(v.get("ownerText")) or _txt(v.get("longBylineText"))
                out.append({
                    "video_id": vid,
                    "title": title,
                    "channel": owner,
                    "duration": length,
                    "badges": badge_text,
                })
        for val in node.values():
            _walk_video_renderers(val, out, depth + 1)
    elif isinstance(node, list):
        for val in node:
            _walk_video_renderers(val, out, depth + 1)


def search_youtube(query: str, keywords: list[str], max_results: int = 5) -> list[dict[str, Any]]:
    if not query:
        return []
    q = urllib.parse.quote(query)
    html = _http_get(f"https://www.youtube.com/results?search_query={q}")
    data = _extract_yt_initial_data(html)
    if not data:
        return []
    raw: list[dict[str, Any]] = []
    _walk_video_renderers(data, raw)

    sources = _load_sources()
    trusted = [str(c).lower() for c in (sources.get("youtube_trusted_channels") or []) if c]
    kws = [k.strip().lower() for k in keywords if k and len(k.strip()) >= 2]

    out: list[dict[str, Any]] = []
    for v in raw:
        title = v.get("title", "")
        channel = v.get("channel", "")
        if _is_blocked(title) or _is_blocked(channel):
            continue
        badges = (v.get("badges") or "").lower()
        if "live" in badges or "ライブ" in badges or "予定" in badges or "upcoming" in badges:
            continue
        secs = _duration_seconds(v.get("duration", ""))
        if secs is not None and secs < 45:
            continue
        if trusted and not any(t in channel.lower() for t in trusted):
            continue
        blob = f"{title} {channel}".lower()
        overlap = sum(1 for k in kws if k in blob)
        if kws and overlap == 0:
            continue
        out.append({
            "url": f"https://www.youtube.com/watch?v={v['video_id']}",
            "title": title,
            "channel": channel,
            "duration": v.get("duration", ""),
            "source": "youtube",
            "score": overlap,
            "reason": f"keyword_overlap={overlap}",
        })
        if len(out) >= max_results:
            break
    out.sort(key=lambda x: -int(x.get("score") or 0))
    return out


def verify_youtube(video_url: str, timeout: int = 10) -> bool:
    try:
        oembed = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(video_url, safe="")
        req = urllib.request.Request(oembed, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8", "replace"))
            return bool(data.get("title"))
    except Exception:
        return False


def _safe_url(url: str) -> bool:
    sources = _load_sources()
    base = str(sources.get("blog_base_url") or DEFAULT_BLOG_BASE).rstrip("/")
    u = (url or "").strip()
    if u.startswith(base + "/"):
        return True
    return bool(re.match(r"^https://(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[A-Za-z0-9_-]{6,}", u))


def resolve_link(decision: dict[str, Any] | None, post_text: str, keywords: list[str]) -> dict[str, Any] | None:
    """LLMのリンク判断を受けて、実在するURLを1件返す。無ければ None。"""
    if not isinstance(decision, dict) or not decision.get("needed"):
        return None
    kind = str(decision.get("kind") or "auto").lower()
    query = str(decision.get("query") or "").strip()
    kws = [k for k in (keywords or []) if isinstance(k, str) and k.strip()]
    if query:
        kws = kws + [query]

    candidates: list[dict[str, Any]] = []
    if kind in ("blog", "auto"):
        b = choose_blog_link(kws)
        if b:
            candidates.append(b)
    if kind in ("youtube", "auto") and (kind == "youtube" or not candidates):
        try:
            yt = search_youtube(query or " ".join(kws[:3]), kws)
        except Exception:
            yt = []
        for y in yt:
            if verify_youtube(y["url"]):
                candidates.append(y)
                break

    for c in candidates:
        url = str(c.get("url") or "")
        if _safe_url(url):
            c["llm_reason"] = decision.get("reason", "")
            return c
    return None

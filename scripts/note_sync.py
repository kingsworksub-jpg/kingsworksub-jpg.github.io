# -*- coding: utf-8 -*-
"""note の公開状態（無料/有料・有料部分の開始位置）を GitHub Pages 記事と同期する。

方針（2026-11-17、ユーザー指示）:
  - note の無料記事は、全文を GitHub Pages にも載せる。
  - note の有料記事は、無料部分だけを GitHub Pages に載せ、
    有料部分の先頭に「続きは note で読む」CTA を置く。
  - 有料かどうか・無料部分の終わりは **note 側の API を正** とする
    （price / separator / body）。記事側の推測や手書きマーカーを正にしない。

note API の読み方（2026-11-17 実測）:
  - price > 0            … 有料記事
  - separator            … 有料部分の先頭ブロックの id
  - body                 … 無料部分＋有料部分の HTML。separator の要素より前が無料部分。
  - 無料部分の先頭 <p>   … 記事の description（note が本文先頭に置く）

使い方:
  python scripts/note_sync.py sync [--slug SLUG]     # note を取得して note-index.json を更新
  python scripts/note_sync.py list                    # 現在の index を表示
  python scripts/note_sync.py check [--slug SLUG]     # index と記事の整合を検査（ブラウザ不要）
  python scripts/note_sync.py apply --slug SLUG [--dry-run] [--force]
                                                      # 有料記事を「無料部分＋CTA」に書き換える

apply の動作:
  - 全文を scripts/note-full/<slug>.md に退避する（note 再投稿・再変換用）。
  - content/posts/<slug>.md を frontmatter＋無料部分＋CTA に置き換える。
  - note の区切り（separator）が記事内の見出しと一致しない場合は、書き換えずにエラーにする。
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import html
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import distribution as dist  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "scripts")
POSTS = os.path.join(ROOT, "content", "posts")
NOTE_FULL = os.path.join(S, "note-full")
INDEX = os.path.join(S, "note-index.json")
PROFILE = os.path.join(ROOT, "data", "note_user_data")
STATS_API = "https://note.com/api/v1/stats/pv?filter=all&page="
NOTE_API = "https://note.com/api/v3/notes/"
JST = dt.timezone(dt.timedelta(hours=9))

CTA_START = "<!-- note-paywall-cta:start -->"
CTA_END = "<!-- note-paywall-cta:end -->"
CTA_RE = re.compile(re.escape(CTA_START) + r".*?" + re.escape(CTA_END), re.S)
PAYWALL_MARKER = "<!-- note-paywall -->"
MIN_FREE_COVERAGE = 0.95
MIN_FREE_CHARS = 800

JS_NOTE = """async (k) => {
  try {
    const res = await fetch('https://note.com/api/v3/notes/' + k, {credentials: 'include'});
    if (res.status !== 200) return {status: res.status, key: k};
    const j = await res.json();
    const d = j.data || {};
    return {status: 200, key: d.key, name: d.name, price: d.price,
            separator: d.separator, note_url: d.note_url, publish_at: d.publish_at,
            body: d.body, description: d.description};
  } catch (e) {
    return {err: String(e), key: k};
  }
}"""

JS_STATS = """async (pg) => {
  const res = await fetch('https://note.com/api/v1/stats/pv?filter=all&page=' + pg,
                          {credentials: 'include'});
  if (res.status !== 200) return {status: res.status};
  const j = await res.json();
  return j.data || {};
}"""


# ---------------------------------------------------------------------------
# text / frontmatter helpers
# ---------------------------------------------------------------------------

def norm(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"[\s\u3000]+", "", s)
    s = re.sub(r"[#*`>|]+", "", s)
    return s


def plain(html_or_md: str) -> str:
    """HTML / Markdown を比較用の素の文字列にする。"""
    s = html.unescape(html_or_md or "")
    s = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", s, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|h[1-6]|li|blockquote|div|figure|figcaption|td|th|tr)>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"[\s\u3000]+", "", s)
    s = re.sub(r"[#*`>|]+", "", s)
    return s


def bigrams(s: str) -> set[str]:
    return {s[i:i + 2] for i in range(len(s) - 1)}


def coverage(target: str, candidate: str) -> float:
    a, b = bigrams(target), bigrams(candidate)
    return len(a & b) / len(a) if a else 0.0


def split_doc(text: str) -> tuple[str, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError("frontmatter が読めない")
    return m.group(1), m.group(2)


def fm_get(fm: str, name: str) -> str:
    m = re.search(rf'(?m)^{re.escape(name)}:\s*"?(.*?)"?\s*$', fm)
    return m.group(1) if m else ""


def fm_set(fm: str, name: str, value: str) -> str:
    line = f"{name}: {value}"
    pat = rf"(?m)^{re.escape(name)}:.*$"
    if re.search(pat, fm):
        return re.sub(pat, line, fm, count=1)
    return fm.rstrip() + "\n" + line


def q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def now_iso() -> str:
    return dt.datetime.now(JST).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# note fetch
# ---------------------------------------------------------------------------

def fetch_stats(page) -> list[dict]:
    out, pg = [], 1
    while True:
        d = page.evaluate(JS_STATS, pg)
        if not isinstance(d, dict) or "note_stats" not in d:
            hint = "（ログイン切れの可能性。python scripts/post-to-note.py --login を実行）" \
                if isinstance(d, dict) and d.get("status") in (401, 403, 404) else ""
            raise RuntimeError(f"note の記事一覧を取得できません: {d}{hint}")
        ns = d.get("note_stats") or []
        out += ns
        if d.get("last_page") or not ns:
            break
        pg += 1
    return out


def fetch_notes(keys: list[str]) -> dict[str, dict]:
    from playwright.sync_api import sync_playwright

    if not os.path.isdir(PROFILE):
        raise RuntimeError(f"note のログインプロファイルが無い: {PROFILE}")
    result: dict[str, dict] = {}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=True,
            args=["--disable-blink-features=AutomationControlled"],
            locale="ja-JP", timezone_id="Asia/Tokyo", ignore_https_errors=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://note.com/", wait_until="domcontentloaded", timeout=60000)
        for k in keys:
            result[k] = page.evaluate(JS_NOTE, k)
        ctx.close()
    return result


# ---------------------------------------------------------------------------
# note body analysis
# ---------------------------------------------------------------------------

def first_block(body: str, eid: str) -> tuple[str, int]:
    """separator の id を持つ要素の (開始位置, タグ名) を返す。無ければ (-1, '')。"""
    m = re.search(r"<([a-zA-Z0-9]+)\b[^>]*\bid=\"%s\"" % re.escape(eid), body)
    if not m:
        return "", -1
    return m.group(1).lower(), m.start()


def inner_text_by_id(body: str, eid: str) -> str:
    tag, start = first_block(body, eid)
    if not tag:
        return ""
    # 開始タグの終わりを探す
    open_end = body.find(">", start)
    if open_end == -1:
        return ""
    if tag in ("hr", "br", "img", "input", "meta", "link"):
        return ""
    close = body.find(f"</{tag}>", open_end)
    if close == -1:
        return ""
    inner = html.unescape(re.sub(r"<[^>]+>", "", body[open_end + 1:close]))
    return re.sub(r"\s+", " ", inner).strip()


def analyze_note(meta: dict) -> dict:
    """note の API レスポンスから、無料部分・有料部分の情報を取り出す。"""
    body = meta.get("body") or ""
    price = int(meta.get("price") or 0)
    sep = meta.get("separator") or ""
    if price > 0 and sep:
        tag, start = first_block(body, sep)
        if start < 0:
            raise RuntimeError(
                f"note の separator {sep!r} が body 内に見つかりません（API 仕様変更の疑い）")
        free_html, paid_html = body[:start], body[start:]
        paid_from = inner_text_by_id(body, sep)
    else:
        free_html, paid_html, paid_from = body, "", ""

    # 無料部分の先頭 <p> は description（note が本文先頭に自動で置く）。
    # GitHub Pages 側には frontmatter の description があるので、比較時だけ除く。
    desc = meta.get("description") or ""
    free_for_compare = free_html
    m = re.search(r"<p\b[^>]*>(.*?)</p>", free_for_compare, re.S)
    if m and desc:
        first_p = plain(m.group(1))
        if first_p and first_p == plain(desc):
            free_for_compare = free_for_compare[:m.start()] + free_for_compare[m.end():]

    free_text = plain(free_for_compare)
    paid_text = plain(paid_html)
    return {
        "price": price,
        "separator": sep,
        "paid_from": paid_from,
        "free_html": free_html,
        "paid_html": paid_html,
        "free_chars": len(free_text),
        "paid_chars": len(paid_text),
        "body_chars": len(plain(body)),
        "free_text": free_text,
    }


def paid_headings(paid_html: str) -> list[str]:
    out = []
    for m in re.finditer(r"<h([2-4])\b[^>]*>(.*?)</h\1>", paid_html, re.S):
        t = plain(m.group(2))
        if t:
            out.append(t)
    return out


# ---------------------------------------------------------------------------
# slug <-> note mapping
# ---------------------------------------------------------------------------

def post_titles() -> dict[str, str]:
    out = {}
    for p in glob.glob(os.path.join(POSTS, "*.md")):
        try:
            fm, _ = split_doc(open(p, encoding="utf-8-sig").read().replace("\r\n", "\n"))
        except Exception:
            continue
        t = fm_get(fm, "title")
        if t:
            out[os.path.basename(p)[:-3]] = t
    return out


def known_keys() -> dict[str, str]:
    """slug → note_key（topic-log / post-platforms / frontmatter から）。"""
    out: dict[str, str] = {}
    log = load_json(os.path.join(S, "topic-log.json"), {"entries": []})
    for e in log.get("entries", []):
        if e.get("slug") and e.get("note_key"):
            out.setdefault(e["slug"], e["note_key"])
    pp = load_json(os.path.join(S, "post-platforms.json"), {})
    for slug, st in pp.items():
        if isinstance(st, dict) and st.get("note_key"):
            out.setdefault(slug, st["note_key"])
    for p in glob.glob(os.path.join(POSTS, "*.md")):
        try:
            fm, _ = split_doc(open(p, encoding="utf-8-sig").read().replace("\r\n", "\n"))
        except Exception:
            continue
        k = fm_get(fm, "note_key")
        if k:
            out.setdefault(os.path.basename(p)[:-3], k)
    return out


def slug_for_note(meta: dict, titles: dict[str, str]) -> str:
    body = meta.get("body") or ""
    m = re.search(r"https://kingsworksub-jpg\.github\.io/posts/([^/\s\"<>]+)/", body)
    if m:
        return m.group(1)
    name = (meta.get("name") or "").strip()
    for slug, title in titles.items():
        if title.strip() == name:
            return slug
    return ""


# ---------------------------------------------------------------------------
# sync / index
# ---------------------------------------------------------------------------

def cmd_sync(args) -> int:
    from playwright.sync_api import sync_playwright

    if not os.path.isdir(PROFILE):
        print(f"[error] note のログインプロファイルが無い: {PROFILE}", file=sys.stderr)
        return 1
    notes: list[dict] = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=True,
            args=["--disable-blink-features=AutomationControlled"],
            locale="ja-JP", timezone_id="Asia/Tokyo", ignore_https_errors=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://note.com/", wait_until="domcontentloaded", timeout=60000)
        stats = fetch_stats(page)
        print(f"note の公開記事: {len(stats)} 件")
        keys = [n.get("key") for n in stats if n.get("key")]
        if args.slug:
            km = {s: k for s, k in known_keys().items()}
            want = km.get(args.slug)
            if not want:
                print(f"[error] {args.slug} の note_key が分かりません", file=sys.stderr)
                ctx.close()
                return 1
            keys = [want]
        titles = post_titles()
        failed = 0
        for i, k in enumerate(keys, 1):
            meta = page.evaluate(JS_NOTE, k)
            if meta.get("status") != 200:
                print(f"  [warn] {k}: API status {meta.get('status')}", file=sys.stderr)
                failed += 1
                continue
            slug = slug_for_note(meta, titles)
            try:
                a = analyze_note(meta)
            except RuntimeError as ex:
                print(f"  [warn] {k}: {ex}", file=sys.stderr)
                failed += 1
                continue
            rec = {
                "key": k,
                "slug": slug,
                "url": meta.get("note_url") or f"https://note.com/shining_finger01/n/{k}",
                "title": meta.get("name") or "",
                "price": a["price"],
                "separator": a["separator"],
                "paid_from": a["paid_from"],
                "free_chars": a["free_chars"],
                "paid_chars": a["paid_chars"],
                "body_chars": a["body_chars"],
                "paid_heading_count": len(paid_headings(a["paid_html"])),
                "publish_at": meta.get("publish_at") or "",
                "synced_at": now_iso(),
            }
            notes.append(rec)
            mark = "PAID" if rec["price"] > 0 else "free"
            print(f"  [{i}/{len(keys)}] {mark} {k} {slug or '(slug未特定)'} {rec['price']}円")
        ctx.close()

    if failed:
        print(f"[error] {failed} 件取得できなかったため index は更新しません", file=sys.stderr)
        return 1

    if args.slug:
        # 1記事だけ更新するときは、他の記事の記録を消さない。
        new_notes = [n for n in index_notes() if n.get("slug") != args.slug] + notes
    else:
        new_notes = notes
    new_notes.sort(key=lambda r: (r.get("publish_at") or "", r["key"]))
    save_json(INDEX, {"generated_at": now_iso(), "notes": new_notes})
    paid = [n for n in new_notes if n["price"] > 0]
    print(f"index: {len(new_notes)} 件（有料 {len(paid)} 件）-> {os.path.relpath(INDEX, ROOT)}")
    for n in paid:
        print(f"  有料: {n['slug'] or '(slug未特定)'} / {n['price']}円 / 区切り={n['paid_from']!r}")
    return 0


def index_notes() -> list[dict]:
    return load_json(INDEX, {"notes": []}).get("notes", [])


def index_by_slug(slug: str) -> dict | None:
    """slug に対応する note。複数ある場合は有料を優先し、次に新しいもの。"""
    cands = [n for n in index_notes() if n.get("slug") == slug]
    if not cands:
        return None
    cands.sort(key=lambda n: (n.get("price", 0) > 0, n.get("publish_at") or ""), reverse=True)
    return cands[0]


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

def post_path(slug: str) -> str:
    return os.path.join(POSTS, slug + ".md")


def read_post(slug: str) -> tuple[str, str, str]:
    p = post_path(slug)
    if not os.path.exists(p):
        raise FileNotFoundError(p)
    fm, body = split_doc(open(p, encoding="utf-8-sig").read().replace("\r\n", "\n"))
    return p, fm, body


def post_free_body(body: str) -> str:
    m = CTA_RE.search(body)
    if m:
        return body[:m.start()]
    i = body.find(PAYWALL_MARKER)
    if i != -1:
        return body[:i]
    return body


def check_post(slug: str, rec: dict | None) -> list[str]:
    """1記事と note index の整合を検査する。ブラウザ不要。"""
    if "github" not in dist.platforms(slug):
        return []  # GitHub 版が無い記事は note 側が正本なので比較対象が無い
    errs: list[str] = []
    try:
        _, fm, body = read_post(slug)
    except FileNotFoundError:
        return [f"記事ファイルが無い: content/posts/{slug}.md"]
    paid_flag = fm_get(fm, "note_paid").strip().lower() in ("true", "yes", "1")
    has_cta = bool(CTA_RE.search(body))
    if rec is None:
        if paid_flag or has_cta:
            errs.append("note_index に無いのに有料設定（note_paid / CTA）がある")
        return errs

    if rec.get("price", 0) > 0:
        if not paid_flag:
            errs.append(f"note は有料（{rec['price']}円）なのに note_paid: true が無い")
        if fm_get(fm, "note_key") != rec.get("key"):
            errs.append(f"note_key が note 側と不一致（記事={fm_get(fm, 'note_key')!r} / note={rec.get('key')!r}）")
        if fm_get(fm, "note_url").rstrip("/") != (rec.get("url") or "").rstrip("/"):
            errs.append("note_url が note 側と不一致")
        if str(rec.get("price")) != fm_get(fm, "note_price").strip():
            errs.append("note_price が note 側と不一致")
        if not has_cta:
            errs.append("有料記事なのに CTA（<!-- note-paywall-cta:start -->）が無い")
        pf = rec.get("paid_from") or ""
        content = post_free_body(body)
        if pf and norm(pf) and norm(pf) in norm(content):
            errs.append(f"有料部分の見出しが GitHub Pages 側に残っている: {pf!r}")
        if not os.path.exists(os.path.join(NOTE_FULL, slug + ".md")):
            errs.append(f"有料記事の全文退避が無い: scripts/note-full/{slug}.md")
        free_chars = len(plain(content))
        if free_chars < MIN_FREE_CHARS:
            errs.append(f"無料部分が短すぎる（{free_chars}字）。note の無料部分と一致しているか確認")
    else:
        if paid_flag:
            errs.append("note は無料なのに note_paid: true になっている")
        if has_cta:
            errs.append("note は無料なのに有料 CTA が入っている（全文を掲載する）")
        body_chars = int(rec.get("body_chars") or 0)
        if body_chars:
            n = len(plain(post_free_body(body)))
            if n < body_chars * 0.85:
                errs.append(f"本文が note より短い（記事 {n}字 / note {body_chars}字）。全文を掲載する")
    return errs


def cmd_check(args) -> int:
    notes = index_notes()
    if not notes:
        print("[error] note-index.json が無い。先に `python scripts/note_sync.py sync` を実行", file=sys.stderr)
        return 1
    by_slug: dict[str, dict] = {}
    for n in notes:
        s = n.get("slug")
        if not s:
            continue
        old = by_slug.get(s)
        if old is None or (n.get("price", 0) > 0 and old.get("price", 0) == 0):
            by_slug[s] = n
        elif n.get("price", 0) > 0 and old.get("price", 0) > 0:
            if (n.get("publish_at") or "") > (old.get("publish_at") or ""):
                by_slug[s] = n
    if args.slug:
        targets = [args.slug]
    else:
        targets = sorted(by_slug)
    bad = 0
    for slug in targets:
        errs = check_post(slug, by_slug.get(slug))
        if errs:
            bad += 1
            print(f"NG {slug}")
            for e in errs:
                print(f"   - {e}")
    print(f"check: {len(targets)} 件 / NG {bad} 件")
    return 1 if bad else 0


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

def find_boundary(body: str, paid_from: str) -> int:
    """記事本文中で有料部分の先頭にあたる位置を返す。見つからなければ -1。"""
    target = norm(paid_from)
    if not target:
        return -1
    for m in re.finditer(r"(?m)^(#{1,6})\s+(.*)$", body):
        if norm(m.group(2)) == target:
            return m.start()
    # 見出しでない場合（先頭ブロックが段落）は、行頭一致で探す
    for m in re.finditer(r"(?m)^(.+)$", body):
        if target and target in norm(m.group(1)):
            return m.start()
    return -1


def cta_block(rec: dict) -> str:
    price = rec["price"]
    url = rec["url"]
    pf = rec.get("paid_from") or ""
    if pf:
        lead = f"「{html.escape(pf)}」以降の章と総括は、note の有料記事で読めます。"
    else:
        lead = "この記事の続きは、note の有料記事で読めます。"
    return f"""{CTA_START}
<aside class="note-cta">
<p class="note-cta__eyebrow">ここから先は note の有料記事です</p>
<p class="note-cta__lead">{lead}</p>
<a class="note-cta__button" href="{html.escape(url)}" target="_blank" rel="noopener">続きは note で読む（{price}円）</a>
<p class="note-cta__note">note の無料部分はこのページと同じ内容です。購入すると note で全文が読めます。</p>
</aside>
{CTA_END}"""


def cmd_apply(args) -> int:
    # GitHub が配信先でない記事は、note 側の本文を書き換える相手が無い。全文は content/posts に残す。
    if "github" not in dist.platforms(args.slug):
        print(f"{args.slug}: GitHub が配信先ではないため apply はスキップ（note 側が本文の正本）")
        return 0
    # 有料/無料の取り違えを防ぐため、apply では必ず note を取り直す（index は手がかりに使う）。
    km = known_keys()
    rec0 = index_by_slug(args.slug)
    key = args.note_key or (rec0 or {}).get("key") or km.get(args.slug)
    if not key:
        print(f"[error] {args.slug} の note_key が分かりません。--note-key を指定してください",
              file=sys.stderr)
        return 1
    meta = fetch_notes([key]).get(key, {})
    if meta.get("status") != 200:
        print(f"[error] note API で {key} を取得できません: {meta}", file=sys.stderr)
        return 1
    a = analyze_note(meta)
    rec = {
        "key": key, "slug": args.slug,
        "url": meta.get("note_url") or f"https://note.com/shining_finger01/n/{key}",
        "title": meta.get("name") or "", "price": a["price"],
        "separator": a["separator"], "paid_from": a["paid_from"],
        "free_chars": a["free_chars"], "paid_chars": a["paid_chars"],
        "body_chars": a["body_chars"], "publish_at": meta.get("publish_at") or "",
        "free_text": a["free_text"],
    }
    if rec.get("price", 0) <= 0:
        print(f"{args.slug}: note は無料記事（price=0）。全文掲載のままでよい（変更なし）")
        return 0

    try:
        path, fm, body = read_post(args.slug)
    except FileNotFoundError:
        print(f"[error] 記事が無い: content/posts/{args.slug}.md", file=sys.stderr)
        return 1

    already = bool(CTA_RE.search(body))
    free_body = post_free_body(body)
    paid_from = rec.get("paid_from") or ""
    boundary = find_boundary(free_body, paid_from)
    if boundary < 0 and not already:
        print(f"[error] note の有料境界「{paid_from}」が記事内に見つかりません。", file=sys.stderr)
        print("        note 側の区切り位置と記事の見出しを確認してください（推測で切らない）。",
              file=sys.stderr)
        return 1

    if boundary >= 0:
        free_md = free_body[:boundary].rstrip()
    else:
        free_md = free_body.rstrip()

    # note の無料部分と記事の無料部分が一致するか（有料/無料の取り違え防止）
    note_free = rec.get("free_text") or ""
    cov = coverage(note_free, plain(free_md)) if note_free else 0.0
    print(f"無料部分の一致度: {cov:.3f}（note {len(note_free)}字 / 記事 {len(plain(free_md))}字）")
    if cov < MIN_FREE_COVERAGE and not args.force:
        print("[error] note の無料部分と記事の無料部分が一致しません。", file=sys.stderr)
        print("        note の有料区切りを記事に合わせるか、記事を note に合わせてください。",
              file=sys.stderr)
        print("        （--force で強制適用できますが、有料部分が漏れる危険があります）", file=sys.stderr)
        return 1

    # 全文を退避（初回のみ。既存の退避は上書きしない）
    archive = os.path.join(NOTE_FULL, args.slug + ".md")
    if not already:
        if args.dry_run:
            print(f"[dry-run] 全文退避予定: {os.path.relpath(archive, ROOT)}")
        elif os.path.exists(archive) and not args.force:
            print(f"[warn] 全文退避が既にあるため上書きしません: {os.path.relpath(archive, ROOT)}")
        else:
            os.makedirs(NOTE_FULL, exist_ok=True)
            with open(archive, "w", encoding="utf-8", newline="\n") as f:
                f.write("---\n" + fm + "\n---\n" + body)
            print(f"全文を退避: {os.path.relpath(archive, ROOT)}")

    related = re.search(r"(?m)^\*\*関連記事\*\*:.*$", body)
    related_line = related.group(0).strip() if related else ""

    new_body = free_md.rstrip() + "\n\n" + cta_block(rec)
    if related_line and not already:
        new_body += "\n\n" + related_line
    new_body += "\n"

    fm = fm_set(fm, "note_key", q(rec["key"]))
    fm = fm_set(fm, "note_url", q(rec["url"]))
    fm = fm_set(fm, "note_paid", "true")
    fm = fm_set(fm, "note_price", str(rec["price"]))
    fm = fm_set(fm, "note_separator", q(rec.get("separator") or ""))
    fm = fm_set(fm, "note_paid_from", q(paid_from))
    fm = fm_set(fm, "note_synced_at", q(now_iso()))

    out = "---\n" + fm.rstrip() + "\n---\n" + new_body
    if args.dry_run:
        print("--- dry-run: 書き換え後の本文（先頭1200字） ---")
        print(out[:1200])
        return 0
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    print(f"更新: {os.path.relpath(path, ROOT)}")
    print(f"  有料: {rec['price']}円 / 区切り: {paid_from!r} / CTA: {rec['url']}")
    return 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def cmd_list(args) -> int:
    notes = index_notes()
    if not notes:
        print("note-index.json が空。`python scripts/note_sync.py sync` を実行してください")
        return 0
    print(f"{'price':>6}  {'slug':40}  {'key':14}  区切り")
    for n in notes:
        print(f"{n.get('price', 0):>6}  {(n.get('slug') or '(未特定)'):40}  {n['key']:14}  "
              f"{n.get('paid_from') or ''}")
    print(f"合計 {len(notes)} 件（有料 {sum(1 for n in notes if n.get('price', 0) > 0)} 件）")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="note の無料/有料と GitHub Pages 記事を同期する")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sync", help="note を取得して note-index.json を更新")
    p.add_argument("--slug", help="1記事だけ更新（note_key は topic-log / post-platforms / frontmatter から）")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("list", help="index を表示")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("check", help="index と記事の整合を検査（ブラウザ不要）")
    p.add_argument("--slug")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("apply", help="有料記事を無料部分＋CTA に書き換える")
    p.add_argument("--slug", required=True)
    p.add_argument("--note-key")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="一致度が低くても強制適用")
    p.set_defaults(func=cmd_apply)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

"""Quality gate for a new post. Exit 1 (with reasons) if the post must not be published.

    python scripts/validate_post.py <slug> [<slug> ...]

Run by the posting job before commit, and by the git pre-push hook for every newly
added post, so a broken article (e.g. truncated or mixed-language model output,
placeholder images) never reaches GitHub Pages / Hatena / note.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JST = dt.timezone(dt.timedelta(hours=9))
MIN_BODY = 3500
MIN_IMAGE_BYTES = 15000
SIMPLIFIED = set("们这说刚价么还让给开关头见问题实现经电动书长东车门马鸟龙变显话认识语应该从发进时为")
BANNED_TITLE = ["を全機能解剖", "の味と仕様", "の仕様と使い方", "の現在地 — ", "徹底比較", "隅から隅まで", "味わい尽くす", "五番勝負"]
BANNED_BODY = [r"実際に.{0,12}してみた", "あるレビューでは", "海外フォーラムでは", "と評されている", "隅から隅まで",
               "味わい尽くす", "の転載です", "エージェント", "自動生成", "読み込んで"]

sys.stdout.reconfigure(encoding="utf-8")


def check(slug: str) -> list[str]:
    p = os.path.join(ROOT, "content", "posts", slug + ".md")
    if not os.path.exists(p):
        return [f"記事ファイルが無い: {p}"]
    s = open(p, encoding="utf-8-sig").read().replace("\r\n", "\n")
    m = re.match(r"---\n(.*?)\n---\n(.*)", s, re.S)
    if not m:
        return ["frontmatter が読めない"]
    fm, body = m.group(1), m.group(2)
    errs = []

    def field(name):
        x = re.search(rf'(?m)^{name}:\s*"?(.*?)"?\s*$', fm)
        return x.group(1) if x else ""

    title, desc = field("title"), field("description")
    if not title:
        errs.append("title が無い")
    for b in BANNED_TITLE:
        if b in title:
            errs.append(f"タイトルに廃止した型・禁止語: {b}")
    if not 90 <= len(desc) <= 140:
        errs.append(f"description の長さ {len(desc)}（110〜120字が目安）")
    if re.search(r"(?m)^draft:\s*true", fm):
        errs.append("draft: true のまま")
    cm = re.search(r"(?m)^categories:\s*\[([^\]]*)\]", fm)
    cats = re.findall(r"[\"']?([\w-]+)[\"']?", cm.group(1)) if cm else []
    plan = {c["id"] for c in json.load(open(os.path.join(ROOT, "scripts", "category-plan.json"), encoding="utf-8"))}
    if len(cats) != 1:
        errs.append(f"categories は1つだけ（現在 {cats}）")
    elif cats[0] not in plan:
        errs.append(f"未登録のカテゴリー {cats[0]}（category-plan.json と hugo.toml に追加が必要）")
    dm = re.search(r"(?m)^date:\s*\"?([0-9T:\-+]+)", fm)
    if not dm:
        errs.append("date が無い")
    else:
        try:
            d = dt.datetime.fromisoformat(dm.group(1))
            d = d if d.tzinfo else d.replace(tzinfo=JST)
            if d > dt.datetime.now(JST):
                errs.append(f"date が未来 {dm.group(1)}（ビルドから除外される）")
        except ValueError:
            errs.append(f"date の形式が不正 {dm.group(1)}")
    og = re.search(r'(?m)^images:\s*\["([^"]+)"\]', fm)
    if not og or not os.path.exists(os.path.join(ROOT, "static", og.group(1).lstrip("/"))):
        errs.append("OGP画像（images:）が無い")

    text = re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)|\[([^\]]*)\]\([^)]*\)|[#|*`>-]", r"\1", body)
    plain = re.sub(r"\s+", "", text)
    if len(plain) < MIN_BODY:
        errs.append(f"本文が短い（{len(plain)}字 < {MIN_BODY}字）")
    zh = [ch for ch in plain if ch in SIMPLIFIED]
    if len(zh) >= 3:
        errs.append(f"中国語の簡体字が混入: {''.join(sorted(set(zh)))[:20]}")
    if re.search(r"[\u0400-\u04FF\u0E00-\u0E7F\uAC00-\uD7AF]", plain):
        errs.append("日本語以外の文字（キリル・タイ・ハングル）が混入")
    for b in BANNED_BODY:
        if re.search(b, body):
            errs.append(f"禁止表現: {b}")
    if len(re.findall(r"(?m)^## ", body)) < 3:
        errs.append("見出し（##）が3つ未満")

    figs = re.findall(r'<figure class="photo photo--(?:left|right)">(.*?)</figure>', body, re.S)
    if not figs:
        errs.append("回り込み画像（figure.photo）が1枚も無い")
    for f in figs:
        src = re.search(r'<img\s+src="([^"]+)"', f)
        if not src:
            errs.append("figure に img が無い")
            continue
        if "<figcaption>" not in f:
            errs.append(f"figcaption が無い: {src.group(1)}")
        cr = re.search(r'<span class="credit">(.*?)</span>', f, re.S)
        # 複数の形式に対応: Photo: / Photo by / 撮影: / 撮影 / CC / Public domain / Image: / 出典 etc.
        if not cr or not re.search(r"(CC|Public domain|Image:|Photo:?(?:\s|$)|撮影|出典)", cr.group(1), re.I):
            errs.append(f"クレジット（撮影者・ライセンス）が無い: {src.group(1)}")
        if src.group(1).startswith("/"):
            path = os.path.join(ROOT, "static", src.group(1).lstrip("/"))
            if not os.path.exists(path):
                errs.append(f"画像ファイルが無い: {src.group(1)}")
            elif os.path.getsize(path) < MIN_IMAGE_BYTES:
                errs.append(f"画像が小さすぎる（仮画像の疑い）: {src.group(1)} {os.path.getsize(path)}B")
    for a in re.findall(r'https://www\.amazon\.co\.jp/[^\s"\)]+', body):
        if "tag=nakimoto1-22" not in a:
            errs.append(f"Amazonリンクにアソシエイトタグが無い: {a[:60]}")
    return errs


def main():
    slugs = sys.argv[1:]
    if not slugs:
        sys.exit("usage: validate_post.py <slug> [...]")
    bad = 0
    for slug in slugs:
        errs = check(slug)
        if errs:
            bad += 1
            print(f"NG {slug}")
            for e in errs:
                print(f"  - {e}")
        else:
            print(f"OK {slug}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

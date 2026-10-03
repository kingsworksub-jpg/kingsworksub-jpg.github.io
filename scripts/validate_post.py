"""Quality gate for a new post. Exit 1 (with reasons) if the post must not be published.

    python scripts/validate_post.py <slug> [<slug> ...]

Run by the posting job before commit, and by the git pre-push hook for every newly
added post, so a broken article (e.g. truncated or mixed-language model output,
placeholder images) never reaches GitHub Pages / Hatena / note.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import re
import subprocess
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
    figs_src = [re.search(r'<img\s+src="([^"]+)"', f).group(1) for f in figs if re.search(r'<img\s+src="([^"]+)"', f)]
    for dup in {x for x in figs_src if figs_src.count(x) > 1}:
        errs.append(f"同じ画像を複数の figure で使い回している: {dup}")
    if "amazon.co.jp" in body and figs and not any(re.search(r'<a\s+href="https://www\.amazon\.co\.jp/', f) for f in figs):
        errs.append("Amazon で扱う製品の記事なのに、画像が Amazon アソシエイトリンクで包まれていない")
    errs += check_images(slug, body)
    return errs


def _dhash(im) -> int:
    g = im.convert("L").resize((9, 8))
    px = list(g.get_flattened_data())
    return sum(1 << i for i in range(64) if px[(i // 8) * 9 + i % 8] > px[(i // 8) * 9 + i % 8 + 1])


def _added_long_ago(path: str) -> bool:
    """True if the file has been in git for more than 2 days (an image reused from an older post)."""
    out = subprocess.run(["git", "log", "--diff-filter=A", "--format=%ct", "--", path], cwd=ROOT,
                         capture_output=True, text=True).stdout.split()
    return bool(out) and (dt.datetime.now().timestamp() - int(out[-1])) > 2 * 86400


def check_images(slug: str, body: str) -> list[str]:
    """Every local image must be a real, decodable picture; new ones must trace back to their recorded source.

    Images are fetched with scripts/fetch_image.py, which writes scripts/image-sources/<slug>.json. Here each
    recorded image is downloaded again and compared (perceptual hash) with the saved file, so pictures drawn or
    generated locally cannot pass. Radar charts must come from scripts/radar-chart.awk.
    """
    from PIL import Image, ImageFilter
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from fetch_image import get, photo_problem

    errs = []
    sources = {}
    src_dir = os.path.join(ROOT, "scripts", "image-sources")
    if os.path.isdir(src_dir):
        for fn in os.listdir(src_dir):
            if fn.endswith(".json"):
                sources.update(json.load(open(os.path.join(src_dir, fn), encoding="utf-8")))
    refs = set(re.findall(r'(?:src="|\]\()(/images/[^"\)\s]+)', body))
    for ref in sorted(refs):
        path = os.path.join(ROOT, "static", ref.lstrip("/"))
        if not os.path.exists(path):
            errs.append(f"画像ファイルが無い: {ref}")
            continue
        if ref.lower().endswith(".svg"):
            svg = open(path, encoding="utf-8", errors="replace").read()
            if not ref.startswith("/images/radar/"):
                errs.append(f"SVG はレーダーチャート（/images/radar/）以外に使わない: {ref}")
            elif 'viewBox="0 0 500 460"' not in svg or svg.count("<polygon") < 6:
                errs.append(f"レーダーチャートが scripts/radar-chart.awk で作られていない: {ref}")
            continue
        try:
            im = Image.open(path)
            im.load()
        except Exception:
            errs.append(f"画像として開けない（壊れたファイル）: {ref}")
            continue
        bad = photo_problem(im)
        if not bad:
            g = im.convert("L").resize((256, 256))
            lap = g.filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], 1, 128))
            tex = sum(1 for v in lap.get_flattened_data() if abs(v - 128) > 6) / 65536
            if tex < 0.03:
                bad = f"写真としての質感が無い（グラデーションや単色の疑い, {tex:.3f}）"
        if bad:
            errs.append(f"画像が実写・実画面ではない: {ref}（{bad}）")
            continue
        rec = sources.get(ref)
        if not rec:
            if not _added_long_ago(os.path.join("static", ref.lstrip("/"))):
                errs.append(f"画像の出典記録が無い: {ref}（scripts/fetch_image.py で取得すること）")
            continue
        try:
            orig = Image.open(io.BytesIO(get(rec["download"])))
            orig.load()
        except Exception as e:
            errs.append(f"出典から画像を取得できない: {ref} ← {rec['download'][:80]}（{e}）")
            continue
        if bin(_dhash(orig) ^ _dhash(im)).count("1") > 10:
            errs.append(f"保存した画像が出典の画像と一致しない: {ref}")
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

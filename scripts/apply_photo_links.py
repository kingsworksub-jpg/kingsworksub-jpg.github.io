# -*- coding: utf-8 -*-
"""編集用写真(<figure class="photo...">の<img>)をAmazonアフィリエイトリンクで
包む。mapping JSON ({"slug": {"/images/.../x.jpg": "ASIN", ...}, ...}) を読み、
該当する<img src="...">をその直前直後で<a href="https://www.amazon.co.jp/dp/{ASIN}
?tag=nakimoto1-22" target="_blank" rel="noopener sponsored nofollow">...</a>で
包む。既に<a>で包まれているimgはスキップする(冪等)。

使い方:
    python apply_photo_links.py mapping.json
"""
import io
import json
import os
import re
import sys

BASE = r"C:\Users\norio\my-github-blog"
POSTS = os.path.join(BASE, "content", "posts")

TAG = "nakimoto1-22"


def wrap_image(text, src, asin):
    # img タグ全体にマッチ(src属性で特定)。既に何らかの <a href="..."> に包まれている
    # 場合は(Amazonであれ公式サイトであれ)スキップする(2026-10-23の事故対策: 既存の
    # <a>(例: 本家サイトへの意図的なリンク)にネストした<a>を差し込んで不正なHTMLを
    # 作ってしまったため。figure開始からこのimgまでの間に開いた<a>があるかを数える)。
    img_re = re.compile(r'<img\s+src="' + re.escape(src) + r'"[^>]*>')
    m = img_re.search(text)
    if not m:
        return text, "not-found"
    fig_start = text.rfind('<figure', 0, m.start())
    between = text[fig_start if fig_start != -1 else max(0, m.start() - 300):m.start()]
    opens = len(re.findall(r'<a\s+href=', between))
    closes = between.count('</a>')
    if opens > closes:
        return text, "already-linked"
    img_tag = m.group(0)
    href = f"https://www.amazon.co.jp/dp/{asin}?tag={TAG}"
    wrapped = f'<a href="{href}" target="_blank" rel="noopener sponsored nofollow">{img_tag}</a>'
    return text[:m.start()] + wrapped + text[m.end():], "ok"


def main():
    mapping_file = sys.argv[1]
    with io.open(mapping_file, encoding="utf-8") as f:
        mapping = json.load(f)

    for slug, images in mapping.items():
        path = os.path.join(POSTS, slug + ".md")
        if not os.path.exists(path):
            print(f"[skip] {slug}: file not found")
            continue
        with io.open(path, encoding="utf-8") as f:
            text = f.read()
        changed = False
        for src, asin in images.items():
            text, status = wrap_image(text, src, asin)
            print(f"  {slug} {src} -> {asin}: {status}")
            if status == "ok":
                changed = True
        if changed:
            with io.open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print(f"[saved] {slug}")


if __name__ == "__main__":
    main()

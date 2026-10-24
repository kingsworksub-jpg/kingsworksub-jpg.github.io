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
    # img タグ全体にマッチ(src属性で特定)。既に <a href="...amazon...">  に包まれて
    # いる場合はスキップする(直前50文字にamazonリンクのaタグがあれば既存とみなす)。
    img_re = re.compile(r'<img\s+src="' + re.escape(src) + r'"[^>]*>')
    m = img_re.search(text)
    if not m:
        return text, "not-found"
    before = text[max(0, m.start() - 120):m.start()]
    if re.search(r'<a\s+href="[^"]*amazon[^"]*"[^>]*>\s*$', before):
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

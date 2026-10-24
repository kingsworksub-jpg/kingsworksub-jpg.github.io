# -*- coding: utf-8 -*-
"""content/posts/*.md 内の <figure class="photo ..."> のうち、まだ Amazon リンクで
包まれていないものを列挙する(2026-10-23〜、新規アフィリエイトリンク付与プロジェクト用)。
"""
import glob
import io
import json
import os
import re

BASE = r"C:\Users\norio\my-github-blog"
POSTS = os.path.join(BASE, "content", "posts")

FIGURE_RE = re.compile(
    r'<figure class="photo photo--(left|right)">\s*'
    r'(?:<a\s+href="([^"]*)"[^>]*>\s*)?'
    r'<img\s+src="([^"]+)"[^>]*alt="([^"]*)"[^>]*>\s*(?:</a>\s*)?'
    r'<figcaption>(.*?)</figcaption>\s*'
    r'(?:<span class="credit">.*?</span>\s*)?'
    r'</figure>',
    re.S,
)

HEADING_RE = re.compile(r'^##\s+(.+)$', re.M)


def nearest_heading(text, pos):
    best = None
    for m in HEADING_RE.finditer(text):
        if m.start() > pos:
            break
        best = m.group(1).strip()
    return best


def main():
    out = []
    for path in sorted(glob.glob(os.path.join(POSTS, "*.md"))):
        slug = os.path.splitext(os.path.basename(path))[0]
        with io.open(path, encoding="utf-8") as f:
            text = f.read()
        for m in FIGURE_RE.finditer(text):
            side, href, src, alt, caption = m.groups()
            if href and "amazon." in href:
                continue  # already linked
            heading = nearest_heading(text, m.start())
            out.append({
                "slug": slug,
                "side": side,
                "src": src,
                "alt": alt,
                "caption": re.sub(r"<[^>]+>", "", caption).strip(),
                "heading": heading,
                "has_other_link": bool(href),
            })
    print(f"unlinked photo figures: {len(out)} across {len(set(o['slug'] for o in out))} articles")
    with io.open(os.path.join(BASE, "scripts", "photo-link-inventory.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

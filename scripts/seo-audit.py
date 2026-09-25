#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SEO/structrual audit for the Hugo blog. Writes reports/seo-audit-report.md"""
import os, re, sys, glob, urllib.request, urllib.error, urllib.parse
from pathlib import Path
from collections import defaultdict
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / "content" / "posts"
IMAGES = ROOT / "static" / "images"
OUT = ROOT / "scripts" / "seo-audit-report.md"

CHECK_LINKS = "--check-links" in sys.argv

def frontmatter(md: str):
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n(.*)", md, re.S)
    fm, body = (m.group(1), m.group(2)) if m else ("", md)
    title = re.search(r'^title\s*:\s*"(.+?)"\s*$', fm, re.M) or re.search(r"^title\s*:\s*(.+?)\s*$", fm, re.M)
    date = re.search(r"^date\s*:\s*([\d\-T:+ ]+)\s*$", fm, re.M)
    draft = bool(re.search(r"^draft\s*:\s*true", fm, re.M | re.I))
    return (title.group(1).strip() if title else "(no title)", date.group(1).strip() if date else "", body, draft)

def count_h(body, lvl=2, lvl2=3):
    # Hugo markdown headings. Japanese headings use full-width spaces; match '^#+ ' 
    h2 = re.findall(r"^##\s+.+", body, re.M)
    h3 = re.findall(r"^###\s+.+", body, re.M)
    return len(h2), len(h3)

def jp_chars(body):
    return len(re.sub(r"\s", "", body))

def images_in(body):
    md = re.findall(r"!\[[^\]]*\]\((/[^)]+?)(?:#|\s)", body)
    html = re.findall(r'<img[^>]*\bsrc="(/[^"]+)"', body)
    return sorted(set(p for p in md + html if p.startswith("/images/")))

def internal_links(body):
    md = re.findall(r"\]\((/posts/[^)#\s]+)", body)
    html = re.findall(r'href="(/posts/[^"]+)"', body)
    return sorted(set(md + html))

def external_links(body):
    md = re.findall(r"\]\((https?://[^)#\s]+)", body)
    html = re.findall(r'href="(https?://[^"]+)"', body)
    return sorted(set(md + html))

posts = {}
drafts = []
for p in sorted(POSTS.glob("*.md")):
    md = p.read_text(encoding="utf-8")
    title, date, body, draft = frontmatter(md)
    if draft:
        drafts.append(p.name)
        continue
    h2, h3 = count_h(body)
    posts[p.name] = dict(path=p, title=title, date=date, jp=jp_chars(body),
                         h2=h2, h3=h3,
                         imgs=images_in(body), internal=internal_links(body), external=external_links(body))

inbound = defaultdict(int)
for name, d in posts.items():
    for lk in d["internal"]:
        for n, dd in posts.items():
            if f"/posts/{n[:-3]}" in lk or f"/{n[:-3]}/" in lk:
                inbound[n] += 1

# images on disk
img_report = []
for f in sorted(IMAGES.rglob("*")):
    if f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        continue
    size_kb = f.stat().st_size / 1024
    try:
        w, h = Image.open(f).size
    except Exception:
        w, h = -1, -1
    if size_kb > 250 or w > 1600:
        img_report.append(f"{f.relative_to(ROOT)}\t{size_kb:.0f}KB\t{w}x{h}")

# unreferenced images (scan every /images/ token over content, layouts and config)
def norm_image(u):
    return u.strip().strip('"').split("#", 1)[0].split("?", 1)[0].strip(")")

image_refs = set()
for base in (ROOT / "content", ROOT / "layouts"):
    for p in base.rglob("*"):
        if p.suffix.lower() not in (".md", ".html"):
            continue
        for u in re.findall(r"/images/[A-Za-z0-9_./\"()-]+", p.read_text(encoding="utf-8", errors="replace")):
            image_refs.add(norm_image(u))
for p in ROOT.glob("*.toml"):
    for u in re.findall(r"/images/[A-Za-z0-9_./\"()-]+", p.read_text(encoding="utf-8", errors="replace")):
        image_refs.add(norm_image(u))

unused_imgs = []
for f in sorted(IMAGES.rglob("*")):
    if f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        continue
    rel = "/images/" + f.relative_to(IMAGES).as_posix()
    if rel not in image_refs:
        unused_imgs.append(f.relative_to(ROOT))

# broken external links (404/410 and hard network failures only;
# 403/405/429/503 are bot-blocks by big sites, not page failures)
# JS ゲート等で実ブラウザでは開けるのにボットに 404 を返すドメイン
SKIP_JS_GATE_DOMAINS = {"tal-software.com"}
broken = []
if CHECK_LINKS:
    seen = set()
    for name, d in posts.items():
        for url in d["external"]:
            if url in seen:
                continue
            seen.add(url)
            domain = urllib.parse.urlsplit(url).netloc.lower()
            try:
                req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
                urllib.request.urlopen(req, timeout=12)
            except urllib.error.HTTPError as e:
                if e.code in (404, 410) and domain not in SKIP_JS_GATE_DOMAINS:
                    broken.append((name, url, f"HTTP {e.code}: 削除済み"))
                elif e.code not in (403, 405, 429, 407, 503) and domain not in SKIP_JS_GATE_DOMAINS:
                    broken.append((name, url, f"HTTP {e.code}: 要確認"))
            except Exception as e:
                broken.append((name, url, f"接続失敗: {type(e).__name__}"))

lines = ["# SEO監査レポート(自動生成)\n"]
lines.append(f"生成日時: { __import__('datetime').datetime.now().isoformat() }\n")
lines.append(f"対象記事数: {len(posts)} (下書き: {len(drafts)})\n")
if drafts:
    lines.append(f"下書き(本番非掲載): {', '.join(drafts)}\n")
lines.append("\n## 記事サマリ (記事名 | 文字数 | h2/h3 | 画像数 | 内部リンク送信 | 被内部リンク)\n")
for name in sorted(posts, key=lambda n: posts[n]["date"], reverse=True):
    d = posts[name]
    t = d["title"]
    lines.append(f"- {name} ({d['date']}) | {d['jp']}字 | h2={d['h2']} h3={d['h3']} | 画像{len(d['imgs'])} | 内発{len(d['internal'])} | 被内{inbound[name]} | 「{t[:40]}」")
lines.append("\n## 孤立記事(被内部リンク0)\n")
for name in sorted(posts):
    if inbound[name] == 0:
        lines.append(f"- {name}")
lines.append("\n## 巨大画像 (>250KB または 幅>1600px)\n")
lines += [f"- {l}" for l in img_report] or ["- (なし)"]
lines.append("\n## 未参照画像(static/images で参照ゼロ)\n")
lines += [f"- {l}" for l in unused_imgs] or ["- (なし)"]
lines.append("\n## 破損外部リンク\n")
lines += [f"- {n}: {u} ({e})" for n, u, e in broken] or ["- (未チェック or なし)"]
lines.append("\n## 画像無し/文字数少ない記事\n")
for name in sorted(posts):
    d = posts[name]
    if not d["imgs"] or d["jp"] < 1200:
        lines.append(f"- {name}: 画像{len(d['imgs'])}/文字数{d['jp']}")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"written: {OUT.relative_to(ROOT)}")
print(f"posts={len(posts)} drafts={len(drafts)} orphans={sum(1 for n in posts if inbound[n]==0)} "
      f"big_images={len(img_report)} broken={len(broken)}")
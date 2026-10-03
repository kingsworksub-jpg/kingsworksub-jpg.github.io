"""Download a licensed image for a post and record where it came from.

    python scripts/fetch_image.py <slug> <dest> "File:Some photo.jpg"            # Wikimedia Commons
    python scripts/fetch_image.py <slug> <dest> https://commons.wikimedia.org/wiki/File:Some_photo.jpg
    python scripts/fetch_image.py <slug> <dest> <direct-image-url> --page <url> --license "CC BY 2.0" --author "Name"

<dest> is the path under static/ that the post will reference, e.g. images/condenser-mic/at2020.jpg.
The image is checked (decodes, real photo-like content), resized to at most 1000px and saved, and an entry is
written to scripts/image-sources/<slug>.json. validate_post.py re-downloads every recorded image and compares it
with the saved file, so images must come from this script; images drawn or generated locally are rejected.
Prints the credit text to put in <span class="credit">.
"""

from __future__ import annotations

import argparse
import html
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "StudioNotesBlogBot/1.0 (https://kingsworksub-jpg.github.io/; kingsworksub-jpg)"
MAX_SIDE = 1000
BANNED_LICENSE = re.compile(r"\b(NC|ND)\b|non-?commercial|no ?deriv", re.I)

sys.stdout.reconfigure(encoding="utf-8")


def get(url: str) -> bytes:
    # Wikimedia wants a descriptive bot UA; Flickr and others reject anything that says "Bot".
    ua = UA if "wikimedia.org" in url else "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def commons_info(title: str) -> dict:
    q = urllib.parse.urlencode({
        "action": "query", "titles": title, "prop": "imageinfo", "format": "json",
        "iiprop": "url|extmetadata|size|mime", "iiurlwidth": str(MAX_SIDE),
    })
    data = json.loads(get("https://commons.wikimedia.org/w/api.php?" + q))
    page = next(iter(data["query"]["pages"].values()))
    if "imageinfo" not in page:
        sys.exit(f"Commons にファイルが無い: {title}")
    ii = page["imageinfo"][0]
    meta = ii.get("extmetadata", {})
    strip = lambda s: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()
    return {
        "download": ii.get("thumburl") or ii["url"],
        "page": ii["descriptionurl"],
        "license": strip(meta.get("LicenseShortName", {}).get("value")),
        "author": strip(meta.get("Artist", {}).get("value"))[:80],
        "title": page["title"],
    }


def photo_problem(im: Image.Image) -> str | None:
    """Reject images that are obviously not real photos/screenshots (blank, flat, tiny)."""
    w, h = im.size
    if max(w, h) < 300 or min(w, h) < 120:
        return f"小さすぎる {w}x{h}"
    rgb = im.convert("RGB")
    thumb = rgb.resize((64, 64))
    colors = len(set(thumb.get_flattened_data()))
    if colors < 200:
        return f"色数が少なすぎる（{colors}色。単色・図形だけの画像の疑い）"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("dest", help="path under static/, e.g. images/foo/bar.jpg")
    ap.add_argument("source", help="Commons file title / Commons page URL / direct image URL")
    ap.add_argument("--page")
    ap.add_argument("--license")
    ap.add_argument("--author", default="")
    a = ap.parse_args()

    src = a.source
    m = re.search(r"commons\.wikimedia\.org/wiki/(File:[^?#]+)", src)
    if m:
        src = urllib.parse.unquote(m.group(1)).replace("_", " ")
    if src.startswith("File:"):
        info = commons_info(src)
    else:
        if not (a.page and a.license):
            sys.exit("直接URLのときは --page と --license が必要")
        info = {"download": src, "page": a.page, "license": a.license, "author": a.author, "title": ""}
    if not info["license"] or BANNED_LICENSE.search(info["license"]):
        sys.exit(f"使えないライセンス: {info['license']!r}（NC/ND・不明は不可）")

    im = Image.open(io.BytesIO(get(info["download"])))
    im.load()
    bad = photo_problem(im)
    if bad:
        sys.exit(f"画像として不適: {bad}")
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    dest = a.dest.lstrip("/").replace("\\", "/")
    if dest.startswith("static/"):
        dest = dest[len("static/"):]
    path = os.path.join(ROOT, "static", dest)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if path.lower().endswith((".jpg", ".jpeg")):
        im.convert("RGB").save(path, "JPEG", quality=85, optimize=True)
    else:
        im.save(path)

    rec_path = os.path.join(ROOT, "scripts", "image-sources", a.slug + ".json")
    os.makedirs(os.path.dirname(rec_path), exist_ok=True)
    rec = json.load(open(rec_path, encoding="utf-8")) if os.path.exists(rec_path) else {}
    rec["/" + dest] = info
    with open(rec_path, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)

    credit = f"Photo: {info['author']} / {info['license']}" if info["author"] else info["license"]
    print(json.dumps({"saved": "/" + dest, "size": f"{im.size[0]}x{im.size[1]}", "credit": credit,
                      "page": info["page"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

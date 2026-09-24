#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Search & download CC-licensed images from Wikimedia Commons with attribution."""
import argparse, json, re, sys
from pathlib import Path
import requests

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "StudioNotesBlog/1.0 (personal blog)"}

def api(params):
    r = requests.get(API, params=params, headers=UA, timeout=25)
    r.raise_for_status()
    return r.json()

def candidates(q, limit=10):
    data = api({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": q, "gsrnamespace": "6", "gsrlimit": limit,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime",
        "iiurlwidth": 1400,
    })
    pages = data.get("query", {}).get("pages", {})
    out = []
    for p in pages.values():
        ii = p.get("imageinfo", [{}])[0]
        if ii.get("mime") != "image/jpeg":
            continue
        w, h = ii.get("width", 0), ii.get("height", 0)
        if 700 <= w <= 2200 and 600 <= h <= 2400:
            meta = ii.get("extmetadata", {})
            lic = meta.get("LicenseShortName", {}).get("value", "")
            if not (("CC" in lic) or ("Public domain" in lic) or ("PD" in lic)):
                continue
            artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()
            artist = re.sub(r"\s+", " ", artist)
            out.append({
                "file": p["title"], "url": ii.get("thumburl") or ii.get("url"),
                "w": w, "h": h, "lic": lic, "artist": artist[:120],
                "desc": re.sub(r"<[^>]+>", "", meta.get("ImageDescription", {}).get("value", ""))[:200],
            })
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="list candidates only")
    ap.add_argument("--out", default=".")
    ap.add_argument("terms", nargs="+")
    args = ap.parse_args()

    for term in args.terms:
        print(f"\n=== {term} ===")
        for i, c in enumerate(candidates(term)):
            print(f"[{i}] {c['file']}\n    {c['w']}x{c['h']} {c['url']}\n    LIC={c['lic']} ARTIST={c['artist']}\n    {c['desc']}")
        if args.list:
            continue
        chosen = candidates(term)
        if not chosen:
            print("(no candidate)"); continue
        c = chosen[0]
        r = requests.get(c["url"], headers=UA, timeout=30)
        r.raise_for_status()
        name = c["file"].split(":")[-1].replace(" ", "_")
        p = Path(args.out) / name
        p.write_bytes(r.content)
        print(f"DOWNLOADED -> {p}")

if __name__ == "__main__":
    main()
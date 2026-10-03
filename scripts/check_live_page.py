"""Open a published post in a real browser (Playwright/Chromium) and check that it renders.

    python scripts/check_live_page.py <slug> [--base https://kingsworksub-jpg.github.io] [--shot out.png]

Checks every image in the article body actually loaded (naturalWidth > 0), and that a post with Amazon
links has product photos wrapped in Amazon associate links. Saves a full-page screenshot
(default: $TMP/<slug>.png) so the page can also be inspected by eye. Exit 1 on any problem.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--base", default="https://kingsworksub-jpg.github.io")
    ap.add_argument("--shot")
    a = ap.parse_args()
    url = f"{a.base}/posts/{a.slug}/"
    shot = a.shot or os.path.join(os.environ.get("TMP", tempfile.gettempdir()), f"{a.slug}.png")
    problems = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1280, "height": 900})
        resp = page.goto(url + "?v=" + str(os.getpid()), wait_until="networkidle")
        if not resp or resp.status != 200:
            sys.exit(f"NG {url}: HTTP {resp.status if resp else '?'}")
        # scroll through the page so lazy images load
        h = page.evaluate("document.body.scrollHeight")
        for y in range(0, h + 900, 600):
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(150)
        page.wait_for_load_state("networkidle")
        imgs = page.evaluate("""() => [...document.querySelectorAll('.post-content img')].map(i => ({
            src: i.getAttribute('src'), ok: i.complete && i.naturalWidth > 0,
            w: i.naturalWidth, shown: i.getBoundingClientRect().width,
            inFigure: !!i.closest('figure.photo'), link: i.closest('a') ? i.closest('a').href : null }))""")
        for i in imgs:
            status = "ok" if i["ok"] else "NOT LOADED"
            print(f"  {status:10} {i['src']}  natural={i['w']}px shown={round(i['shown'])}px"
                  + (f"  link={i['link'][:70]}" if i["link"] else ""))
            if not i["ok"]:
                problems.append(f"画像が表示されない: {i['src']}")
        has_amazon = page.evaluate("() => !!document.querySelector('.post-content a[href*=\"amazon.co.jp\"]')")
        if has_amazon and not any(i["inFigure"] and i["link"] and "amazon.co.jp" in i["link"] for i in imgs):
            problems.append("Amazon の製品を扱う記事なのに、Amazon リンクで包まれた写真が1枚も無い")
        if not imgs:
            problems.append("本文に画像が1枚も無い")
        page.screenshot(path=shot, full_page=True)
        b.close()
    print(f"screenshot: {shot}")
    if problems:
        print(f"NG {url}")
        for x in problems:
            print("  - " + x)
        sys.exit(1)
    print(f"OK {url}")


if __name__ == "__main__":
    main()

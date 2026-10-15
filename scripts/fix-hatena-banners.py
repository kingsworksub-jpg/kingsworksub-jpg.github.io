"""Re-sync every published Hatena entry so its Amazon banner has inline (CSS-free) sizing.

For each entry in the AtomPub collection: GET its current HTML, run hatena_banner.inline_banners,
and PUT it back (same title, published, no other change). Entries without a banner, or already
inlined, are skipped.

    python fix-hatena-banners.py                 # dry run: report what would change
    python fix-hatena-banners.py --apply         # update all
    python fix-hatena-banners.py --apply --only ENTRY_ID
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))
from hatena_banner import inline_banners  # noqa: E402
from hatena_api import load_env, request, list_entries  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", help="entry id (last part of the edit URL) to update")
    args = ap.parse_args()

    env = load_env()
    user, domain, key = env["HATENA_ID"], env["HATENA_BLOG_DOMAIN"], env["HATENA_API_KEY"]
    base = f"https://blog.hatena.ne.jp/{user}/{domain}/atom/entry"

    total = changed = failed = 0
    for e in list_entries(base, user, key):
        total += 1
        eid = e["edit"].rsplit("/", 1)[-1]
        if args.only and eid != args.only:
            continue
        if e["type"] != "text/html" or "product-banner" not in e["html"]:
            print(f"skip  (no banner / type={e['type']}): {e['title'][:40]}")
            continue
        new = inline_banners(e["html"])
        if new == e["html"]:
            print(f"ok    (already inlined): {e['title'][:40]}")
            continue
        n = len(re.findall(r'class="product-banner"', new))
        if not args.apply:
            print(f"WOULD update {n} banner(s): {e['title'][:40]} [{eid}]")
            changed += 1
            continue
        xml = ('<?xml version="1.0" encoding="utf-8"?>\n'
               '<entry xmlns="http://www.w3.org/2005/Atom" xmlns:app="http://www.w3.org/2007/app">\n'
               f'  <title>{escape(e["title"])}</title>\n'
               f'  <author><name>{escape(user)}</name></author>\n'
               f'  <content type="text/html"><![CDATA[{new}]]></content>\n'
               f'  <updated>{datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}</updated>\n'
               f'  <app:control><app:draft>{"yes" if e["draft"] else "no"}</app:draft></app:control>\n'
               '</entry>\n')
        try:
            status, _ = request(e["edit"], user, key, "PUT", xml.encode("utf-8"))
            print(f"UPDATED {status}: {n} banner(s): {e['title'][:40]} -> {e['url']}")
            changed += 1
        except Exception as ex:
            print(f"FAILED: {e['title'][:40]}: {ex}", file=sys.stderr)
            failed += 1
        time.sleep(1.0)
    print(f"\nentries seen: {total}, {'updated' if args.apply else 'would update'}: {changed}, failed: {failed}")


if __name__ == "__main__":
    main()

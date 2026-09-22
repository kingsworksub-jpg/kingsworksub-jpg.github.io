import html as html_mod
import json
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

with open(sys.argv[1], encoding="utf-8") as f:
    content = f.read()

chunks = content.split('data-component-type="s-search-result"')[1:]

results = []
seen = set()
for chunk in chunks:
    block = chunk[:12000]
    asin_m = re.search(r'data-asin="([A-Z0-9]{10})"', block)
    if not asin_m:
        continue
    asin = asin_m.group(1)
    if asin in seen:
        continue
    seen.add(asin)

    title_m = re.search(r'<h2[^>]*aria-label="([^"]+)"', block)
    title = html_mod.unescape(title_m.group(1)).strip() if title_m else ""

    price_m = re.search(r'a-price-whole">([\d,]+)', block)
    price = int(price_m.group(1).replace(",", "")) if price_m else None

    url = f"https://www.amazon.co.jp/dp/{asin}"

    results.append({"asin": asin, "title": title, "price": price, "url": url})

print(json.dumps(results, ensure_ascii=False, indent=2))

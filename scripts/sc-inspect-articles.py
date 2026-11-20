# -*- coding: utf-8 -*-
"""ゼロIMP記事を Search Console URL Inspection API で分类する（再開可能な小バッチ）。

- 対象: git 管理されている公開記事のうち、scripts/p0-sc.csv に載っていないもの
- 結果: data/sc-inspection-results.json に URL 単位で追記保存（途中停止しても再実行で続きから）
- 認証: GOOGLE_SERVICE_ACCOUNT_JSON / SC_SITE_URL

使い方:
    python scripts/sc-inspect-articles.py            # 未検査のものをすべて（並列4）
    python scripts/sc-inspect-articles.py --limit 20 # 最大20件だけ
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTS_DIR = os.path.join(ROOT, "content", "posts")
SC_CSV = os.path.join(ROOT, "scripts", "p0-sc.csv")
OUT_JSON = os.path.join(ROOT, "data", "sc-inspection-results.json")
SITE_DEFAULT = "https://kingsworksub-jpg.github.io/"
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
_local = threading.local()


def tracked_slugs() -> list[str]:
    out = subprocess.check_output(
        ["git", "ls-files", "content/posts"], cwd=ROOT, text=True, encoding="utf-8"
    )
    slugs = []
    for line in out.splitlines():
        if not line.endswith(".md"):
            continue
        path = os.path.join(ROOT, line.replace("/", os.sep))
        with io.open(path, "r", encoding="utf-8-sig") as fh:
            head = "".join(fh.readlines()[:40])
        if "\ndraft: true" in "\n" + head or "\ndraft: 'true'" in "\n" + head:
            continue
        slugs.append(os.path.basename(line)[:-3])
    return sorted(slugs)


def imp_slugs() -> set[str]:
    import re
    pat = re.compile(r"/posts/([^/?#]+)/?")
    got = set()
    with io.open(SC_CSV, "r", encoding="utf-8-sig", newline="") as fh:
        for row in __import__("csv").DictReader(fh):
            key = next(iter(row.values()), "") or ""
            m = pat.search(key)
            if m:
                got.add(m.group(1))
    return got


def load_results() -> dict:
    if os.path.exists(OUT_JSON):
        with io.open(OUT_JSON, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_results(results: dict) -> None:
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    tmp = OUT_JSON + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, OUT_JSON)


def service():
    if not hasattr(_local, "svc"):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if not raw:
            with io.open(os.path.join(ROOT, "data", "google-service-account.json"), "r", encoding="utf-8") as fh:
                raw = fh.read()
        info = json.loads(raw)
        cred = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        _local.svc = build("searchconsole", "v1", credentials=cred, cache_discovery=False)
    return _local.svc


def inspect_one(slug: str, site: str) -> dict:
    url = f"{site}posts/{slug}/"
    last = ""
    for attempt in range(4):
        try:
            r = service().urlInspection().index().inspect(
                body={"inspectionUrl": url, "siteUrl": site}
            ).execute()
            res = r.get("inspectionResult", {}).get("indexStatusResult", {})
            return {
                "url": url,
                "verdict": res.get("verdict", ""),
                "coverage": res.get("coverageState", ""),
                "last_crawl": res.get("lastCrawlTime", ""),
                "page_fetch": res.get("pageFetchState", ""),
                "robots": res.get("robotsTxtState", ""),
                "sitemap": r.get("inspectionResult", {}).get("sitemapResult", {}).get("sitemapName", ""),
                "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        except Exception as exc:
            last = str(exc)[:200]
            if "429" in last or "503" in last or "timed out" in last.lower():
                time.sleep(2 * (attempt + 1))
            else:
                break
    return {"url": url, "error": last, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def main() -> int:
    ap = argparse.ArgumentParser(description="ゼロIMP記事のURL検査（再開可能）")
    ap.add_argument("--limit", type=int, default=0, help="今回処理する最大件数（0=全部）")
    ap.add_argument("--workers", type=int, default=4, help="並列数（既定4）")
    args = ap.parse_args()

    site = (os.environ.get("SC_SITE_URL") or SITE_DEFAULT).strip()
    results = load_results()
    pending = [s for s in tracked_slugs() if s not in imp_slugs() and s not in results]
    if args.limit:
        pending = pending[: args.limit]
    print(f"pending={len(pending)} inspected_already={len(results)} workers={args.workers}", flush=True)
    if not pending:
        return 0

    done = 0
    save_every = 5
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(inspect_one, s, site): s for s in pending}
        for fut in as_completed(futures):
            slug = futures[fut]
            results[slug] = fut.result()
            done += 1
            if done % save_every == 0 or done == len(pending):
                save_results(results)
                print(f"  progress {done}/{len(pending)}", flush=True)
    save_results(results)
    print(f"OK: {OUT_JSON} (total {len(results)})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

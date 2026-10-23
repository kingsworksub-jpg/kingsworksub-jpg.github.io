# -*- coding: utf-8 -*-
"""全てのHatena公開済みエントリに対し、Amazonアフィリエイトリンクのtagを
hatena-img-sub-22 に一括で書き換えて再同期する(2026-10-23作業)。

スラッグ -> entry_id の対応は scripts/_tmp_hatena_slug_map.json (Hatenaの
AtomPubフィードを実際にfetchして現在のタイトルで突合済み) を使う。

1記事につき: 1) hugo buildして本文HTMLを抽出・tag書き換え(extract-post-html.sh
が自動で行う) 2) hatena_update.py でPUT更新。

進捗は scripts/_retag_hatena_progress.json に記録し、再実行時は成功済みを
スキップする(中断しても再開できるように)。
"""
import io
import json
import os
import subprocess
import sys
import time

BASE = r"C:\Users\norio\my-github-blog"
MAP_FILE = os.path.join(BASE, "scripts", "_tmp_hatena_slug_map.json")
PROGRESS_FILE = os.path.join(BASE, "scripts", "_retag_hatena_progress.json")
TITLE_FILE = os.path.join(BASE, "scripts", "_retag_title.txt")
HTML_FILE = os.path.join(BASE, "scripts", "_retag_body.html")


def load_json(path, default):
    if os.path.exists(path):
        with io.open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    slug_map = load_json(MAP_FILE, {})
    entries = load_json(os.path.join(BASE, "scripts", "_tmp_hatena_entries.json"), [])
    title_by_entry_id = {e["entry_id"]: e["title"] for e in entries}

    progress = load_json(PROGRESS_FILE, {})

    slugs = sorted(slug_map.keys())
    total = len(slugs)
    for i, slug in enumerate(slugs, 1):
        if progress.get(slug) == "ok":
            continue
        entry_id = slug_map[slug]["entry_id"]
        title = title_by_entry_id.get(entry_id)
        if not title:
            progress[slug] = "no-title"
            save_json(PROGRESS_FILE, progress)
            continue

        print(f"[{i}/{total}] {slug} (entry {entry_id})", flush=True)

        with io.open(TITLE_FILE, "w", encoding="utf-8") as f:
            f.write(title)

        extract = subprocess.run(
            ["bash", "scripts/extract-post-html.sh", slug, "scripts/_retag_body.html"],
            cwd=BASE, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if extract.returncode != 0 or not os.path.exists(HTML_FILE):
            print("  EXTRACT FAILED:", extract.stderr[-800:])
            progress[slug] = "extract-failed"
            save_json(PROGRESS_FILE, progress)
            continue

        update = subprocess.run(
            [sys.executable, "scripts/hatena_update.py", entry_id, TITLE_FILE, HTML_FILE],
            cwd=BASE, capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ},
        )
        print("  ", update.stdout.strip().splitlines()[-1] if update.stdout.strip() else "(no output)")
        if update.returncode != 0:
            print("  UPDATE FAILED:", update.stdout[-500:], update.stderr[-500:])
            progress[slug] = "update-failed"
        else:
            progress[slug] = "ok"
        save_json(PROGRESS_FILE, progress)
        time.sleep(1)

    ok = sum(1 for v in progress.values() if v == "ok")
    print(f"\nDone. {ok}/{total} updated successfully.")
    failed = {k: v for k, v in progress.items() if v != "ok"}
    if failed:
        print("Failures:", json.dumps(failed, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

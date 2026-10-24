# -*- coding: utf-8 -*-
"""全てのnote公開済み記事に対し、Amazonアフィリエイトリンク(「Amazonで見る: URL」の
テキストリンク)のtagをnote-img-sub-22に一括で書き換えて再同期する(2026-10-23作業)。

スラッグ -> note_key の対応は scripts/_tmp_note_slug_map.json を使う
(CLAUDE.mdのnoteテーブルと現在のfront matterタイトルを突合済み。曖昧な
重複1件は手動レビュー対象として除外済み)。

1記事につき: 1) convert-to-note.py で下書きを再生成(タグ書き換え込み)
2) post-to-note.py --edit-key で既存記事を直接開いて上書き・再公開。

進捗は scripts/_retag_note_progress.json に記録し、再実行時は成功済みを
スキップする(中断しても再開できるように)。1記事あたり数分かかる。
"""
import io
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE = r"C:\Users\norio\my-github-blog"
MAP_FILE = os.path.join(BASE, "scripts", "_tmp_note_slug_map.json")
PROGRESS_FILE = os.path.join(BASE, "scripts", "_retag_note_progress.json")


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
    progress = load_json(PROGRESS_FILE, {})

    slugs = sorted(slug_map.keys())
    total = len(slugs)
    for i, slug in enumerate(slugs, 1):
        if progress.get(slug) == "ok":
            continue
        key = slug_map[slug]["note_key"]
        print(f"\n[{i}/{total}] {slug} (key={key})", flush=True)

        conv = subprocess.run(
            [sys.executable, "scripts/convert-to-note.py", slug],
            cwd=BASE, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if conv.returncode != 0:
            print("  CONVERT FAILED:", conv.stderr[-500:])
            progress[slug] = "convert-failed"
            save_json(PROGRESS_FILE, progress)
            continue

        post = subprocess.run(
            [sys.executable, "scripts/post-to-note.py", "--edit-key", key,
             "--slug", slug, "--publish", "--no-wait", "--hold", "3"],
            cwd=BASE, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=600,
        )
        out = post.stdout
        print(out[-600:])
        if post.returncode == 0 and "RESULT: https://note.com/" in out:
            progress[slug] = "ok"
        else:
            print("  UPDATE FAILED (returncode=%s)" % post.returncode)
            print(post.stderr[-800:])
            progress[slug] = "update-failed"
        save_json(PROGRESS_FILE, progress)
        time.sleep(2)

    ok = sum(1 for v in progress.values() if v == "ok")
    print(f"\nDone. {ok}/{total} updated successfully.")
    failed = {k: v for k, v in progress.items() if v != "ok"}
    if failed:
        print("Failures:", json.dumps(failed, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

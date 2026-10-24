# -*- coding: utf-8 -*-
"""生存が確認できているAmeba公開済み記事に対し、Amazonアフィリエイトリンクの
tagをameba-img-sub-22に書き換えて再同期する(2026-10-23〜24作業)。

対象は ALIVE_SLUGS に列挙した、HTTP 200を直接確認済みのslugのみ(19件中9件は
404で消滅していたため対象外。別件として保留中)。スケジュール自動投稿と同じ
ブラウザプロファイルを使うため、タスクスケジューラの次回実行時刻を避けて
手動で時間を見て実行すること(STOP_BEFORE で安全マージンを切る)。
"""
import datetime
import io
import json
import os
import re
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = r"C:\Users\norio\my-github-blog"
PROGRESS_FILE = os.path.join(BASE, "scripts", "_retag_ameba_progress.json")

ALIVE_SLUGS = {
    "non-alcohol-beer-5choice-2026": "12981311163",
    "wilkinson-ginger-ale-dry-deep-dive-2026": "12981373235",
    "winter-coat-5types-2026": "12981373364",
    "sodastream-terra-carbonation-guide-2026": "12981488746",
    "dr-pepper-23-flavors-deep-dive-2026": "12981847669",
    "home-mocktail-soda-syrup-2026": "12981943133",
    "canned-coffee-5choice-2026": "12982044521",
    "ramune-5choice-2026": "12982141822",
    "irish-whiskey-pot-still-guide-2026": "12982371997",
    "energy-drink-caffeine-5choice-2026": "12982451423",
}

# このJSTローカル時刻を過ぎたら、スケジュール投稿との衝突を避けるため新規実行を始めない
STOP_BEFORE = os.environ.get("AMEBA_RETAG_STOP_BEFORE", "11:45")


def load_json(path, default):
    if os.path.exists(path):
        with io.open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_title(slug):
    path = os.path.join(BASE, "content", "posts", slug + ".md")
    with io.open(path, encoding="utf-8") as f:
        text = f.read(2000)
    m = re.search(r'^title:\s*"(.*?)"\s*$', text, re.M)
    if not m:
        m = re.search(r'^title:\s*(.+?)\s*$', text, re.M)
    return m.group(1) if m else slug


def main():
    progress = load_json(PROGRESS_FILE, {})
    slugs = sorted(ALIVE_SLUGS.keys())
    total = len(slugs)
    stop_h, stop_m = (int(x) for x in STOP_BEFORE.split(":"))

    for i, slug in enumerate(slugs, 1):
        if progress.get(slug) == "ok":
            continue
        now = datetime.datetime.now()
        if (now.hour, now.minute) >= (stop_h, stop_m):
            print(f"\n[stop] {STOP_BEFORE} を過ぎたため、スケジュール投稿との衝突を避けて停止します。"
                  f"残り: {[s for s in slugs if progress.get(s) != 'ok']}")
            break

        entry_id = ALIVE_SLUGS[slug]
        title = get_title(slug)
        print(f"\n[{i}/{total}] {slug} (entry={entry_id})", flush=True)

        proc = subprocess.run(
            [sys.executable, "scripts/post-to-ameba.py", "--update-entry", entry_id,
             "--slug", slug, "--expect-title", title],
            cwd=BASE, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=400,
        )
        out = proc.stdout
        print(out[-800:])
        if proc.stderr.strip():
            print("[stderr]", proc.stderr[-500:])

        if proc.returncode == 0 and "公開URL:" in out and "[abort]" not in out:
            progress[slug] = "ok"
        else:
            print(f"  UPDATE FAILED (returncode={proc.returncode})")
            progress[slug] = "failed"
        save_json(PROGRESS_FILE, progress)
        time.sleep(3)

    ok = sum(1 for v in progress.values() if v == "ok")
    print(f"\nDone. {ok}/{total} updated successfully.")


if __name__ == "__main__":
    main()

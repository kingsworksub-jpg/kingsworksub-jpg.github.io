# -*- coding: utf-8 -*-
"""note / Ameba の重複投稿・未記録IDを読み取り専用で監査する。

2026-11-24 の重複投稿事故の再発確認用。外部サイトへの投稿・削除・状態ファイルの
変更は一切行わない。出力は JSON (--out でファイルへ) とコンソール要約。

    python scripts/audit-platform-duplicates.py
    python scripts/audit-platform-duplicates.py --out data/duplicate-audit.json

必要なログインプロファイルは post-to-note.py / post-to-ameba.py と同じものを使う。
"""
import argparse
import collections
import importlib.util
import json
import os
import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
S = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(S)


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(S, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ameba = load_module("post_to_ameba_mod", "post-to-ameba.py")
note = load_module("post_to_note_mod", "post-to-note.py")
ADMIN_LIST_URL = ameba.ADMIN_LIST_URL
dismiss_dialogs = ameba.dismiss_dialogs
open_browser = ameba.open_browser
list_existing_notes = note.list_existing_notes

PLATFORMS = os.path.join(S, "post-platforms.json")

def list_ameba_entries():
    """管理画面の月別記事一覧から id/title/status を読み取る(読み取り専用)。"""
    rows, seen = [], set()
    with sync_playwright() as p:
        ctx = open_browser(p)
        page = ctx.new_page()
        page.goto(ADMIN_LIST_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        if "blog.ameba.jp/ucs/entry" not in page.url:
            raise RuntimeError("Amebaの記事一覧を開けません。post-to-ameba.py --login を実行してください。")
        for r in ameba.iter_admin_rows(page):
            if r["id"] not in seen:
                rows.append(r)
                seen.add(r["id"])
        ctx.close()
    return rows


def duplicates(rows, id_field):
    by_title = collections.defaultdict(list)
    for r in rows:
        by_title[r["title"]].append(r[id_field])
    return [{"title": t, "ids": ids} for t, ids in by_title.items() if len(ids) > 1]


def compare_state(platforms, rows, id_field, state_field, recorded_status):
    """外部に実在する記事が post-platforms.json に未記録/古く記録されていないか。"""
    by_title = collections.defaultdict(list)
    for r in rows:
        by_title[r["title"]].append(r)
    missing, stale = [], []
    for slug, state in platforms.items():
        title = (state or {}).get("title")
        if not title or title not in by_title:
            continue
        ids = {str(r[id_field]) for r in by_title[title]}
        recorded = state.get(state_field)
        if recorded in (None, "", 0, "0"):
            missing.append({"slug": slug, "title": title, "external_ids": sorted(ids)})
        elif str(recorded) not in ids and recorded != "N/A":
            stale.append({"slug": slug, "title": title, "recorded": recorded,
                          "external_ids": sorted(ids)})
    return {"missing_record": missing, "stale_record": stale}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="JSONレポートの出力先")
    ap.add_argument("--skip-ameba", action="store_true", help="Amebaの監査をスキップ")
    ap.add_argument("--skip-note", action="store_true", help="noteの監査をスキップ")
    args = ap.parse_args()

    platforms = json.load(open(PLATFORMS, encoding="utf-8"))
    report = {}

    if not args.skip_note:
        notes = list_existing_notes()
        report["note"] = {
            "total": len(notes),
            "duplicates": duplicates(notes, "key"),
            "drafts": [n for n in notes if n["status"] == "draft"],
            "state": compare_state(platforms, notes, "key", "note_key", "published"),
        }
    if not args.skip_ameba:
        ameba = list_ameba_entries()
        report["ameba"] = {
            "total": len(ameba),
            "duplicates": duplicates(ameba, "id"),
            "drafts": [n for n in ameba if n["status"] == "draft"],
            "state": compare_state(platforms, ameba, "id", "ameba_entry", "published"),
        }

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()

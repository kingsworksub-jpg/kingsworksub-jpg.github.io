# -*- coding: utf-8 -*-
"""post-platforms.json の記録状態を外部監査結果に合わせて修整する。

入力は audit-platform-duplicates.py の --out JSON。既定は dry-run で、
--apply を付けたときだけ post-platforms.json を書き換える。
重複記事の削除は行わない(削除はユーザー承認後に手動/専用コマンドで実施)。

    python scripts/audit-platform-duplicates.py --out data/duplicate-audit.json
    python scripts/repair-platform-state.py --audit data/duplicate-audit.json
    python scripts/repair-platform-state.py --audit data/duplicate-audit.json --apply
"""
import argparse
import datetime
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")
S = os.path.dirname(os.path.abspath(__file__))
PLATFORMS = os.path.join(S, "post-platforms.json")
NOTE_INDEX = os.path.join(S, "note-index.json")


def note_index_keys():
    d = json.load(open(NOTE_INDEX, encoding="utf-8")) if os.path.exists(NOTE_INDEX) else {}
    by_slug, by_title = {}, {}
    for n in d.get("notes", []):
        if n.get("slug"):
            by_slug.setdefault(n["slug"], []).append(n["key"])
        if n.get("title"):
            by_title.setdefault(n["title"], []).append(n["key"])
    return by_slug, by_title


def choose_note_key(title, candidates, by_slug, by_title, slug):
    """記録済みキーを優先し、次に note-index.json のキー、最後に最新publishを選ぶ。"""
    keys = set(candidates)
    for k in by_slug.get(slug, []):
        if k in keys:
            return k, "note-index slug"
    for k in by_title.get(title, []):
        if k in keys:
            return k, "note-index title"
    return sorted(keys)[-1], "latest key"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", required=True, help="audit-platform-duplicates.py の出力JSON")
    ap.add_argument("--apply", action="store_true", help="実際に post-platforms.json を更新する")
    args = ap.parse_args()

    audit = json.load(open(args.audit, encoding="utf-8"))
    platforms = json.load(open(PLATFORMS, encoding="utf-8"))
    by_slug, by_title = note_index_keys()
    changed = []

    note_by_title = {}
    for n in audit.get("note", {}).get("state", {}).get("_all", []):
        note_by_title.setdefault(n["title"], []).append(n)

    # 監査レポートには state 差分しか入っていないので、必要な外部IDは
    # missing_record / stale_record から取得する。
    for entry in audit.get("note", {}).get("state", {}).get("missing_record", []) + \
                 audit.get("note", {}).get("state", {}).get("stale_record", []):
        slug, title = entry["slug"], entry["title"]
        state = platforms.get(slug)
        if not state:
            continue
        keys = entry["external_ids"]
        key, why = choose_note_key(title, keys, by_slug, by_title, slug)
        if state.get("note_key") == key:
            continue
        changed.append({
            "slug": slug, "field": "note_key", "from": state.get("note_key"), "to": key,
            "why": why, "external_ids": keys,
        })
        if args.apply:
            state["note_key"] = key

    for entry in audit.get("ameba", {}).get("state", {}).get("missing_record", []) + \
                 audit.get("ameba", {}).get("state", {}).get("stale_record", []):
        slug, title = entry["slug"], entry["title"]
        state = platforms.get(slug)
        if not state:
            continue
        ids = [int(x) for x in entry["external_ids"]]
        recorded = state.get("ameba_entry")
        if isinstance(recorded, int) and recorded in ids:
            eid = recorded
            why = "already recorded"
        else:
            eid = max(ids)
            why = "latest entry"
        if state.get("ameba_entry") == eid:
            continue
        changed.append({
            "slug": slug, "field": "ameba_entry", "from": recorded, "to": eid,
            "why": why, "external_ids": ids,
        })
        if args.apply:
            state["ameba_entry"] = eid

    # IDが入ったら platforms と review フラグも整合させる。
    for slug, state in platforms.items():
        for plat, field in (("note", "note_key"), ("ameba", "ameba_entry"), ("hatena", "hatena_entry")):
            v = state.get(field)
            if v not in (None, "", 0, "0", "N/A") and plat not in state.get("platforms", []):
                changed.append({"slug": slug, "field": "platforms", "to": plat, "why": "id present"})
                if args.apply:
                    state["platforms"] = sorted(set(state.get("platforms", [])) | {plat})

    print(json.dumps(changed, ensure_ascii=False, indent=2))
    print(f"\n{len(changed)} change(s). {'APPLIED' if args.apply else 'DRY RUN'}")

    if args.apply and changed:
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec="seconds")
        for c in changed:
            s = platforms.get(c["slug"])
            if s is not None:
                s["updated_at"] = now
        backup = PLATFORMS + ".bak-" + now.replace(":", "").replace("+", "-")
        shutil.copy2(PLATFORMS, backup)
        tmp = PLATFORMS + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(platforms, f, ensure_ascii=False, indent=1)
            f.write("\n")
        os.replace(tmp, PLATFORMS)
        print(f"backup: {backup}")


if __name__ == "__main__":
    main()

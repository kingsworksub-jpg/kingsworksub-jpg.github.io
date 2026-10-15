"""Reconciles each published post's platform set (post-platforms.json) against PPP-change
requests dropped by the netaManager Android app (scripts/ppp-requests/*.json).

Deterministic, non-agent script. It is invoked directly by
scripts/scheduled/run-platform-sync.ps1 — never by a Claude Code job — because the work here
(diff a platform list, call an existing publish/delete function, commit) is mechanical, and an
LLM agent in the loop of an unattended destructive operation would make it non-deterministic
and harder to reason about, not safer.

Every external side effect (publish to a platform, delete from a platform) is followed
immediately by a commit+push of post-platforms.json, so a crash mid-run leaves a safely
resumable state: the next run just re-diffs against whatever post-platforms.json currently
records as true, rather than redoing or losing track of partially-applied work.

    python platform_sync.py backfill             # one-time: seed post-platforms.json from topic-log.json
    python platform_sync.py status                # pending requests + current per-slug platforms
    python platform_sync.py diff SLUG              # requested vs current platforms for one slug
    python platform_sync.py reconcile [--dry-run]  # process all pending ppp-requests

GitHub invariant: GitHub Pages is the rendering source for every other platform (Hatena/note/
Ameba content is generated FROM content/posts/<slug>.md) and the canonical backlink baked into
every cross-posted copy. It is therefore never treated as a peer platform that can be removed
on its own — removing it is only ever allowed as part of removing everything (full unpublish),
and re-adding it to a fully-unpublished slug is never automated (that needs a human to decide
whether/how to resurrect the content).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import topic_plan as tp  # noqa: E402
import hatena_api  # noqa: E402

ROOT = tp.ROOT
S = tp.S
PLATFORMS_FILE = os.path.join(S, "post-platforms.json")
PPP_REQUESTS = os.path.join(S, "ppp-requests")
TMP = os.path.join(S, "tmp-ppp-sync")
ALL_PLATFORMS = ("github", "hatena", "ameba", "note")


# ---------------------------------------------------------------------------
# state file
# ---------------------------------------------------------------------------

def load_platforms() -> dict:
    return tp.load(PLATFORMS_FILE, {})


def save_platforms(d: dict) -> None:
    tp.save(PLATFORMS_FILE, d)


def rel(path: str) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


def git_commit_push(message: str, paths: list[str]) -> bool:
    """Stage exactly `paths` (existing or deleted), commit, then push. Returns False (no-op) if
    nothing in `paths` actually changed — callers should not assume a commit was made.

    The commit itself always either succeeds or raises (correctness of local git/filesystem
    state is non-negotiable — every caller relies on it before moving to its next step). The
    push is best-effort: on failure it retries once after a fetch+rebase (handles origin having
    moved), and if that still fails it only prints a warning rather than raising, so a single
    transient network/push hiccup doesn't abort the whole reconcile run (which, mid-loop, may
    already hold other slugs' local-only commits that still need to be processed/committed).
    scripts/scheduled/run-platform-sync.ps1 does a final `git push` sweep after every run as a
    safety net, so an unpushed local commit here is caught up at the latest by the next run.
    """
    for p in paths:
        tp.git("add", "-A", "--", p, check=True)
    status = tp.git("status", "--porcelain", "--", *paths)
    if not status.strip():
        return False
    tp.git("commit", "-m", message, check=True)
    try:
        tp.git("push", check=True)
    except RuntimeError:
        try:
            tp.git("fetch", "-q", "origin", check=True)
            tp.git("rebase", "origin/main", check=True)
            tp.git("push", check=True)
        except RuntimeError as ex:
            print(f"  [warn] git push failed after retry (commit is local-only for now): {ex}",
                  file=sys.stderr)
    return True


# ---------------------------------------------------------------------------
# backfill
# ---------------------------------------------------------------------------

def backfill() -> int:
    """Seed post-platforms.json from topic-log.json's published entries, and fill in `title`
    (the real article headline, from content/posts/<slug>.md's frontmatter) for every tracked
    slug that's missing one — including already-tracked slugs. The queue's `theme` field is a
    planning-stage working title that the final article headline is deliberately rewritten from
    (see CLAUDE.md's title-writing rules), so it must never be shown as if it were the title;
    `title` here is the only place the real one is cheaply available to the Android app without
    an extra fetch per card.

    New slugs are added with `platforms: ["github"]` only — NOT a category->channel guess (that
    guess is what caused platforms to disagree with reality in the first place: category-plan.json's
    mapping has changed over time, so applying today's mapping to an old post is unreliable, and it
    also ignores publish failures). `verify()` fills in the rest from confirmed signals. Otherwise
    only adds slugs not already tracked — safe to re-run after a manual ameba_entry edit without
    clobbering it."""
    platforms = load_platforms()
    log = tp.load(tp.LOG, {"entries": []})
    latest_by_slug: dict[str, dict] = {}
    for e in log["entries"]:
        if e.get("status") == "published" and e.get("slug"):
            latest_by_slug[e["slug"]] = e  # later entries overwrite earlier ones for the same slug
    title_by_slug = {p["slug"]: p["title"] for p in tp.posts()}

    added = 0
    for slug, e in latest_by_slug.items():
        if slug in platforms:
            continue
        platforms[slug] = {
            "title": title_by_slug.get(slug, e.get("theme", slug)),
            "platforms": ["github"],
            "hatena_entry": e.get("hatena_entry"),
            "note_key": e.get("note_key"),
            "ameba_entry": None,  # never tracked historically; backfill by hand from CLAUDE.md if needed
            "needs_manual_review": None,
            "updated_at": tp.now().isoformat(timespec="seconds"),
        }
        added += 1

    retitled = 0
    for slug, state in platforms.items():
        if not state.get("title") and slug in title_by_slug:
            state["title"] = title_by_slug[slug]
            retitled += 1

    save_platforms(platforms)
    print(f"backfilled {added} new slug(s), filled in {retitled} missing title(s); {len(platforms)} tracked total")
    return added


def discover_hatena_entries() -> dict[str, dict]:
    """Title -> {entry_id, url} for every non-draft entry in the Hatena AtomPub feed. Read-only
    (a GET over the same API post-to-hatena.sh/update-hatena-post.sh already use for writes)."""
    env = hatena_api.load_env()
    user, domain, key = env["HATENA_ID"], env["HATENA_BLOG_DOMAIN"], env["HATENA_API_KEY"]
    base = f"https://blog.hatena.ne.jp/{user}/{domain}/atom/entry"
    out: dict[str, dict] = {}
    for e in hatena_api.list_entries(base, user, key):
        if e["draft"] or not e["edit"]:
            continue
        out[e["title"]] = {"entry_id": int(e["edit"].rsplit("/", 1)[-1]), "url": e["url"]}
    return out


def verify() -> dict:
    """Recomputes `platforms` for every tracked slug from VERIFIED ground truth, replacing
    whatever was there before (but never clobbering a manually- or previously-confirmed entry
    id). This is the actual fix for platforms disagreeing with the real blogs: the old logic
    inferred platforms from category-plan.json's current category->channel mapping, which drifts
    over time (categories/channels have been added, renamed and reassigned — see CLAUDE.md) and
    says nothing about whether a given post's publish to that channel actually succeeded.

    - github: always included (content/posts/<slug>.md existing is the fact itself).
    - hatena: included iff hatena_entry is already recorded, OR discoverable by an exact title
      match against the live Hatena AtomPub feed (post-to-hatena.sh posts under the article's
      exact frontmatter title, so this match is reliable) — newly discovered ids are recorded.
    - note: included iff note_key is already recorded. No passive, unauthenticated way to list
      a note.com account's published articles exists in this codebase (note.com has no public
      listing API and the existing automation only reaches it via a logged-in Playwright
      session) — slugs without a recorded note_key are flagged, not guessed.
    - ameba: included iff ameba_entry is already recorded (never auto-discovered — same
      reasoning as note, and Ameba's existing-entry list page has never been explored either).

    category-plan.json's channel is used ONLY to word the manual-review note (e.g. "this
    category normally goes to ameba but no ameba_entry is recorded"), never to assert a platform.
    """
    platforms = load_platforms()
    category_by_slug = {p["slug"]: p["category"] for p in tp.posts()}
    hatena_by_title = discover_hatena_entries()

    changed = 0
    for slug, state in platforms.items():
        before = (list(state.get("platforms", [])), state.get("hatena_entry"), state.get("needs_manual_review"))
        title = state.get("title")

        if not state.get("hatena_entry") and title and title in hatena_by_title:
            state["hatena_entry"] = hatena_by_title[title]["entry_id"]

        confirmed = ["github"]
        if state.get("hatena_entry"):
            confirmed.append("hatena")
        if state.get("note_key"):
            confirmed.append("note")
        if state.get("ameba_entry"):
            confirmed.append("ameba")
        state["platforms"] = confirmed

        expected_channel = tp.channel_for(category_by_slug.get(slug, ""))
        if expected_channel != "github" and expected_channel not in confirmed:
            label = {"hatena": "はてな", "note": "note", "ameba": "アメブロ"}.get(expected_channel, expected_channel)
            state["needs_manual_review"] = (
                f"カテゴリー上は{label}が想定されますが、entry_idが未記録のため確認できていません。"
                f"実際に{label}に投稿済みなら、該当IDをpost-platforms.jsonに手動で追記してください。"
            )
        elif (state.get("needs_manual_review") or "").startswith("カテゴリー上は"):
            state["needs_manual_review"] = None  # the earlier gap was since resolved

        if (state["platforms"], state.get("hatena_entry"), state.get("needs_manual_review")) != before:
            state["updated_at"] = tp.now().isoformat(timespec="seconds")
            changed += 1

    save_platforms(platforms)
    print(f"verified {len(platforms)} slug(s), {changed} changed")
    return {"checked": len(platforms), "changed": changed}


# ---------------------------------------------------------------------------
# request handling
# ---------------------------------------------------------------------------

def pending_requests() -> dict[str, dict]:
    """Newest ppp-request per slug. Older duplicate requests for the same slug are deleted
    unactioned (the newest one supersedes them) — this also removes unparseable files."""
    by_slug: dict[str, list[tuple[str, dict]]] = {}
    for f in sorted(glob.glob(os.path.join(PPP_REQUESTS, "*.json"))):
        try:
            d = tp.load(f, None)
        except json.JSONDecodeError:
            d = None
        if not d or not d.get("slug"):
            os.remove(f)
            continue
        by_slug.setdefault(d["slug"], []).append((f, d))
    result = {}
    for slug, entries in by_slug.items():
        entries.sort(key=lambda fe: fe[1].get("requested_at", ""))
        *stale, newest = entries
        for f, _ in stale:
            os.remove(f)
        result[slug] = {"file": newest[0], "request": newest[1]}
    return result


def normalize_target(requested: list, current: list) -> tuple[list, str | None]:
    """Apply the GitHub invariant. Returns (effective_target_platforms, note). `note` is set
    when the literal request was adjusted or rejected; the caller should record it."""
    req = set(requested)
    if not req:
        return [], None  # empty PPP = full unpublish, exactly what was asked
    if "github" not in req:
        return [], "github は単独では外せないため、全プラットフォームからの削除として扱いました"
    if not current:
        return list(current), "この記事は現在どのプラットフォームにも公開されていないため、自動では復元しません(要手動対応)"
    return sorted(req), None


# ---------------------------------------------------------------------------
# content helpers
# ---------------------------------------------------------------------------

def post_md_path(slug: str) -> str:
    return os.path.join(ROOT, "content", "posts", f"{slug}.md")


def post_title(slug: str) -> str:
    for p in tp.posts():
        if p["slug"] == slug:
            return p["title"]
    raise RuntimeError(f"content/posts/{slug}.md が見つからない、またはfrontmatterが壊れています")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    kw.setdefault("cwd", ROOT)
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("encoding", "utf-8")
    kw.setdefault("timeout", 900)
    return subprocess.run(cmd, **kw)


# ---------------------------------------------------------------------------
# GitHub (source of truth)
# ---------------------------------------------------------------------------

def referenced_elsewhere(image_rel_path: str, exclude_slug: str) -> bool:
    """True if any OTHER (non-excluded) post still references this /images/... path.
    Mirrors seo-audit.py's unreferenced-image scan, scoped to a single candidate path."""
    needle = image_rel_path
    for f in glob.glob(os.path.join(ROOT, "content", "posts", "*.md")):
        slug = os.path.basename(f)[:-3]
        if slug == exclude_slug:
            continue
        body = open(f, encoding="utf-8-sig", errors="replace").read()
        if needle in body:
            return True
    return False


def remove_github(slug: str) -> list[str]:
    """git rm the post + any static/images files only this post references. Returns the list
    of repo-relative paths removed (for the caller's commit)."""
    removed = []
    md = post_md_path(slug)
    if not os.path.exists(md):
        return removed
    body = open(md, encoding="utf-8-sig", errors="replace").read()
    for image_path in sorted(set(re.findall(r"/images/[A-Za-z0-9_./-]+", body))):
        if referenced_elsewhere(image_path, slug):
            continue
        full = os.path.join(ROOT, image_path.lstrip("/"))
        if os.path.exists(full):
            os.remove(full)
            removed.append(rel(full))
    os.remove(md)
    removed.append(rel(md))
    return removed


# ---------------------------------------------------------------------------
# Hatena
# ---------------------------------------------------------------------------

def _hatena_env() -> dict:
    env = dict(os.environ)
    env.update(hatena_api.load_env())
    return env


def add_hatena(slug: str) -> int:
    out_html = os.path.join(TMP, f"{slug}.html")
    os.makedirs(TMP, exist_ok=True)
    r = run(["bash", os.path.join(S, "extract-post-html.sh"), slug, out_html])
    if r.returncode != 0:
        raise RuntimeError(f"extract-post-html.sh failed: {r.stderr[-500:] or r.stdout[-500:]}")
    r = run(["bash", os.path.join(S, "post-to-hatena.sh"), post_title(slug), out_html, "publish"],
            env=_hatena_env())
    if r.returncode != 0:
        raise RuntimeError(f"post-to-hatena.sh failed: {r.stderr[-500:] or r.stdout[-500:]}")
    m = re.search(r"atom/entry/(\d+)", r.stdout)
    if not m:
        raise RuntimeError(f"post-to-hatena.sh output に entry id が見つかりません: {r.stdout[-500:]}")
    return int(m.group(1))


def remove_hatena(entry_id: int) -> None:
    env = _hatena_env()
    r = run(["bash", os.path.join(S, "delete-hatena-post.sh"), str(entry_id)], env=env)
    if r.returncode != 0:
        raise RuntimeError(f"delete-hatena-post.sh failed: {r.stdout[-500:]}{r.stderr[-500:]}")


# ---------------------------------------------------------------------------
# note.com
# ---------------------------------------------------------------------------

def add_note(slug: str) -> str:
    r = run(["python", os.path.join(S, "convert-to-note.py"), slug])
    if r.returncode != 0:
        raise RuntimeError(f"convert-to-note.py failed: {r.stderr[-500:] or r.stdout[-500:]}")
    r = run(["python", os.path.join(S, "post-to-note.py"), "--slug", slug, "--publish", "--no-wait"],
            timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"post-to-note.py failed: {r.stderr[-500:] or r.stdout[-500:]}")
    m = re.search(r"RESULT:\s*(\S*/n/([a-z0-9]+))", r.stdout)
    if not m:
        raise RuntimeError(
            "post-to-note.py の出力から公開URL/keyを特定できません(公開が完了していない可能性があります): "
            f"{r.stdout[-800:]}")
    return m.group(2)


def remove_note(key: str, expected_title: str) -> None:
    """Delete a published note. UNVERIFIED territory: the draft-deletion UI pattern documented
    in CLAUDE.md ('その他' menu -> '削除' -> confirm dialog) is attempted against a published
    note's editor screen, which has never been confirmed to behave the same way. post-to-note.py's
    delete_note() aborts (raises) instead of clicking anything destructive if the editor's title
    doesn't match `expected_title`, or if the expected menu/dialog elements aren't found."""
    r = run(["python", os.path.join(S, "post-to-note.py"), "--delete-key", key,
             "--expect-title", expected_title], timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"note delete failed: {r.stdout[-500:]}{r.stderr[-500:]}")


# ---------------------------------------------------------------------------
# Ameba
# ---------------------------------------------------------------------------

def add_ameba(slug: str) -> int:
    r = run(["python", os.path.join(S, "post-to-ameba.py"), "--slug", slug, "--publish"], timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"post-to-ameba.py failed: {r.stdout[-500:]}{r.stderr[-500:]}")
    m = re.search(r"entry_id=(\d+)", r.stdout)
    if not m:
        raise RuntimeError(f"post-to-ameba.py の出力に entry_id が見つかりません: {r.stdout[-500:]}")
    return int(m.group(1))


def remove_ameba(entry_id: int, expected_title: str) -> None:
    """UNVERIFIED territory: Ameba's existing-entry list/edit page has never been explored in
    this codebase. post-to-ameba.py's delete_entry() aborts instead of clicking anything
    destructive if the row/title can't be confidently matched."""
    r = run(["python", os.path.join(S, "post-to-ameba.py"), "--delete-entry", str(entry_id),
             "--expect-title", expected_title], timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"ameba delete failed: {r.stdout[-500:]}{r.stderr[-500:]}")


# ---------------------------------------------------------------------------
# reconcile
# ---------------------------------------------------------------------------

def reconcile(dry_run: bool = False) -> dict:
    # Keeps post-platforms.json current for posts published since the last run (complete() in
    # topic_plan.py doesn't touch this file) and fills in any missing `title`s, then re-verifies
    # every tracked slug's platforms against confirmed signals (see verify()'s docstring for why
    # this can't just be done once at backfill time -- it must run every cycle so a newly
    # discovered/recorded hatena_entry etc. keeps platforms honest). Both are cheap and
    # idempotent -- neither touches already-correct data.
    if not dry_run:
        backfill()
        verify()
        git_commit_push("PPP: backfill + verify platforms", [rel(PLATFORMS_FILE)])
    platforms = load_platforms()
    requests = pending_requests()
    summary = {"slugs": 0, "added": 0, "removed": 0, "errors": 0, "flagged": 0}

    for slug, req in requests.items():
        summary["slugs"] += 1
        state = platforms.setdefault(slug, {
            "platforms": [], "hatena_entry": None, "note_key": None, "ameba_entry": None,
            "needs_manual_review": None, "updated_at": tp.now().isoformat(timespec="seconds"),
        })
        current = state.get("platforms", [])
        target, note = normalize_target(req["request"].get("platforms", []), current)

        if note and target == current:
            # Hard reject: nothing to actually do (e.g. can't resurrect a fully-unpublished
            # slug automatically). Record why and consume the request so it isn't retried
            # forever; the user has to resubmit after manual handling if they still want it.
            print(f"[{slug}] rejected: {note}{' (dry-run)' if dry_run else ''}")
            summary["flagged"] += 1
            if dry_run:
                continue
            state["needs_manual_review"] = note
            state["updated_at"] = tp.now().isoformat(timespec="seconds")
            save_platforms(platforms)
            git_commit_push(f"PPP: flag {slug} ({note})", [rel(PLATFORMS_FILE)])
            os.remove(req["file"])
            git_commit_push(f"PPP: consume rejected request for {slug}", [rel(req["file"])])
            continue

        if note:
            # Soft adjustment (e.g. "github removed" normalized to a full unpublish): the
            # literal request was altered, but we still act on the adjusted `target` below.
            # The note is recorded alongside the real state changes further down, not here,
            # so a dry run never writes anything and a crash mid-action doesn't lose it.
            summary["flagged"] += 1

        to_add = [p for p in target if p not in current]
        to_remove = [p for p in current if p not in target]
        title = post_title(slug) if os.path.exists(post_md_path(slug)) else state.get("last_known_title", slug)

        print(f"[{slug}] current={current} target={target} add={to_add} remove={to_remove}"
              f"{' (dry-run)' if dry_run else ''}")
        if dry_run:
            continue

        # Clears a stale flag when this request supersedes an earlier adjusted/failed one;
        # sets it when this run's request was itself adjusted (soft case above).
        state["needs_manual_review"] = note

        try:
            for plat in to_add:
                if plat == "github":
                    continue  # github is the source; it's only ever removed, never separately re-added here
                if plat == "hatena":
                    state["hatena_entry"] = add_hatena(slug)
                elif plat == "note":
                    state["note_key"] = add_note(slug)
                elif plat == "ameba":
                    state["ameba_entry"] = add_ameba(slug)
                state["platforms"] = sorted(set(state["platforms"]) | {plat})
                state["updated_at"] = tp.now().isoformat(timespec="seconds")
                save_platforms(platforms)
                git_commit_push(f"PPP: add {plat} for {slug}", [rel(PLATFORMS_FILE)])
                tp.log_entry(id=f"ppp-{slug}", category="", theme=title, slug=slug,
                              status="platform_added", reason=plat)
                summary["added"] += 1

            for plat in to_remove:
                # Each branch must either perform the deletion or raise — falling through
                # without deleting anything must NEVER reach the "mark as removed" line below,
                # or we'd silently record a platform as gone while the live post is still up.
                if plat == "hatena":
                    if not state.get("hatena_entry"):
                        raise RuntimeError(
                            f"{slug}: hatena_entry が記録されておらず自動削除できません(手動で削除し、"
                            "post-platforms.jsonを修正してください)")
                    remove_hatena(state["hatena_entry"])
                    state["hatena_entry"] = None
                elif plat == "note":
                    if not state.get("note_key"):
                        raise RuntimeError(
                            f"{slug}: note_key が記録されておらず自動削除できません(手動で削除し、"
                            "post-platforms.jsonを修正してください)")
                    remove_note(state["note_key"], title)
                    state["note_key"] = None
                elif plat == "ameba":
                    if not state.get("ameba_entry"):
                        raise RuntimeError(
                            f"{slug}: ameba_entry が記録されておらず自動削除できません(手動で削除し、"
                            "post-platforms.jsonを修正してください)")
                    remove_ameba(state["ameba_entry"], title)
                    state["ameba_entry"] = None
                elif plat == "github":
                    removed_paths = remove_github(slug)
                    if removed_paths:
                        git_commit_push(f"PPP: unpublish {slug} from github",
                                         [rel(os.path.join(ROOT, p)) for p in removed_paths])
                else:
                    raise RuntimeError(f"{slug}: unknown platform {plat!r}")
                state["platforms"] = [p for p in state["platforms"] if p != plat]
                state["updated_at"] = tp.now().isoformat(timespec="seconds")
                save_platforms(platforms)
                git_commit_push(f"PPP: remove {plat} for {slug}", [rel(PLATFORMS_FILE)])
                tp.log_entry(id=f"ppp-{slug}", category="", theme=title, slug=slug,
                              status="unpublished" if not state["platforms"] else "platform_removed",
                              reason=plat)
                summary["removed"] += 1

            os.remove(req["file"])
            git_commit_push(f"PPP: done with {slug}", [rel(req["file"])])
        except Exception as ex:  # noqa: BLE001
            print(f"  [error] {slug}: {ex}", file=sys.stderr)
            state["needs_manual_review"] = f"reconcile error: {ex}"
            state["updated_at"] = tp.now().isoformat(timespec="seconds")
            save_platforms(platforms)
            git_commit_push(f"PPP: {slug} needs manual review after an error", [rel(PLATFORMS_FILE)])
            summary["errors"] += 1
            # leave the request file in place so the next run retries from wherever state now is

    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backfill")
    sub.add_parser("verify")
    sub.add_parser("status")
    sub.add_parser("diff").add_argument("slug")
    r = sub.add_parser("reconcile")
    r.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.cmd == "backfill":
        backfill()
    elif a.cmd == "verify":
        verify()
    elif a.cmd == "status":
        platforms = load_platforms()
        pending = pending_requests()
        print(f"tracked slugs: {len(platforms)}, pending requests: {len(pending)}")
        for slug, info in pending.items():
            cur = platforms.get(slug, {}).get("platforms", [])
            print(f"  {slug}: current={cur} requested={info['request'].get('platforms')}")
        flagged = {s: v.get("needs_manual_review") for s, v in platforms.items() if v.get("needs_manual_review")}
        if flagged:
            print("needs manual review:")
            for s, reason in flagged.items():
                print(f"  {s}: {reason}")
    elif a.cmd == "diff":
        platforms = load_platforms()
        pending = pending_requests()
        if a.slug not in pending:
            print(f"{a.slug}: 保留中のリクエストはありません")
            return
        current = platforms.get(a.slug, {}).get("platforms", [])
        target, note = normalize_target(pending[a.slug]["request"].get("platforms", []), current)
        print(json.dumps({"slug": a.slug, "current": current, "requested": pending[a.slug]["request"],
                          "effective_target": target, "note": note}, ensure_ascii=False, indent=1))
    elif a.cmd == "reconcile":
        summary = reconcile(dry_run=a.dry_run)
        print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

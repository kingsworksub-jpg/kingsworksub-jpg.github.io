"""Topic planning helper for the automated blog pipeline.

Holds the deterministic parts so the planning / posting jobs (Claude Code or opencode
only has to do the creative work:

  status [--json]            category priorities, queue counts, today's posts, today's engine
  allocate N                 split N new topics across categories by priority
  today-count                number of published posts dated today (JST), manual posts included
  engine                     model used by the jobs (always "claude" since 2026-10-02)
  slot                       the fixed daily time-slot nearest to now (channel + content preference; see SLOTS)
  similar TEXT               closest existing posts / queued / logged topics (2-gram Jaccard)
  add FILE                   add candidate topics (JSON list) to the queue after a duplicate check
  claim                      apply app deletions, pick the next approved topic (slot-aware), mark it in_progress
  complete ID --slug S [--hatena ID] [--note KEY]
  fail ID --reason R         retry later (rejected after 2 failures)
  reject ID --reason R
  sync-skips                 apply deletions made in the Android app (scripts/topic-skips/*.json)
  ingest-requests            turn topics added in the Android app (scripts/topic-requests/*.json) into queue items
  images QUERY [--n N]       licence-checked image candidates (Wikimedia Commons + Openverse)
  news CATEGORY [--days D]   recent headlines from the category's feeds (topic-sources.json)
  calendar                   seasonal topics for this month and next (topic-calendar.json)
  matrix CATEGORY            evergreen idea axes for a category (topic-matrix.json)
  gaps                       existing-content gaps (compared products without a deep dive, etc.)
  health                     consecutive posting failures (the job pauses at 3)
  run-status --job J --state S [--detail D]
                             record a job run (started / finished / failed / timeout) in pipeline-status.json
                             (called by run-claude-task.ps1 so the Android app sees every run, even launch failures)
  bootstrap                  register every published post in topic-log.json (run once)
  count STATUS               number of queue items with that status (e.g. in_progress), for the job runner
  release-stale --reason R   return abandoned in_progress topics to the queue as failures
  health-reset --reason R    clear the consecutive-failure pause after a human has fixed the cause
  snapshot FILE              save the working-tree state before a job (git status), used by recover
  recover --snapshot FILE --reason R
                             after a failed job: drop its unpushed commits and leftover files, return abandoned
                             in_progress topics to the queue, and push the queue (used before the engine fallback)
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "scripts")
QUEUE = os.path.join(S, "topics-queue.json")
LOG = os.path.join(S, "topic-log.json")
CATS = os.path.join(S, "category-plan.json")
SKIPS = os.path.join(S, "topic-skips")
REQUESTS = os.path.join(S, "topic-requests")
STATUS_FILE = os.path.join(S, "pipeline-status.json")
JST = dt.timezone(dt.timedelta(hours=9))
UA = "StudioNotesBot/1.0 (kingswork.sub@gmail.com)"
WINDOW = 60
MIN_SCORE = 60
DUP_THRESHOLD = 0.45
MAX_RETRY = 2

# Fixed daily posting schedule (2026-10-08 redesign: replaced the 8 runs/2h cadence with 6 slots
# timed 30-60 min ahead of each traffic peak, each pinned to one channel so the three platforms
# post evenly through the day instead of being decided purely by category priority). Each slot can
# also narrow which categories or article_types it prefers, so the two slots sharing a channel read
# differently (e.g. practical tech in the morning vs. theory at night). Preferences are soft: if no
# approved topic matches, claim() falls back to any topic in the right channel, then to anything at
# all, so a thin queue never stalls the run.
SLOTS = [
    {"time": "07:30", "channel": "github", "categories": ["lab", "notes"],
     "label": "朝: 検証メモ/個人備忘録"},
    {"time": "12:00", "channel": "hatena", "categories": ["tech", "software", "setup"],
     "label": "昼: テック/ソフト/制作環境"},
    {"time": "17:30", "channel": "ameba", "categories": ["gear", "learning"],
     "label": "夕: 機材レビュー/学習体験談"},
    {"time": "20:00", "channel": "ameba", "categories": ["fashion", "drink"],
     "label": "夜: ファッション/飲料"},
    {"time": "21:30", "channel": "note", "categories": ["whisky", "music", "sakeware"],
     "label": "夜ピーク: ウイスキー/音楽/酒器"},
    {"time": "23:00", "channel": "note", "categories": ["essay"],
     "label": "就寝前: カルチャーエッセイ"},
]
POSTS_PER_DAY = len(SLOTS)

sys.stdout.reconfigure(encoding="utf-8")


def now() -> dt.datetime:
    return dt.datetime.now(JST)


def load(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, data):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def posts():
    out = []
    for f in glob.glob(os.path.join(ROOT, "content", "posts", "*.md")):
        s = open(f, encoding="utf-8-sig").read().replace("\r\n", "\n")
        m = re.match(r"---\n(.*?)\n---", s, re.S)
        if not m or re.search(r"(?m)^draft:\s*true", m.group(1)):
            continue
        fm = m.group(1)
        title = re.search(r'(?m)^title:\s*"?(.*?)"?\s*$', fm).group(1)
        cm = re.search(r"(?m)^categories:\s*\[([^\]]*)\]", fm) or re.search(r"(?m)^categories:\s*\n\s*-\s*(\S+)", fm)
        cat = re.sub(r"[\[\]\"' ]", "", cm.group(1).split(",")[0]) if cm else ""
        dm = re.search(r'(?m)^date:\s*"?([0-9T:\-+.]+)', fm)
        date = dm.group(1) if dm else ""
        tm = re.search(r"(?m)^tags:\s*\[([^\]]*)\]", fm)
        tags = [t.strip().strip("\"'") for t in tm.group(1).split(",")] if tm else []
        out.append({"slug": os.path.basename(f)[:-3], "title": title, "category": cat, "date": date, "tags": tags})
    return sorted(out, key=lambda p: p["date"])


def post_date(p) -> dt.date | None:
    d = p["date"]
    if not d:
        return None
    try:
        if "T" in d:
            x = dt.datetime.fromisoformat(d)
            return (x if x.tzinfo else x.replace(tzinfo=JST)).astimezone(JST).date()
        return dt.date.fromisoformat(d[:10])
    except ValueError:
        return None


def engine_for(day: dt.date) -> str:
    """Every job runs on Claude Code (the daily big-pickle alternation was dropped on 2026-10-02)."""
    return "claude"


def categories():
    return load(CATS, [])


def category_meta(cat_id):
    """Return the category-plan entry (with channel / content_dir) for a category id."""
    for c in categories():
        if c["id"] == cat_id:
            return c
    return {"id": cat_id, "name": cat_id, "weight": 1.0, "channel": "github", "content_dir": "tech"}


def channel_for(cat_id):
    """Distribution channel for a category: github / hatena / note."""
    return category_meta(cat_id).get("channel", "github")


def content_dir_for(cat_id):
    """Hugo content sub-directory for a category: tech / reviews / culture."""
    return category_meta(cat_id).get("content_dir", "tech")


def _slot_minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def slot_for(moment: "dt.datetime | None" = None) -> dict:
    """The fixed daily slot (see SLOTS) nearest to `moment` (default: now, JST)."""
    moment = moment or now()
    mins = moment.hour * 60 + moment.minute
    return min(SLOTS, key=lambda s: abs(_slot_minutes(s["time"]) - mins))


def slot_match_score(it, slot) -> tuple:
    """Lower sorts first. (0/1 channel mismatch, 0/1 preferred-category-or-type mismatch)."""
    channel_mismatch = 0 if channel_for(it["category"]) == slot["channel"] else 1
    if "categories" in slot:
        pref_mismatch = 0 if it["category"] in slot["categories"] else 1
    elif "article_types" in slot:
        pref_mismatch = 0 if it.get("article_type") in slot["article_types"] else 1
    else:
        pref_mismatch = 0
    return (channel_mismatch, pref_mismatch)


def priorities():
    cats = categories()
    ps = posts()
    recent = ps[-WINDOW:]
    total_w = sum(c.get("weight", 1.0) for c in cats) or 1
    today = now().date()
    rows = []
    for c in cats:
        if c.get("weight", 1.0) <= 0:
            continue
        target = c.get("weight", 1.0) / total_w
        share = sum(1 for p in recent if p["category"] == c["id"]) / max(len(recent), 1)
        dates = [post_date(p) for p in ps if p["category"] == c["id"]]
        dates = [d for d in dates if d]
        days = (today - max(dates)).days if dates else 30
        pri = (target - share) * 3 + min(days / 7, 1) * 0.3
        rows.append({"id": c["id"], "name": c["name"], "target": round(target, 3), "share": round(share, 3),
                     "days_since": days, "total": sum(1 for p in ps if p["category"] == c["id"]),
                     "priority": round(max(pri, 0.05), 3)})
    return sorted(rows, key=lambda r: -r["priority"])


def allocate(n: int, per_day: int = POSTS_PER_DAY):
    """Hand out n slots one at a time, re-scoring after each as if that post had gone out."""
    cats = [c for c in categories() if c.get("weight", 1.0) > 0]
    total_w = sum(c.get("weight", 1.0) for c in cats) or 1
    ps = posts()
    recent = [p["category"] for p in ps[-WINDOW:]]
    today = now().date()
    last = {}
    for p in ps:
        d = post_date(p)
        if d:
            last[p["category"]] = max(last.get(p["category"], d), d)
    queued = [it["category"] for it in queue()["items"] if it["status"] in ("approved", "in_progress")]
    recent = (recent + queued)[-WINDOW:]
    alloc = {c["id"]: 0 for c in cats}
    for i in range(n):
        day = today + dt.timedelta(days=i // per_day)

        def score(c):
            share = recent.count(c["id"]) / max(len(recent), 1)
            days = (day - last[c["id"]]).days if c["id"] in last else 30
            return (c.get("weight", 1.0) / total_w - share) * 3 + min(days / 7, 1) * 0.3

        best = max(cats, key=lambda c: (score(c), -alloc[c["id"]]))
        alloc[best["id"]] += 1
        recent = (recent + [best["id"]])[-WINDOW:]
        last[best["id"]] = day
    return alloc


def today_count() -> int:
    t = now().date()
    return sum(1 for p in posts() if post_date(p) == t)


def bigrams(s: str):
    s = re.sub(r"[\s、。・「」『』（）()!！?？,，.:：\-—]+", "", s.lower())
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def sim(a: str, b: str) -> float:
    x, y = bigrams(a), bigrams(b)
    return len(x & y) / len(x | y) if x and y else 0.0


def corpus():
    items = [("post", p["slug"], p["title"] + " " + " ".join(p["tags"])) for p in posts()]
    for it in load(QUEUE, {"items": []})["items"]:
        if it.get("status") not in ("deleted",):
            items.append(("queue:" + it.get("status", ""), it["id"], it["theme"] + " " + " ".join(it.get("keywords", []))))
    for e in load(LOG, {"entries": []})["entries"]:
        if e.get("status") in ("rejected", "deleted"):
            items.append(("log:" + e["status"], e.get("id", ""), e.get("theme", "")))
    return items


def similar(text: str, top=5):
    scored = [(round(sim(text, t), 3), kind, key, t[:60]) for kind, key, t in corpus()]
    return sorted(scored, key=lambda x: -x[0])[:top]


def log_entry(**kw):
    log = load(LOG, {"entries": []})
    kw.setdefault("at", now().isoformat(timespec="seconds"))
    log["entries"].append(kw)
    save(LOG, log)


def queue():
    return load(QUEUE, {"updated": "", "items": []})


def save_queue(q):
    q["updated"] = now().isoformat(timespec="seconds")
    save(QUEUE, q)
    write_status()


def write_status(extra=None):
    q = queue()
    st = load(STATUS_FILE, {})
    counts = {}
    for it in q["items"]:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    pending = len(glob.glob(os.path.join(REQUESTS, "*.json")))
    st.update({"updated": now().isoformat(timespec="seconds"), "queue": counts, "pending_requests": pending,
               "today_posts": today_count(), "daily_limit": POSTS_PER_DAY, "engine_today": engine_for(now().date())})
    if extra:
        st.update(extra)
    save(STATUS_FILE, st)


JOB_LABELS = {"blog-post": "投稿", "topic-planning": "ネタ会議", "topic-topup": "ネタ補充"}


def run_status(job, state, detail=""):
    st = load(STATUS_FILE, {})
    at = now().isoformat(timespec="seconds")
    label = JOB_LABELS.get(job, job)
    if state == "started":
        extra = {"current_job": {"job": job, "label": label, "since": at, "engine": engine_for(now().date())}}
    else:
        extra = {"current_job": None,
                 "last_run": {"job": job, "label": label, "state": state, "at": at,
                              "engine": engine_for(now().date()), "detail": detail[:300]}}
        runs = st.get("recent_runs", [])
        runs.insert(0, extra["last_run"])
        extra["recent_runs"] = runs[:10]
    write_status(extra)


def sync_skips():
    q = queue()
    ids = {}
    for f in glob.glob(os.path.join(SKIPS, "*.json")):
        try:
            d = load(f, {})
        except json.JSONDecodeError:
            continue
        ids[d.get("id") or os.path.basename(f)[:-5]] = d
    changed = 0
    for it in q["items"]:
        if it["id"] in ids and it["status"] in ("approved", "hold", "failed"):
            it["status"] = "deleted"
            it["deleted_at"] = ids[it["id"]].get("deleted_at", now().isoformat(timespec="seconds"))
            log_entry(id=it["id"], category=it["category"], theme=it["theme"], status="deleted", reason="Androidアプリで削除")
            changed += 1
    if changed:
        save_queue(q)
    return changed


def ingest_requests():
    """Topics typed into the Android app arrive as scripts/topic-requests/<name>.json.

    Each becomes an approved, user-sourced queue item (posted before anything else). They carry
    only a theme (plus optional category and memo), so the posting job researches them and finds
    images itself. The request file is deleted; the caller commits that deletion.
    """
    files = sorted(glob.glob(os.path.join(REQUESTS, "*.json")))
    if not files:
        return 0
    q = queue()
    known = {c["id"] for c in categories()}
    week = now().strftime("%Gw%V")
    n0 = sum(1 for it in q["items"] if it["id"].startswith(week + "-r"))
    done = 0
    for f in files:
        try:
            d = load(f, {})
        except json.JSONDecodeError:
            os.remove(f)
            continue
        theme = (d.get("theme") or "").strip()
        if theme:
            n0 += 1
            cat = d.get("category") if d.get("category") in known else ""
            q["items"].append({
                "id": f"{week}-r{n0:02d}", "status": "approved", "category": cat, "new_category": None,
                "theme": theme, "angle": (d.get("memo") or "").strip(), "article_type": d.get("article_type") or "",
                "keywords": [], "subjects": [], "sources": [], "images": [], "season": "",
                "score": {"total": 100}, "source_of_idea": "user", "needs_research": True,
                "requested_at": d.get("requested_at", ""), "created": now().date().isoformat(), "retry": 0,
            })
            log_entry(id=f"{week}-r{n0:02d}", category=cat, theme=theme, status="requested", reason="Androidアプリから追加")
            done += 1
        os.remove(f)
    save_queue(q)
    return done


REQUIRED = ("category", "theme", "angle", "article_type", "keywords", "sources", "images", "score")


def add(path):
    cands = load(path, [])
    q = queue()
    known = {c["id"] for c in categories()}
    week = now().strftime("%Gw%V")
    n0 = sum(1 for it in q["items"] if it["id"].startswith(week))
    added, rejected = [], []
    for c in cands:
        miss = [k for k in REQUIRED if k not in c]
        total = c.get("score", {}).get("total", 0)
        best = similar(c.get("theme", "") + " " + " ".join(c.get("keywords", [])), 1)
        dup = best[0] if best and best[0][0] >= DUP_THRESHOLD else None
        cat_ok = c.get("category") in known or c.get("new_category")
        reason = ("不足項目: " + ",".join(miss)) if miss else \
                 (f"点数{total}<{MIN_SCORE}" if total < MIN_SCORE else
                  (f"重複({dup[2]} {dup[0]})" if dup else
                   ("画像候補が2件未満" if len(c.get("images", [])) < 2 else
                    ("未登録カテゴリー" if not cat_ok else ""))))
        if reason and c.get("source_of_idea") != "user":
            rejected.append((c.get("theme", ""), reason))
            log_entry(id="", category=c.get("category", ""), theme=c.get("theme", ""), status="rejected", reason=reason)
            continue
        n0 += 1
        item = dict(c)
        item.update({"id": f"{week}-{n0:03d}", "status": "approved", "created": now().date().isoformat(), "retry": 0})
        q["items"].append(item)
        added.append(item["id"])
    save_queue(q)
    print(json.dumps({"added": added, "rejected": rejected}, ensure_ascii=False, indent=1))


def last_category():
    ps = posts()
    return ps[-1]["category"] if ps else ""


def claim():
    ingest_requests()
    sync_skips()
    q = queue()
    ready = [it for it in q["items"] if it["status"] == "approved"]
    if not ready:
        print(json.dumps({"empty": True}))
        return
    order = {r["id"]: i for i, r in enumerate(priorities())}
    last = last_category()
    slot = slot_for()
    user_first = sorted(ready, key=lambda it: (not it.get("pinned"),
                                                *slot_match_score(it, slot),
                                                it.get("source_of_idea") != "user",
                                                it["category"] == last,
                                                order.get(it["category"], 99),
                                                -it.get("score", {}).get("total", 0)))
    it = user_first[0]
    it["status"] = "in_progress"
    it["claimed_at"] = now().isoformat(timespec="seconds")
    it["channel"] = channel_for(it["category"])
    it["content_dir"] = content_dir_for(it["category"])
    it["slot_time"] = slot["time"]
    it["slot_label"] = slot["label"]
    save_queue(q)
    print(json.dumps(it, ensure_ascii=False, indent=1))


def find(q, tid):
    for it in q["items"]:
        if it["id"] == tid:
            return it
    sys.exit(f"no such topic: {tid}")


def complete(tid, slug, hatena=None, note=None, category=None):
    q = queue()
    it = find(q, tid)
    if category:
        it["category"] = category
    it.update({"status": "published", "slug": slug, "published_at": now().isoformat(timespec="seconds"), "channel": it.get("channel", "github")})
    save_queue(q)
    log_entry(id=tid, category=it["category"], theme=it["theme"], slug=slug, status="published",
              url=f"https://kingsworksub-jpg.github.io/posts/{slug}/", hatena_entry=hatena, note_key=note,
              engine=engine_for(now().date()))
    write_status({"last_result": f"published {slug}", "consecutive_failures": 0})


def fail(tid, reason):
    q = queue()
    it = find(q, tid)
    it["retry"] = it.get("retry", 0) + 1
    it["status"] = "rejected" if it["retry"] >= MAX_RETRY else "approved"
    it["last_error"] = reason
    save_queue(q)
    log_entry(id=tid, category=it["category"], theme=it["theme"], status="failed", reason=reason,
              engine=engine_for(now().date()))
    write_status({"last_result": f"failed {tid}: {reason}", "consecutive_failures": health()})


def reject(tid, reason):
    q = queue()
    it = find(q, tid)
    it["status"] = "rejected"
    it["last_error"] = reason
    save_queue(q)
    log_entry(id=tid, category=it["category"], theme=it["theme"], status="rejected", reason=reason)


def health() -> int:
    n = 0
    for e in reversed(load(LOG, {"entries": []})["entries"]):
        if e.get("status") in ("published", "health-reset"):
            break
        if e.get("status") == "failed":
            n += 1
    return n


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def images(query, n=6):
    out = []
    try:
        q = urllib.parse.quote(query)
        d = http_json("https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=search"
                      f"&gsrnamespace=6&gsrlimit={n * 2}&gsrsearch={q}&prop=imageinfo&iiprop=url|size|extmetadata|mime&iiurlwidth=800")
        for p in d.get("query", {}).get("pages", {}).values():
            i = p["imageinfo"][0]
            m = i["extmetadata"]
            lic = m.get("LicenseShortName", {}).get("value", "")
            if not i["mime"].startswith("image/") or "NC" in lic or "ND" in lic:
                continue
            out.append({"source": "commons", "title": p["title"][5:], "url": i.get("thumburl") or i["url"],
                        "page": i["descriptionurl"], "license": lic,
                        "author": re.sub(r"<[^>]+>", "", m.get("Artist", {}).get("value", "")).strip()[:60],
                        "size": f'{i["width"]}x{i["height"]}'})
    except Exception as e:  # noqa: BLE001
        out.append({"error": f"commons: {e}"})
    try:
        d = http_json(f"https://api.openverse.org/v1/images/?q={urllib.parse.quote(query)}&license_type=commercial&page_size={n}")
        for r in d.get("results", []):
            if "nd" in r["license"]:
                continue
            out.append({"source": r["source"], "title": r["title"][:60], "url": r["url"], "page": r["foreign_landing_url"],
                        "license": f'{r["license"].upper()} {r["license_version"]}', "author": (r.get("creator") or "")[:60],
                        "size": f'{r.get("width")}x{r.get("height")}'})
    except Exception as e:  # noqa: BLE001
        out.append({"error": f"openverse: {e}"})
    print(json.dumps(out[: n * 2], ensure_ascii=False, indent=1))


def news(cat, days=14):
    src = load(os.path.join(S, "topic-sources.json"), {}).get(cat, [])
    cutoff = now() - dt.timedelta(days=days)
    for feed in src:
        try:
            req = urllib.request.Request(feed, headers={"User-Agent": "Mozilla/5.0"})
            root = ET.fromstring(urllib.request.urlopen(req, timeout=20).read())
        except Exception as e:  # noqa: BLE001
            print(f"## {feed} (取得失敗: {e})")
            continue
        print(f"## {feed}")
        shown = 0
        for el in root.iter():
            tag = el.tag.split("}")[-1]
            if tag not in ("item", "entry"):
                continue
            g = {c.tag.split("}")[-1]: (c.text or c.get("href") or "") for c in el}
            when = g.get("pubDate") or g.get("date") or g.get("updated") or g.get("published") or ""
            try:
                from email.utils import parsedate_to_datetime
                t = parsedate_to_datetime(when) if "," in when else dt.datetime.fromisoformat(when.replace("Z", "+00:00"))
                if t.tzinfo and t < cutoff:
                    continue
            except Exception:  # noqa: BLE001, S110
                pass
            print(f"- {g.get('title', '').strip()[:90]} | {g.get('link', '').strip()}")
            shown += 1
            if shown >= 15:
                break


def calendar():
    cal = load(os.path.join(S, "topic-calendar.json"), {})
    m = now().month
    for mm in (m, m % 12 + 1):
        print(f"## {mm}月")
        for line in cal.get(str(mm), []):
            print("- " + line)


def matrix(cat):
    print(json.dumps(load(os.path.join(S, "topic-matrix.json"), {}).get(cat, {}), ensure_ascii=False, indent=1))


def gaps():
    ps = posts()
    slugs = {p["slug"] for p in ps}
    titles = " ".join(p["title"] for p in ps)
    print("## 比較記事で紹介しているが単独記事が無い製品")
    for p in ps:
        if not re.search(r"(5choice|10choice)", p["slug"]):
            continue
        s = open(os.path.join(ROOT, "content", "posts", p["slug"] + ".md"), encoding="utf-8-sig").read()
        for name in re.findall(r"(?m)^## ([^\n—]+?)\s+—", s):
            name = name.strip()
            key = re.sub(r"[^a-z0-9]", "", name.lower())[:8]
            if key and not any(key in re.sub(r"[^a-z0-9]", "", x) for x in slugs) and name not in titles:
                print(f"- {name}（{p['slug']}）")
    print("## タグに出てくるが主役の記事が無い話題（出現2回以上）")
    from collections import Counter
    cnt = Counter(t for p in ps for t in p["tags"] if t)
    for t, c in cnt.most_common(60):
        if c >= 2 and t not in titles:
            print(f"- {t}（{c}記事）")


def git(*args, check=False):
    import subprocess
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def porcelain():
    out = {}
    for line in git("status", "--porcelain", "--untracked-files=all").splitlines():
        if len(line) > 3:
            out[line[3:].strip().strip('"')] = line[:2]
    return out


def snapshot(path):
    save(path, {"head": git("rev-parse", "HEAD").strip(), "status": porcelain()})


def release_stale(reason):
    q = queue()
    n = 0
    for it in q["items"]:
        if it["status"] == "in_progress":
            it["retry"] = it.get("retry", 0) + 1
            it["status"] = "rejected" if it["retry"] >= MAX_RETRY else "approved"
            it["last_error"] = reason
            log_entry(id=it["id"], category=it["category"], theme=it["theme"], status="failed", reason=reason,
                      engine=engine_for(now().date()))
            n += 1
    if n:
        save_queue(q)
    return n


def recover(snap_path, reason):
    """Undo what a failed job left behind, without touching changes that existed before it started."""
    import shutil
    snap = load(snap_path, {"head": "", "status": {}})
    git("fetch", "-q", "origin")
    ahead = git("rev-list", "origin/main..HEAD").split()
    if ahead:
        git("reset", "-q", "--mixed", "origin/main", check=True)  # unpushed commits from the failed run
    files = ["scripts/topics-queue.json", "scripts/topic-log.json", "scripts/pipeline-status.json"]
    released = release_stale(reason)  # first, so the claim is recorded as a failure, not silently reverted
    before = snap["status"]
    removed, restored = [], []
    for path, code in porcelain().items():
        if path in files or (path in before and before[path] == code):
            continue
        full = os.path.normpath(os.path.join(ROOT, path))
        if code == "??" and path.startswith(("content/", "static/", "scripts/note-drafts/")):
            if os.path.isdir(full):
                shutil.rmtree(full, ignore_errors=True)
            elif os.path.exists(full):
                os.remove(full)
            removed.append(path)
            img_root = os.path.normpath(os.path.join(ROOT, "static", "images"))
            parent = os.path.dirname(full)
            while parent.startswith(img_root) and parent != img_root and os.path.isdir(parent) and not os.listdir(parent):
                os.rmdir(parent)
                parent = os.path.dirname(parent)
        elif code.strip() in ("M", "MM", "AM", "D") and path not in before:
            git("checkout", "-q", "origin/main", "--", path)
            restored.append(path)
    git("add", *files)
    if git("diff", "--cached", "--name-only").strip():
        git("commit", "-q", "-m", f"Recover: {reason[:60]}", "--", *files)
        git("pull", "-q", "--rebase", "--autostash", "origin", "main")
        git("push", "-q", "origin", "main")
    print(json.dumps({"dropped_commits": len(ahead), "removed": removed, "restored": restored,
                      "released_topics": released}, ensure_ascii=False))


def bootstrap():
    log = load(LOG, {"entries": []})
    have = {e.get("slug") for e in log["entries"] if e.get("status") == "published"}
    for p in posts():
        if p["slug"] in have:
            continue
        log["entries"].append({"id": "post-" + p["slug"], "category": p["category"], "theme": p["title"],
                               "slug": p["slug"], "status": "published", "at": p["date"], "engine": "legacy"})
    save(LOG, log)
    print(f"log entries: {len(log['entries'])}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").add_argument("--json", action="store_true")
    sub.add_parser("allocate").add_argument("n", type=int)
    sub.add_parser("today-count")
    sub.add_parser("engine")
    sub.add_parser("slot")
    sub.add_parser("similar").add_argument("text")
    sub.add_parser("add").add_argument("file")
    sub.add_parser("claim")
    c = sub.add_parser("complete")
    c.add_argument("id")
    c.add_argument("--slug", required=True)
    c.add_argument("--hatena")
    c.add_argument("--note")
    c.add_argument("--category")
    for name in ("fail", "reject"):
        x = sub.add_parser(name)
        x.add_argument("id")
        x.add_argument("--reason", required=True)
    sub.add_parser("sync-skips")
    sub.add_parser("ingest-requests")
    x = sub.add_parser("images")
    x.add_argument("query")
    x.add_argument("--n", type=int, default=6)
    x = sub.add_parser("news")
    x.add_argument("category")
    x.add_argument("--days", type=int, default=14)
    sub.add_parser("calendar")
    sub.add_parser("matrix").add_argument("category")
    sub.add_parser("gaps")
    sub.add_parser("health")
    x = sub.add_parser("run-status")
    x.add_argument("--job", required=True)
    x.add_argument("--state", required=True, choices=["started", "finished", "failed", "timeout", "skipped"])
    x.add_argument("--detail", default="")
    sub.add_parser("bootstrap")
    sub.add_parser("snapshot").add_argument("file")
    sub.add_parser("count").add_argument("status")
    sub.add_parser("release-stale").add_argument("--reason", required=True)
    sub.add_parser("health-reset").add_argument("--reason", required=True)
    x = sub.add_parser("recover")
    x.add_argument("--snapshot", required=True)
    x.add_argument("--reason", required=True)
    a = ap.parse_args()

    if a.cmd == "status":
        q = queue()
        counts = {}
        for it in q["items"]:
            counts[it["status"]] = counts.get(it["status"], 0) + 1
        data = {"engine_today": engine_for(now().date()), "today_posts": today_count(), "daily_limit": POSTS_PER_DAY,
                "queue": counts, "consecutive_failures": health(), "priorities": priorities()}
        if a.json:
            print(json.dumps(data, ensure_ascii=False, indent=1))
        else:
            print(f"engine={data['engine_today']} today={data['today_posts']}/{POSTS_PER_DAY} queue={counts} failures={data['consecutive_failures']}")
            for r in data["priorities"]:
                print(f"  {r['id']:10} pri={r['priority']:<6} share={r['share']:<6} target={r['target']:<6} last={r['days_since']}d total={r['total']}")
    elif a.cmd == "allocate":
        print(json.dumps(allocate(a.n), ensure_ascii=False))
    elif a.cmd == "today-count":
        print(today_count())
    elif a.cmd == "engine":
        print(engine_for(now().date()))
    elif a.cmd == "slot":
        print(json.dumps(slot_for(), ensure_ascii=False, indent=1))
    elif a.cmd == "similar":
        for row in similar(a.text):
            print(*row, sep=" | ")
    elif a.cmd == "add":
        add(a.file)
    elif a.cmd == "claim":
        claim()
    elif a.cmd == "complete":
        complete(a.id, a.slug, a.hatena, a.note, a.category)
    elif a.cmd == "fail":
        fail(a.id, a.reason)
    elif a.cmd == "reject":
        reject(a.id, a.reason)
    elif a.cmd == "ingest-requests":
        print(f"ingested: {ingest_requests()}")
    elif a.cmd == "sync-skips":
        print(f"deleted: {sync_skips()}")
    elif a.cmd == "images":
        images(a.query, a.n)
    elif a.cmd == "news":
        news(a.category, a.days)
    elif a.cmd == "calendar":
        calendar()
    elif a.cmd == "matrix":
        matrix(a.category)
    elif a.cmd == "gaps":
        gaps()
    elif a.cmd == "run-status":
        run_status(a.job, a.state, a.detail)
    elif a.cmd == "health":
        print(health())
    elif a.cmd == "bootstrap":
        bootstrap()
    elif a.cmd == "count":
        print(sum(1 for it in queue()["items"] if it["status"] == a.status))
    elif a.cmd == "health-reset":
        log_entry(id="", category="", theme="", status="health-reset", reason=a.reason)
        write_status({"consecutive_failures": 0})
        print(health())
    elif a.cmd == "release-stale":
        print(release_stale(a.reason))
    elif a.cmd == "snapshot":
        snapshot(a.file)
    elif a.cmd == "recover":
        recover(a.snapshot, a.reason)


if __name__ == "__main__":
    main()

"""Per-article distribution model (new flow, 2026-11-28).

Historically every article in content/posts/<slug>.md was published to GitHub Pages first and
then cross-posted elsewhere. Under the current model each article carries its own distribution
set in front matter:

    platforms: ["hatena", "note"]      # destinations for THIS article
    canonical_platform: "note"         # source of X links / backlinks / cross-links

GitHub Pages is one peer destination: it is rendered only when "github" is in `platforms`.
Articles without these keys are legacy posts and continue to mean `platforms: ["github"]`,
canonical platform github — so existing posts and historical state files keep working.

This module is deliberately dependency-light (stdlib only) so it can be called from the Hugo
deploy workflow as well as from the local publishing scripts.

    python scripts/distribution.py plan SLUG                 # JSON summary
    python scripts/distribution.py url SLUG                  # canonical URL only
    python scripts/distribution.py platforms SLUG --set a,b  # rewrite front matter
    python scripts/distribution.py prepare DEST              # copy content/ with non-github posts hidden
    python scripts/distribution.py build [--destination public] [--baseURL URL]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTS_DIR = os.path.join(ROOT, "content", "posts")
PLATFORMS_FILE = os.path.join(ROOT, "scripts", "post-platforms.json")
SITE_ORIGIN = "https://kingsworksub-jpg.github.io"
PLATFORMS = ("github", "hatena", "ameba", "note")
PLATFORM_HOME = {
    "github": SITE_ORIGIN,
    "hatena": "https://kinbro.hatenablog.com/",
    "ameba": "https://ameblo.jp/sfd0501/",
    "note": "https://note.com/shining_finger01",
}
CANONICAL_URL_TOKEN = "{{CANONICAL_URL}}"  # generated x_post text; replaced after publication


# --------------------------------------------------------------------------- front matter

def post_path(slug: str) -> str:
    return os.path.join(POSTS_DIR, slug + ".md")


def _split_frontmatter(slug: str) -> tuple[str, str]:
    with open(post_path(slug), encoding="utf-8-sig") as f:
        text = f.read().replace("\r\n", "\n")
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if not m:
        raise ValueError(f"frontmatter が読めない: {post_path(slug)}")
    return m.group(1), m.group(2)


def field(fm: str, name: str) -> str:
    m = re.search(rf'(?m)^{re.escape(name)}:\s*"?(.*?)"?\s*$', fm)
    return m.group(1).strip() if m else ""


def parse_list(value: str) -> list[str]:
    return [x.strip().strip("\"'") for x in value.strip().strip("[]").split(",") if x.strip()]


def records() -> dict:
    if not os.path.exists(PLATFORMS_FILE):
        return {}
    with open(PLATFORMS_FILE, encoding="utf-8") as f:
        return json.load(f)


def read_record(slug: str, cache: dict | None = None) -> dict:
    data = cache if cache is not None else records()
    return data.get(slug, {})


def is_new_model(slug: str, fm: str | None = None) -> bool:
    """True when the article explicitly opts into the per-article distribution model."""
    fm = fm if fm is not None else _split_frontmatter(slug)[0]
    return bool(re.search(r"(?m)^(platforms|canonical_platform|canonical_url):", fm))


def platforms(slug: str, fm: str | None = None, record: dict | None = None) -> list[str]:
    fm = fm if fm is not None else _split_frontmatter(slug)[0]
    raw = field(fm, "platforms")
    if not raw:
        # An explicit `platforms:` line with an empty list is a valid (unpublished) state.
        if re.search(r"(?m)^platforms:\s*(?:\[\s*\])?\s*$", fm):
            return []
        if record and record.get("platforms"):
            return [p for p in record["platforms"] if p in PLATFORMS]
        return ["github"]  # legacy article: GitHub was always the base
    return [p for p in parse_list(raw) if p in PLATFORMS]


def canonical_platform(slug: str, fm: str | None = None, plats: list[str] | None = None) -> str:
    fm = fm if fm is not None else _split_frontmatter(slug)[0]
    explicit = field(fm, "canonical_platform")
    plats = plats if plats is not None else platforms(slug, fm)
    # An explicitly blank canonical means the article is fully unpublished (PPP empty).
    if explicit == "" and re.search(r"(?m)^canonical_platform:\s*(?:\"\"|'')?\s*$", fm):
        return ""
    if explicit in PLATFORMS:
        return explicit
    if "github" in plats:
        return "github"
    return plats[0] if plats else "github"


def platform_url(platform: str, slug: str, fm: str, record: dict) -> str:
    if platform == "github":
        return f"{SITE_ORIGIN}/posts/{slug}/"
    if platform == "hatena":
        entry = record.get("hatena_entry") or field(fm, "hatena_entry")
        return f"https://kinbro.hatenablog.com/entry/{entry}" if entry else PLATFORM_HOME["hatena"]
    if platform == "ameba":
        entry = record.get("ameba_entry") or field(fm, "ameba_entry")
        return f"https://ameblo.jp/sfd0501/entry-{entry}.html" if entry else PLATFORM_HOME["ameba"]
    if platform == "note":
        url = field(fm, "note_url") or record.get("note_url") or ""
        if not url:
            key = field(fm, "note_key") or record.get("note_key") or ""
            url = f"https://note.com/shining_finger01/n/{key}" if key else PLATFORM_HOME["note"]
        return url
    return PLATFORM_HOME.get(platform, SITE_ORIGIN)


def canonical_url(slug: str, fm: str | None = None, record: dict | None = None) -> str:
    fm = fm if fm is not None else _split_frontmatter(slug)[0]
    explicit = field(fm, "canonical_url")
    if explicit.startswith("http"):
        return explicit
    record = record if record is not None else read_record(slug)
    plat = canonical_platform(slug, fm)
    if plat not in PLATFORMS:
        return ""  # fully unpublished article: no canonical destination
    return platform_url(plat, slug, fm, record)


def plan(slug: str) -> dict:
    fm = _split_frontmatter(slug)[0]
    plats = platforms(slug, fm)
    return {
        "slug": slug,
        "new_model": is_new_model(slug, fm),
        "platforms": plats,
        "canonical_platform": canonical_platform(slug, fm, plats),
        "canonical_url": canonical_url(slug, fm),
        "github_selected": "github" in plats,
    }


def _replace_or_insert(fm: str, key: str, value: str) -> str:
    line = f"{key}: {value}"
    pat = re.compile(rf"(?m)^{re.escape(key)}:.*$")
    if pat.search(fm):
        return pat.sub(lambda _: line, fm, count=1)
    for anchor in ("draft:", "categories:", "date:", "title:"):
        m = re.search(rf"(?m)^{re.escape(anchor)}.*$", fm)
        if m:
            return fm[:m.end()] + "\n" + line + fm[m.end():]
    return line + "\n" + fm


def set_platforms(slug: str, new_platforms: list[str], new_canonical: str | None = None) -> dict:
    """Rewrite platforms/canonical_platform in front matter (used by PPP reconciliation)."""
    bad = [p for p in new_platforms if p not in PLATFORMS]
    if bad:
        raise ValueError(f"unknown platform(s): {bad}")
    fm, body = _split_frontmatter(slug)
    fm = _replace_or_insert(fm, "platforms", json.dumps(new_platforms, ensure_ascii=False))
    canon = new_canonical or canonical_platform(slug, fm, new_platforms)
    if not new_platforms:
        canon = ""
    elif canon not in new_platforms:
        canon = new_platforms[0]
    fm = _replace_or_insert(fm, "canonical_platform", json.dumps(canon))
    with open(post_path(slug), "w", encoding="utf-8", newline="\n") as f:
        f.write("---\n" + fm + "\n---\n" + body)
    return plan(slug)


# --------------------------------------------------------------------------- Hugo build

BUILD_BLOCK = "build:\n  list: never\n  publishResources: false\n  render: never"


def _hide_from_build(fm: str) -> str:
    """Append Hugo's headless build options, replacing any existing `build:` block."""
    without_block = re.sub(r"(?ms)^build:\n(?:(?:[ \t]+.*\n?)|(?:\n))*", "", fm)
    return without_block.rstrip() + "\n" + BUILD_BLOCK


def prepare_content(dest: str) -> dict:
    """Copy content/ to `dest`, hiding articles whose platforms exclude GitHub from the Pages
    build. The local Markdown stays exactly where it is — only the deploy-time copy is filtered,
    so the cross-post renderers (which need HTML for ALL articles) keep working unchanged."""
    src = os.path.join(ROOT, "content")
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    hidden = []
    for name in sorted(os.listdir(POSTS_DIR)):
        if not name.endswith(".md"):
            continue
        slug = name[:-3]
        fm, body = _split_frontmatter(slug)
        if "github" in platforms(slug, fm):
            continue
        hidden.append(slug)
        target = os.path.join(dest, "posts", name)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write("---\n" + _hide_from_build(fm) + "\n---\n" + body)
    return {"hidden_from_github": hidden, "content_dir": dest}


def build_site(destination: str = "public", base_url: str | None = None) -> int:
    with tempfile.TemporaryDirectory(prefix="studio-notes-content-") as tmp:
        content_dir = os.path.join(tmp, "content")
        info = prepare_content(content_dir)
        if info["hidden_from_github"]:
            print("GitHub Pages から除外: " + ", ".join(info["hidden_from_github"]))
        cmd = ["hugo", "--minify", "--contentDir", content_dir, "--destination", destination]
        if base_url:
            cmd += ["--baseURL", base_url]
        return subprocess.call(cmd, cwd=ROOT)


# --------------------------------------------------------------------------- CLI

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "url"):
        sub.add_parser(name).add_argument("slug")
    p = sub.add_parser("platforms")
    p.add_argument("slug")
    p.add_argument("--set", dest="value", required=True, help="comma-separated platform ids")
    p.add_argument("--canonical-platform")
    sub.add_parser("prepare").add_argument("dest")
    b = sub.add_parser("build")
    b.add_argument("--destination", default="public")
    b.add_argument("--baseURL", dest="base_url")
    args = ap.parse_args()

    if args.cmd == "plan":
        print(json.dumps(plan(args.slug), ensure_ascii=False, indent=1))
    elif args.cmd == "url":
        print(canonical_url(args.slug))
    elif args.cmd == "platforms":
        print(json.dumps(set_platforms(args.slug, parse_list(args.value), args.canonical_platform), ensure_ascii=False, indent=1))
    elif args.cmd == "prepare":
        print(json.dumps(prepare_content(args.dest), ensure_ascii=False, indent=1))
    elif args.cmd == "build":
        sys.exit(build_site(args.destination, args.base_url))


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Generate 110-120 char meta descriptions for content/posts/*.md lacking
frontmatter `description:`. Built from opening prose paragraph(s), ends at a
Japanese sentence boundary. CRLF/BOM preserved. Inserts after `title:`."""
import pathlib, re

posts_dir = pathlib.Path("content/posts")


def strip_md(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`~]", "", text)
    return re.sub(r"\s+", " ", text)


def cut(s, limit=120):
    s = s.strip()
    if len(s) <= limit:
        return s
    marks = [m.start() + 1 for m in re.finditer(r"。", s)]
    if marks:
        nearest = min(marks, key=lambda m: abs(m - 118))
        if 100 <= nearest <= 130:
            return s[: nearest]
    head = s[:118]
    i = head.rfind(" ")
    if i > 50:
        return s[:i]
    return head.rstrip("、,。）」( ")


def prose_blocks(body):
    blocks = []
    for b in re.split(r"\n\s*\n", body):
        t = b.strip()
        if not t:
            continue
        if t.startswith(("#", "- ", ">", "|", "<", "```", "{{", "![", "---")):
            continue
        txt = strip_md(t)
        if len(txt) < 15:
            continue
        blocks.append(txt)
    return blocks


def make_description(title, blocks):
    if not blocks:
        return None
    t0 = "".join(title.split())
    chosen = []
    for p in blocks:
        if not chosen and "".join(p.split()).startswith(t0[:12]):
            continue
        chosen.append(p)
        total = "。".join(chosen)
        if len(total) >= 110:
            break
    total = "。".join(chosen)
    if len(total) < 90:
        return total if total else None
    return cut(total, 120)


changed, skipped = [], []
for f in sorted(posts_dir.glob("*.md")):
    raw = f.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    txt = raw.decode("utf-8-sig")
    eol = "\r\n" if "\r\n" in txt else "\n"
    nl = txt.replace("\r\n", "\n")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", nl, re.S)
    if not m:
        skipped.append((f.name, "no-frontmatter"))
        continue
    fm, rest = m.group(1), m.group(2)
    existing = re.search(r"(?m)^description:\s*\"?(.*?)\"?\s*$", fm)
    if existing and 85 <= len(existing.group(1).strip()) <= 125:
        continue
    mt = re.search(r"(?m)^title:\s*(.+)$", fm)
    title = mt.group(1).strip().strip('"\'') if mt else f.stem
    body = re.sub(r"```.*?```", "", rest, flags=re.S)
    desc = make_description(title, prose_blocks(body))
    if not desc:
        skipped.append((f.name, "no-prose"))
        continue
    desc_safe = desc.replace("\\", "\\\\").replace('"', '\\"')
    line = 'description: "' + desc_safe + '"'
    existing = re.search(r"(?m)^description:.*$", fm)
    if existing:
        new_fm = fm[: existing.start()] + line + fm[existing.end():]
    elif mt:
        new_fm = fm[: mt.start()] + fm[mt.start(): mt.end()] + "\n" + line + fm[mt.end():]
    else:
        new_fm = line + "\n" + fm
    out = "---\n" + new_fm + "\n---\n" + rest
    out = out.replace("\n", eol)
    f.write_bytes(("\ufeff" if bom else "").encode("utf-8") + out.encode("utf-8"))
    changed.append((f.name, len(desc)))

print("changed:", len(changed), "| skipped:", len(skipped))
for n, l in changed:
    print(f"  {n}: {l} chars")
for n, r in skipped:
    print(f"  SKIP {n}: {r}")
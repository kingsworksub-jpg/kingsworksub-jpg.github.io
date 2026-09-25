# -*- coding: utf-8 -*-
"""Generate OGP/twitter-card eye-catch images (1200x630) for every post that
has no `images:` frontmatter, compositing title + category + author, saving to
static/images/og/<slug>.jpg. Adds `images: ["/images/og/<slug>.jpg"]` to the
post's frontmatter. Also renders a site default image when invoked with
`--site-default`.
Run: python scripts/og-image-generator.py [--site-default]"""
import pathlib, re, sys, textwrap

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
POSTS = ROOT / "content" / "posts"
OUT = ROOT / "static" / "images" / "og"
W, H = 1200, 630

BOLD = r"C:\Windows\Fonts\YuGothB.ttc"
MED = r"C:\Windows\Fonts\YuGothM.ttc"
CHIP = "#3b7dd8"
BG_TOP = (22, 24, 29)
BG_BOT = (37, 42, 52)
ACCENT = (154, 230, 180)
TXT = (240, 243, 247)
MUTED = (156, 163, 175)


def font(path, size):
    return ImageFont.truetype(path, size)


def wrap(d, text, f, max_w):
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur); cur = ""; continue
        if d.textlength(cur + ch, font=f) <= max_w:
            cur += ch
        else:
            lines.append(cur); cur = ch
    if cur:
        lines.append(cur)
    return lines


def draw_base(d):
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t),
                                       int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t),
                                       int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t)))
    # decorative ring
    d.ellipse([(W - 260, -120), (W + 120, 260)], outline=(70, 78, 92), width=2)
    d.ellipse([(W - 190, -50), (W + 190, 330)], outline=(56, 63, 75), width=1)


def render(title, category, author, out_path):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    draw_base(d)
    # site name
    d.text((64, 56), "STUDIO NOTES", font=font(MED, 30), fill=ACCENT)
    # category chip
    chip_txt = category or "ブログ"
    cw = d.textlength(chip_txt, font=font(MED, 30)) + 48
    d.rounded_rectangle([(64, 116), (64 + cw, 166)], radius=25, fill=CHIP)
    d.text((64 + 24, 122), chip_txt, font=font(MED, 30), fill=(255, 255, 255))
    # title
    tf = font(BOLD, 56)
    lines = wrap(d, title, tf, W - 128) [:4]
    x0, y = 64, 222
    d.rectangle([(x0, y - 6), (x0 + 10, y + len(lines) * 76 - 10)], fill=ACCENT)
    for ln in lines:
        d.text((x0 + 34, y), ln, font=tf, fill=TXT)
        y += 76
    # footer
    d.line([(64, H - 92), (W - 64, H - 92)], fill=(56, 63, 75), width=1)
    d.text((64, H - 72), "kingsworksub-jpg - " + author, font=font(MED, 26), fill=MUTED)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=85, optimize=True, progressive=True)
    print("  wrote", out_path.relative_to(ROOT))


def frontmatter_of(text):
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    return m.group(1) if m else None


def add_images_fm(raw):
    txt = raw.decode("utf-8-sig")
    eol = "\r\n" if "\r\n" in txt else "\n"
    nl = txt.replace("\r\n", "\n")
    m = re.match(r"^(---\n)(.*?)(\n---)(.*)$", nl, re.S)
    fm, rest = m.group(2), m.group(4)
    slug = None
    return nl, fm, rest


def main():
    site_default = "--site-default" in sys.argv
    if site_default:
        render("Studio Notes", "音響・DTM・音楽ブログ", "kingsworksub-jpg", OUT / "site-default.jpg")
        return
    changed = []
    for f in sorted(POSTS.glob("*.md")):
        raw = f.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        txt = raw.decode("utf-8-sig")
        eol = "\r\n" if "\r\n" in txt else "\n"
        nl = txt.replace("\r\n", "\n")
        m = re.search(r"^---\n(.*?)\n---", nl, re.S)
        if not m:
            continue
        fm = m.group(1)
        if re.search(r"(?m)^images:\s*\[", fm):
            continue  # already has og image
        mt = re.search(r"(?m)^title:\s*\"?([^\"]*?)\"?\s*$", fm)
        title = mt.group(1).strip() if mt else f.stem
        mc = re.search(r"(?m)^categories:\s*\[([^\]]*)\]", fm)
        cat = ""
        if mc:
            cat = re.sub(r"[\[\]\",' ]", "", mc.group(1).split(",")[0])
        slug = f.stem
        out = OUT / f"{slug}.jpg"
        render(title, cat, "kingsworksub-jpg", out)
        # insert images line after description (or title)
        line = f'images: ["/images/og/{slug}.jpg"]'
        ins = 0
        md = re.search(r"(?m)^description:.*$", fm)
        if md:
            ins = md.end()
            new_fm = fm[:ins] + "\n" + line + fm[ins:]
        elif mt:
            ins = mt.end()
            new_fm = fm[:ins] + "\n" + line + fm[ins:]
        else:
            new_fm = line + "\n" + fm
        out_txt = "---\n" + new_fm + "\n---\n" + nl[m.end():]
        out_txt = out_txt.replace("\n", eol)
        f.write_bytes(("\ufeff" if bom else "").encode("utf-8") + out_txt.encode("utf-8"))
        changed.append(f.name)
    print("updated frontmatter:", len(changed))


if __name__ == "__main__":
    main()
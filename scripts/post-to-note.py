# -*- coding: utf-8 -*-
"""note.com への投稿を Playwright でsemi自動化する。

なぜブラウザか:
  note.com には投稿用の公開 API が存在しない（はてなブログは AtomPub がある）。
  そのため Chromium の永続プロファイルにログイン状態を保存し、
  エディタへの入力だけ自动化する。公開ボタンだけは人が押す（--publish で自動化も可）。

エディタの仕様（2026-09 実測 + 公開事例）:
  - タイトルは通常の input。fill() が効く。
  - 本文は [contenteditable="true"]。fill() は効かないのでキー入力か insertText を使う。
  - note のエディタは Markdown ショートカットをリアルタイムで解釈する
    （"## " → 見出し、"**x**" → 太字、"#tag" → タグチップ）。
  - 画像は markdown の ![](url) を理解しない。アップロード/貼り付けで挿入する必要がある。
  - class 名はビルドごとに変わるため、文字列ベースのセレクタだけを使う。

使い方:
  # 1回だけ。ブラウザが開くので手動でログインして端末に Enter を押す
  python scripts/post-to-note.py --login

  # 下書きを投稿画面に入力して止まる（推奨）
  python scripts/post-to-note.py --slug bebop-52nd-street-nights

  # 公開ボタンまで自動で押す
  python scripts/post-to-note.py --slug bebop-52nd-street-nights --publish

オプション:
  --slug <slug>   対象記事のスラッグ（省略時は note-drafts/ の一覧を表示）
  --all           note-drafts/ にある全ファイルを順番に処理
  --login         ログイン状態の初期化/更新だけを行う
  --publish       入力後に「公開する」まで自動で押す（既定は押さない）
  --no-images     画像を挿入せずテキストのみ（貼り付けが失敗したとき用）
  --fast          insertText で一括入力（高速。ただし Markdown 変換が効かない場合あり）
  --profile <dir> Chromium プロファイルの場所（既定 data/note_user_data）
"""
import argparse
import base64
import os
import re
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

BASE = r"C:\Users\norio\my-github-blog"
DRAFTS = os.path.join(BASE, "scripts", "note-drafts")
PROFILE = os.path.join(BASE, "data", "note_user_data")
NEW_NOTE_URL = "https://note.com/new"

IMG_RE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<url>https://[^)\s]+)\)\s*$")


# ---------------------------------------------------------------- draft parse


def parse_draft(path):
    """note ドラフトを title / tags / body に分解する。"""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().split("\n")

    title, tags, body = "", "", []
    mode = None
    for ln in lines:
        s = ln.rstrip()
        if s.startswith("# タイトル"):
            mode = "title"
            continue
        if s.startswith("# タグ"):
            mode = "tags"
            continue
        if s.startswith("# 本文"):
            mode = "body"
            continue
        if mode == "title":
            if s.strip() and not title:
                title = s.strip()
                mode = None
        elif mode == "tags":
            if s.strip():
                tags = s.strip()
                mode = None
        elif mode == "body":
            body.append(ln)
    return title, tags, "\n".join(body).strip("\n")


def split_blocks(body):
    """空行区切りのブロックに分ける。マークダウン記号で始まる行を先に処理するため。"""
    return [b for b in re.split(r"\n{2,}", body) if b.strip()]


# ---------------------------------------------------------------- image paste


def download(url):
    ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
    fd, path = tempfile.mkstemp(suffix=ext, prefix="noteimg_")
    os.close(fd)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
        f.write(r.read())
    return path


def count_figures(page):
    return page.evaluate(
        "() => document.querySelectorAll('.note-prose-image, figure, [data-image-id]').length"
    )


def paste_image(page, url):
    """画像をクリップボード経由で貼り込む。失敗時は False。"""
    path = download(url)
    try:
        mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
        b64 = base64.b64encode(open(path, "rb").read()).decode()
        page.evaluate(
            """async ([b64, mime]) => {
                const res = await fetch(`data:${mime};base64,${b64}`);
                const blob = await res.blob();
                await navigator.clipboard.write([new ClipboardItem({[mime]: blob})]);
            }""",
            [b64, mime],
        )
        before = count_figures(page)
        page.keyboard.press("Control+V")
        page.wait_for_timeout(2500)
        after = count_figures(page)
        if after <= before:
            return False
        page.keyboard.press("End")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"    [warn] 画像貼付失敗: {e}")
        return False
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ---------------------------------------------------------------- input


def type_block(page, text, fast):
    """1ブロックを入力する。マークダウン記号で始まる行は実キー入力にして変換させる。"""
    first = text.lstrip()[:1]
    needs_keys = first in ("#", "-", "*", ">", "[", "|", "1")
    if fast and not needs_keys:
        page.keyboard.insert_text(text)
    else:
        page.keyboard.type(text, delay=8)
    page.keyboard.press("Enter")
    page.wait_for_timeout(120)


def fill_body(page, body, tags, use_images, fast):
    """本文をブロック単位で入力する。"""
    blocks = split_blocks(body)
    total = len(blocks)
    for i, block in enumerate(blocks, 1):
        m = IMG_RE.match(block.strip())
        if m:
            url = m.group("url")
            alt = m.group("alt")
            print(f"  [{i}/{total}] 画像: {os.path.basename(url)}")
            if use_images and paste_image(page, url):
                if alt:
                    type_block(page, f"*{alt}*", fast)
            else:
                # 貼れなかったときは、対象が分かる行をそのまま残す
                type_block(page, f"[画像: {alt or url}]", fast)
            page.wait_for_timeout(300)
            continue

        head = block.split("\n")[0]
        print(f"  [{i}/{total}] {head[:34]}")
        for line in block.split("\n"):
            type_block(page, line, fast)

    if tags:
        page.keyboard.press("Enter")
        page.keyboard.press("Enter")
        type_block(page, tags, False)  # #tag をチップ化させるため実キー入力


def find_title_input(page):
    """タイトル欄を探す。note は class 名が変わり続けるので文字列セレクタを優先。"""
    cands = [
        page.get_by_placeholder(re.compile("タイトル")).first,
        page.locator('input[placeholder*="タイトル"]').first,
        page.locator('textarea[placeholder*="タイトル"]').first,
    ]
    for c in cands:
        try:
            c.wait_for(state="visible", timeout=8000)
            return c
        except Exception:  # noqa: BLE001, S110
            continue
    raise RuntimeError("タイトル欄が見つかりません（note のUIが変更された可能性があります）")


def find_body_editor(page):
    """本文の contenteditable を探す。"""
    cands = [
        page.locator('[contenteditable="true"]').first,
        page.locator('[contenteditable="true"]').last,
        page.locator('.ProseMirror[contenteditable="true"]').first,
    ]
    for c in cands:
        try:
            c.wait_for(state="visible", timeout=8000)
            if c.evaluate("e => e.getBoundingClientRect().height") > 100:
                return c
        except Exception:  # noqa: BLE001, S110
            continue
    raise RuntimeError("本文エディタが見つかりません（note のUIが変更された可能性があります）")


def fill_title(page, title):
    el = find_title_input(page)
    el.click()
    el.fill(title)


def ensure_logged_in(page, wait=0):
    if "/login" in page.url or "accounts.google" in page.url:
        return False
    if wait:
        print("  ブラウザでログインしてください。完了したらこの端末に Enter を押してください…")
        input()
    return True


# ---------------------------------------------------------------- main


def open_editor(p):
    ctx = p.chromium.launch_persistent_context(
        PROFILE,
        headless=False,
        args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        viewport=None,
    )
    try:
        ctx.grant_permissions(["clipboard-read", "clipboard-write"])
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] クリップボード権限を付与できませんでした: {e}")
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    for url in ("https://note.com/new", "https://note.com/notes/new"):
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        if "/login" not in page.url:
            break
    page.wait_for_timeout(3000)
    return ctx, page


def do_login(p):
    ctx, page = open_editor(p)
    print(f"ブラウザを起動しました: {page.url}")
    if not ensure_logged_in(page, wait=1):
        input()
    page.wait_for_timeout(1500)
    print("ログイン状態を保存しました。以後は --login なしでも利用できます。")
    time.sleep(2)
    ctx.close()


def list_drafts():
    if not os.path.isdir(DRAFTS):
        print(f"note ドラフトがありません: {DRAFTS}")
        return []
    return sorted(f for f in os.listdir(DRAFTS) if f.endswith(".note.txt"))


def post_one(p, path, args):
    slug = os.path.basename(path).replace(".note.txt", "")
    title, tags, body = parse_draft(path)
    print(f"\n=== {slug} ===")
    print(f"  タイトル: {title}")
    print(f"  タグ    : {tags[:60]}")
    print(f"  本文    : {len(body)} 文字 / {len(split_blocks(body))} ブロック")

    ctx, page = open_editor(p)
    try:
        if not ensure_logged_in(page, wait=1):
            print("  [error] ログインが必要です。先に --login を実行してください。")
            return None
        fill_title(page, title)
        ed = find_body_editor(page)
        ed.click()
        page.wait_for_timeout(400)
        t0 = time.time()
        fill_body(page, body, tags, not args.no_images, args.fast)
        print(f"  入力完了 ({time.time() - t0:.0f} 秒)")

        page.wait_for_timeout(3000)
        if args.publish:
            btn = None
            for sel in (
                page.get_by_role("button", name=re.compile("公開する")).first,
                page.get_by_role("button", name=re.compile("投稿する")).first,
                page.locator('button:has-text("公開する")').first,
            ):
                try:
                    sel.wait_for(state="visible", timeout=5000)
                    btn = sel
                    break
                except Exception:  # noqa: BLE001, S110
                    continue
            if btn is None:
                print("  [warn] 公開ボタンが見つかりません。ブラウザ側で手で押してください。")
            else:
                btn.click(timeout=30000)
                page.wait_for_load_state("networkidle", timeout=90000)
                print(f"  公開しました: {page.url}")
                return page.url
        print("  ここで内容を確認して、ブラウザの「公開する」を押してください。")
        print("  (自動で押す場合は --publish を付けます)")
        input("  ブラウザを閉じてよいったら Enter …")
        return page.url
    finally:
        try:
            ctx.close()
        except Exception:  # noqa: BLE001
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--fast", action="store_true")
    args = ap.parse_args()

    with sync_playwright() as p:
        if args.login:
            do_login(p)
            return

        if args.all:
            targets = [os.path.join(DRAFTS, f) for f in list_drafts()]
        elif args.slug:
            cand = os.path.join(DRAFTS, args.slug + ".note.txt")
            if not os.path.exists(cand):
                print(f"ドラフトが見つかりません: {cand}")
                print("利用可能:")
                for f in list_drafts():
                    print("  " + f.replace(".note.txt", ""))
                return
            targets = [cand]
        else:
            print("note ドラフト一覧:")
            for f in list_drafts():
                print("  " + f.replace(".note.txt", ""))
            print("\n--slug <slug> で個別に投稿、--all で全件")
            return

        for t in targets:
            post_one(p, t, args)


if __name__ == "__main__":
    main()

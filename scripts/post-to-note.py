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
EDITOR_URL = "https://editor.note.com/new"  # 実際の編集画面（note.com/new からリダイレクトされる）
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
)
# bot 判定回避。headless のままだと本文进水ISLAって取得できないことがある。
INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || {runtime: {}};
Object.defineProperty(navigator, 'languages', {get: () => ['ja', 'ja-JP', 'en']});
"""

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


CLIP_MIME = "image/png"  # Chromium の ClipboardItem.write が対応しているのは png だけ


def to_png(src_path):
    """jpeg/png を png に変換する（ClipboardItem は image/png しか書けない）。"""
    try:
        from PIL import Image
    except ImportError:
        return None
    dst = src_path + ".conv.png"
    with Image.open(src_path) as im:
        im.convert("RGB").save(dst, "PNG")
    return dst


def paste_image(page, url):
    """画像をクリップボード経由で貼り込む。失敗時は False。"""
    path = download(url)
    try:
        orig = path
        conv = to_png(orig)
        if conv:
            path = conv
            try:
                os.remove(orig)
            except OSError:
                pass
        b64 = base64.b64encode(open(path, "rb").read()).decode()
        page.evaluate(
            """async ([b64, mime]) => {
                const res = await fetch(`data:${mime};base64,${b64}`);
                const blob = await res.blob();
                await navigator.clipboard.write([new ClipboardItem({[mime]: blob})]);
            }""",
            [b64, CLIP_MIME],
        )
        before = count_figures(page)
        page.keyboard.press("Control+V")
        page.wait_for_timeout(3000)
        after = count_figures(page)
        if after <= before:
            # 失敗しても latin にはもうOrganisation入れない（note は Enter で <br> を挿入するだけ）
            page.keyboard.press("Control+z")
            page.wait_for_timeout(500)
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


def convert_italics(text):
    """note は斜体のマークダウン記法（*斜体* / _斜体_）に未対応（2026-09-28 実測）。

    `**x**` と `__x__` だけが <strong> になるため、斜体はボールドにフォールバックする。
    画像行の `![alt](url)` は変えない。
    """
    if IMG_RE.match(text.strip()):
        return text
    # **bold** / __bold__ は保護してから、*italic* / _italic_ を **bold** に落とす
    bolds = []

    def stash(m):
        bolds.append(m.group(0))
        return f"\x00{len(bolds) - 1}\x00"

    t = re.sub(r"(\*\*|__).+?\1", stash, text)
    # 単独 *x* / _x_ → **x**
    #   uls: 前が空白/行頭 or 閉じ括弧類、後が空白/行末 or 開き括弧類、
    #        内側に空白を含まない。`2*3=6` や `foo*bar*baz` の誤爆を防ぐ。
    t = re.sub(r"(?<![A-Za-z0-9*])\*(?!\s)([^*\n]*\S[^*\n]*)(?<!\s)\*(?![A-Za-z0-9*])", r"**\1**", t)
    t = re.sub(r"(?<![A-Za-z0-9_])_(?!\s)([^_\n]*\S[^_\n]*)(?<!\s)_(?![A-Za-z0-9_])", r"**\1**", t)
    for i, b in enumerate(bolds):
        t = t.replace(f"\x00{i}\x00", b)
    return t


def type_block(page, text, fast, enter=True):
    """1ブロックを入力する。

    実DOM仕様（2026-09-28 実測）:
      - `## ` は入力すると <h2> に変換される
      - `**x**` は <strong> に変換される
      - `*斜体*` は変換されない（`__太字__` は変換される）
      - Enter で改行すると同じ <p> 内に <br> が入る（見た目上の行間なので問題ない）
    """
    first = text.lstrip()[:1]
    needs_keys = first in ("#", "-", "*", ">", "[", "|", "1")
    converted = convert_italics(text)
    if converted != text:
        needs_keys = True  # 変換後なので実キー入力（insertText では変換されない）
    if fast and not needs_keys:
        page.keyboard.insert_text(converted)
    else:
        page.keyboard.type(converted, delay=8)
    if enter:
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
            print(f"  [{i}/{total}] 画像: {os.path.basename(url)}", flush=True)
            if use_images and paste_image(page, url):
                # 直後のブロックが *キャプション* なので、ここでは alt を重ねない
                pass
            else:
                type_block(page, f"[画像: {alt or url}]", fast)
            page.wait_for_timeout(300)
            continue

        head = block.split("\n")[0]
        print(f"  [{i}/{total}] {head[:34]}", flush=True)
        for line in block.split("\n"):
            type_block(page, line, fast)

    if tags:
        page.keyboard.press("Enter")
        page.keyboard.press("Enter")
        type_block(page, tags, False)  # #tag をチップ化させるため実キー入力


def find_title_input(page):
    """タイトル欄を探す。実DOMは textarea[placeholder="記事タイトル"]（2026-09-28 実測）。"""
    cands = [
        page.locator('textarea[placeholder*="タイトル"]').first,
        page.locator('input[placeholder*="タイトル"]').first,
        page.get_by_placeholder(re.compile("タイトル")).first,
    ]
    for c in cands:
        try:
            c.wait_for(state="visible", timeout=8000)
            return c
        except Exception:  # noqa: BLE001, S110
            continue
    raise RuntimeError("タイトル欄が見つかりません（note のUIが変更された可能性があります）")


def find_body_editor(page):
    """本文の contenteditable を探す。実DOMは .ProseMirror（2026-09-28 実測）。"""
    cands = [
        page.locator('.ProseMirror[contenteditable="true"]').first,
        page.locator('.ProseMirror[contenteditable="true"]').last,
        page.locator('[contenteditable="true"]').first,
    ]
    for c in cands:
        try:
            c.wait_for(state="visible", timeout=10000)
            if c.evaluate("e => e.getBoundingClientRect().height") > 30:
                return c
        except Exception:  # noqa: BLE001, S110
            continue
    raise RuntimeError("本文エディタが見つかりません（note のUIが変更された可能性があります）")


def fill_title(page, title):
    el = find_title_input(page)
    el.click()
    el.fill(title)


LOGIN_URLS = ("/login", "accounts.google", "sign_in", "/signup")


def is_login_page(page):
    return any(k in page.url for k in LOGIN_URLS)


def is_logged_in(page):
    """投稿画面が開いている = ログイン済み。

    実DOM（2026-09-28 実測）:
      textarea[placeholder="記事タイトル"]
      div.ProseMirror[contenteditable="true"]
      ボタン: 下書き保存 / 公開に進む
    """
    if is_login_page(page):
        return False
    try:
        if page.locator(".ProseMirror").count() > 0:
            return True
        return page.locator(
            'textarea[placeholder*="タイトル"], input[placeholder*="タイトル"]'
        ).first.is_visible(timeout=3000)
    except Exception:  # noqa: BLE001
        return False


def ensure_logged_in(page, wait=0):
    if is_logged_in(page):
        return True
    if wait:
        print("  ブラウザでログインしてください。完了したらこの端末に Enter を押してください…")
        input()
    return is_logged_in(page)


def wait_for_login(page, timeout=900):
    """ログイン完了をポーリングで待つ（input() が使えない環境向け）。"""
    print("  ブラウザで note.com にログインしてください（自動検知します）…")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_logged_in(page):
            print("  ログインを検知しました。")
            return True
        page.wait_for_timeout(2000)
    return False


# ---------------------------------------------------------------- main


def open_editor(p, headless=False):
    ctx = p.chromium.launch_persistent_context(
        PROFILE,
        headless=headless,
        args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        viewport={"width": 1440, "height": 900},
        user_agent=UA,
        locale="ja-JP",
        timezone_id="Asia/Tokyo",
        ignore_https_errors=True,
    )
    ctx.add_init_script(INIT_SCRIPT)
    try:
        ctx.grant_permissions(["clipboard-read", "clipboard-write"])
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] クリップボード権限を付与できませんでした: {e}")
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    # 初回だけ編集画面が空のことがあるため最大3回リトライする
    for attempt_no in range(1, 4):
        page.goto(NEW_NOTE_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(12000)
        if is_login_page(page) or page.locator(".ProseMirror").count() > 0:
            break
        print(f"  [retry] 編集画面が空でした（{attempt_no} 回目）。再読み込みします…", flush=True)
    print(f"  編集画面: {page.url}", flush=True)
    return ctx, page


def do_login(p, args):
    ctx, page = open_editor(p)
    print(f"ブラウザを起動しました: {page.url}", flush=True)
    if is_logged_in(page):
        print("  既にログイン済みです。", flush=True)
    else:
        ok = wait_for_login(page, timeout=args.login_timeout)
        if not ok:
            print("  [error] タイムアウトしました。ログインし直してください。", flush=True)
            ctx.close()
            return
    page.wait_for_timeout(1500)
    print("ログイン状態を保存しました。以後は --login なしでも利用できます。", flush=True)
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
        if not is_logged_in(page):
            print("  ログインが必要です。ブラウザを開いたままログインしてください…", flush=True)
            if not wait_for_login(page, timeout=args.login_timeout):
                print("  [error] ログインできません。先に --login を実行してください。")
                return None
            page.goto(NEW_NOTE_URL, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(12000)
        fill_title(page, title)
        ed = find_body_editor(page)
        ed.click()
        page.wait_for_timeout(400)
        t0 = time.time()
        fill_body(page, body, tags, not args.no_images, args.fast)
        print(f"  入力完了 ({time.time() - t0:.0f} 秒)")

        page.wait_for_timeout(3000)
        if args.save:
            sbtn = page.get_by_role("button", name="下書き保存").first
            try:
                sbtn.click(timeout=15000)
                page.wait_for_timeout(4000)
                print("  下書き保存しました。", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"  [warn] 下書き保存: {e}", flush=True)
        if args.publish:
            # 実DOMのボタンは「公開に進む」。その後confirm dialogが出る。
            btn = None
            for name in ("公開に進む", "公開する", "投稿する"):
                sel = page.get_by_role("button", name=name).first
                try:
                    sel.wait_for(state="visible", timeout=6000)
                    btn = sel
                    break
                except Exception:  # noqa: BLE001, S110
                    continue
            if btn is None:
                print("  [warn] 公開ボタンが見つかりません。ブラウザ側で手で押してください。", flush=True)
            else:
                print(f"  「{btn.inner_text().strip()}」を押します…", flush=True)
                btn.click(timeout=30000)
                page.wait_for_timeout(3000)
                for cname in ("公開する", "公開"):
                    cbtn = page.get_by_role("button", name=cname).last
                    try:
                        if cbtn.is_visible(timeout=5000):
                            print(f"  確認ダイアログの「{cname}」を押します…", flush=True)
                            cbtn.click(timeout=30000)
                            page.wait_for_timeout(6000)
                            break
                    except Exception:  # noqa: BLE001, S110
                        continue
                page.wait_for_load_state("networkidle", timeout=90000)
                print(f"  公開しました: {page.url}", flush=True)
                return page.url
        print("  ここで内容を確認して、ブラウザの「公開に進む」を押してください。", flush=True)
        print("  (自動で押す場合は --publish を付けます)", flush=True)
        if args.no_wait:
            time.sleep(args.hold)
        else:
            try:
                input("  ブラウザを閉じてよいったら Enter …")
            except EOFError:
                print("  (stdin なし。時間経過で閉じます)", flush=True)
                time.sleep(args.hold)
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
    ap.add_argument("--profile", default=None, help="Chromium プロファイルの場所")
    ap.add_argument("--login-timeout", type=int, default=900, help="ログイン待ちの秒数")
    ap.add_argument("--no-wait", action="store_true", help="確認待ちの Enter を求めない")
    ap.add_argument("--hold", type=int, default=180,
                    help="--no-wait のときブラウザを開いておく秒数")
    ap.add_argument("--save", action="store_true", help="下書き保存ボタンを押す")
    args = ap.parse_args()

    global PROFILE  # noqa: PLW0603
    if args.profile:
        PROFILE = args.profile

    with sync_playwright() as p:
        if args.login:
            do_login(p, args)
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

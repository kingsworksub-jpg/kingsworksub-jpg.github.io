# -*- coding: utf-8 -*-
"""Amebaブログ(アメブロ) への投稿を Playwright で自動化する。

Ameba には投稿用の公開 API が無いため、Chromium/Edge の永続プロファイルに
ログイン状態を保存し、ブログ編集画面への入力を自動化する。

編集画面の仕様(2026-10-11 実測):
  - エディタURL: https://blog.ameba.jp/ucs/entry/srventryinsertinput.do
    (未ログインだと auth.user.ameba.jp へリダイレクトされる)
  - タイトル: input[name="entry_title"]  (placeholder「タイトルを入力してください」)
  - 本文: textarea#amebloeditor[name="entry_text"] を CKEditor が置き換える。
    `CKEDITOR.instances['amebloeditor'].setData(html)` で内容を設定する。
  - 投稿/下書き: button.js-submitButton[publishflg="0"]=投稿する / [publishflg="1"]=下書き保存
  - ログイン画面は https://auth.user.ameba.jp/signin (user.ameba.jp/login は接続できない)
  - **本文に amazon.co.jp への生リンクがあると「投稿する」が失敗する**(2026-10-11実測。「保存ができませんでした。
    リンクを削除するかAmeba Pickリンクに差し替えて投稿を行ってください。」というエラーが、投稿する押下後に開く
    ポップアップ(srventryupdateend.do)に出る。見た目は普通に編集画面へ戻るだけなので気づきにくい)。
    `strip_amazon_links()` が setData 後に amazon.co.jp への <a> を自動で剥がす(画像自体は残す)。
    Ameba Pick(編集画面右サイドバーの「Pick」タブ、またはブログ管理左メニューの「Ameba Pick」→
    商品カテゴリ(Amazon等)→「アイテムを探す」)に登録済みなら商品リンクを貼れるが、自動挿入は未実装
    (2026-10-11時点ではリンクを完全に外すだけ)。
  - 公開URL: https://ameblo.jp/sfd0501/entry-{entry_id}.html (ブログID "sfd0501")

使い方:
  # 1回だけ。ブラウザ(Edge)が開くので手動でログインすると検知して終了する
  python scripts/post-to-ameba.py --login

  # 記事を下書き保存 (Hugo でレンダリングした本文を入力し、下書き保存ボタンを押す)
  python scripts/post-to-ameba.py --slug <slug> --save

  # 記事を公開
  python scripts/post-to-ameba.py --slug <slug> --publish
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

BASE = r"C:\Users\norio\my-github-blog"
POSTS = os.path.join(BASE, "content", "posts")
PROFILE = os.path.join(BASE, "data", "ameba_user_data")
EDITOR_URL = "https://blog.ameba.jp/ucs/entry/srventryinsertinput.do"
LOGIN_URL = "https://auth.user.ameba.jp/signin"
SITE = "https://kingsworksub-jpg.github.io"
LOGIN_TIMEOUT = 480  # seconds

INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || {runtime: {}};
Object.defineProperty(navigator, 'languages', {get: () => ['ja', 'ja-JP', 'en']});
"""


def parse_front_matter(text):
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end]
    body = text[end + 4:].lstrip("\n")
    meta = {}
    for line in raw.split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        meta[k] = v
    return meta, body


def extract_post_content(html_path):
    """<div class="post-content md-content"> の中身を div のネストを追跡して抽出する。

    extract-post-html.sh の awk ロジックの移植。開始マーカー行の残りも本文に含める。
    """
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    marker = '<div class="post-content md-content">'
    start = html.find(marker)
    if start == -1:
        raise RuntimeError(f"post-content not found in {html_path}")
    i = start + len(marker)
    depth = 1
    out = []
    buf = []
    n = len(html)
    while i < n and depth > 0:
        # 次の <div か </div> を探す
        open_i = html.find("<div", i)
        close_i = html.find("</div>", i)
        if open_i == -1 and close_i == -1:
            buf.append(html[i:])
            break
        if close_i != -1 and (open_i == -1 or close_i < open_i):
            buf.append(html[i:close_i])
            depth -= 1
            i = close_i + 6
            if depth == 0:
                break
            buf.append("</div>")
        else:
            buf.append(html[i:open_i + 4])
            depth += 1
            i = open_i + 4
    out = "".join(buf)
    # ルート相対の src/href を絶対URLにする
    out = re.sub(r'(src|href)="/([^"#])', rf'\1="{SITE}/\2', out)
    return out


FIGURE_RE = re.compile(r'<figure class="photo photo--(?:left|right)".*?</figure>', re.S)
IMG_TAG_RE = re.compile(r"<img\b[^>]*>")
WIDTH_ATTR_RE = re.compile(r'width="(\d+)"')
HEIGHT_ATTR_RE = re.compile(r'height="(\d+)"')
AMEBA_FIGURE_IMG_WIDTH = 220


def shrink_figure_img_attrs(html, target_width=AMEBA_FIGURE_IMG_WIDTH):
    """Rewrite width/height on <img> inside .photo figures down to the float's real display
    size (220px, see figures.css / hatena_figures.py's FIG_STYLE).

    Ameba's own lazy-load rewriter (added on save: data-src + a placeholder SVG) looks at the
    img's width/height *attributes*, not our inline float CSS, to decide layout. A large
    attribute (e.g. the image's native 750x1000 from fetch_image.py) makes it pick
    data-amb-layout="fill-width" and stretch the image to the full column width, breaking the
    float and overlapping the text that was supposed to wrap beside it (seen 2026-10-11 on
    non-alcohol-beer-5choice-2026's mobile rendering). Site/Hatena render fine regardless since
    their CSS constrains the box; only Ameba needs the attributes themselves shrunk.
    """

    def fix_img(m):
        tag = m.group(0)
        w, h = WIDTH_ATTR_RE.search(tag), HEIGHT_ATTR_RE.search(tag)
        if not w or not h:
            return tag
        ow, oh = int(w.group(1)), int(h.group(1))
        if ow <= target_width:
            return tag
        nh = round(oh * target_width / ow)
        tag = WIDTH_ATTR_RE.sub(f'width="{target_width}"', tag, count=1)
        tag = HEIGHT_ATTR_RE.sub(f'height="{nh}"', tag, count=1)
        return tag

    def fix_figure(m):
        return IMG_TAG_RE.sub(fix_img, m.group(0), count=1)

    return FIGURE_RE.sub(fix_figure, html)


def render_body_html(slug):
    """Hugo で記事をレンダリングし、本文の HTML を返す(はてな用変換も適用)。"""
    build = tempfile.mkdtemp(prefix="ameba-build-")
    try:
        subprocess.run(
            ["hugo", "--destination", build],
            cwd=BASE, check=True, capture_output=True,
        )
        post = os.path.join(build, "posts", slug, "index.html")
        if not os.path.exists(post):
            raise RuntimeError(f"rendered post not found: {post} (slug={slug})")
        body = extract_post_content(post)

        py = None
        for cand in (
            os.path.join(BASE, "scripts", ".venv", "Scripts", "python.exe"),
            sys.executable,
        ):
            if os.path.exists(cand):
                py = cand
                break
        if py is None:
            py = sys.executable
        for helper in ("hatena_banner.py", "hatena_figures.py"):
            body = subprocess.run(
                [py, os.path.join(BASE, "scripts", helper)],
                input=body.encode("utf-8"),
                capture_output=True, check=True,
            ).stdout.decode("utf-8")
        body = shrink_figure_img_attrs(body)
        return body
    finally:
        shutil.rmtree(build, ignore_errors=True)


def open_browser(p):
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE,
        headless=False,
        channel="msedge",
        viewport={"width": 1366, "height": 900},
        locale="ja-JP",
    )
    ctx.add_init_script(INIT_SCRIPT)
    return ctx


def is_logged_in(checker):
    try:
        checker.goto(EDITOR_URL, wait_until="domcontentloaded", timeout=30000)
        checker.wait_for_timeout(1200)
        return "blog.ameba.jp/ucs/entry" in checker.url and "login" not in checker.url
    except Exception as e:
        print("  (check err)", str(e)[:100])
        return False


def do_login(p):
    ctx = open_browser(p)
    page = ctx.new_page()
    checker = ctx.new_page()
    print("Ameba ログインページを開きます。表示された画面でログインしてください。")
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print("login page err:", e)
    page.bring_to_front()

    start = time.time()
    ok = False
    while time.time() - start < LOGIN_TIMEOUT:
        time.sleep(5)
        if is_logged_in(checker):
            ok = True
            break
        print(f"  ... waiting ({int(time.time()-start)}s)")
    if not ok:
        print("TIMEOUT: ログインを検知できませんでした。")
        ctx.close()
        sys.exit(1)
    print("ログイン完了。プロファイルを保存しました。後は --slug で投稿できます。")
    ctx.close()


def dismiss_dialogs(page):
    """Ameba editor pops up onboarding/notice <dialog> elements (e.g. "AmebaPickからのお知らせ")
    that intercept clicks. Close whatever is open, a few times, falling back to Escape."""
    for _ in range(4):
        dlg = page.query_selector("dialog[open]")
        if not dlg:
            return
        closed = False
        for b in dlg.query_selector_all("button"):
            try:
                if b.is_visible():
                    b.click(timeout=1500, force=True)
                    closed = True
                    break
            except Exception:
                pass
        page.wait_for_timeout(500)
        if not closed:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)


def strip_amazon_links(page):
    """Ameba refuses to publish (see publish-time error) any entry whose body contains a plain
    amazon.co.jp link ("リンクを削除するかAmeba Pickリンクに差し替えて投稿を行ってください" — bare
    affiliate links aren't allowed, only their own Ameba Pick widget is). Unwrap such <a> tags,
    keeping their contents (the product image), so the article can publish. Discovered 2026-10-11
    when both pending drafts failed to publish with that exact error."""
    removed = page.evaluate(
        """() => {
            const ed = window.CKEDITOR.instances['amebloeditor'];
            const doc = ed.document.$;
            let count = 0;
            doc.querySelectorAll('a[href*="amazon.co.jp"]').forEach(a => {
                const parent = a.parentNode;
                while (a.firstChild) parent.insertBefore(a.firstChild, a);
                parent.removeChild(a);
                count++;
            });
            ed.updateElement();
            return count;
        }"""
    )
    if removed:
        print(f"Amazonリンクを{removed}件除去しました(Ameba Pick未対応のため)。")


def click_submit_and_check(page, ctx, publish):
    """Click 投稿する/下書き保存 and, for publish, follow the confirmation popup it opens
    (srventryupdateend.do) to detect Ameba's "保存ができませんでした" rejection."""
    flg = "0" if publish else "1"
    label = "投稿する" if publish else "下書き保存"
    sel = f'button.js-submitButton[publishflg="{flg}"]'
    btn = page.wait_for_selector(sel, timeout=20000)
    btn.scroll_into_view_if_needed()
    page.wait_for_timeout(500)

    if not publish:
        btn.click(timeout=10000)
        print(f"{label} を押しました。処理を待ちます…")
        page.wait_for_timeout(6000)
        dismiss_dialogs(page)
        return True

    try:
        with ctx.expect_page(timeout=15000) as pinfo:
            btn.click(timeout=10000)
        popup = pinfo.value
        popup.wait_for_load_state("domcontentloaded", timeout=30000)
        popup.wait_for_timeout(2000)
        text = popup.inner_text("body")
        popup.close()
    except Exception as e:
        print(f"投稿する クリック後にポップアップを検出できませんでした: {e}")
        return False

    if "できませんでした" in text or "エラー" in text:
        print("公開エラー:", text[:300])
        return False
    print(f"{label} を押しました。公開を確認しました。")
    return True


def fill_editor_and_submit(slug, publish):
    with sync_playwright() as p:
        ctx = open_browser(p)
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())

        print(f"Amebaエディタを開いています: {EDITOR_URL}")
        page.goto(EDITOR_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        if "blog.ameba.jp/ucs/entry" not in page.url:
            print("ログインされていません。`python scripts/post-to-ameba.py --login` を実行してください。")
            ctx.close()
            sys.exit(1)
        dismiss_dialogs(page)

        title_box = page.wait_for_selector('input[name="entry_title"]', timeout=30000)
        if title_box is None:
            print("タイトル欄が見つかりません。")
            if "/login" in page.url:
                print("ログインされていません。")
            ctx.close()
            sys.exit(1)

        with open(os.path.join(POSTS, f"{slug}.md"), encoding="utf-8-sig") as f:
            meta, _ = parse_front_matter(f.read())
        title = meta.get("title", slug)
        page.fill('input[name="entry_title"]', title)
        print(f"タイトル入力: {title}")

        body = render_body_html(slug)
        print(f"本文HTML: {len(body)} chars")
        page.wait_for_function(
            "window.CKEDITOR && window.CKEDITOR.instances && window.CKEDITOR.instances['amebloeditor']",
            timeout=60000,
        )
        page.evaluate("(html) => window.CKEDITOR.instances['amebloeditor'].setData(html)", body)
        page.wait_for_timeout(2500)
        strip_amazon_links(page)

        # 初期化モーダルが邪魔になった場合に備えて閉じる
        try:
            page.click("#js-initializing-modal", timeout=1000)
        except Exception:
            pass
        dismiss_dialogs(page)

        ok = click_submit_and_check(page, ctx, publish)
        if not ok:
            page.screenshot(path=os.path.join(BASE, "data", "ameba_fail.png"), full_page=True)
            ctx.close()
            sys.exit(1)

        eid = ""
        try:
            eid = page.input_value('input[name="entry_id"]')
        except Exception:
            pass
        print("URL:", page.url[:160])
        print(f"entry_id={eid}")
        if eid:
            print(f"公開URL(publish時): https://ameblo.jp/sfd0501/entry-{eid}.html")
        ctx.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", help="Article slug")
    parser.add_argument("--login", action="store_true", help="Login only")
    parser.add_argument("--publish", action="store_true", help="Publish directly")
    parser.add_argument("--save", action="store_true", help="Save as draft")
    args = parser.parse_args()

    os.makedirs(PROFILE, exist_ok=True)

    with sync_playwright() as p:
        if args.login:
            do_login(p)
            return
        if not args.slug:
            print("Error: --slug <slug> is required.")
            sys.exit(1)
        if not os.path.exists(os.path.join(POSTS, f"{args.slug}.md")):
            print(f"Error: Post file not found: {os.path.join(POSTS, args.slug + '.md')}")
            sys.exit(1)
    fill_editor_and_submit(args.slug, args.publish)


if __name__ == "__main__":
    main()
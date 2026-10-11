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

        # 初期化モーダルが邪魔になった場合に備えて閉じる
        try:
            page.click("#js-initializing-modal", timeout=1000)
        except Exception:
            pass

        flg = "0" if publish else "1"
        label = "投稿する" if publish else "下書き保存"
        sel = f'button.js-submitButton[publishflg="{flg}"]'
        try:
            page.click(sel, timeout=10000)
        except Exception as e:
            page.screenshot(path=os.path.join(BASE, "data", "ameba_fail.png"), full_page=True)
            print(f"ボタンクリック失敗: {e}")
            ctx.close()
            sys.exit(1)

        print(f"{label} を押しました。処理を待ちます…")
        page.wait_for_timeout(8000)

        eid = ""
        try:
            eid = page.input_value('input[name="entry_id"]')
        except Exception:
            pass
        print("URL:", page.url[:160])
        print(f"entry_id={eid}")
        print("完了(入力とボタン押下は成功。公開物はブログ管理画面で確認してください)。")
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
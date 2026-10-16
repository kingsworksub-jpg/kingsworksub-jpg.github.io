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
    `convert_amazon_links_to_pick()` が setData 後に対応する。ASINが分かるリンク(`.../dp/{ASIN}`)が
    画像を包んでいれば、Ameba自身の「pickCreative」アンカー(`href=""` + `data-df-item-id`/`data-item-id`
    属性)に作り替える — Ameba側のJSがページ表示時にこれを実際の追跡リンクに解決する(2026-10-11実機確認: クリックで
    `amazon.co.jp/dp/{ASIN}?...&tag=amebablog_st1-22` に遷移。Amebaの共有Associatesタグによる按分)。
    画像の直後に「（※画像からAmazonの詳細・購入ページへ移動します）」という小さな注記も挿入する。
    ASINが無い/画像を包んでいないAmazonリンク(検索リンクのフォールバック、キャプション内の文字リンク、
    まとめ表など)はリンクだけ外す(今まで通り)。
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
import urllib.error
import urllib.request

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


AMEBA_PICK_DISCLAIMER = "（※画像からAmazonの詳細・購入ページへ移動します）"
AMAZON_CATEGORY_ID = "AZ000001"  # Ameba Pick's fixed id for the Amazon "shop"
ASIN_RE = re.compile(r"amazon\.co\.jp/dp/([A-Z0-9]{10})")


def convert_amazon_links_to_pick(page):
    """Ameba refuses to publish (see publish-time error) any entry whose body contains a plain
    amazon.co.jp link ("リンクを削除するかAmeba Pickリンクに差し替えて投稿を行ってください" — bare
    affiliate links aren't allowed). Discovered 2026-10-11 when both pending drafts failed to
    publish with that exact error.

    For a link that wraps a product image and has a real ASIN (.../dp/{ASIN}), rebuild it as
    Ameba's own "pickCreative" anchor instead of just stripping it: same image, same float
    layout, but `href=""` plus `data-df-item-id`/`data-item-id` attributes. Ameba's own
    front-end JS hydrates that on page view into a real tracked redirect (confirmed 2026-10-11:
    clicking one on the live page opened `https://www.amazon.co.jp/dp/<asin>?...&tag=amebablog_st1-22`,
    i.e. Ameba's shared Associates tag with per-press tracking — this is the only way a
    affiliate link survives Ameba's publish check). A small-print line is inserted right after
    the image to disclose that it's an Amazon link.

    Any other amazon.co.jp link (search-fallback `/s?k=`, or a plain text link with no ASIN,
    e.g. the "Amazonで見る →" caption credit or the summary table) can't be turned into a
    pickCreative card, so it's just unwrapped (kept as plain text) like before.
    """
    counts = page.evaluate(
        """(disclaimer) => {
            const ed = window.CKEDITOR.instances['amebloeditor'];
            const doc = ed.document.$;
            let picked = 0, stripped = 0;
            doc.querySelectorAll('a[href*="amazon.co.jp"]').forEach(a => {
                const m = a.href.match(/amazon\\.co\\.jp\\/dp\\/([A-Z0-9]{10})/);
                const img = a.querySelector('img');
                if (m && img) {
                    a.setAttribute('class', 'pickCreative');
                    a.setAttribute('data-df-item-id', m[1]);
                    a.setAttribute('data-item-id', 'AZ000001');
                    a.setAttribute('href', '');
                    a.removeAttribute('data-cke-saved-href');
                    a.setAttribute('target', '_blank');
                    a.setAttribute('rel', 'noopener');
                    a.removeAttribute('sponsored');
                    const existing = a.style.cssText || '';
                    a.setAttribute('style', existing + ';display:block');
                    const p = doc.createElement('p');
                    p.setAttribute('style', 'font-size:0.7em;color:#999;margin:0.2em 0 0;text-align:left');
                    p.textContent = disclaimer;
                    a.parentNode.insertBefore(p, a.nextSibling);
                    picked++;
                } else {
                    const parent = a.parentNode;
                    while (a.firstChild) parent.insertBefore(a.firstChild, a);
                    parent.removeChild(a);
                    stripped++;
                }
            });
            ed.updateElement();
            return {picked, stripped};
        }""",
        AMEBA_PICK_DISCLAIMER,
    )
    if counts["picked"]:
        print(f"Amazon画像リンクを{counts['picked']}件 Ameba Pick形式に変換しました。")
    if counts["stripped"]:
        print(f"ASIN無しのAmazonリンクを{counts['stripped']}件除去しました(Ameba Pick未対応)。")


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

    # A handful of one-off modals ("カバーを設定してみましょう", "編集途中の記事があります。復元しますか？")
    # can intercept the 投稿する click instead of opening the confirmation popup. Dismiss whichever
    # one shows up and retry the click, a few times.
    DISMISS_BUTTONS = ["カバーなしで投稿する", "復元しない", "閉じる"]
    popup = None
    for attempt in range(4):
        try:
            with ctx.expect_page(timeout=7000) as pinfo:
                btn.click(timeout=10000)
            popup = pinfo.value
            break
        except Exception:
            popup = None
        dismissed = False
        for label_text in DISMISS_BUTTONS:
            try:
                b = page.get_by_role("button", name=label_text)
                if b.is_visible(timeout=1000):
                    b.click(timeout=3000)
                    print(f"モーダルを「{label_text}」で閉じました。")
                    dismissed = True
                    page.wait_for_timeout(1000)
                    break
            except Exception:
                pass
        if not dismissed:
            break

    if popup is None:
        print("投稿する クリック後にポップアップを検出できませんでした。")
        return False

    try:
        popup.wait_for_load_state("domcontentloaded", timeout=30000)
        popup.wait_for_timeout(2000)
        text = popup.inner_text("body")
        popup.close()
    except Exception as e:
        print(f"確認ポップアップの読み込みに失敗: {e}")
        return False

    if "できませんでした" in text or "エラー" in text:
        print("公開エラー:", text[:300])
        return False
    print(f"{label} を押しました。公開を確認しました。")
    return True


def _dump_delete_diagnostics(page, entry_id, stage):
    """Best-effort screenshot + visible-element dump for debugging a failed delete_entry() step.
    Returns the screenshot path (or None if even that failed) — never raises itself."""
    try:
        path = os.path.join(BASE, "data", f"ameba_delete_fail_{entry_id}_{stage}.png")
        page.screenshot(path=path, full_page=True)
    except Exception:  # noqa: BLE001
        path = None
    try:
        texts = page.evaluate(
            "() => Array.from(document.querySelectorAll('button, a, [role=menuitem]'))"
            ".map(e => (e.innerText || e.getAttribute('aria-label') || '').trim()).filter(Boolean).slice(0, 80)"
        )
        print(f"  [debug] ameba entry {entry_id} @ {stage}: url={page.url}", flush=True)
        print(f"  [debug] visible button/link texts: {texts}", flush=True)
    except Exception:  # noqa: BLE001
        pass
    return path


def delete_entry(entry_id, expected_title):
    """Delete a PUBLISHED Ameba entry, via the article LIST page (srventrylist.do) — NOT the
    per-entry edit page (an earlier version of this function guessed the delete control lived
    there; it doesn't). Confirmed 2026-10-16 by reading the real DOM: each row in the list has
    an actions block

        <li class="action"><a href=".../srventryupdateinput.do?id={id}" class="process">編集</a></li>
        <li class="action"><button onclick="copyEntry(this,{id});..." class="process">複製</button></li>
        <li class="action"><button class="process" data-remove-article-button data-entry-id="{id}">削除</button></li>

    so the delete control is selected directly and unambiguously by
    `button[data-remove-article-button][data-entry-id="{id}"]` — no text/position guessing
    needed. The row's own `<h2><a>` holds the article title, which is checked against
    `expected_title` BEFORE anything is clicked (raises, rather than returning a falsy value, on
    any mismatch or missing element). What happens after the click (native confirm() vs. a
    custom modal) was NOT observed before this was first run live, so both are handled: a native
    dialog is auto-accepted (and logged) by the page.on("dialog", ...) handler registered below,
    and dismiss_dialogs() mops up any custom <dialog> that might appear instead.
    """
    with sync_playwright() as p:
        ctx = open_browser(p)
        page = ctx.new_page()
        page.on("dialog", lambda d: (print(f"  [debug] native dialog: {d.message}", flush=True), d.accept()))

        list_url = "https://blog.ameba.jp/ucs/entry/srventrylist.do"
        page.goto(list_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        if "blog.ameba.jp/ucs/entry" not in page.url:
            ctx.close()
            raise RuntimeError(f"ameba entry {entry_id}: 記事一覧を開けません(ログイン切れの可能性): {page.url}")
        dismiss_dialogs(page)

        row = page.evaluate(
            """(id) => {
                const editLink = Array.from(document.querySelectorAll('a[href*="srventryupdateinput.do"]'))
                    .find(a => a.href.includes('id=' + id));
                if (!editLink) return {found: false};
                const entryDiv = editLink.closest('.entry-column')?.querySelector('.entry');
                const titleLink = entryDiv?.querySelector('h2 a');
                const delBtn = editLink.closest('li.entry-item')
                    ?.querySelector('button[data-remove-article-button][data-entry-id="' + id + '"]');
                return {found: true, title: (titleLink?.innerText || '').trim(), hasDeleteButton: !!delBtn};
            }""",
            entry_id,
        )
        if not row.get("found"):
            shot = _dump_delete_diagnostics(page, entry_id, "row-not-found")
            ctx.close()
            raise RuntimeError(
                f"ameba entry {entry_id}: 記事一覧にこの記事の行が見つかりません"
                f"(表示範囲外の月の可能性があります。スクリーンショット: {shot})")
        actual_title = row.get("title", "")
        if actual_title != expected_title.strip():
            shot = _dump_delete_diagnostics(page, entry_id, "title-mismatch")
            ctx.close()
            raise RuntimeError(
                f"ameba entry {entry_id}: 一覧のタイトル「{actual_title}」が期待値「{expected_title}」と"
                f"一致しないため中止(スクリーンショット: {shot})")
        if not row.get("hasDeleteButton"):
            shot = _dump_delete_diagnostics(page, entry_id, "no-delete-button")
            ctx.close()
            raise RuntimeError(f"ameba entry {entry_id}: 「削除」ボタンが見つかりません(削除操作を中止、"
                                f"スクリーンショット: {shot})")

        # Title confirmed correct — screenshot right before the destructive click, so a wrong
        # outcome is diagnosable even though everything checked out beforehand.
        _dump_delete_diagnostics(page, entry_id, "pre-delete-click")

        delete_btn = page.locator(f'button[data-remove-article-button][data-entry-id="{entry_id}"]')
        delete_btn.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        delete_btn.click(timeout=10000)
        page.wait_for_timeout(1500)
        # Unknown post-click flow: could be a native confirm() (auto-accepted above), a custom
        # <dialog>, or an immediate delete with no confirmation at all. Screenshot now, before
        # touching anything else, so whichever it was is visible in the diagnostics.
        _dump_delete_diagnostics(page, entry_id, "immediately-after-click")
        dismiss_dialogs(page)
        page.wait_for_timeout(2000)
        _dump_delete_diagnostics(page, entry_id, "post-click-settled")
        ctx.close()

    public_url = f"https://ameblo.jp/sfd0501/entry-{entry_id}.html"
    try:
        req = urllib.request.Request(public_url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        urllib.request.urlopen(req, timeout=15)
        raise RuntimeError(f"ameba entry {entry_id}: 削除操作後も公開URLが200を返します({public_url})。"
                            "削除できていない可能性が高いため、成功として扱わないでください。")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise RuntimeError(f"ameba entry {entry_id}: 削除後の確認で想定外のHTTP {e.code}: {public_url}") from e
    # 404 confirmed — deletion verified.


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
        convert_amazon_links_to_pick(page)

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
    parser.add_argument("--delete-entry", help="削除する公開済み記事の entry_id")
    parser.add_argument("--expect-title", help="--delete-entry 使用時、削除前に照合するタイトル(必須・誤削除防止)")
    args = parser.parse_args()

    os.makedirs(PROFILE, exist_ok=True)

    if args.delete_entry:
        if not args.expect_title:
            print("Error: --delete-entry には --expect-title が必須です(誤削除防止のため)")
            sys.exit(1)
        delete_entry(args.delete_entry, args.expect_title)
        print(f"DELETED: {args.delete_entry}")
        return

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
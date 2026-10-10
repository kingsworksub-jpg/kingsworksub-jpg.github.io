# -*- coding: utf-8 -*-
"""Amebaブログ への投稿を Playwright で自動化する。

使い方:
  # 1回だけ。ブラウザが開くので手動でログインして Enter
  python scripts/post-to-ameba.py --login

  # 記事を下書き保存
  python scripts/post-to-ameba.py --slug <slug> --save

  # 記事を公開
  python scripts/post-to-ameba.py --slug <slug> --publish
"""
import argparse
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

BASE = r"C:\Users\norio\my-github-blog"
POSTS = os.path.join(BASE, "content", "posts")
PROFILE = os.path.join(BASE, "data", "ameba_user_data")
EDITOR_URL = "https://blog.ameba.jp/ucs/entry/srventryinput.nht"
LOGIN_URL = "https://user.ameba.jp/login"
SITE = "https://kingsworksub-jpg.github.io"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


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


def convert_content(body):
    # Figure blocks to Markdown/HTML for Ameba
    def repl(m):
        href, src, alt, caption = m.group(1), m.group(2), m.group(3), m.group(4)
        if src.startswith("/"):
            src = SITE + src
        out = f'<div style="text-align:center; margin:20px 0;"><img src="{src}" alt="{alt}" style="max-width:100%; height:auto;" /><br><em>{caption}</em>'
        if href and "amazon." in href:
            out += f'<br><a href="{href}">Amazonで見る →</a>'
        out += "</div>"
        return out

    body = re.sub(
        r'<figure[^>]*>\s*'
        r'(?:<a\s+href="([^"]+)"[^>]*>\s*)?'
        r'<img\s+src="([^"]+)"[^>]*alt="([^"]*)"[^>]*>\s*(?:</a>\s*)?'
        r'<figcaption>(.*?)</figcaption>.*?</figure>',
        repl,
        body,
        flags=re.DOTALL,
    )
    body = re.sub(r"\]\(/", f"]({SITE}/", body)
    return body


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", help="Article slug")
    parser.add_argument("--login", action="store_true", help="Login mode")
    parser.add_argument("--publish", action="store_true", help="Publish directly")
    parser.add_argument("--save", action="store_true", help="Save draft")
    args = parser.parse_args()

    os.makedirs(PROFILE, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE,
            headless=False,
            viewport={"width": 1280, "height": 800},
            user_agent=UA,
        )
        page = browser.new_page()

        if args.login:
            print("Amebaログインページを開きます。手動でログイン後、Enterを押してください。")
            page.goto(LOGIN_URL)
            input("ログイン完了後、ここにEnterを押してください...")
            browser.close()
            return

        if not args.slug:
            print("Error: --slug <slug> is required.")
            browser.close()
            sys.exit(1)

        post_path = os.path.join(POSTS, f"{args.slug}.md")
        if not os.path.exists(post_path):
            print(f"Error: Post file not found: {post_path}")
            browser.close()
            sys.exit(1)

        with open(post_path, "r", encoding="utf-8-sig") as f:
            raw_text = f.read()

        meta, body_md = parse_front_matter(raw_text)
        title = meta.get("title", args.slug)
        body_html = convert_content(body_md)

        print(f"Amebaエディタを開いています: {EDITOR_URL}")
        page.goto(EDITOR_URL)
        time.sleep(3)

        if "login" in page.url or "signin" in page.url:
            print("ログインされていません。`python scripts/post-to-ameba.py --login` を実行してください。")
            browser.close()
            sys.exit(1)

        # Fill title
        try:
            page.fill('input[name="title"]', title)
        except Exception:
            try:
                page.fill('#title', title)
            except Exception as e:
                print(f"タイトル欄が見つかりません: {e}")

        # Fill body (Ameba uses CKEditor / rich text or textarea)
        try:
            # Switch to HTML editor mode if available or fill contenteditable / iframe
            page.evaluate(f"""(html) => {{
                const editor = document.querySelector('.cke_editable') || document.querySelector('textarea[name="content"]') || document.querySelector('[contenteditable="true"]');
                if (editor) {{
                    if (editor.tagName === 'TEXTAREA') {{
                        editor.value = html;
                    }} else {{
                        editor.innerHTML = html;
                    }}
                }}
            }}""", body_html)
        except Exception as e:
            print(f"本文入力エラー: {e}")

        time.sleep(2)

        if args.publish:
            print("公開ボタンを探しています...")
            try:
                # Click publish/commit button
                page.click('button:has-text("投稿する"), input[value="投稿する"], button:has-text("公開"), input[value="公開"]')
                time.sleep(5)
                print("Amebaへの公開が完了しました。")
            except Exception as e:
                print(f"公開ボタンのクリックに失敗しました: {e}")
        elif args.save:
            print("下書き保存ボタンを探しています...")
            try:
                page.click('button:has-text("下書き保存"), input[value="下書き保存"]')
                time.sleep(3)
                print("Amebaに下書き保存しました。")
            except Exception as e:
                print(f"下書き保存に失敗しました: {e}")
        else:
            print("ブラウザを開いたまま保持します。確認後閉じてください。")
            input("終了するにはEnterを押してください...")

        browser.close()


if __name__ == "__main__":
    main()

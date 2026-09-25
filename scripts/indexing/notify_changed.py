#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Indexing API へ URL を自動申請するスクリプト。

モード1(差分自動検知・CI用): git の old..new コミット間で content/ 配下が
追加・変更・削除された記事 URL を特定し、Indexing API へ通知する。

モード2(手動・OpenCode用): --publish / --delete で任意 URL を即時通知する。

設定
----
・認証情報(service account JSON)は --creds <path> で渡す。
  未指定時は環境変数 GOOGLE_INDEXING_CREDENTIALS_JSON(JSON文字列)を使う。
  どちらも無ければ「スキップ」して終了コード0で返る(CI未設定時に安全)。

・Google Cloud で Indexing API を有効化し、サービスアカウントを作成して
   JSON キーを取得する。動作確認ができるまでは --dry-run で実行すること。

注意
----
・Google Indexing API は公式には求人(JobPosting)・ライブ動画(LiveStream)
  ページのみを対象としています。通常のブログ記事ではエラーや無視される
  ことがあります(結果は実行ログに出力します)。
・クォータは既定 1日あたり200リクエストまで。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

NOINDEX_RE = re.compile(r"<meta\s+name=robots\s+content=\"?noindex", re.IGNORECASE)
DRAFT_RE = re.compile(r"^draft\s*:\s*(true|True|yes|YES|on)", re.MULTILINE)


def is_draft(file: Path) -> bool:
    """front matter の draft: true を判定(公開しない記事を除外するため)。"""
    try:
        head = file.read_text(encoding="utf-8")[:2000]
    except Exception:
        return False
    return bool(DRAFT_RE.search(head))


def git_diff(repo: Path, old: str, new: str, pathspec: str = "content/"):
    """old..new の --name-status 差分を返す(dict: relpath -> status)。"""
    cmd = ["git", "diff", "--name-status", old, new, "--", pathspec]
    proc = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git diff 失敗: {proc.stderr.strip()}")
    out = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        path = parts[1]
        prefixes = ("A", "M", "D", "C", "R")
        for p in prefixes:
            if status.startswith(p):
                status = p  # R100 等は R に正規化
                break
        else:
            status = status[0]
        if status == "R":
            # リネーム: [R100]\t旧\t新
            if len(parts) >= 3:
                out[parts[2]] = "R"
            continue
        out[path] = status
    return out


def build_url(base: str, relpath: str) -> str:
    """content/posts/foo.md -> base/posts/foo/ 、content/about.md -> base/about/。"""
    p = Path(relpath)
    slug = p.stem
    parent = p.parent.as_posix()
    if slug == "_index":
        return f"{base}/{parent}/".replace("//", "/")
    if parent == ".":
        return f"{base}/{slug}/"
    return f"{base}/{parent}/{slug}/"


def is_published(public: Path, relpath: str) -> bool:
    """ビルド済み public/ に対応 HTML があり、かつ noindex でないか。"""
    p = Path(relpath)
    if p.stem == "_index":
        html = public / p.parent / "index.html"
    else:
        html = public / p.parent / p.stem / "index.html"
    if not html.exists():
        return False
    try:
        raw = html.read_bytes()[:60000]
        return NOINDEX_RE.search(raw.decode("utf-8", "ignore")) is None
    except Exception:
        return True


def detect(repo: Path, base: str, old: str, new: str, public: Path):
    """差分から {publish: [...], delete: [...]} の URL リストを返す。"""
    diff = git_diff(repo, old, new)
    publish, delete = [], []
    for relpath, status in diff.items():
        if not relpath.startswith("content/"):
            continue
        r = relpath[len("content/"):]
        if r.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg")) and status != "D":
            continue  # 本文の画像リソースは記事本体の差分に含まれるためスキップ
        url = build_url(base, r)
        if status == "D":
            delete.append(url)
        elif is_draft(repo / relpath):
            print(f"  . draft のためスキップ: {url}")
        elif is_published(public, r):
            publish.append(url)
    return publish, delete


def send(creds_json: str, publish, delete, dry_run=False):
    """Indexing API へ publish(URL_UPDATED)/delete(URL_DELETED) を送る。"""
    if not creds_json:
        print("[skip] 認証情報が無いため送信しません(--creds または "
              "GOOGLE_INDEXING_CREDENTIALS_JSON を指定)")
        return 0
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError as e:
        print(f"[error] 依存が不足しています: {e}")
        print("        pip install google-auth google-api-python-client")
        return 1

    if dry_run:
        print("[dry-run] 送信しません(実送信時: publish=%d, delete=%d)"
              % (len(publish), len(delete)))
        return 0

    creds = service_account.Credentials.from_service_account_info(
        json.loads(creds_json),
        scopes=["https://www.googleapis.com/auth/indexing"],
    )
    service = build("indexing", "v3", credentials=creds)
    failures = 0
    for url in publish:
        try:
            res = service.urlNotifications().publish(
                body={"url": url, "type": "URL_UPDATED"}).execute()
            print(f"[OK] UPDATED {url} -> {res.get('urlNotificationMetadata', {})}")
        except HttpError as e:
            print(f"[warn] UPDATED {url}: {e.resp.status} {e._get_reason()}")
            if e.resp.status in (401, 429, 500, 503):
                failures += 1
        except Exception as e:
            print(f"[error] UPDATED {url}: {e}")
            failures += 1
    for url in delete:
        try:
            res = service.urlNotifications().publish(
                body={"url": url, "type": "URL_DELETED"}).execute()
            print(f"[OK] DELETED {url}")
        except HttpError as e:
            print(f"[warn] DELETED {url}: {e.resp.status} {e._get_reason()}")
            if e.resp.status in (401, 429, 500, 503):
                failures += 1
        except Exception as e:
            print(f"[error] DELETED {url}: {e}")
            failures += 1
    return 1 if failures else 0


def load_creds(args) -> str:
    if args.creds and Path(args.creds).exists():
        return Path(args.creds).read_text(encoding="utf-8")
    env = os.environ.get("GOOGLE_INDEXING_CREDENTIALS_JSON", "")
    return env.strip()


def main():
    ap = argparse.ArgumentParser(description="Google Indexing API への URL 自動申請")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--old", help="差分の基準コミット(old)")
    mode.add_argument("--publish", action="append", default=[],
                      help="即時通知するURL(複数指定可・手動モード)")
    ap.add_argument("--new", help="差分対象コミット(new)。未指定時は HEAD")
    ap.add_argument("--repo", default=".", help="git リポジトリのパス")
    ap.add_argument("--public", default="public", help="ビルド出力ディレクトリ")
    ap.add_argument("--base", default="https://kingsworksub-jpg.github.io",
                    help="サイトの baseURL")
    ap.add_argument("--delete", action="append", default=[],
                    help="削除通知するURL(手動モード)")
    ap.add_argument("--creds", help="サービスアカウント JSON へのパス")
    ap.add_argument("--dry-run", action="store_true",
                    help="送信せず内容だけ表示")
    args = ap.parse_args()

    creds_json = load_creds(args)

    if args.publish or args.delete:
        print("[manual] publish:", args.publish)
        print("[manual] delete :", args.delete)
        return send(creds_json, args.publish, args.delete, args.dry_run)

    repo = Path(args.repo).resolve()
    new = args.new or "HEAD"
    try:
        old = args.old or subprocess.run(
            ["git", "rev-parse", f"{new}~1"], cwd=str(repo),
            capture_output=True, text=True, check=True).stdout.strip()
    except subprocess.CalledProcessError:
        print("[skip] 初回コミットで親が無いため差分なし")
        return 0
    if not old:
        print("[skip] 差分の基準コミット(old)が無いため処理なし")
        return 0

    publish, delete = detect(repo, args.base, old, new, Path(args.public))
    print(f"[diff] {old}..{new} -> publish: {len(publish)}, delete: {len(delete)}")
    for u in publish:
        print("  +", u)
    for u in delete:
        print("  -", u)
    if not publish and not delete:
        print("[ok] 通知対象なし")
        return 0
    return send(creds_json, publish, delete, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
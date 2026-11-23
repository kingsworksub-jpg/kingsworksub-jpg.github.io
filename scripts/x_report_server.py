"""X会計レポートを社内LAN限定で公開する小さなHTTPサーバー。

`python -m http.server --bind 0.0.0.0` を使わない理由:
- バインド先を1つのLAN IPv4に固定し、ワイルドカード(0.0.0.0/::)を禁止する。
  これでTailscaleや将来接続する公共Wi-Fiなど、他のインターフェースからは見えない。
- リポジトリ全体ではなく、公開用にコピーした data/x-report-web/ だけを配信する。
- 生成レポートが更新されたら自動でコピーを取り直す（再起動不要）。

起動は scripts/scheduled/serve-x-report.ps1 経由（バインドIPはPowerShell側で選ぶ）。
"""
from __future__ import annotations

import argparse
import http.server
import shutil
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PUBLISH_DIR = BASE / "data" / "x-report-web"
SOURCE_HTML = BASE / "xaccounting-reports.html"
CONSULTING_DIR = BASE / "data" / "x-consulting"
CHART_CDN = "https://cdn.jsdelivr.net/npm/chart.js"
CHART_LOCAL = "vendor/chart.umd.min.js"


def sync_publish_dir() -> None:
    """生成物を公開用ディレクトリへコピーする（CDN参照はローカル版に差し替え）。"""
    PUBLISH_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLISH_DIR / "reports").mkdir(exist_ok=True)
    (PUBLISH_DIR / "vendor").mkdir(exist_ok=True)

    if SOURCE_HTML.is_file():
        html = SOURCE_HTML.read_text(encoding="utf-8")
        if (PUBLISH_DIR / "vendor" / "chart.umd.min.js").is_file():
            html = html.replace(CHART_CDN, CHART_LOCAL)
        (PUBLISH_DIR / "index.html").write_text(html, encoding="utf-8")

    src_reports = CONSULTING_DIR / "reports"
    if src_reports.is_dir():
        for src in src_reports.iterdir():
            if src.is_file():
                dst = PUBLISH_DIR / "reports" / src.name
                if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
                    shutil.copy2(src, dst)


_last_sync = 0.0


def maybe_sync() -> None:
    """リクエストごとに更新を確認するが、実コピーは30秒に1回まで。"""
    global _last_sync
    now = time.monotonic()
    if now - _last_sync < 30:
        return
    _last_sync = now
    try:
        sync_publish_dir()
    except Exception as exc:  # 配信そのものは止めない
        print(f"[!] 公開ディレクトリの更新に失敗: {exc}", flush=True)


class ReportHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("directory", str(PUBLISH_DIR))
        super().__init__(*args, **kwargs)

    def do_GET(self):
        maybe_sync()
        super().do_GET()

    def end_headers(self):
        # レポートは毎回最新を表示させる（ブラウザキャッシュで古くならないように）
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def validate_bind(ip: str) -> str:
    if ip.strip() in {"0.0.0.0", "::", "[::]", "*"}:
        raise SystemExit("[!] 0.0.0.0 / :: へのバインドは禁止です（LAN内限定のため）")
    return ip


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bind", required=True, help="バインドするLAN IPv4（ワイルドカード禁止）")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--log-file", default="", help="指定すると標準出力をUTF-8で追記")
    args = ap.parse_args()

    if args.log_file:
        log_path = Path(args.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = log_path.open("a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log

    bind = validate_bind(args.bind)
    sync_publish_dir()

    with http.server.ThreadingHTTPServer((bind, args.port), ReportHandler) as httpd:
        print(
            f"[*] Xレポート公開開始: http://{bind}:{args.port}/ "
            f"(公開先 {PUBLISH_DIR}, バインドはこのIPのみ)",
            flush=True,
        )
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("[i] 停止しました。", flush=True)


if __name__ == "__main__":
    main()

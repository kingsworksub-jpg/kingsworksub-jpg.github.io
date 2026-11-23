"""X会計レポートを「Wi-FiのLAN IP」と「Tailscale IP」だけに公開するHTTPサーバー。

公開範囲（2026-11-23、ユーザー指示）:
- バインドするのは PowerShell が選んだ LAN IPv4 と Tailscale IPv4 のみ。
- ワイルドカード(0.0.0.0/::)へのバインドは禁止。ルーターのポート開放もしない。
  → Tailscale は登録済み端末だけが入れる閉じたネットワークなので外部公開ではない。
    公共Wi-Fi等、意図しないインターフェースからは見えないまま。
- リポジトリ全体ではなく、公開用にコピーした data/x-report-web/ だけを配信する。
- 生成レポートが更新されたら自動でコピーを取り直す（再起動不要）。

起動は scripts/scheduled/serve-x-report.ps1 経由（バインドIPはPowerShell側で選ぶ）。
"""
from __future__ import annotations

import argparse
import http.server
import shutil
import sys
import threading
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
    ap.add_argument("--bind", required=True, nargs="+",
                    help="バインドするIPv4を1つ以上（LAN用とTailscale用。ワイルドカード禁止）")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--log-file", default="", help="指定すると標準出力をUTF-8で追記")
    args = ap.parse_args()

    if args.log_file:
        log_path = Path(args.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = log_path.open("a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log

    binds = [validate_bind(b) for b in args.bind]
    sync_publish_dir()

    servers = []
    for bind in binds:
        httpd = http.server.ThreadingHTTPServer((bind, args.port), ReportHandler)
        servers.append(httpd)
        threading.Thread(
            target=httpd.serve_forever,
            kwargs={"poll_interval": 0.5},
            daemon=True,
        ).start()
        print(
            f"[*] Xレポート公開開始: http://{bind}:{args.port}/ "
            f"(公開先 {PUBLISH_DIR})",
            flush=True,
        )
    print("[i] バインドは上記IPのみ。0.0.0.0への公開・外部ポート開放はしていません。", flush=True)

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("[i] 停止しました。", flush=True)
    finally:
        for httpd in servers:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    main()

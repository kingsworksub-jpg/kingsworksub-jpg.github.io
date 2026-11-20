# -*- coding: utf-8 -*-
"""GA4カスタム定義の登録と Search Console CSV の取得を自動化する。

GitHub Actions から実行する。認証情報はチャット/リポジトリに置かず、
以下の Environment/Secret から読む（未設定なら何もせず正常終了する）:

  GOOGLE_SERVICE_ACCOUNT_JSON ... サービスアカウントのJSON文字列
  GA4_PROPERTY_ID             ... GA4 の数値プロパティID
  SC_SITE_URL                 ... Search Console のサイトURL
                                  (既定: https://kingsworksub-jpg.github.io/)

やること:
  1. GA4 にカスタムディメンション4つを作成（既存はスキップ）
       article_slug / link_source / asin / ascsubtag
  2. Search Console API で直近30日の page 単位データを取得し、
     scripts/p0-sc.csv に保存（p0-metrics.py が読める形式・母集団の基準）
  3. page×query データは補助として scripts/p0-sc-queries.csv に保存。
     query ディメンションはこの property で強く間引かれるため、分母には使わない。

必要ライブラリ:
  pip install -r requirements-automation.txt
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_CSV = os.path.join(ROOT, "scripts", "p0-sc.csv")
OUT_QUERIES_CSV = os.path.join(ROOT, "scripts", "p0-sc-queries.csv")
SCOPES = [
    "https://www.googleapis.com/auth/analytics.edit",
    "https://www.googleapis.com/auth/webmasters.readonly",
]

CUSTOM_DIMENSIONS = [
    ("article_slug", "記事Slug"),
    ("link_source", "リンク種別"),
    ("asin", "ASIN"),
    ("ascsubtag", "Sub Tag"),
]


def credentials():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        print("SKIP: GOOGLE_SERVICE_ACCOUNT_JSON が未設定です", flush=True)
        return None, None
    try:
        from google.oauth2 import service_account
    except ImportError as exc:
        print(f"SKIP: google-auth が未インストールです ({exc})", flush=True)
        return None, None
    try:
        info = json.loads(raw)
        cred = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    except Exception as exc:
        print(f"WARN: サービスアカウントの読み込みに失敗しました ({exc})", flush=True)
        return None, None
    return cred, info.get("client_email", "")


def setup_ga4(cred) -> None:
    prop = os.environ.get("GA4_PROPERTY_ID", "").strip()
    if not prop:
        print("SKIP: GA4_PROPERTY_ID が未設定です", flush=True)
        return
    try:
        from google.analytics.admin import AnalyticsAdminServiceClient
        try:
            from google.analytics.admin.types import CustomDimension, DimensionScope
            from google.analytics.admin.types import DataRetentionSettings
        except ImportError:
            from google.analytics.admin_v1alpha.types import CustomDimension
            from google.analytics.admin_v1alpha.types import DataRetentionSettings

            # このバージョンでは DimensionScope は CustomDimension のネスト enum。
            DimensionScope = CustomDimension.DimensionScope
    except ImportError as exc:
        print(f"SKIP: google-analytics-admin が未インストールです ({exc})", flush=True)
        return
    try:
        client = AnalyticsAdminServiceClient(credentials=cred)
        parent = f"properties/{prop}"
        existing = {
            d.display_name
            for d in client.list_custom_dimensions(parent=parent)
        }
        for parameter, display in CUSTOM_DIMENSIONS:
            if display in existing:
                print(f"  GA4: 既存のためスキップ {display} ({parameter})", flush=True)
                continue
            client.create_custom_dimension(
                parent=parent,
                custom_dimension=CustomDimension(
                    display_name=display,
                    scope=DimensionScope.EVENT,
                    parameter_name=parameter,
                ),
            )
            print(f"  GA4: 作成 {display} ({parameter})", flush=True)

        # データ保持期間を14ヶ月にする（既定2ヶ月だと週次データが消える）
        retention_name = client.data_retention_settings_path(prop)
        settings = client.get_data_retention_settings(name=retention_name)
        fourteen = DataRetentionSettings.RetentionDuration.FOURTEEN_MONTHS
        if settings.event_data_retention != fourteen:
            settings.event_data_retention = fourteen
            client.update_data_retention_settings(
                data_retention_settings=settings,
                update_mask={"paths": ["event_data_retention"]},
            )
            print("  GA4: データ保持期間を14ヶ月に設定", flush=True)
        else:
            print("  GA4: データ保持期間は既に14ヶ月", flush=True)
    except Exception as exc:
        print(f"WARN: GA4カスタム定義の登録に失敗しました ({exc})", flush=True)


def _fetch_sc_rows(service, site, start, end, dimensions):
    """Search Console をページングして全行取得する。"""
    rows = []
    start_row = 0
    while True:
        res = service.searchanalytics().query(body={
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": dimensions,
            "rowLimit": 25000,
            "startRow": start_row,
        }, siteUrl=site).execute()
        batch = res.get("rows", [])
        rows.extend(batch)
        if len(batch) < 25000:
            break
        start_row += 25000
    return rows


def _write_sc_csv(path, header, rows, key_count):
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            keys = r.get("keys", [])
            out = [keys[i] if len(keys) > i else "" for i in range(key_count)]
            out.extend([
                r.get("impressions", 0),
                r.get("clicks", 0),
                f"{r.get('ctr', 0) * 100:.2f}%",
                f"{r.get('position', 0):.2f}",
            ])
            w.writerow(out)


def fetch_search_console(cred) -> None:
    site = (os.environ.get("SC_SITE_URL") or "https://kingsworksub-jpg.github.io/").strip()
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        print(f"SKIP: google-api-python-client が未インストールです ({exc})", flush=True)
        return
    end = (datetime.now(timezone.utc) - timedelta(days=2)).date()
    start = end - timedelta(days=29)
    try:
        service = build("searchconsole", "v1", credentials=cred, cache_discovery=False)
    except Exception as exc:
        print(f"WARN: Search Console クライアントの初期化に失敗しました ({exc})", flush=True)
        return

    # 主データ: page 単位。こちらを母集団（分母）として使う。
    try:
        page_rows = _fetch_sc_rows(service, site, start, end, ["page"])
        _write_sc_csv(
            OUT_CSV,
            ["ページ", "インプレッション数", "クリック数", "CTR", "平均順位"],
            page_rows, 1,
        )
        print(f"OK: {OUT_CSV} ({len(page_rows)}行 / page単位 / {start} 〜 {end})", flush=True)
    except Exception as exc:
        print(f"WARN: page単位の取得に失敗しました ({exc})", flush=True)

    # 補助データ: page×query。query は強く間引かれるため分母には使わない。
    try:
        query_rows = _fetch_sc_rows(service, site, start, end, ["page", "query"])
        _write_sc_csv(
            OUT_QUERIES_CSV,
            ["ページ", "クエリ", "インプレッション数", "クリック数", "CTR", "平均順位"],
            query_rows, 2,
        )
        print(f"OK: {OUT_QUERIES_CSV} ({len(query_rows)}行 / page×query / 補助)", flush=True)
    except Exception as exc:
        print(f"WARN: page×query の取得に失敗しました ({exc})", flush=True)


def main() -> int:
    cred, email = credentials()
    if cred is None:
        return 0
    print(f"Google API: {email or '(service account)'}", flush=True)
    setup_ga4(cred)
    fetch_search_console(cred)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

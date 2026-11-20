# P5 週次SEOレポート

- 生成: 2026-11-20 18:45 JST
- 記事数: **272本** / 合計ビュー: **3,217**（前回比 **+5**）
- 比較元: 2026-11-20

## Amazon アソシエイト（前回回収値のまま）

- period: Oct 21 2026 〜 Nov 19 2026 / 過去30日間
- clicks: 223
- orders: 0
- cvr: 0.00%
- revenue: 0
- approval_status: 直近30日で注文0件。180日以内3件の本承認には至っていない可能性が高い（管理画面に明示表示なし）
- 更新: `python scripts/amazon-associates-probe.py --collect-only`（ローカルのみ）

## GA4（Data API 実数値・直近30日）

- screenPageViews: **2311**
- activeUsers: **1861**
- eventCount: **7285**
- sessions: **2049**
- keyEvents: **0**
- ブログ記事のみ (`/posts/`): pageviews **405** / activeUsers **332**
- affiliate_click イベント: 0 件

| pagePath | pageviews | activeUsers |
|---|---:|---:|
| `/sfd0501/` | 448 | 263 |
| `/` | 107 | 47 |
| `/sfd0501/entrylist.html` | 21 | 17 |
| `/sfd0501/entry-12983785056.html` | 18 | 15 |
| `/posts/digital-performer-12-chunks-2026/` | 16 | 14 |
| `/sfd0501/page-2.html` | 13 | 7 |
| `/sfd0501/entry-12983859634.html` | 11 | 10 |
| `/entry/2026/10/14/121304` | 9 | 8 |
| `/posts/odate-akita-sugi-sake-set-deep-dive-2026/` | 9 | 9 |
| `/sfd0501/entry-12982392252.html` | 9 | 7 |

## P4 計測の確認チェック

- [ ] GA4 カスタム定義に `article_slug` / `link_source` / `asin` / `ascsubtag` を登録済みか
- [ ] 「探索」で `affiliate_click` × `記事Slug` が見えているか
- [ ] Amazonリンクの `ascsubtag=kingsworksub-jpg-<slug>` を1件確認したか

## 先週比で伸びた記事 Top10

| slug | ビュー | 増分 |
|---|---:|---:|
| `chrome-mv3-ublock-origin-lite-2026` | 21 | +1 |
| `minipc-dtm-ryzen-7730u-guide-2026` | 9 | +1 |
| `monitor-arm-vesa-desk-depth-2026` | 8 | +1 |
| `shiboritate-sake-winter-namazake-2026` | 7 | +1 |
| `evans-lafaro-village-vanguard-1961-2026` | 6 | +1 |
| `piano-practice-apps-3choice-2026` | 77 | +0 |
| `sony-pslx3bt-deep-dive-2026` | 66 | +0 |
| `bodum-douro-carafe-deep-dive-2026` | 65 | +0 |
| `budget-whisky-10choice-2026` | 56 | +0 |
| `odate-akita-sugi-sake-set-deep-dive-2026` | 54 | +0 |

## 次のP1候補（未バックフィル・ビュー順 Top20）

| slug | ビュー | Amazonリンク |
|---|---:|---:|
| `scotch-whisky-5choice-2026` | 29 | 5 |
| `nousaku-tin-sake-set-deep-dive-2026` | 28 | 1 |
| `scarlett-2i2-deep-dive-2026` | 28 | 1 |
| `windows-11-26h2-memory-daw-2026` | 28 | 4 |
| `arita-enka-sake-set-deep-dive-2026` | 26 | 1 |
| `modern-spiritual-jazz-2026` | 26 | 3 |
| `statement-hat-trend-2026` | 26 | 2 |
| `technics-sl1200mk7-deep-dive-2026` | 26 | 1 |
| `mitsuya-cider-zero-deep-dive-2026` | 25 | 1 |
| `2026-jazz-new-albums-jon-batiste-chihiro-yamanaka` | 24 | 2 |
| `ableton-live-12-session-view-2026` | 23 | 5 |
| `coca-cola-zero-deep-dive-2026` | 23 | 1 |
| `cool-jazz-birth-of-the-cool` | 23 | 2 |
| `jazz-instruments-guide` | 23 | 4 |
| `jazz-listening-guide-2026` | 23 | 4 |
| `jazz-shoes-trend-2026` | 23 | 1 |
| `jazz-style-menswear-2026` | 23 | 3 |
| `bebop-52nd-street-nights` | 22 | 4 |
| `bourbon-5choice-2026` | 22 | 6 |
| `crystal-spark-grape-deep-dive-2026` | 22 | 1 |

## 商品リンクなしの高ビュー記事 Top10

| slug | ビュー |
|---|---:|
| `digital-performer-12-chunks-2026` | 22 |
| `chrome-mv3-ublock-origin-lite-2026` | 21 |
| `hello` | 18 |
| `logic-pro-mac-songwriting-2026` | 18 |
| `free-plugin-mix-eq-comp-reverb-2026` | 13 |
| `new-scotch-distilleries-young-whisky-2026` | 10 |
| `vocalign-7-multitrack` | 10 |
| `hibp-password-breach-check-order-2026` | 9 |
| `typescript-first-step-2026` | 9 |
| `audacity-4-guide-2026` | 8 |

## 今週のアクション

1. Amazon数値を更新する（上記コマンド）
2. P1候補の上位10本へCVRパーツを適用する:

   ```bash
   python scripts/cvr_backfill_md.py --apply --slugs scotch-whisky-5choice-2026,nousaku-tin-sake-set-deep-dive-2026,scarlett-2i2-deep-dive-2026,windows-11-26h2-memory-daw-2026,arita-enka-sake-set-deep-dive-2026,modern-spiritual-jazz-2026,statement-hat-trend-2026,technics-sl1200mk7-deep-dive-2026,mitsuya-cider-zero-deep-dive-2026,2026-jazz-new-albums-jon-batiste-chihiro-yamanaka
   ```

3. Search Consoleにデータが溜まってきたら `p0-metrics.py --sc scripts/p0-sc.csv` で順位/クエリを統合

# P0 数値サマリ（Search Console × 記事 × Amazon）

- 生成: 2026-11-20 07:50 JST
- 入力CSV: `scripts/p0-sc.csv`
- 検索結果に出た記事: **5本** / 公開記事 271本（CSVに無い記事はインプレッション0扱い）
- 合計インプレッション: **15** / 合計クリック: **0**

## 記事別（インプレッション順）

| slug | タイトル | IMP | クリック | CTR | 平均順位 | ASIN | 検索リンク | メモ |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `gguf-quantization-q4-q5-guide-2026` | ローカルLLMの量子化、GGUFの数字を読む — Q4とQ5が削るもの、残すもの | 8 | 0 | 0.0% | 23.5 | 1 | 0 | P2候補 |
| `taiwan-india-whisky-climate-2026` | 台湾とインドのウイスキー、熱い土地で樽は速く働く | 4 | 0 | 0.0% | 30.5 | 3 | 0 | - |
| `condenser-mic-5choice-2026` | コンデンサーマイク5本比較 — 指向性と電源から選ぶ、宅録の最初の一本 | 1 | 0 | 0.0% | 33.0 | 5 | 0 | 比較ハブ |
| `four-roses-yellow-deep-dive-2026` | 10種の原酒で組み上げる、フォアローゼズ イエローの手間 | 1 | 0 | 0.0% | 56.0 | 1 | 0 | - |
| `modal-jazz-challenge` | モーダルジャズという挑戦、『Kind of Blue』から『A Love Supre | 1 | 0 | 0.0% | 27.0 | 3 | 0 | P2候補 |

## 上位クエリ Top 30

| クエリ | IMP | クリック | 平均順位 |
|---|---:|---:|---:|
| gguf q8 | 5 | 0 | 9.8 |
| ウイスキー インド 台湾 | 4 | 0 | 30.5 |
| gguf | 2 | 0 | 65.0 |
| at2020 指向性 | 1 | 0 | 33.0 |
| フォア ローゼス ハイ ボール | 1 | 0 | 56.0 |
| gguf q4_k_m | 1 | 0 | 9.0 |
| モーダル・ジャズ | 1 | 0 | 27.0 |

## Amazon アソシエイト（サイト全体）

- period: Oct 20 2026 〜 Nov 18 2026 / 過去30日間
- clicks: 220
- orders: 0
- revenue: 0
- cvr: 0.00%
- approval_status: 直近30日で注文0件。180日以内3件の本承認には至っていない可能性が高い（管理画面に明示表示なし）

| トラッキングID | 媒体 | クリック | 注文 | 売上 | CVR |
|---|---|---:|---:|---:|---:|
| `nakimoto1-22` | GitHub Pages | None | None | None | None |
| `hatena-img-sub-22` | はてな | None | None | None | None |
| `note-img-sub-22` | note | None | None | None | None |
| `ameba-img-sub-22` | Ameba | None | None | None | None |
| `x-img-22` | X | None | None | None | None |

## 次のアクション

1. `P1候補` の記事（上位20〜30本）にプランAのCTA/テキストリンク/価格注記/不安解消をバックフィル
2. `P2候補`（順位11〜30）のタイトル・description・h2を修正
3. P4で `affiliate_click` イベントを追加し、記事別CVRを計測可能にする

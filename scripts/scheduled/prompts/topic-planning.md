# ネタ会議（ブログのネタの自動生成・無人実行）

Windows タスクスケジューラから無人で起動されている。人間は見ていないので質問せず、最後まで自分で判断すること。
起動時の指示に `Mode: weekly`（毎週日曜03:00）か `Mode: topup`（毎日04:00）が付いている。


コマンドはすべてリポジトリのルート（`C:\Users\norio\my-github-blog`）で実行する。Python は `python`（環境変数 PYTHONIOENCODING=utf-8 は設定済み）。

## 0. 準備

1. `git pull --rebase origin main`（Android アプリで削除されたネタ＝`scripts/topic-skips/*.json` を取り込むため）
2. `python scripts/topic_plan.py sync-skips` と `python scripts/topic_plan.py ingest-requests`（アプリから追加されたネタを最優先でキューに入れる。
   これらはテーマとメモだけなので、ここでは補完しなくてよい。投稿ジョブが記事を書くときに調べる）
3. `python scripts/topic_plan.py status` を見る。キューの `approved` 件数を確認する。
   - `Mode: topup` で `approved` が 16 件以上なら、何もせず「補充不要」と出力して終了する。
   - それ以外は、`approved` が **64 件**になるまで補充する。必要数 N = 64 − approved。

## 1. 配分

`python scripts/topic_plan.py allocate N` で、カテゴリーごとの採用件数を得る（JSON）。
この件数どおりに採用する。各カテゴリーで、**採用件数の約2倍**の候補を作ってから採点で絞る。

## 2. 持ち込みネタ（最優先）

`scripts/themes.txt` の `#` 以外の行は、ユーザーが手で書いたネタ。1行ずつ候補にし、`source_of_idea: "user"` を付ける
（採点はするが不採用にはしない。カテゴリーは内容から判断）。取り込んだ行は themes.txt から削除する（先頭のコメントは残す）。

## 3. 材料集め（カテゴリーごと）

- `python scripts/topic_plan.py news <category> --days 14` … 直近のニュース見出し
- `python scripts/topic_plan.py calendar` … 今月と来月の季節・行事
- `python scripts/topic_plan.py gaps` … 既存記事のすき間（単独記事の無い製品など）
- `python scripts/topic_plan.py matrix <category>` … 定番テーマの軸（ネタ切れ防止）
- 必要に応じて Web 検索で、新製品・新作・トレンドが**実在し、現在の情報か**を確かめる。

## 4. 候補の作成

1候補ごとに、次の JSON オブジェクトを作る（全項目必須。subjects は無ければ空配列）。

```json
{
  "category": "setup",
  "new_category": null,
  "theme": "6畳で始める宅録環境、予算別の組み方",
  "angle": "何が新しいか・誰向けか（1〜2文）",
  "article_type": "guide",
  "keywords": ["宅録 機材 予算", "DTM 環境 6畳"],
  "subjects": [{"name": "製品・人物・作品名", "status": "current", "amazon_asin": null}],
  "sources": ["https://...", "https://...", "https://..."],
  "images": [{"url": "...", "page": "...", "license": "CC BY 2.0", "author": "..."}],
  "season": "通年",
  "score": {"novelty": 0, "verifiable": 0, "images": 0, "season": 0, "demand": 0, "amazon": 0, "total": 0},
  "source_of_idea": "news"
}
```

- `article_type`: `deep-dive`（1製品）/ `comparison`（3〜5製品）/ `theme`（テーマ記事）/ `styling`（スタイリング）/ `guide`（入門・学習・環境づくり）
- `source_of_idea`: `news` / `calendar` / `gap` / `matrix` / `search` / `user`
- 製品中心でなくてよい。Amazon で扱いがあれば `amazon_asin` を入れる（加点のみ。必須ではない）。
- **重複確認**: 各候補で `python scripts/topic_plan.py similar "<theme>"` を実行し、既存記事・キュー・不採用履歴と
  同じ題材・同じ切り口なら作り直す（文字の類似度が低くても、内容が同じなら重複とみなす）。
- **画像の事前確認（必須）**: `python scripts/topic_plan.py images "<英語の検索語>"` で、ライセンスが確認できる画像を
  **2件以上**見つけ、`images` に入れる。非商用（NC）・改変禁止（ND）は不可。見つからない候補は捨てる。
- **事実確認**: `sources` は実在する URL を3件以上。製品は現行品か確認し、生産終了なら後継機に触れられるか確認する。

## 5. 採点（100点満点）

novelty（重複していない 25）／verifiable（事実を確かめられる 20）／images（画像を用意できる 20）／
season（季節・旬 15）／demand（検索需要 10）／amazon（Amazonで紹介できる 10）。
`total` が 60 未満は不採用。カテゴリーごとに点数の高い順で、配分の件数だけ残す。

## 6. 新カテゴリー

既存のどのカテゴリーにも合わない有力な候補が **3件以上**（いずれも60点以上）出せるときだけ、新カテゴリーを作ってよい（1週間に1つまで）。
- `scripts/category-plan.json` に `{"id": "英小文字", "name": "日本語名", "weight": 1.0}` を追加
- `hugo.toml` の `[menu]` にカテゴリーの項目を追加（既存の項目と同じ形式。url は `/categories/<id>/`）
- `layouts/index.html` の `CATEGORY_LABELS` に日本語名を追加
- 候補の `category` に新しい id を入れる

## 7. キューへの投入

採用した候補を JSON 配列として `scripts/.topic-candidates.json` に書き、
`python scripts/topic_plan.py add scripts/.topic-candidates.json` を実行する（重複・点数・画像数をもう一度機械的に確認し、
通ったものだけ `approved` で追加される）。終わったら `scripts/.topic-candidates.json` を削除する。

## 8. 記録

`git add scripts/topics-queue.json scripts/topic-log.json scripts/pipeline-status.json scripts/themes.txt scripts/topic-requests`（新カテゴリーを作った場合は
`scripts/category-plan.json hugo.toml layouts/index.html` も）→ `git commit -m "Plan: <件数> topics (<Mode>)"` → `git push origin main`。
`git add -A` は使わない。

最後に、追加件数・カテゴリー別の件数・不採用件数を1〜3行で出力する。

## push について

Android アプリからの削除（`scripts/topic-skips/*.json`）が同時に push されることがある。`git push` が拒否されたら `git pull --rebase origin main` してからもう一度 push する。

## 一時ファイル

作業用の一時ファイル（画像の検索結果、候補の下書きなど）は `scripts/` やリポジトリの中に作らず、`/tmp`（`$TMP`）に置く。終了前に削除する。

# ブログ記事の投稿（キューから1件・無人実行）

Windows タスクスケジューラから1日6回（07:30 / 12:00 / 17:30 / 20:00 / 21:30 / 23:00、`scripts/topic_plan.py` の
`SLOTS` で定義。2026-10-08、1日6投稿・時間帯別タイムテーブルに改修）無人で起動されている。各回はアクセスピークの
30〜60分前に当たり、時間帯ごとに配信先チャンネル（github/hatena/note）と記事の性格（実用寄り/理論・エッセイ寄り）が
決まっている。人間は見ていないので質問せず、最後まで自分で判断すること。**1回の実行で公開するのは最大1記事**。

コマンドはすべてリポジトリのルート（`C:\Users\norio\my-github-blog`）で実行する。Python は `python`。
ルールの詳細は `CLAUDE.md`（文体・禁止事項・タイトル・画像・アフィリエイト・はてな・note の節）にある。**作業前に必ず読む。**

## 1. 開始前の確認

1. `git pull --rebase origin main`
2. `python scripts/topic_plan.py health` が **3以上**なら、連続失敗のため何もせず「停止中（連続失敗）」と出力して終了する。
3. `python scripts/topic_plan.py today-count` が **6以上**なら「本日の上限（6記事）に到達」と出力して終了する（手動投稿も含めて数えている）。
4. `python scripts/topic_plan.py slot` でこの回の時間帯スロット（`time` / `channel` / `label`、`categories` か `article_types` の優先条件）を確認する。
   この後の「ネタを取り出す」「チャンネル判定」「クロスリンク挿入」はこのスロット情報に沿って動く。

## 2. ネタを取り出す

`python scripts/topic_plan.py claim` を実行する。内部でも同じスロット判定が働き、現在のスロットのチャンネル・優先条件に合う
承認済みネタを優先して選ぶ（合うネタが無ければチャンネルだけ合うネタ、それも無ければ通常の優先順位にフォールバックする）。
Android アプリで削除されたネタはここで自動的に除外され、アプリから追加されたネタ（`scripts/topic-requests/*.json`）はここでキューに取り込まれて最優先で選ばれる。
- 出力が `{"empty": true}` なら、`scripts/scheduled/prompts/topic-planning.md` の手順3〜7を**1件分だけ**行ってキューに足し、もう一度 claim する。
- 取り出したネタ（JSON）の `id` を控える。状態は `in_progress` になる。出力には `channel`（配信先）・`slot_time`・`slot_label`
  （今回のスロット）も含まれる。ここで一度
  `git add scripts/topics-queue.json scripts/topic-log.json scripts/pipeline-status.json scripts/topic-requests && git commit -m "Claim <id>" && git push origin main`。
- **アプリから追加されたネタ**（`source_of_idea: "user"`、`needs_research: true`）は、テーマとメモしか無い。`sources`・`images`・`keywords` は
  このあとの手順で自分で集める。`category` が空なら、まず手順1で確認した今回のスロットのチャンネル（github/hatena/note）に合う既存カテゴリーから、
  内容に合うものを選ぶ（合わなければ新カテゴリーも可）。`article_type` が空なら記事の型を決める。メモ（`angle`）はユーザーの希望なので必ず反映する。
- **チャンネル判定**: 取り出したネタの出力に含まれる `channel` フィールドに基づき、以下の配信先を決定する。
  - `github` → GitHub Pages へのみ投稿（はてな・note への転載はしない）
  - `hatena` → GitHub Pages へサマリーを生成し、はてなブログ API で全文投稿
  - `note` → GitHub Pages へサマリーを生成し、note 投稿スクリプト経由で送信
  - `channel` フィールドが無い場合はデフォルトで `github` となる。

## 3. リサーチ

Web 検索は**必ずサブエージェントに任せる**。Agent ツールを `subagent_type: "general-purpose"`、`model: "haiku"`（Haiku 4.5）で起動し、
自分では WebSearch / WebFetch を呼ばない。比較記事など対象が複数あるときは、対象ごとに並列で起動してよい。
- 依頼内容: ネタの `sources` から始めて、合計5サイト以上（英語の情報源を優先）を調べる。製品・人物・作品が実在し現在の情報であることを確かめる。
- 返してもらうもの: 調べた事実の要点（出典URL付き）、現行モデル・最新版かどうか、確かめられなかった点。
- サブエージェントには調査だけをさせ、ファイルの作成・編集、画像の取得や作成はさせない（記事・画像・ASIN は自分で扱う）。
- 返ってきた内容で事実が食い違う・あいまいな点は、記事に書く前に追加のサブエージェントで確かめ直す。
- 事実が確かめられない・題材が存在しない・既存記事と同じ内容だと分かったら、
  `python scripts/topic_plan.py reject <id> --reason "<理由>"` → 手順2からやり直す（やり直しは1回の実行で2回まで）。

## 4. 執筆

- **本文は日本語だけで書く**。韓国語・中国語・英語の文や単語を混ぜない（製品名・固有名詞の英字は可）。書き終えたらすぐに
  `python scripts/validate_post.py <slug>` を実行し、NG の箇所だけを直す。1文ずつ置換スクリプトで直すような細かい修正を何十回も繰り返さず、
  崩れた段落は段落ごと書き直す。

- `content/posts/<slug>.md`（slug は英小文字とハイフン）。カテゴリーはネタの `category`（1つだけ）。
- 記事の型はネタの `article_type` に従う（deep-dive / comparison / theme / styling / guide）。
- **タイトル**: CLAUDE.md の規則どおり、記事ごとに言い回しを変える。固定の型（全機能解剖／味と仕様／仕様と使い方／の現在地／徹底比較）は禁止。
  書く前に `content/posts/` の最近のタイトルを数本見て、同じ構文を続けない。
- 文体: 素直で丁寧な一人称。他サイト・媒体名を根拠にしない。情報源や調べ方に触れない。所持に触れない。「実際に〜してみた」禁止。
- 本文は日本語のみ（中国語・英語の文章を混ぜない）。深掘り・テーマ記事は5,000字前後以上。見出し（##）は3つ以上。
- frontmatter: `title` / `description`（110〜120字）/ `images: ["/images/og/<slug>.jpg"]` / `date`（**現在時刻より前**、+09:00）/
  `categories: ["<category>"]` / `tags` / `draft: false` / `scheduled_time: "<slot の time>"`（手順1で確認したこの回のスロット時刻。
  例 `"20:00"`。公開は即時だが、どの時間帯枠で書かれた記事かを記録する）。
- 新カテゴリー（ネタの `new_category` あり）なら、`category-plan.json`・`hugo.toml` の `[menu]`・`layouts/index.html` の `CATEGORY_LABELS` に追加する。

## 5. 画像

- ネタの `images` を出発点に、記事に合う画像を2〜5枚（比較記事は製品ごとに1枚）。候補は `python scripts/topic_plan.py images "<検索語>"`。
  非商用（NC）・改変禁止（ND）・Amazon の商品画像は使わない。
- **画像は必ず `python scripts/fetch_image.py <slug> images/<slug-短縮>/<名前>.jpg "<File:Commonsのファイル名 か URL>"` で取得する**
  （Commons 以外は `--page <出典ページ> --license <ライセンス> --author <作者>` を付ける）。出典が `scripts/image-sources/<slug>.json` に記録され、
  validate_post.py が出典から取り直して同じ画像か照合する。出力の `credit` をそのまま `<span class="credit">` に使う。
- **画像を自分で作らない**。Python（PIL 等）・SVG・awk などで絵・図形・グラデーション・ロゴ風画像・地図風画像を描いて代用することは禁止
  （例外はレーダーチャートだけ。必ず `scripts/radar-chart.awk` で、記事に書いた点数から作る）。
  2026-10-03 に、モデルが本物の画像を探しきれず、格子模様・白紙・乱数データの「画像」を作って公開する事故が起きた。
- 取得した画像は**1枚ずつ Read で開いて目で確認**し、題材そのもの（その製品・その場所）が写っているかを確かめる。ファイル名と中身が違うことがある。
- 実在の画像が2枚そろわない、製品の写真が見つからない場合は、**画像を作らずに** `python scripts/topic_plan.py fail <id> --reason "画像が見つからない"` で終了する。
- 配置は CLAUDE.md の回り込みルール（`<figure class="photo photo--left|right">`、見出しの直後、左右交互、幅220、figcaption と credit 必須）。
  クレジットは必ず `<span class="credit">CC / Public domain / Image: / Photo: / 撮影: など の具体的なクレジット情報</span>` の形式で。
- Amazon で扱いのある製品は、画像を `<a href="https://www.amazon.co.jp/dp/<ASIN>?tag=nakimoto1-22" target="_blank" rel="noopener sponsored nofollow">` で包む
  （**画像をクリックするとその製品の Amazon ページが開くこと**。ASIN が分からなければ `https://www.amazon.co.jp/s?k=<製品名>&tag=nakimoto1-22`）。
  Amazon に無いもの（無料ソフト等）は公式サイトへのリンクで包む。
- 公開後、`curl` の 200 だけで済ませない。`python scripts/check_live_page.py <slug>` で実ブラウザ表示を確認する（画像が全部表示され、figure がリンク付きか）。

## 6. 仕上げと検査

1. OGP 画像: `python -c "import importlib.util as u;s=u.spec_from_file_location('og','scripts/og-image-generator.py');m=u.module_from_spec(s);s.loader.exec_module(m);m.render('<タイトル>','<category>','kingsworksub-jpg',m.OUT/'<slug>.jpg')"`
2. `python scripts/og_dimensions.py`
3. **`python scripts/validate_post.py <slug>`** — NG が出たら直して再実行する。2回直しても通らなければ、作った記事・画像を削除し、
   `python scripts/topic_plan.py fail <id> --reason "<NG内容>"` を実行して終了する（公開しない）。
4. `hugo --minify` でビルドし、`public/posts/<slug>/index.html` ができていることを確認する。
5. **チャンネル判定**: `python scripts/topic_plan.py claim` の出力JSONに含まれる `channel` フィールドを確認する。その結果に応じて以下の配信先を決定する。
   - `channel: github` → はてな・note への転載は行わない（GitHub Pages へのみデプロイ）
   - `channel: hatena` → はてなブログへ全文投稿（ステップ9へ進む）
   - `channel: note` → GitHub Pages へサマリー掲載し、note へ投稿（ステップ9 の note 実行前にサマリー生成）
6. クロスリンク挿入: 記事の最後に「関連記事」ブロックを挿入する（手順7.5のスロット別フォーマットを参照）。

## 7. 公開

1. `git add` で自分が作ったファイルだけを追加（記事・画像フォルダ・OGP画像・必要なら category-plan.json / hugo.toml / layouts/index.html）。
   `git add -A` は使わない。`git commit` → `git push origin main`（pre-push フックが validate_post.py を再実行する。失敗したら直す）。
2. `gh run list --workflow=hugo.yml --limit 1` で成功を確認し、`curl` で記事ページと各画像が 200 を返すことを確認する。
3. **チャンネル別外部プラットフォーム投稿**:
   - `channel: github` → 外部転送スキップ
   - `channel: hatena` → `source .secrets/hatena.env && bash scripts/extract-post-html.sh <slug> /tmp/<slug>.html && bash scripts/post-to-hatena.sh "<タイトル>" /tmp/<slug>.html publish`
   - `channel: note` → `python scripts/convert-to-note.py <slug>` → `python scripts/post-to-note.py --slug <slug> --publish`
   - `channel: ameba` → `python scripts/post-to-ameba.py --slug <slug> --publish`
4. チャンネル判定用の一時ファイル `/tmp/.blog_channel` が存在する場合は削除する。

5. **クロスリンク挿入（CV誘導、手順1.4で確認したスロットに応じて出し分ける）**: 記事の本文末尾（Amazonリンク等より後）に
   「## 関連記事」ブロックを挿入する。目的は、昼間の記事から夜の主力記事への予告、夜の記事からの本家・他チャンネルへの回遊。
   - `07:30`（朝・github）/ `12:00`・`17:30`（昼・夕・hatena）: 下記の共通リンクに加えて、まだ存在しない今夜の記事URLではなく
     プラットフォームのトップページへの「予告」行を1つ足す。例:
     `- 今夜はウイスキー・カルチャーの記事やDTM理論の記事も公開予定です → [note はこちら](https://note.com/shining_finger01)`
   - `20:00`（夜・github）: 下記の共通リンクのみでよい（予告行は不要）。
   - `21:30`・`23:00`（夜ピーク・就寝前・note）: 下記の共通リンクのうち GitHub Pages への行を必ず残す（本家への回遊）。
   共通フォーマット（自分が今回投稿するチャンネル以外へのリンクだけを載せる）:
   ```
   ## 関連記事
   - [GitHub Pages で技術・理論記事を読む](https://kingsworksub-jpg.github.io/)
   - [はてなブログ版はこちら](https://kinbro.hatenablog.com/)
   - [note版はこちら](https://note.com/shining_finger01/n/XXXX)
   ```
   ※ `XXXX` は実際のnote記事キーを執筆後に埋める。このステップの時点ではプレースホルダのまま残す。

1. `python scripts/topic_plan.py complete <id> --slug <slug> --hatena <EntryID> --note <key>`（カテゴリーを自分で決めた場合は `--category <id>` も付ける）
2. CLAUDE.md の「はてなブログ連携」表と「note.com への投稿」表に1行ずつ追記。
3. `git add scripts/topics-queue.json scripts/topic-log.json scripts/pipeline-status.json CLAUDE.md scripts/note-drafts/<slug>.note.txt`
   → `git commit -m "Record <slug>"` → `git push origin main`。

## 失敗したとき

- 途中で失敗したら、未コミットの自分の生成物（記事・画像）を削除し、`python scripts/topic_plan.py fail <id> --reason "<内容>"` を実行して
  `scripts/topics-queue.json scripts/topic-log.json scripts/pipeline-status.json` を commit & push する。
- すでに push 済みなら、記事は公開状態のまま残し、はてな・note の失敗だけを結果に書く。
- CronCreate などのスケジュール系ツールは使わない。最後に、結果（公開した記事の URL、またはスキップ・失敗の理由）を1〜3行で出力する。

## push について

Android アプリからの削除（`scripts/topic-skips/*.json`）が同時に push されることがある。`git push` が拒否されたら `git pull --rebase origin main` してからもう一度 push する。

## 一時ファイル

作業用の一時ファイル（画像の検索結果、候補の下書きなど）は `scripts/` やリポジトリの中に作らず、`/tmp`（`$TMP`）に置く。終了前に削除する。

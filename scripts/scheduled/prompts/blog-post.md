# ブログ記事の投稿（キューから1件・無人実行）

Windows タスクスケジューラから1日9回（07:30 / 09:30 / 12:00 / 14:30 / 17:00 / 18:30 / 20:00 / 21:30 / 23:00、
`scripts/topic_plan.py` の `slots_for_date` で定義。2026-10-22、1日9投稿・時間帯別タイムテーブルに改修）無人で起動されている。
9枠は **hatena・ameba・note にそれぞれ3枠ずつ**で、毎日同じ配分（隔日の入れ替えはない）。**GitHub Pages はスロットを持たず、
どのチャンネルの記事も公開と同時に必ずデプロイされる（別枠・全記事）**。各回はアクセスピークの30〜60分前に当たり、
時間帯ごとに記事の性格（実用寄り/理論・エッセイ寄り）が決まっている。
どのチャンネルかは毎回 `python scripts/topic_plan.py slot` の出力で確認すること（時刻から手計算しない）。
人間は見ていないので質問せず、最後まで自分で判断すること。**1回の実行で公開するのは最大1記事**。

コマンドはすべてリポジトリのルート（`C:\Users\norio\my-github-blog`）で実行する。Python は `python`。
ルールの詳細は `CLAUDE.md`（文体・禁止事項・タイトル・画像・アフィリエイト・はてな・note の節）にある。**作業前に必ず読む。**

## 1. 開始前の確認

1. `git pull --rebase origin main`
2. `python scripts/topic_plan.py health` が **3以上**なら、連続失敗のため何もせず「停止中（連続失敗）」と出力して終了する。
3. `python scripts/topic_plan.py today-count` が **9以上**なら「本日の上限（9記事）に到達」と出力して終了する（手動投稿も含めて数えている）。
4. `python scripts/topic_plan.py slot` でこの回の時間帯スロット（`time` / `channel` / `label`、`categories` か `article_types` の優先条件）を確認する。
   この後の「ネタを取り出す」「チャンネル判定」「クロスリンク挿入」はこのスロット情報に沿って動く。

## 2. ネタを取り出す

`python scripts/topic_plan.py claim` を実行する。内部でも同じスロット判定が働き、**現在のスロットと同じチャンネルの
承認済みネタだけ**を選ぶ（他チャンネルのネタにはフォールバックしない。毎日3本ずつを保つため）。
Android アプリで削除されたネタはここで自動的に除外され、アプリから追加されたネタ（`scripts/topic-requests/*.json`）はここでキューに取り込まれて最優先で選ばれる。
- 出力が `{"empty": true}` なら、今回のスロットのチャンネルに合うネタが無いということ。
  `scripts/scheduled/prompts/topic-planning.md` の手順3〜7を**1件分だけ**行い、**必ずこのスロットのチャンネル**
  （hatena / ameba / note）のカテゴリーでキューに足してから、もう一度 claim する。
- 取り出したネタ（JSON）の `id` を控える。状態は `in_progress` になる。出力には `channel`（配信先）・`slot_time`・`slot_label`
  （今回のスロット）も含まれる。ここで一度
  `git add scripts/topics-queue.json scripts/topic-log.json scripts/pipeline-status.json scripts/topic-requests && git commit -m "Claim <id>" && git push origin main`。
- **アプリから追加されたネタ**（`source_of_idea: "user"`、`needs_research: true`）は、テーマとメモしか無い。`sources`・`images`・`keywords` は
  このあとの手順で自分で集める。`category` が空なら、手順1で確認した今回のスロットのチャンネル（hatena / ameba / note）に合う既存カテゴリーから、
  内容に合うものを選ぶ（合わなければ新カテゴリーも可）。`article_type` が空なら記事の型を決める。メモ（`angle`）はユーザーの希望なので必ず反映する。
- **チャンネル判定**: 取り出したネタの出力に含まれる `channel` フィールドに基づき、以下の配信先を決定する。
  GitHub Pages はどのチャンネルでも必ずデプロイされる（別枠・全記事）ので、ここでは外部転載先だけを見る。
  - `hatena` → はてなブログ API で全文投稿
  - `ameba` → Ameba ブログへ全文転載
  - `note` → note 投稿スクリプト経由で送信
  - `github` → 外部転載はしない（`lab` / `notes` は投稿スロット外。通常は選ばれない）

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
- 文体: 素直で丁寧な一人称。他サイト・媒体名を根拠にしない。情報源や調べ方に触れない。所持に触れない。「実際に〜してみた」禁止。読者がその製品・アイテムを手に入れたときの体験価値（ベネフィット）や日常の劇的な変化をエモーショナルに描き出し、自然な購買・導入意欲を高める構成とすること。
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
  （**画像をクリックするとその製品の Amazon ページが開くこと**。**ASIN はできるだけ実際の商品ページから確認して使う**
  （`channel: ameba` の記事は `/dp/<ASIN>` 形式でないと post-to-ameba.py が Ameba Pick リンクに変換できない — 検索リンク
  フォールバックのままだと Ameba 版はリンクなしの画像になる）。ASIN がどうしても分からなければ
  `https://www.amazon.co.jp/s?k=<製品名>&tag=nakimoto1-22`）。Amazon に無いもの（無料ソフト等）は公式サイトへのリンクで包む。
- 公開後、`curl` の 200 だけで済ませない。`python scripts/check_live_page.py <slug>` で実ブラウザ表示を確認する（画像が全部表示され、figure がリンク付きか）。

## 5b. Amebaチャンネル専用フォーマット（channel: ameba の場合）

Amebaブログは「ドリンク・飲料と酒の分析、カクテルの歴史やレシピ、ドリンク関連のツールやハック」に特化した専門ブログとして運用する。`channel: ameba` の記事は以下の標準構成とトーンに従う。

### カテゴリーと記事型の対応
- `drink-lab`（分析・成分・比率）: 数値データ、成分表、アルコール度数や配合の科学的分析を軸にした検証記事
- `drink-recipe`（歴史・レシピ・カクテル）: カクテルの歴史的背景、伝統的レシピ、具体的な配合比率を解説する実用・文化記事
- `drink-tools`（ツール・ギア）: グラス、シェイカー、ジガー、炭酸水メーカーなどの道具やバー用品レビュー
- `drink-hack`（ハック・裏技）: 氷の作り方、冷やし方、保存法、割り方のテクニック等のハック
- `drink`（飲料）: 各種飲料・お酒の総合的な深掘り記事（成分・歴史・飲み比べ）

### 標準構成（テンプレート）
1. **導入** — なぜ今このテーマか、読者が得るメリットを1〜2文で
2. **結論・要約データ** — 記事の核心を数値や比較表で先に示す（例: 「糖質は1本あたりXg、コーラのY%」）
3. **詳細検証・解説** — 成分表の読み方、比率の科学、実験結果、歴史的背景を論理的に展開
4. **実践・レシピ** — 具体的な配合比率、手順、温度・炭酸の条件を再現可能な形で
5. **まとめ・関連ツール** — 結論の再提示と、関連するツールや派生レシピへの言及

### トーン＆マナー
- **論理的かつ分かりやすい**: 感覚ではなく数値と根拠で語る。「〜と感じた」より「〜という結果になった」
- **親しみやすさ**: 難しい成分名はカタカナと併記（例: カフェイン（caffeine））。専門用語の直後に一言解説
- **再現性**: レシピは「目安」ではなく「この比率・この温度・この時間」と具体的に
- **禁止事項**: 過度な煽り、根拠のない「最強」「絶対」、他社製品への不当な比較・貶め
- **数字の扱い**: 成分値は成分表や公式データに基づく。不明な場合は「推定」「目安」と明記

## 6. 仕上げと検査

1. OGP 画像: `python -c "import importlib.util as u;s=u.spec_from_file_location('og','scripts/og-image-generator.py');m=u.module_from_spec(s);s.loader.exec_module(m);m.render('<タイトル>','<category>','kingsworksub-jpg',m.OUT/'<slug>.jpg')"`
2. `python scripts/og_dimensions.py`
3. **`python scripts/validate_post.py <slug>`** — NG が出たら直して再実行する。2回直しても通らなければ、作った記事・画像を削除し、
   `python scripts/topic_plan.py fail <id> --reason "<NG内容>"` を実行して終了する（公開しない）。
4. `hugo --minify` でビルドし、`public/posts/<slug>/index.html` ができていることを確認する。
5. **チャンネル判定**: `python scripts/topic_plan.py claim` の出力JSONに含まれる `channel` フィールドを確認する。その結果に応じて以下の配信先を決定する。
   - `channel: github` → はてな・ameba・note への転載は行わない（GitHub Pages へのみデプロイ）
   - `channel: hatena` → はてなブログへ全文投稿
   - `channel: ameba` → Amebaブログへ全文転載
   - `channel: note` → GitHub Pages へサマリー掲載し、note へ投稿（note 実行前にサマリー生成）
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
4. **X (Twitter) への投稿(全チャンネル共通、2026-11-04 正式復活)**: 上記の外部転載が終わった後、GitHub Pagesの記事URL
   (`https://kingsworksub-jpg.github.io/posts/<slug>/`)を使って自分でポスト文面を作る。
   - 条件: 140〜200字程度。読者の興味を惹くフックを1つ。記事タイトル・核心を簡潔に。ハッシュタグ1〜2個(記事内容に合うもの)。
     最後に改行してGitHub Pagesの記事URLを必ず入れる。全体で280字以内に収める。
   - 誇張・煽り系の表現(「必見」「永久保存版」等の多用)は避け、他の文体ルールと同程度に抑える。
   - 文面を一時ファイル(例 `/tmp/x-post-<slug>.txt`)に保存し、`python scripts/post-to-x.py --text-file /tmp/x-post-<slug>.txt --publish` を実行する。
   - **失敗してもブログ公開自体は失敗にしない**: ログイン切れ・UI変更等でこのコマンドが失敗したら、エラーをログに残すだけで
     次の手順に進む(他チャンネルの転載が終わっていれば記事公開は成功扱い。`topic_plan.py recover` の対象にしない)。
5. チャンネル判定用の一時ファイル `/tmp/.blog_channel` が存在する場合は削除する。

6. **クロスリンク挿入（CV誘導、手順1.4で確認した `channel` に応じて出し分ける。時刻ではなく `channel` の値で判定する）**:
   記事の本文末尾（Amazonリンク等より後）に「## 関連記事」ブロックを挿入する。目的は、日中の記事から夜の主力記事への予告、
   夜の記事からの本家・他チャンネルへの回遊。
   - `channel: hatena`: 下記の共通リンクに加えて、まだ存在しない記事URLではなくプラットフォームのトップページへの「予告」行を1つ足す。例:
     `- 今夜はウイスキー・カルチャーの記事やDTM理論の記事も公開予定です → [note はこちら](https://note.com/shining_finger01)`
   - `channel: ameba`: 下記の共通リンクのみでよい（予告行は不要）。
   - `channel: note`: 下記の共通リンクのうち GitHub Pages への行を必ず残す（本家への回遊）。
    共通フォーマット（自分が今回投稿するチャンネル以外へのリンクだけを載せる。すべての媒体から必ず本陣であるGitHub Pagesへの強力な導線と、読者の興味を惹きつける回遊リンクを自動完備させる）:
    ```
    ## 関連記事・おすすめメディア
    - [【本陣】GitHub Pages で全ての専門記事・深掘りデータベースを読む](https://kingsworksub-jpg.github.io/)
    - [はてなブログ版（最新コラム）はこちら](https://kinbro.hatenablog.com/)
    - [Amebaブログ版（ドリンク・酒の科学とレシピ）はこちら](https://blog.ameba.jp/)
    - [note版（厳選ノウハウ・裏側）はこちら](https://note.com/shining_finger01/n/XXXX)
    ```
   ※ `XXXX` は実際のnote記事キーを執筆後に埋める。このステップの時点ではプレースホルダのまま残す。
   自分が今回投稿したチャンネルの行は含めない（例: 今回 `channel: ameba` ならAmebaの行は省く）。

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

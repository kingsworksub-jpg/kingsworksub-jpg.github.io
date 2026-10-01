# ブログ記事の投稿（キューから1件・無人実行）

Windows タスクスケジューラから1日8回（07:15〜21:15 の2時間おき）無人で起動されている。人間は見ていないので質問せず、
最後まで自分で判断すること。**1回の実行で公開するのは最大1記事**。実行エンジンは日替わり（Claude Code / opencode big-pickle）。

コマンドはすべてリポジトリのルート（`C:\Users\norio\my-github-blog`）で実行する。Python は `python`。
ルールの詳細は `CLAUDE.md`（文体・禁止事項・タイトル・画像・アフィリエイト・はてな・note の節）にある。**作業前に必ず読む。**

## 1. 開始前の確認

1. `git pull --rebase origin main`
2. `python scripts/topic_plan.py health` が **3以上**なら、連続失敗のため何もせず「停止中（連続失敗）」と出力して終了する。
3. `python scripts/topic_plan.py today-count` が **8以上**なら「本日の上限（8記事）に到達」と出力して終了する（手動投稿も含めて数えている）。

## 2. ネタを取り出す

`python scripts/topic_plan.py claim` を実行する。Android アプリで削除されたネタはここで自動的に除外され、アプリから追加されたネタ（`scripts/topic-requests/*.json`）はここでキューに取り込まれて最優先で選ばれる。
- 出力が `{"empty": true}` なら、`scripts/scheduled/prompts/topic-planning.md` の手順3〜7を**1件分だけ**行ってキューに足し、もう一度 claim する。
- 取り出したネタ（JSON）の `id` を控える。状態は `in_progress` になる。ここで一度
  `git add scripts/topics-queue.json scripts/topic-log.json scripts/pipeline-status.json scripts/topic-requests && git commit -m "Claim <id>" && git push origin main`。
- **アプリから追加されたネタ**（`source_of_idea: "user"`、`needs_research: true`）は、テーマとメモしか無い。`sources`・`images`・`keywords` は
  このあとの手順で自分で集める。`category` が空なら内容に合うカテゴリーを決め（合わなければ新カテゴリーも可）、`article_type` が空なら記事の型を決める。
  メモ（`angle`）はユーザーの希望なので必ず反映する。

## 3. リサーチ

ネタの `sources` から始めて、合計10サイト以上（英語の情報源を優先）を調べる。Claude Code の日は Agent（general-purpose）に
調査させてよい。製品・人物・作品が実在し現在の情報であることを確かめる。
- 事実が確かめられない・題材が存在しない・既存記事と同じ内容だと分かったら、
  `python scripts/topic_plan.py reject <id> --reason "<理由>"` → 手順2からやり直す（やり直しは1回の実行で2回まで）。

## 4. 執筆

- `content/posts/<slug>.md`（slug は英小文字とハイフン）。カテゴリーはネタの `category`（1つだけ）。
- 記事の型はネタの `article_type` に従う（deep-dive / comparison / theme / styling / guide）。
- **タイトル**: CLAUDE.md の規則どおり、記事ごとに言い回しを変える。固定の型（全機能解剖／味と仕様／仕様と使い方／の現在地／徹底比較）は禁止。
  書く前に `content/posts/` の最近のタイトルを数本見て、同じ構文を続けない。
- 文体: 素直で丁寧な一人称。他サイト・媒体名を根拠にしない。情報源や調べ方に触れない。所持に触れない。「実際に〜してみた」禁止。
- 本文は日本語のみ（中国語・英語の文章を混ぜない）。深掘り・テーマ記事は5,000字前後以上。見出し（##）は3つ以上。
- frontmatter: `title` / `description`（110〜120字）/ `images: ["/images/og/<slug>.jpg"]` / `date`（**現在時刻より前**、+09:00）/
  `categories: ["<category>"]` / `tags` / `draft: false`。
- 新カテゴリー（ネタの `new_category` あり）なら、`category-plan.json`・`hugo.toml` の `[menu]`・`layouts/index.html` の `CATEGORY_LABELS` に追加する。

## 5. 画像

- ネタの `images` を出発点に、記事に合う画像を2〜5枚。**ダウンロード後に必ず中身を目で確認**し、無関係・低品質なら別の画像を探す
  （`python scripts/topic_plan.py images "<検索語>"`）。非商用（NC）・改変禁止（ND）・Amazon の商品画像・図形だけの仮画像は使わない。
- `static/images/<slug-短縮>/` に保存（幅400〜1000px程度）。
- 配置は CLAUDE.md の回り込みルール（`<figure class="photo photo--left|right">`、見出しの直後、左右交互、幅220、figcaption と credit 必須）。
- Amazon で扱いのある製品は、画像を `<a href="https://www.amazon.co.jp/dp/<ASIN>?tag=nakimoto1-22" target="_blank" rel="noopener sponsored nofollow">` で包む。

## 6. 仕上げと検査

1. OGP 画像: `python -c "import importlib.util as u;s=u.spec_from_file_location('og','scripts/og-image-generator.py');m=u.module_from_spec(s);s.loader.exec_module(m);m.render('<タイトル>','<category>','kingsworksub-jpg',m.OUT/'<slug>.jpg')"`
2. `python scripts/og_dimensions.py`
3. **`python scripts/validate_post.py <slug>`** — NG が出たら直して再実行する。2回直しても通らなければ、作った記事・画像を削除し、
   `python scripts/topic_plan.py fail <id> --reason "<NG内容>"` を実行して終了する（公開しない）。
4. `hugo --minify` でビルドし、`public/posts/<slug>/index.html` ができていることを確認する。

## 7. 公開

1. `git add` で自分が作ったファイルだけを追加（記事・画像フォルダ・OGP画像・必要なら category-plan.json / hugo.toml / layouts/index.html）。
   `git add -A` は使わない。`git commit` → `git push origin main`（pre-push フックが validate_post.py を再実行する。失敗したら直す）。
2. `gh run list --workflow=hugo.yml --limit 1` で成功を確認し、`curl` で記事ページと各画像が 200 を返すことを確認する。
3. はてなブログ: `source .secrets/hatena.env && bash scripts/extract-post-html.sh <slug> /tmp/<slug>.html && bash scripts/post-to-hatena.sh "<タイトル>" /tmp/<slug>.html publish`
   （回り込みは extract が自動で付ける）。応答 `/tmp/hatena-response.xml` から Entry ID と URL を取る。
4. note: `python scripts/convert-to-note.py <slug>` → `python scripts/post-to-note.py --slug <slug> --publish --no-wait --hold 5 --img-scale 1`。
   「公開しました: https://note.com/shining_finger01/n/<key>」が出たら成功。失敗しても記事の公開自体は完了として扱い、結果に書く。

## 8. 記録

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

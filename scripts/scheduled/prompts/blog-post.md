# ブログ記事の投稿（キューから1件・無人実行）

Windows タスクスケジューラから1日6回（07:30 / 12:00 / 17:30 / 20:00 / 21:30 / 23:00、
`scripts/topic_plan.py` の `slots_for_date` で定義。固定4枠＋20:00/23:00 の隔日入替）無人で起動されている。
各回のチャンネルは決まっており、20:00 と 23:00 は偶数日・奇数日で入れ替わる（表は `CLAUDE.md` のタイムテーブル）。
`channel: note` の記事も `content/posts/` に置き、公開と同時に GitHub Pages へデプロイされる（2026-11-17〜）。
note の無料記事は GitHub Pages にも全文、有料記事は無料部分＋「続きは note で読む」CTA を載せる。それ以外のチャンネルも
公開と同時に GitHub Pages へデプロイされる。各回はアクセスピークの30〜60分前に当たり、
時間帯ごとに記事の性格（実用寄り/理論・エッセイ寄り）が決まっている。
どのチャンネルかは毎回 `python scripts/topic_plan.py slot` の出力で確認すること（時刻から手計算しない）。
人間は見ていないので質問せず、最後まで自分で判断すること。**1回の実行で公開するのは最大1記事**。

コマンドはすべてリポジトリのルート（`C:\Users\norio\my-github-blog`）で実行する。Python は `python`。
ルールの詳細は `CLAUDE.md`（文体・禁止事項・タイトル・画像・アフィリエイト・はてな・note の節）にある。**作業前に必ず読む。**

## 1. 開始前の確認

1. `git pull --rebase origin main`
2. `python scripts/topic_plan.py health` が **3以上**なら、連続失敗のため何もせず「停止中（連続失敗）」と出力して終了する。
3. `python scripts/topic_plan.py today-count` が **6以上**なら「本日の上限（6記事）に到達」と出力して終了する（手動投稿も含めて数えている）。
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

## 3. リサーチ（gemini 第一候補、失敗時は Claude Haiku）

リサーチは `python scripts/oc_research.py`（opencode / `google/gemini-3.5-flash-lite`）を第一候補にする。
メインで WebSearch / WebFetch を直接呼ばない。比較記事など対象が複数あるときは、対象ごとに並列で実行してよい。

1. 次のどちらかのポリシーで実行する（`<slug>` はまだ無ければ claim した `id` でよい）。
   - 製品・機材・ソフト・飲料など実在確認が主: `--source-policy official`
   - 音楽・エッセイ・文化・歴史・学習・理論など: `--source-policy any`
   ```
   python scripts/oc_research.py --theme "<theme>" --angle "<angle>" --category "<category>" \
     --sources "<url1>,<url2>" --source-policy <official|any> \
     --out /tmp/<slug>-research.json
   ```
   出力は `facts`（出典URL付き）・`entities`（current / discontinued / unverified）・`numbers`・`unverified`・
   `sources_checked` のJSON。終了コードが0で、facts 4件以上・出典URLの到達確認・言語混入チェックを通ったものだけを使う。
   実行ログは `scripts/scheduled/logs/oc-research.log` に残る（失敗理由の確認に使う）。
2. **失敗時のフォールバック**: 終了コードが0以外、facts が4件未満、出典が怪しい、内容が薄い場合は、
   従来どおり Agent ツールを `subagent_type: "general-purpose"`、`model: "haiku"`（Haiku 4.5）で起動する。
   - 依頼内容: ネタの `sources` から始めて、合計5サイト以上（英語の情報源を優先）を調べる。製品・人物・作品が実在し現在の情報であることを確かめる。
   - 返してもらうもの: 調べた事実の要点（出典URL付き）、現行モデル・最新版かどうか、確かめられなかった点。
   - サブエージェントには調査だけをさせ、ファイルの作成・編集、画像の取得や作成はさせない（記事・画像・ASIN は自分で扱う）。
3. 結果を読み、事実が食い違う・あいまいな点は、追加で `oc_research.py` を狭いテーマで再実行するか Agent（haiku）で確かめ直す。
   **JSON／サブエージェント結果に無い事実を記事に書かせない**（手順4の `research` に転記する）。
4. 事実が確かめられない・題材が存在しない・既存記事と同じ内容だと分かったら、
   `python scripts/topic_plan.py reject <id> --reason "<理由>"` → 手順2からやり直す（やり直しは1回の実行で2回まで）。

## 4. 執筆（生成は opencode / DeepSeek V4.1 に委任）

**記事の生成（本文・タイトル・frontmatter・画像の選定と配置・X投稿文）は自分で書かない。** `scripts/oc_generate.py` が
opencode の `deepseek-v4.1-flash-free` を呼んで作る。Claude Code の仕事は「ブリーフ（調査結果と画像候補）を用意する」
「生成結果を読んで確かめる」「選ばれた画像を取得して目視する」「公開する」の4つ。

1. **ブリーフを作る**（`/tmp/<slug>-brief.json`）。次のキーを必ず入れる。
   - `slug`（英小文字とハイフン）/ `slot_time`（手順1のスロット時刻）/ `channel`（手順2で決めた配信先）/ `category`（ネタの category、1つ）/
     `article_type` / `theme` / `angle` / `target_chars`（深掘り・テーマ記事は 5000）/ `image_dir`（`images/<slug-短縮>`）
   - `date`: JST の現在時刻を秒まで。`python -c "import datetime as d;print(d.datetime.now(d.timezone(d.timedelta(hours=9))).isoformat(timespec='seconds'))"`
   - `research`: 手順3で集めた事実の要点（出典URL付き）。`oc_research.py` の `facts` / `numbers` / `unverified` を
     そのまま転記する（フォールバック時はサブエージェントの結果）。**ここに無い事実は記事に入らない**ので、渡し漏れに注意する。
   - `recent_titles`: 直近のタイトル3〜5本（同じ構文を続けさせない）。
   - `image_candidates`: `python scripts/topic_plan.py images "<検索語>" --n 6` の出力に `id`（c1, c2…）と `credit` を足したもの。
     NC/ND と Amazon の商品画像は除く。`credit` は author があれば `Photo: <author> / <license>`、無ければ `Image: <title> / <license>`。
   - `products`: ASIN を確認できた製品だけ `{"name": "...", "asin": "...", "note": "..."}`。
   - `channel_notes`: チャンネル固有の注記（Ameba はカテゴリーと使える ASIN、note は制約など）。Ameba の標準構成・トーンは
     `oc_generate.py` が `channel: ameba` のとき自動で足すので、ここに書き写さなくてよい。
   - カテゴリーが新規（`new_category`）なら、**生成前に** `category-plan.json`・`hugo.toml` の `[menu]`・`layouts/index.html` の
     `CATEGORY_LABELS` に追加する（`validate_post.py` が未登録カテゴリーを NG にする）。
2. **生成する**（Bash ツールのタイムアウトは 600000 ms を指定する）。
   ```
   python scripts/oc_generate.py article --brief /tmp/<slug>-brief.json \
     --article-out content/posts/<slug>.md --meta-out /tmp/<slug>-meta.json \
     --keep-raw /tmp/<slug>-raw
   ```
   - 全チャンネル共通で `content/posts/<slug>.md` に出力する（`content/note-only/` は廃止）。
   - 内部で `validate_post.py` と同じ検査（本文3500字以上、description 90〜140字、`##`3つ以上、figure 2〜6枚、credit、
     Amazon タグ、画像の重複・meta との整合、X投稿文の重み付き280字）を行う。失敗すると理由を stderr に出して終了する。
   - 失敗したら、stderr の理由を `channel_notes`（または `research` の補足）に足して**最大2回まで**再実行する。
     3回とも通らなければ `python scripts/topic_plan.py fail <id> --reason "<NG内容>"` で終了する。**自分で本文を書き直さない。**
3. **生成物を読む**。事実が `research` からはみ出していないか、日本語以外の文字が混ざっていないか、導入→見出し→まとめの流れが
   通っているかを確認する。直したい点は手で書き換えず、ブリーフか `channel_notes` に反映して再生成する
   （誤字脱字レベルの1〜2箇所だけは直接直してよい）。
4. frontmatter は生成物のまま使う。`meta.json` の `title`・`x_post`・`figures` は手順5・6・7で使う。

## 5. 画像（選定・配置は生成物、取得と目視はここで行う）

- どの画像をどこに置くかは `meta.json` の `figures` が答え。各 figure の `local_path` が記事の `<img src="/...">` と一致し、
  `url` / `page` / `license` / `author` / `credit` に候補の出典が入っている。
- **画像は必ず `python scripts/fetch_image.py <slug> <local_path> "<url か File:...>"` で取得する**（`<local_path>` の先頭 `/` は外す）。
  Commons 以外は `--page <出典ページ> --license <ライセンス> --author <作者>` を付ける。出典は `scripts/image-sources/<slug>.json` に残り、
  `validate_post.py` が出典から取り直して同じ画像か照合する。
- 取得した画像は**1枚ずつ Read で開いて目視**し、題材そのもの（その製品・その場所）が写っているかを確かめる。
  ファイル名と中身が違うことがある。合わない候補は `image_candidates` から外して手順4を再実行する（**自分で画像を作らない**）。
- 実在の画像が2枚そろわない、製品の写真が見つからない場合は、**画像を作らずに**
  `python scripts/topic_plan.py fail <id> --reason "画像が見つからない"` で終了する。
- クレジットは `fetch_image.py` が出力した文字列を正とし、記事の `<span class="credit">` と食い違っていたら記事側をその文字列に合わせる。
- Amazon の条件は従来どおり。画像は `<a href="https://www.amazon.co.jp/dp/<ASIN>?tag=nakimoto1-22" target="_blank" rel="noopener sponsored nofollow">` で包む
  （**Ameba は `/dp/<ASIN>` 形式でないと post-to-ameba.py が Ameba Pick に変換できない**）。ASIN を確認できなかった製品は
  生成時に検索リンクになっているので、実在 ASIN が分かったら該当 figure とテキストリンクだけを置換する。
- 配置・回り込みの形式（`figure class="photo photo--left|right"`、見出し直後、左右交互、幅220、figcaption と credit）は
  生成側の検査で担保されている。崩れている箇所だけ、figure の位置を直す。
- 公開後、`curl` の 200 だけで済ませない。`python scripts/check_live_page.py <slug>` で実ブラウザ表示を確認する（画像が全部表示され、figure がリンク付きか）。

## 5b. Amebaチャンネル専用フォーマット（channel: ameba の場合）

Amebaブログは「ドリンク・飲料と酒の分析、カクテルの歴史やレシピ、ドリンク関連のツールやハック」に特化した専門ブログとして運用する。
標準構成（導入 → 結論・要約データ → 詳細検証 → 実践・レシピ → まとめ）とトーン、drink-lab / drink-recipe / drink-tools /
drink-hack / drink のカテゴリー定義は **`scripts/oc_generate.py` の `AMEBA_NOTES` に移した**。`channel: ameba` のときは
生成プロンプトに自動で入るので、ここに書き写す必要はない。

Claude Code が渡すもの・確かめること:
- ブリーフの `category` を drink-* のいずれかにする（ネタの category が別なら、内容に合う drink-* を選ぶ）。
- `channel_notes` に、使ってよい ASIN（`/dp/<ASIN>` 形式）と、数値・レシピで必ず入れてほしい条件を書く。
  検索リンク（`/s?k=`）は Ameba Pick に変換されないため、分かる ASIN は必ずここで渡す。
- 生成後、記事のカテゴリーが drink-* になっていること、Amazon リンクが `/dp/<ASIN>?tag=nakimoto1-22` になっていることを確認する。

## 5c. CVR最適化（コンバージョン率改善プランA、2026-11-14）

冒頭CTA、figure 直後と商品解説直後のテキストリンク、消耗品リンク、価格注記、まとめ前の不安解消、スマホで読める段落長の
6点は、`scripts/oc_generate.py` の `RULES` に生成条件として入っている（`コンバージョン率改善プランA.md` をパイプライン向けに
具体化したもの）。Claude Code は生成後に次の点だけ確認する。

1. **冒頭CTA**: 導入文の直後に、メイン商品の画像＋「Amazonで見る →」の CTA ブロックがある。
2. **商品ごとのテキストリンク**: figure の直後、および各商品のメリット解説の直後に
   `https://www.amazon.co.jp/dp/<ASIN>?tag=nakimoto1-22` のテキストリンクがある。
3. **消耗品・関連アクセサリ**: 交換パーツ・専用ボトル・シロップ・手入れ用品などへのテキストリンクが1本ある。
4. **価格のクリックインセンティブ**: 価格に触れた段落の直後に
   「※現在の実売価格やセール状況は下のリンクからご確認ください。」が1回だけある（繰り返していない）。
5. **購入直前の不安解消**: `## まとめ` の直前に、サイズ・設置・保証・ランニングコスト・手入れの不安を1〜2文で払拭している。
6. **プレースホルダー**: `[CTA_BLOCK: …]` / `[TEXT_LINK: …]` / `[SUB_LINK: …]` が残っていない（`validate_post.py` も NG にする）。

足りない場合は手で段落を足さず、`channel_notes` に「〜が無い」と書いて手順4を再実行する。

**Ameba（`channel: ameba`）の追加ルール**:
- 投稿スクリプト `scripts/post-to-ameba.py` が `scripts/cvr_optimize.py` を通し、書き漏らしがあれば自動で補う
  （`--no-cvr` で無効化できる）。自動挿入は補助なので、生成側で上の1〜6を満たしておく。
- Ameba は Amazon の生リンクを許可しない。画像リンクは Ameba Pick の商品カードに、ASIN 付きのテキストリンクは
  Ameba Pick のテキストリンクに変換される。**検索リンク（`/s?k=`）は変換できずリンクが外れる**ため、ASIN は `channel_notes` で渡す。
- 投稿後、Ameba 側の CTA を1つ実際にクリックし、Amazon 商品ページへ遷移することを確認する
  （Pick テキストリンクの実機確認を兼ねる）。

## 6. 仕上げと検査

1. OGP 画像: `python -c "import importlib.util as u;s=u.spec_from_file_location('og','scripts/og-image-generator.py');m=u.module_from_spec(s);s.loader.exec_module(m);m.render('<タイトル>','<category>','kingsworksub-jpg',m.OUT/'<slug>.jpg')"`
   （`<タイトル>` は frontmatter か `/tmp/<slug>-meta.json` の `title`、`<category>` はブリーフの category）
2. `python scripts/og_dimensions.py`
3. **`python scripts/validate_post.py <slug>`** — NG が出たら、その理由を `channel_notes` に足して手順4を再実行する
   （画像の欠け・OGP・カテゴリー登録は手順5・6で直す）。生成のやり直しは2回まで。それでも通らなければ、作った記事・画像を削除し、
   `python scripts/topic_plan.py fail <id> --reason "<NG内容>"` を実行して終了する（公開しない）。
4. `hugo --minify` でビルドし、`public/posts/<slug>/index.html` ができていることを確認する。
5. **チャンネル判定**: `python scripts/topic_plan.py claim` の出力JSONに含まれる `channel` フィールドを確認する。その結果に応じて以下の配信先を決定する。
   - `channel: github` → はてな・ameba・note への転載は行わない（GitHub Pages へのみデプロイ）
   - `channel: hatena` → はてなブログへ全文投稿
   - `channel: ameba` → Amebaブログへ全文転載
   - `channel: note` → GitHub Pages へ公開（無料は全文 / 有料は無料部分＋CTA）し、note にも投稿（`content/posts/` の本文を変換して送る）
6. クロスリンク挿入: 記事の最後に「関連記事」ブロックを挿入する（手順7.5のスロット別フォーマットを参照）。

## 7. 公開

1. `git add` で自分が作ったファイルだけを追加（記事・画像フォルダ・OGP画像・必要なら category-plan.json / hugo.toml / layouts/index.html）。
   `git add -A` は使わない。`git commit` → `git push origin main`（pre-push フックが validate_post.py を再実行する。失敗したら直す）。
2. `gh run list --workflow=hugo.yml --limit 1` で成功を確認し、`curl` で記事ページと各画像が 200 を返すことを確認する。
3. **チャンネル別外部プラットフォーム投稿**:
   - `channel: github` → 外部転送スキップ
   - `channel: hatena` → `source .secrets/hatena.env && bash scripts/extract-post-html.sh <slug> /tmp/<slug>.html && bash scripts/post-to-hatena.sh "<タイトル>" /tmp/<slug>.html publish`
   - `channel: note` → `python scripts/convert-to-note.py <slug>` → `python scripts/post-to-note.py --slug <slug> --publish`
     - 有料記事は note エディタで有料ラインと価格を設定したあと、`python scripts/note_sync.py sync` →
       `python scripts/note_sync.py apply --slug <slug>` → `python scripts/note_sync.py check` を実行する。
       詳細は `CLAUDE.md` の「有料記事の扱い」。有料記事は GitHub Pages を先に公開しない（全文が一瞬公開されるため）。
   - `channel: ameba` → `python scripts/post-to-ameba.py --slug <slug> --publish`
4. **X (Twitter) への投稿(全チャンネル共通、2026-11-04 正式復活)**: 上記の外部転載が終わった後、GitHub Pagesの記事URL
   (`https://kingsworksub-jpg.github.io/posts/<slug>/`)を入れて投稿する。文面は手で作らず **`meta.json` の `x_post`** を使う。
   - `x_post` は生成時に「日本語本文100字前後＋改行＋記事URL＋ハッシュタグ1〜2個」で作られ、重み付き280字以内を検査済み
     （日本語などASCII以外は2字、URLはt.co圧縮で23字換算）。`/tmp/x-post-<slug>.txt` に書き出し、URLとハッシュタグが入っているか確認する。
   - `channel: note` は記事URLが note 側になるため、`x_post` の GitHub Pages URL を投稿後の note 記事URL
     （`https://note.com/shining_finger01/n/<key>`）に差し替える。差し替えで280字を超えるなら次の `text` で作り直す。
   - 280字を超える・内容が記事とずれている場合は、`/tmp/x-fix-<slug>.txt` に「次の文を280字相当以内に短くしてください。本文だけ返す」と
     元の文面を書いて `python scripts/oc_generate.py text --instruction /tmp/x-fix-<slug>.txt --out /tmp/x-post-<slug>.txt` で作り直す。
   - 誇張・煽り系の表現(「必見」「永久保存版」等の多用)は避け、他の文体ルールと同程度に抑える。
   - `python scripts/post-to-x.py --text-file /tmp/x-post-<slug>.txt --publish` を実行する（加重文字数で280字超を検知してエラーにする）。
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

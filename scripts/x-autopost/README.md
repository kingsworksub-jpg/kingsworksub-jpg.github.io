# はてなブログ → X 自動投稿パイプライン

はてなブログのRSSフィードで新着記事を検出し、Playwrightで本文を取得、Claude Code CLIで要約とX投稿文(3パターン→最も自然なもの1つを選択)を生成し、**Playwrightでx.comにログインしたブラウザから直接投稿する**(X API課金ゼロ)。処理状況はSQLite(`posts.db`)に記録し、重複投稿を防ぐ。

**なぜAPIを使わないか**: X API v2は2026年2月に無料枠を廃止し、URL付き投稿は1件$0.20の完全従量課金になった。このパイプラインは「無料・ローカル完結」を前提に組んでいるため、あえて公式APIを使わず、Playwrightで実際のx.com Web UIにログインして投稿する方式を採用している。

**既知のトレードオフ(承知の上で採用)**: 公式APIではないブラウザ自動化は、Xの利用規約上グレーゾーンであり、頻度や挙動によってはアカウント制限のリスクがある。このパイプラインはブログの更新頻度(週数回程度)に合わせた低頻度投稿を想定しており、人間の通常利用に近いペースで動かす前提。

## 構成

```
feed_check.py     -- RSSフィードをポーリングし、新着記事をDBに登録(status='detected')
scraper.py        -- Playwrightで記事ページを開き、本文を抽出(status='scraped')
generate.py       -- Claude Code CLI(haikuモデル)で要約+投稿文3案+選定(status='generated')
poster.py         -- Playwrightでx.comにログイン済みセッションから投稿(status='posted')
x_login_setup.py  -- 【初回のみ・手動】ブラウザでXにログインし、セッションを保存する
db.py             -- SQLiteのスキーマ・CRUDヘルパー
main.py           -- 上記を順に実行するオーケストレーター(これを定期実行する)
```

## セットアップ

### 1. 依存パッケージのインストール

```powershell
cd scripts\x-autopost
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Claude Code CLIの確認

```powershell
claude --version
```

インストール済みでない場合は `winget install --id Anthropic.ClaudeCode -e` でインストールできる。`main.py` を実行するユーザーがClaude Codeにログイン済みである必要がある(`claude` を一度対話モードで起動してログインしておく)。

### 3. Xへのログインセッションを保存する(初回のみ・手動)

```powershell
cd scripts\x-autopost
python x_login_setup.py
```

ブラウザウィンドウが開くので、**自分のXアカウントで手動でログイン**する(2段階認証もそのまま画面上で完了する)。パスワードはコードやファイルに一切保存されない——保存されるのはログイン後のセッション情報(Cookie等)のみで、`.secrets/x-auth-state.json`(git管理対象外)に書き出される。ログイン完了後、ターミナルに戻ってEnterを押すとセッションが保存される。

このセッションは長期間有効だが、**Xに再ログインを求められる・投稿が失敗するようになったら、このスクリプトをもう一度実行してセッションを取り直す**こと。

### 4. 【重要】既存記事のバックログをスキップ登録する(初回のみ・必須)

DBが空の状態で`main.py`をいきなり実行すると、RSSフィードに載っている**既存記事すべて**が「新着」と誤認識され、まとめてXに投稿されてしまう(実際に本プロジェクトのセットアップ時、既存12記事がこの状態になったため、`seed_baseline.py`でスキップ登録して防いだ)。**X認証情報を設定する前に、必ず以下を実行すること**:

```powershell
cd scripts\x-autopost
python feed_check.py      # 現時点の既存記事をDBに登録(status='detected')
python seed_baseline.py   # それらを 'skipped_baseline' に変更(投稿対象から除外)
```

これ以降にはてなブログへ新規投稿された記事だけが、`main.py`の処理対象(`detected`→`scraped`→`generated`→`posted`)になる。

### 5. 動作確認(1回だけ手動実行)

```powershell
cd scripts\x-autopost
python main.py
```

新着記事があれば、検出→本文取得→文章生成→X投稿、まで一気に走る。`posts.db` の中身をSQLiteビューアで確認すれば、各記事がどの段階まで進んだか(`status`列)が分かる。

### 6. 定期実行の設定(Windowsタスクスケジューラ)

1. タスクスケジューラを開き、「基本タスクの作成」。
2. トリガー: 例えば「15分ごと」「1時間ごと」など、任意の間隔で繰り返す設定にする。
3. 操作: プログラムの開始 →
   - プログラム: `C:\Users\norio\Projects\kingsworksub-jpg.github.io\scripts\x-autopost\.venv\Scripts\python.exe`
   - 引数: `main.py`
   - 開始場所: `C:\Users\norio\Projects\kingsworksub-jpg.github.io\scripts\x-autopost`

## 運用上の注意

- **失敗した記事は`status='error'`のまま止まる**(無限リトライしない)。`error_message`列に原因が入るので、直して`status`を該当する前段階(`detected`/`scraped`/`generated`)に手動で戻せば、次回実行時に再処理される。
- **コスト**: `generate.py` は1記事あたりおよそ$0.05(haikuモデル)。デフォルトのSonnetモデルだと拡張思考が絡んで$0.27〜0.37程度に跳ね上がることを確認済みなので、`generate.py`内の`MODEL`定数は変更しない方が安全。`--max-budget-usd`で暴走時の上限も設定済み。
- **Windows環境でのエンコーディング**: `claude` CLIの出力をファイルリダイレクト(`>`)経由で読むと文字化けする場合がある(Node.jsのWindows上でのstdout非TTY時のcodepage挙動に起因すると見られる)。`generate.py`は`subprocess.run(capture_output=True, encoding="utf-8")`でパイプ経由の直接読み取りを行っており、この方式では文字化けしないことを確認済み。ファイルリダイレクト方式に変更しないこと。
- **本文取得のセレクタ**: `scraper.py`の`ENTRY_CONTENT_SELECTOR`ははてなブログの標準テーマの`.entry-content.hatenablog-entry`を前提にしている。テーマを変更した場合は要修正。
- **重複投稿防止**: RSSのGUID(記事の一意ID)をSQLiteでユニーク制約管理しているため、同じ記事に対して`main.py`を何度実行しても2重投稿にはならない。ただし「既存記事の内容修整による再投稿」(`update-hatena-post.sh`での更新)はRSSのGUIDが変わらないため、そもそも新着として検出されない(想定通りの挙動)。
- **X投稿のセレクタは未検証**: `poster.py`の投稿欄・投稿ボタンのセレクタ(`data-testid="tweetTextarea_0"`等)はX公式サイトの実装に依存しており、**実際にログインして動かして初めて検証できる**(このセッションでは実アカウントへのログインができないため未実施)。初回実行時にうまく投稿できない場合は、ブラウザの開発者ツールでボタン等の`data-testid`を確認し、`poster.py`のセレクタを調整すること。
- **セッション切れ**: `poster.py`は投稿先URLがログインページにリダイレクトされた場合、`SessionExpiredError`を出して停止する。`x_login_setup.py`を再実行してセッションを取り直すこと。
- **tweet_idは取得しない**: API方式と違い、ブラウザ自動化では投稿後のツイートURLを確実に取得するのが難しいため、`posts.db`の`tweet_id`列は基本的に空のままになる(投稿できたかどうかは`status='posted'`で判断する)。

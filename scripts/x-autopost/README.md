# はてなブログ → X 自動投稿パイプライン

はてなブログのRSSフィードで新着記事を検出し、Playwrightで本文を取得、Claude Code CLIで要約とX投稿文(3パターン→最も自然なもの1つを選択)を生成し、X API v2で自動投稿する。処理状況はSQLite(`posts.db`)に記録し、重複投稿を防ぐ。

## 構成

```
feed_check.py  -- RSSフィードをポーリングし、新着記事をDBに登録(status='detected')
scraper.py     -- Playwrightで記事ページを開き、本文を抽出(status='scraped')
generate.py    -- Claude Code CLI(haikuモデル)で要約+投稿文3案+選定(status='generated')
poster.py      -- X API v2(tweepy)で投稿(status='posted')
db.py          -- SQLiteのスキーマ・CRUDヘルパー
main.py        -- 上記を順に実行するオーケストレーター(これを定期実行する)
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

### 3. X API認証情報の取得

1. https://developer.x.com/en/portal/dashboard でアプリを作成(または既存アプリを使用)。
2. アプリの権限を **Read and Write** に設定。
3. 「Keys and tokens」から API Key/Secret、Access Token/Secret を発行(Access Token発行は権限設定を変更した後に再生成が必要な場合がある)。
4. `scripts/x-autopost/x-api.env.example` を `.secrets/x-api.env`(リポジトリルート直下)にコピーし、値を埋める。**このファイルはgit管理対象外(.gitignore済み)。絶対にコミットしないこと。**

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

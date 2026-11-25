---
title: "PythonのLintと整形をRuffへ統合する移行ガイド：Black・Flake8・isortからの脱却"
description: "Rust製の高速ツールRuffでBlack・Flake8・isortを1本化する実践ガイド。pyproject.tomlの具体例からpre-commit導入、既存プロジェクトの段階的な移行手順まで実務目線で詳しく解説します。"
images: ["/images/og/ruff-black-flake8-migration-guide-2026.jpg"]
ogImageWidth: 1200
ogImageHeight: 630
date: "2026-11-25T23:04:39+09:00"
categories: ["dev"]
tags: ["Python", "Ruff", "Linter"]
draft: false
scheduled_time: "23:00"
---

Pythonプロジェクトの規模が大きくなるほど、コード品質を保つための開発環境は複雑になりがちです。これまで多くの現場では、フォーマッタにBlack、リンターにFlake8、インポート順の整理にisortを組み合わせる構成が定番でした。しかし複数のツールを併用すると、設定ファイルが分散するだけでなく、プラグイン同士の依存関係やCIの実行時間も膨らんでしまいます。

こうした課題を根本から解消する選択肢として注目されているのが、Rust製の「Ruff」です。Ruffは従来のPython製リンターと比べて10倍から100倍という圧倒的な速度で動作し、単一のバイナリだけでLintとフォーマットの両方を完結できます。

本記事では、Black・Flake8・isortの3ツール体制からRuffへ無理なく移行するための手順を整理します。実務でそのまま使える `pyproject.toml` の設定例から、pre-commitフックやCIへの組み込み方まで順を追って解説します。公式の最新仕様や詳細なルール一覧は、[Ruff公式リポジトリ](https://github.com/astral-sh/ruff)および[Ruff公式ドキュメント](https://docs.astral.sh/ruff/)もあわせて参照してください。

## Ruffが選ばれる理由と従来ツールとの違い

Ruffが急速に普及している最大の理由は、実行速度とツール統合の両立にあります。Rustで実装された単一バイナリとして提供されており、Pythonインタプリタ上で動く従来ツールとは処理アーキテクチャそのものが異なります。大規模なリポジトリであっても、ローカル開発やCIの待ち時間を大幅に短縮できるのが強みです。

機能面では、これまで別々に管理していた複数の役割を1本に集約できます。リンターとしてのチェックと自動修正に加え、`ruff format` コマンドを使えばBlackと完全な互換性を持つコード整形を実行可能です。さらにインポート文の並び替えもRuffのルール群に含まれているため、isortを別途インストールする必要がありません。

設定ファイルの管理コストが下がる点も、チーム開発では見逃せないメリットです。以前は `.flake8` や `.isort.cfg`、`pyproject.toml` など複数のファイルへ設定が散らばりがちでしたが、Ruffなら `pyproject.toml` へ一元化できます。ツールごとに異なる除外ディレクトリ指定や行長設定を二重管理する手間がなくなります。

| 比較項目 | 従来の3ツール併用（Black + Flake8 + isort） | Ruff（単一バイナリ） |
| :--- | :--- | :--- |
| 実装言語・実行基盤 | Python（各ツールとプラグインを個別実行） | Rust（単一のネイティブバイナリ） |
| 実行速度 | コードベース拡大に伴い待ち時間が増加 | 従来のPythonリンター比で10〜100倍高速 |
| コード整形（Format） | Blackを別コマンドとして実行 | `ruff format` でBlack互換の整形を実行 |
| 静的解析（Lint） | Flake8本体と多数の外部プラグインが必要 | 組み込みルールで主要プラグイン相当を網羅 |
| インポート整理 | isortを別途設定・実行 | Lintの `I` ルール（isort互換）で統合 |
| 設定ファイル | `.flake8` / `setup.cfg` / `pyproject.toml` に分散 | `pyproject.toml`（または `ruff.toml`）に集約 |

<figure class="photo photo--left">
<a href="https://commons.wikimedia.org/wiki/File:Example_HTML_code_using_Notepad%2B%2B.png" target="_blank" rel="noopener"><img src="/images/ruff-migration/img1.jpg" alt="コードエディタ上のソースコード表示イメージ" width="220" height="150" loading="lazy"></a>
<figcaption>単一のツールへ設定を集約することで可読性と保守性が向上します<span class="credit">Photo: Skyhigh278 / CC BY 4.0</span></figcaption>
</figure>

従来環境から乗り換える際、既存のフォーマット結果が大きく崩れないか不安に感じる開発者も少なくありません。RuffのフォーマッタはBlackとの互換性を重視して設計されているため、既存のBlack適用済みコードに対して大きな差分を出しにくい特性があります。まずは現状の構成を棚卸ししたうえで、段階的に置き換える計画を立てるのが安全です。

## 導入前の準備とインストール手順

移行作業を始める前に、現在のリポジトリで使われている設定ファイルとプラグインを把握しておきましょう。具体的には、`pyproject.toml` 内の `[tool.black]` や `[tool.isort]`、さらに `.flake8` や `setup.cfg`、`tox.ini` に書かれたルールを確認します。特にFlake8の追加プラグイン（flake8-bugbearやflake8-comprehensionsなど）を使っている場合は、どのルールIDを有効にしているかをメモしておくと設定の移植がスムーズです。

確認が済んだら、開発環境にRuffをインストールします。プロジェクトの依存管理ツールに合わせて、pipやuv、pipx、あるいはOSのパッケージマネージャから導入できます。チーム全員で同じバージョンを使い続けるためには、`requirements-dev.txt` や `pyproject.toml` の開発依存グループへバージョンを固定して記載しておくのが確実です。

```bash
# pip を使って開発環境へインストールする場合
pip install ruff

# プロジェクトに依存させずグローバル環境へ独立して入れる場合
pipx install ruff

# バージョン確認とヘルプ表示
ruff --version
ruff --help
```

インストール後は、念のため既存のCI設定やMakefile、package.json内のスクリプトなども確認しておきます。ブラックボックス化したラッパースクリプトの中でFlake8やBlackが呼ばれているケースは意外と多いため、呼び出し箇所を事前に洗い出しておくと後工程での取りこぼしを防げます。準備段階ではまだ旧ツールを削除せず、Ruffを並行して動かせる状態を作っておくのがポイントです。

## pyproject.tomlによる設定の一元化レシピ

Ruffの大きな魅力は、`pyproject.toml` だけでLint・インポート整理・フォーマットのすべてを完結できる点にあります。既存の `pyproject.toml` に `[tool.ruff]` 関連のセクションを追記するだけで設定が有効になり、個別の設定ファイルが不要になります。設定項目が論理的にセクション分けされているため、初めて触るメンバーでも意図を把握しやすい構造です。

実務でそのままベースとして活用できる `pyproject.toml` の設定例を以下に示します。対象のPythonバージョンや1行あたりの最大文字数、有効化するルールセット、テストディレクトリ向けの除外設定まで網羅した構成です。プロジェクトの規約に合わせてルールコードを取捨選択してください。

```toml
[tool.ruff]
# ターゲットとするPythonバージョン（プロジェクトの最小サポート版に合わせる）
target-version = "py311"

# Blackの既定値と同じ1行88文字に設定
line-length = 88

# 解析対象から除外するディレクトリ
exclude = [
    ".git",
    ".venv",
    "build",
    "dist",
    "migrations",
]

[tool.ruff.lint]
# 有効化するルールセット
# E, W: pycodestyle / F: Pyflakes / I: isort / B: flake8-bugbear
# UP: pyupgrade / SIM: flake8-simplify
select = ["E", "W", "F", "I", "B", "UP", "SIM"]

# プロジェクト方針として無視するルール（必要に応じて調整）
ignore = [
    "E501", # 行長はフォーマッタ側に任せる場合などに指定
]

# ファイル単位・ディレクトリ単位で特定ルールを緩和
[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]
"tests/**/*.py" = ["S101", "B011"]

[tool.ruff.lint.isort]
# 自社パッケージやファーストパーティモジュールの明示
known-first-party = ["my_project"]
combine-as-imports = true

[tool.ruff.format]
# クォートスタイルやインデント設定（Black互換の既定値）
quote-style = "double"
indent-style = "space"
skip-magic-trailing-comma = false
line-ending = "auto"
```

この設定では、まず `[tool.ruff]` のトップレベルでPythonバージョンや行長といった共通仕様を定義しています。続く `[tool.ruff.lint]` でFlake8やisort相当のチェックを有効にし、旧環境で使っていた `flake8-bugbear`（`B`）やモダンな構文への書き換えを促す `pyupgrade`（`UP`）も標準機能として取り込んでいます。外部プラグインをpipで追加しなくても、ルールコードを指定するだけで同等の検査が走る仕組みです。

最後に `[tool.ruff.format]` を定義することで、`ruff format` の挙動をBlackの規約と揃えています。注意点として、フォーマッタを併用する場合は `E501`（行長超過）などのレイアウト系ルールをLint側で無視しておくと、フォーマッタが改行できない長いURLやコメントで無用な警告が出なくなります。チームで最初にこの雛形を共有しておけば、環境構築の認識ずれを最小限に抑えられます。

## Flake8・isort・Blackからのコマンド置き換えと移行ステップ

設定ファイルの記述が終わったら、日常的に叩くコマンドをRuffへ切り替えます。これまで `flake8 .`、`isort --check .`、`black --check .` と3回に分けて実行していた処理は、`ruff check` と `ruff format` の2コマンドへ集約されます。しかも単一バイナリで高速に動作するため、手元での試行錯誤がストレスなく進みます。

移行直後はいきなりファイルを自動上書きせず、差分確認コマンドで影響範囲を見極める手順が安全です。まずは `--diff` オプションを使って、どの箇所が修正対象になるかを確認します。問題がなければ `--fix` や通常のフォーマットコマンドを実行し、動作テストを通したうえでコミットします。

```bash
# 1. Lintとインポート順のチェック（修正は行わない）
ruff check .

# 2. 自動修正で何が書き換わるか事前に差分を確認する
ruff check --diff .

# 3. 安全に自動修正できるLintエラーとインポート順を一括修正
ruff check --fix .

# 4. Black互換フォーマットの事前確認（CI向けチェック）
ruff format --check --diff .

# 5. コードフォーマットの実行
ruff format .
```

Flake8から移行する際は、既存の `.flake8` に記載していた `ignore` や `max-complexity` などの独自設定を忘れずに引き継ぎます。たとえば循環的複雑度をチェックしていた場合は `select` に `C901` を追加し、`[tool.ruff.lint.mccabe]` で上限値を設定します。同様にisortで `force-single-line` や `profile = "black"` を指定していた場合は、`[tool.ruff.lint.isort]` 内の対応オプションへ移し替えます。

<figure class="photo photo--right">
<a href="https://commons.wikimedia.org/wiki/File:Visual_Studio_Code_1.18.1_on_Windows10.jpg" target="_blank" rel="noopener"><img src="/images/ruff-migration/img2.jpg" alt="Visual Studio Codeを用いた開発環境の画面例" width="220" height="150" loading="lazy"></a>
<figcaption>エディタ拡張やコマンドラインと組み合わせることで即座にフィードバックを得られます<span class="credit">Photo: Visual Studio Code: Microsoft / MIT</span></figcaption>
</figure>

従来のツールが本当に不要になったことを確認できたら、`pyproject.toml` や `requirements-dev.txt` からBlack・Flake8・isortおよび関連プラグインを削除します。同時に `.flake8` や `.isort.cfg` といった古い設定ファイルもリポジトリから取り除いておきましょう。古い設定を残したままだと、新しく参加したメンバーがどちらのルールが正なのか迷う原因になります。

## pre-commitフックとGitHub Actionsへの組み込み

ローカル環境でのコマンド置き換えが完了したら、コミット時とプルリクエスト時の自動チェックもRuffへ統合します。pre-commitを導入しているリポジトリであれば、公式が提供している `astral-sh/ruff-pre-commit` を使うのが最も手軽です。これまで3つのリポジトリを個別に参照していたフック定義が、1つのリポジトリ参照だけで完結します。

`.pre-commit-config.yaml` に設定を記述する際は、フックの実行順序に気を配る必要があります。基本的にはLintと自動修正を行う `ruff` フックを先に走らせ、その後にフォーマットを行う `ruff-format` フックを実行する並びが推奨されます。インポート順の整理や不要コードの削除によって行構造が変わった後に、最終的な整形を掛けるためです。

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    # 公式リポジトリ（https://github.com/astral-sh/ruff-pre-commit）の最新リリースを指定
    rev: v0.x.x
    hooks:
      # Linterの実行（自動修正を許可する場合）
      - id: ruff
        args: [ --fix ]
      # Formatterの実行
      - id: ruff-format
```

`rev` には固定のタグバージョンを指定し、定期的にアップデートする運用にしておくと再現性が保てます。また、pre-commitのインストール後に `pre-commit run --all-files` を一度実行しておけば、リポジトリ全体がフックの基準を満たしているか即座に検証可能です。高速なRustバイナリのおかげで、コミットごとの待ち時間もほぼ気にならない水準になります。

さらにGitHub ActionsなどのCIパイプラインにも組み込むことで、ローカルでpre-commitをスキップした変更も確実に検知できます。CI上ではファイルを書き換えるのではなく、チェック失敗時にビルドを落とす構成にするのが基本です。以下のように `ruff check` と `ruff format --check` を並べて実行すれば、Lint違反とフォーマット崩れの両方を単一ジョブで高速に検証できます。

```yaml
name: Lint and Format

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  ruff:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install Ruff
        run: pip install ruff
      - name: Run Ruff linter
        run: ruff check --output-format=github .
      - name: Run Ruff formatter check
        run: ruff format --check .
```

GitHub Actions向けの出力オプションである `--output-format=github` を指定しておくと、プルリクエストの画面上で該当行に直接アノテーションが表示されます。CIの実行時間が短縮されるだけでなく、コードレビュー時に指摘箇所をピンポイントで把握できる点も実務上の大きなメリットです。

## 移行時によくある失敗と回避策

Ruffへの移行自体はシンプルですが、既存の大きなコードベースへ一気に適用すると予期せぬ摩擦が起きることがあります。代表的な失敗の1つが、リポジトリ全体にフォーマットや大規模な自動修正を一度に適用してしまい、Gitの履歴（`git blame`）が整形コミットで埋め尽くされるケースです。過去の変更意図を追いたいときにノイズが増えると、保守作業の効率が落ちてしまいます。

この問題を避けるには、整形専用のコミットを機能開発のコミットから明確に分離し、そのコミットハッシュを `.git-blame-ignore-revs` ファイルへ記録しておく方法が有効です。Gitの設定でこのファイルを指定しておけば、整形だけの変更を無視して本来のコード修正履歴を追跡できます。大規模リポジトリほど、最初の1手として履歴への配慮を組み込んでおく価値があります。

もう1つのよくある失敗は、最初から厳格すぎるルールセットを一気に有効化して大量のLintエラーを抱え込んでしまうパターンです。特に `select = ["ALL"]` のような設定を既存プロジェクトへ適用すると、数百件以上の警告が出て手が止まりがちです。まずは従来のFlake8相当の基本ルール（`E`、`F`、`I` など）から始め、チームで合意が取れたルールを段階的に追加する方が無理なく定着します。

どうしても既存コードの修正を後回しにしたい場合は、`--add-noqa` ではなく `per-file-ignores` を活用してディレクトリ単位で一時的に除外する方法が整理しやすいです。また、フォーマッタと競合しやすい空白や引用符、インデント関連のLintルールを `ignore` に逃がしておくことも忘れないようにしましょう。公式ドキュメントで非推奨またはフォーマッタと競合すると案内されているルールを事前に外しておけば、ツール間の食い違いによる手戻りを防げます。

## どんなプロジェクトに向くか・運用を続けるほど効いてくる点

Ruffへの移行は小規模なスクリプトから巨大なWebアプリケーションまで幅広く有効ですが、特に恩恵が大きいのはファイル数や開発メンバーが多いプロジェクトです。モノレポ構成やマイクロサービス群を1つのリポジトリで管理している場合、従来のPython製ツールではCIのLint工程だけで数分かかることも珍しくありません。Ruffへ切り替えることでチェック時間が数秒単位まで縮まれば、開発者の集中力を途切れさせずにフィードバックを返せます。

新規に立ち上げるプロジェクトにとっても、最初からRuffを選んでおく利点は明確です。開発環境のセットアップ手順書に「BlackとFlake8とisortをそれぞれ設定する」工程を書く必要がなくなり、`pyproject.toml` の一角を説明するだけで済みます。オンボーディングの負荷が下がるため、Pythonに不慣れなメンバーが参加するチームでも品質基準を保ちやすくなります。

運用を長く続けるほど効いてくるのは、依存関係のメンテナンスコストが劇的に軽くなる点です。従来はPythonのメジャーバージョンが上がるたびに、Flake8本体と各プラグインの互換性を確認しながらアップデートする必要がありました。単一バイナリのRuffであれば依存ライブラリの衝突に悩まされる場面が減り、ツールのバージョン更新を計画的に進められます。

また、ルール追加のハードルが下がることも長期的な資産になります。たとえば新しいPythonバージョンの構文へ移行したいとき、設定ファイルに `UP` ルールを加えて `target-version` を更新するだけで、古い書き方を安全に検出して書き換え候補を提示してくれます。導入時の移行コスト以上に、日々の開発サイクル全体が軽く回り続ける点がRuff最大の価値と言えます。

なお、導入にあたっては既存のCI時間やルール競合への懸念があるかもしれませんが、Ruffは単一バイナリかつ無料（MITライセンス）のツールであり、既存ファイルと並行テストしながら段階的に適用できるため、運用上の維持負担や切り戻しリスクを最小限に抑えて移行できます。

## まとめ

Black・Flake8・isortという3つのツールに分かれていたPythonのコード品質管理は、Ruffの登場によって1本化できる時代になりました。Rust製の高速な実行エンジンにより、従来のPythonリンターと比較して10倍から100倍の速度を実現しつつ、`pyproject.toml` へ設定を集約できるメリットは極めて大きいです。

移行を成功させるポイントは、いきなり全ルールを厳格化するのではなく、現状のルールを棚卸ししたうえで `ruff check --diff` や `ruff format --check --diff` で影響を確認しながら進めることです。さらに `astral-sh/ruff-pre-commit` とGitHub Actionsを組み合わせれば、ローカルからCIまで一貫したチェック体制を短時間で構築できます。

まずは開発中のプロジェクトの `pyproject.toml` にRuffの設定を追加し、手元で `ruff check` と `ruff format` を試すところから始めてみてください。最新のルール一覧やオプションの詳細は、[Ruff公式ドキュメント](https://docs.astral.sh/ruff/)および[GitHubリポジトリ](https://github.com/astral-sh/ruff)で確認できます。


## 関連記事・おすすめメディア
- [はてなブログ版（最新コラム）はこちら](https://kinbro.hatenablog.com/)
- [Amebaブログ版（ドリンク・酒の科学とレシピ）はこちら](https://blog.ameba.jp/)
- [note版（厳選ノウハウ・裏側）はこちら](https://note.com/shining_finger01/n/XXXX)

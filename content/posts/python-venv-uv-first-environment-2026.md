---
title: "Pythonの仮想環境、venvとuvの違いは「箱」と「記録」の分担にある"
description: "Pythonで最初に迷う仮想環境を、標準のvenvとAstralのuvで比較する。作り方と有効化、pipとの関係、Python本体の扱い、uv.lockとrequirements.txtの違いを整理し、最初の1本の選び方を示す。"
images: ["/images/og/python-venv-uv-first-environment-2026.jpg"]
ogImageWidth: 1200
ogImageHeight: 630
date: 2026-10-25T12:00:00+09:00
scheduled_time: "12:00"
categories: ["dev"]
tags: ["Python", "uv", "venv", "仮想環境", "pip", "パッケージ管理"]
draft: false
---

Python を書き始めてしばらくすると、どこかで「仮想環境を作りましょう」という一文に出会う。入門書の多くは標準の `venv` を使う手順を載せていて、ここ数年の解説記事やプロジェクトの README には `uv` という名前もよく出てくる。どちらも「仮想環境を作る」ための道具として紹介されるので、最初のうちは何が違うのか分かりにくい。

私自身、両方を使い分けるようになってから気づいたのは、この二つは同じ仕事を奪い合っているのではなく、受け持つ範囲の広さが違うということだった。venv は「部品を入れる箱」を作るところまでを担当し、uv は箱を作ったうえで「何をどの版で入れたか」の記録や、Python 本体の用意まで引き受ける。この記事では、そもそも仮想環境が何を解決しているのかを確かめたうえで、venv と uv の作り方、記録の残し方、速さの理由を順に見ていき、最初の1本をどちらで作るかの目安を示したい。

## 仮想環境は、プロジェクトごとに部品の置き場を分ける仕組み

<figure class="photo photo--left">
<a href="https://docs.python.org/ja/3/library/venv.html" target="_blank" rel="noopener"><img src="/images/py-venv-uv/python-code.jpg" alt="Visual Studio Code の画面に Python の自由落下シミュレーションのコードが表示され、右側にグラフのウィンドウが開いている。下端のステータスバーには使用中の Python の版が出ている" width="220" height="124" loading="lazy"></a>
<figcaption>エディターの下端には、そのファイルを動かしている Python の版が表示される。仮想環境を作ると、ここで選ぶ相手が増える<span class="credit">Photo: MikeRun / <a href="https://commons.wikimedia.org/wiki/File:Screen-python-code-matplotlib-physics-simulation.jpg" target="_blank" rel="noopener">CC BY-SA 4.0</a></span></figcaption>
</figure>

Python で何かを作るときは、表計算のデータを扱う部品やグラフを描く部品のように、ほかの人が公開しているパッケージを取り込んで使うことが多い。これらは `pip install` で入れるのが基本だが、何も考えずに入れると、パソコンに入っている Python 本体の置き場にすべてが積み上がっていく。

困るのは、プロジェクトが二つ、三つと増えたときだ。古いプロジェクトでは部品の版1を前提に書いたのに、新しいプロジェクトのために版2へ上げた途端、古いほうが動かなくなる。版を戻せば今度は新しいほうが壊れる。どちらのプロジェクトがどの部品を必要としていたのかも、時間がたつと分からなくなる。

仮想環境は、この置き場をプロジェクトごとに分ける仕組みだ。プロジェクトのフォルダーの中に `.venv` という専用の置き場を作り、そこに Python の実行ファイルへの参照と、部品を入れる `site-packages` というフォルダーを用意する。その環境を使っているあいだは、`pip install` した部品が `.venv` の中だけに入り、ほかのプロジェクトには影響しない。不要になったら、`.venv` のフォルダーを丸ごと消せば元どおりになる。

要するに、仮想環境の本体はただのフォルダーで、特別な仮想マシンのようなものではない。この点を押さえておくと、venv と uv の違いも見通しやすくなる。

## venvは標準の道具で、箱を作るところまでを担当する

venv は Python 3.3 から標準で付いてくる仕組みで、追加で何かを入れなくても使える。作り方は、プロジェクトのフォルダーで次の1行を実行するだけだ。

```bash
python -m venv .venv
```

これで `.venv` フォルダーができる。中には環境の設定を書いた `pyvenv.cfg` と、実行ファイルを置く場所(Windows では `Scripts`、macOS と Linux では `bin`)、部品を入れる `site-packages` が並ぶ。Python 3.4 以降は、作った時点で pip も環境の中に入っている。

作っただけではまだ使われないので、次に「有効化」をする。

```bash
# Windows(PowerShell)
.venv\Scripts\Activate.ps1

# Windows(コマンドプロンプト)
.venv\Scripts\activate.bat

# macOS / Linux
source .venv/bin/activate
```

有効化するとプロンプトの先頭に `(.venv)` と表示され、その端末で打つ `python` や `pip` が `.venv` の中のものに切り替わる。この状態で `pip install` すれば、部品は箱の中に入る。作業を終えるときは `deactivate` で元に戻す。Windows の PowerShell では、スクリプトの実行が許可されていないと有効化の段階で止まることがあり、最初につまずきやすいのはここだと思う。

venv の受け持ちは、ここまでだ。どの版の Python で箱を作るかは、`python` を打ったときに呼ばれる本体で決まる。3.12 で作りたいのに手元には 3.13 しかない、という場合、venv は Python 本体を用意してはくれない。別の方法で 3.12 を入れてから、そちらの `python` で `-m venv` を実行する必要がある。

また、何をどの版で入れたかの記録も、venv 自身は残さない。慣習として `pip freeze > requirements.txt` で、いま箱に入っている部品と版の一覧をテキストに書き出し、別のパソコンでは `pip install -r requirements.txt` で同じ部品を入れ直す。この書き出しを忘れると、箱の中身を再現する手がかりがなくなる。箱は作れても、その中身の記録は自分の手作業に任される、というのが venv の性格だ。

## uvは、箱と記録とPython本体をまとめて引き受ける

<figure class="photo photo--right">
<a href="https://docs.astral.sh/uv/" target="_blank" rel="noopener"><img src="/images/py-venv-uv/rust-code.jpg" alt="黒い背景の画面に、紫・緑・黄・水色で色分けされた Rust のソースコードが大きく映っている" width="220" height="208" loading="lazy"></a>
<figcaption>uv は Python ではなく Rust で書かれている。部品の依存関係を解く計算の速さは、ここから来ている<span class="credit">Photo: Slashme / <a href="https://commons.wikimedia.org/wiki/File:RustCodeOnScreen.jpg" target="_blank" rel="noopener">CC0</a></span></figcaption>
</figure>

uv は、コードの整形・検査ツール Ruff で知られる Astral が開発しているパッケージとプロジェクトの管理ツールだ。ソースコードは公開されていて、MIT ライセンスと Apache 2.0 ライセンスのどちらでも使える。Python 自体ではなく Rust という言語で書かれていて、pip、pip-tools、pipx、Poetry、pyenv、virtualenv といった、これまで別々に使っていた道具の役割を一つにまとめることを目指している。

Python の外の道具なので、最初に uv そのものを入れる。公式のインストーラーは、Windows なら PowerShell、macOS や Linux なら `curl` を使う1行のコマンドで、ほかに pip や Homebrew、winget からも入れられる。

プロジェクトを始めるときは `uv init` を使う。

```bash
uv init my-tool
cd my-tool
uv add requests
uv run main.py
```

`uv init` は、プロジェクトの設定を書く `pyproject.toml`、使う Python の版を書く `.python-version`、ひな形の `main.py` などを用意する。ここで少し意外なのは、`.venv` と `uv.lock` は `uv init` の時点ではまだ作られないことだ。最初に `uv add`、`uv run`、`uv sync` のようなプロジェクト向けのコマンドを実行したときに、仮想環境とロックファイルが自動で作られる。

`uv add requests` は、部品を箱に入れるだけでなく、`pyproject.toml` の依存関係の欄に `requests` を書き足し、解決した版を `uv.lock` に記録する。venv で手作業だった「何を入れたかの記録」が、部品を入れる操作と同時に済む。

もう一つ大きいのが `uv run` で、有効化をしなくても、プロジェクトの仮想環境でスクリプトを実行できる。しかも実行の前に、環境が `pyproject.toml` と `uv.lock` の内容と合っているかを確かめ、足りない部品があれば入れてから動かす。PowerShell の実行許可でつまずく心配もない。

Python 本体の用意も uv の受け持ちに入る。`uv python install 3.12` と打てば、uv がその版の Python を取ってきて管理してくれる。`.python-version` に書かれた版が手元に無ければ、`uv run` のときに自動で用意されることもある。venv では別の道具が必要だった部分を、uv は自分で済ませてしまう。

## 記録の違いは、requirements.txtとuv.lockに出る

二つの道具の差がいちばんはっきり出るのは、別のパソコンや半年後の自分が、同じ環境を作り直すときだと思う。

`pip freeze` で書き出す requirements.txt は、その時点で箱に入っていた部品と版を一行ずつ並べたものだ。分かりやすく、ほとんどの道具が読めるのが利点だが、自分で入れた部品と、それに引きずられて入った部品の区別がつかない。また、書き出したパソコンの OS や Python の版で解決した結果なので、Windows で作った一覧が Linux でもそのまま通るとは限らない。そして何より、書き出しを忘れれば記録は古いまま残る。

uv.lock は、uv が部品を入れるたびに自動で更新するロックファイルで、部品ごとの版に加えて、ダウンロードしたファイルが本物かどうかを確かめるためのハッシュ値まで記録する。特徴は、OS や Python の版の違いをまとめて解いた「どこでも通用する」記録になっている点だ。Windows で作った uv.lock を Linux に持っていっても、`uv sync` を打てば同じ組み合わせの部品が入る。自分で指定した部品は `pyproject.toml` に、実際に入った部品の全体は `uv.lock` に、と役割が分かれているので、後から読み返したときに「なぜこの部品が入っているのか」も追いやすい。

uv.lock は uv のための形式だが、外へ出す手段もある。`uv export --format requirements.txt` で従来の requirements.txt を書き出せるので、pip しか使えない環境にも渡せる。さらに、Python のロックファイルの標準形式として 2025年に PEP 751 で決まった `pylock.toml` にも、`uv export --format pylock.toml` で書き出せる。uv を使い始めたら他の道具と行き来できなくなる、という心配はしなくてよいと思う。

## 速さの理由と、知っておきたい注意点

<figure class="photo photo--left">
<a href="https://docs.astral.sh/uv/concepts/cache/" target="_blank" rel="noopener"><img src="/images/py-venv-uv/programmer.jpg" alt="木のテーブルの上に置いたノートパソコンに向かい、腕時計をした人が両手でキーボードを打っている。画面にはエディターのコードが映っている" width="220" height="159" loading="lazy"></a>
<figcaption>部品を入れる待ち時間が短くなると、試しに環境を作っては消す、という動き方がしやすくなる<span class="credit">Photo: Crew crew / <a href="https://commons.wikimedia.org/wiki/File:Programmer_at_work_(Unsplash).jpg" target="_blank" rel="noopener">CC0</a></span></figcaption>
</figure>

uv の紹介で必ず出てくるのが速さで、Astral は pip より10倍から100倍速いとうたっている。この数字は、一度ダウンロードした部品が手元に残っている状態での比較なので、初めて入れる部品ばかりのときにそこまで差が開くわけではない。ただ、普段使いで速さを感じる場面は確かに多い。

理由は大きく二つある。一つは、依存関係の解決やダウンロードを Rust で並列に処理していること。もう一つは、部品をパソコン全体で共有するキャッシュに一度だけ保存し、各プロジェクトの `.venv` へはハードリンクやコピーオンライトという仕組みで、ファイルを複製せずに置いていくことだ。同じ部品を使うプロジェクトがいくつあっても、ディスク上の実体は一つで済む。仮想環境を作るたびに数百MBの部品を入れ直していた頃と比べると、作って消すことへのためらいがかなり減った。

一方で、uv を使うときに知っておきたい点もある。まず、`uv venv` で作った仮想環境には、標準では pip が入っていない。uv では `uv pip install` のように uv 側のコマンドで部品を入れる前提なので、箱の中で `pip` を直接打つと「見つからない」と言われる。どうしても pip を入れておきたいときは、作成時に `--seed` を付ける。

次に、uv は標準ライブラリではなく、一つの会社が開発している外部の道具だという点だ。オープンソースで、作った `.venv` 自体はふつうの仮想環境と同じ構造なので、uv を外しても箱の中身はそのまま使えるし、requirements.txt や pylock.toml への書き出しもできる。それでも、職場や学校のパソコンで外部の道具を入れられない場合は、標準の venv しか選べないこともある。

最後に、更新の速さだ。uv は今も活発に開発が続いていて、版が頻繁に上がる。新しい機能が早く届く反面、古い解説記事のコマンドが今の uv と少し違う、ということも起こりうる。手順に迷ったら、まず公式のドキュメントを見るのが確実だと思う。

## 最初の1本をどちらで作るか

ここまでを踏まえて、私なりの目安をまとめておく。

**venv から始めるとよい人**は、Python の仕組みそのものを理解したい人、入門書や授業の手順どおりに進めたい人、外部の道具を入れられない環境にいる人だ。`python -m venv .venv` で箱を作り、有効化して `pip install` し、`pip freeze` で記録を残す、という一連の流れを一度自分の手で通すと、仮想環境が「ただのフォルダー」だということが体感として分かる。この理解は、後で uv に移ったときにも役に立つ。

**uv から始めるとよい人**は、すでに何本かスクリプトを書いていて、プロジェクトが増えてきた人、Python の版を使い分ける必要がある人、別のパソコンやサーバーで同じ環境を作り直す場面がある人だ。`uv init` と `uv add` と `uv run` の三つを覚えるだけで、箱と記録と Python 本体の管理がそろう。有効化を忘れて全体の置き場に部品を入れてしまう、という事故も起きにくい。

どちらを選んでも、作られる `.venv` の中身は同じ考え方でできている。違うのは、その周りの「記録」と「準備」を自分でやるか、道具に任せるかだ。私自身は、使い捨ての小さな検証なら今でも venv で済ませることがあり、何週間も手を入れ続けるものや、自動で動かす仕組みに載せるものは uv で始めている。後者のように別の機械で動かす場面については、[GitHub Actionsの最初の1本は、pushで動かすか時刻で動かすかを決めるところから](/posts/github-actions-schedule-push-guide-2026/)でも触れた。

まずは手元のどこかに練習用のフォルダーを一つ作り、片方の道具で箱を作って、部品を一つだけ入れてみてほしい。`.venv` の中をのぞいて、入れた部品がどこに置かれたかを確かめると、仮想環境という言葉が急に具体的に見えてくるはずだ。

## 関連記事
- [VS CodeのDev ContainersでPCを汚さない開発環境を作る、devcontainer.jsonは4行から](/posts/vscode-dev-containers-docker-guide-2026/)(仮想環境をさらにコンテナごと分けたいときに)
- [画像の知覚ハッシュをPythonで比べた記録、縮小では動かず左右反転で30ビット変わる](/posts/python-perceptual-hash-image-compare/)(Python で小さな検証スクリプトを書いた例)
- [GitHub Pages で技術・理論記事を読む](https://kingsworksub-jpg.github.io/)
- [Amebaブログ版はこちら](https://ameblo.jp/sfd0501/)
- 今夜はウイスキー・カルチャーの記事やジャズ・映画のエッセイも公開予定です → [note はこちら](https://note.com/shining_finger01)

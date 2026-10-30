---
title: "VS CodeのDev ContainersでPCを汚さない開発環境を作る、devcontainer.jsonは4行から"
description: "VS CodeのDev Containersで、言語やツールをPCに入れずに開発環境を作る手順を整理する。Dockerと拡張機能の用意、4行のdevcontainer.json、featuresでの道具の追加、Windowsの注意点まで。"
images: ["/images/og/vscode-dev-containers-docker-guide-2026.jpg"]
ogImageWidth: 1200
ogImageHeight: 630
date: 2026-10-26T20:00:00+09:00
scheduled_time: "20:00"
categories: ["dev"]
tags: ["VS Code", "Dev Containers", "Docker", "開発環境", "WSL2", "devcontainer.json"]
draft: false
---

新しい言語を触ってみようとするたびに、パソコンに何かが積み上がっていく。Python の版をもう一つ、Node.js をもう一つ、ついでにデータベースのクライアントも。数か月たつと、どれが何のために入れたものか分からなくなり、消してよいのかどうかも判断できなくなる。私の作業用パソコンも、しばらくそういう状態が続いていた。

VS Code の Dev Containers は、この積み上げを手元のパソコンではなく Docker のコンテナの中で起こすための仕組みだ。言語の処理系やコマンドはコンテナに入れ、エディターの見た目や操作はいつもの VS Code のまま使う。要らなくなったらコンテナごと捨てればよく、パソコン本体には何も残らない。設定は `devcontainer.json` という1枚のファイルに書かれるので、別のパソコンでも同じ環境を作り直せる。

この記事では、Dev Containers が何をどこに置く仕組みなのかを確かめたうえで、最小の4行の設定ファイルから動かし、道具を少しずつ書き足していく順番を追っていく。最後に、Windows で使うときにつまずきやすい点もまとめておく。

## Dev Containersは、エディターの中身だけをコンテナへ移す

<figure class="photo photo--left">
<a href="https://code.visualstudio.com/docs/devcontainers/containers" target="_blank" rel="noopener"><img src="/images/devcontainers/vscode.jpg" alt="Ubuntu のデスクトップで Visual Studio Code が2つのウィンドウで開かれ、奥には C++ のソースコード、手前には起動直後のようこそ画面が表示されている" width="220" height="122" loading="lazy"></a>
<figcaption>画面に見えているのはいつもの VS Code だが、Dev Containers では言語の処理系や拡張機能の多くがコンテナの側で動く<span class="credit">Photo: Pota12 / <a href="https://commons.wikimedia.org/wiki/File:VS_code2013_v1.60.1.png" target="_blank" rel="noopener">CC BY-SA 4.0</a></span></figcaption>
</figure>

最初に押さえておきたいのは、VS Code が二つに分かれて動くという点だ。ウィンドウやメニュー、配色のテーマといった画面まわりは手元のパソコンで動く。一方、コンテナの中には「VS Code Server」と呼ばれる小さな本体が自動で入り、ファイルの読み書き、ターミナル、言語の補完やデバッガーといった拡張機能は、そちらの側で動く。最初にコンテナへつないだとき、この VS Code Server が手元からコンテナに送り込まれる。

この分け方のおかげで、拡張機能はコンテナに入っている処理系やコマンドをそのまま使える。Python の拡張機能はコンテナの中の Python を見に行き、ターミナルを開けばコンテナの中のシェルが立ち上がる。手元のパソコンに Python が入っていなくても、補完もデバッグも普段どおりに動く。ただし、配色のテーマやキー割り当てのように画面にしか関わらない拡張機能は、手元の側で動く。

作業中のファイルそのものは、標準では手元のフォルダーがコンテナの中に「バインドマウント」という形で見えるようになっている。コンテナの中では `/workspaces/フォルダー名` という場所に現れ、そこで編集した内容は手元のフォルダーにそのまま反映される。つまり、コードは手元に残り、それを動かす道具だけがコンテナに入る。コンテナを消してもソースコードは消えない、というのがこの仕組みの安心できるところだと思う。

## 用意するのはDockerと拡張機能が1つずつ

コンテナを動かす土台として、Docker が必要になる。Windows と macOS では Docker Desktop を入れるのがいちばん手早く、Windows では WSL2 を使う設定にしておくのが基本だ。Linux なら Docker Engine をそのまま使える。Docker Desktop は個人での利用や学習、従業員250人未満かつ年間売上1,000万ドル未満の小規模な事業であれば無料で使える。それを超える会社で使う場合は有料の契約が必要になるので、職場のパソコンで試すときは一度確かめておきたい。Docker Desktop の代わりに Podman や Rancher Desktop を土台にする方法もある。

次に、VS Code に拡張機能「Dev Containers」(識別子は `ms-vscode-remote.remote-containers`)を入れる。Microsoft が出している公式の拡張機能で、拡張機能の画面で検索すればすぐに見つかる。入れると、ウィンドウの左下に緑色の小さなボタンが現れる。これは「いまどこにつながっているか」を示す表示で、クリックすると、コンテナで開き直す、手元で開き直す、といった操作の一覧が出てくる。

準備はこれだけだ。Python や Node.js を手元に入れる必要はない。むしろ、ここから先は手元に入れないことが目的になる。

## devcontainer.jsonは4行で動き出す

<figure class="photo photo--right">
<a href="https://docs.docker.com/get-started/" target="_blank" rel="noopener"><img src="/images/devcontainers/docker-start.jpg" alt="黒いターミナルに docker run コマンドが入力され、ポートの指定や作業フォルダーの割り当てのあと、コンテナの中でサービスが起動していくログが流れている" width="220" height="87" loading="lazy"></a>
<figcaption>コマンドで直接コンテナを起動すると、ポートやフォルダーの指定を毎回打つことになる。Dev Containers はそれを設定ファイルに書いておく<span class="credit">Photo: Alexandru.munteanu98 / <a href="https://commons.wikimedia.org/wiki/File:Starting_the_Docker_container..png" target="_blank" rel="noopener">CC BY-SA 4.0</a></span></figcaption>
</figure>

設定ファイルは、プロジェクトのフォルダーの中に `.devcontainer` というフォルダーを作り、そこに `devcontainer.json` という名前で置く。フォルダーを作らずに、プロジェクトの直下へ `.devcontainer.json` として置くこともできる。Python を試す練習用のフォルダーなら、中身は次の4行で足りる。

```json
{
  "name": "python-practice",
  "image": "mcr.microsoft.com/devcontainers/python:1-3.12-bookworm"
}
```

`name` はウィンドウの左下などに出る表示名で、自由に付けてよい。大事なのは `image` のほうで、どのコンテナイメージを土台にするかをここで決める。`mcr.microsoft.com/devcontainers/` で始まるイメージは Dev Containers 向けに用意された公式のもので、Python のほかに Node.js、Go、Java、Rust、C++ などがそろっている。末尾の `1-3.12-bookworm` は、イメージ自体の版、Python の版、土台になる Debian の版の名前を順に並べたものだ。これらのイメージには `vscode` という一般ユーザーがあらかじめ作られていて、管理者の権限を持たないまま作業できるようになっている。

ファイルを保存したら、コマンドパレット(Ctrl+Shift+P)から「Dev Containers: Reopen in Container」を選ぶ。左下の緑のボタンから選んでも同じだ。初回はイメージのダウンロードが始まるので、回線によっては数分かかる。待っているあいだに右下の通知から作業の記録を開くと、イメージの取得、コンテナの起動、VS Code Server の送り込みが順に進んでいく様子が見える。

開き直しが終わったら、ターミナルで `python --version` と打ってみてほしい。手元に Python を入れていなくても、3.12 の版が返ってくるはずだ。左下の表示も `name` に書いたコンテナの名前に変わり、いまコンテナの中で作業していることが分かる。手元に戻りたいときは、同じボタンから「Reopen Folder Locally」を選べばよい。

自分で書くのが不安なら、「Dev Containers: Add Dev Container Configuration Files...」を選ぶと、言語や版を一覧から選ぶだけで同じようなファイルを作ってくれる。ただ、最初の1回は4行を自分で書いてみるのがよいと思う。何が最小限なのかが分かると、そのあと自動で作られた長い設定ファイルを読むときに迷わなくなる。

## 道具を足すときはfeaturesとextensionsに書き足す

4行で動いたら、そこから必要なものを少しずつ足していく。よく使うのは次のような形だ。

```json
{
  "name": "python-practice",
  "image": "mcr.microsoft.com/devcontainers/python:1-3.12-bookworm",
  "features": {
    "ghcr.io/devcontainers/features/node:1": {},
    "ghcr.io/devcontainers/features/github-cli:1": {}
  },
  "customizations": {
    "vscode": {
      "extensions": ["ms-python.python"]
    }
  },
  "forwardPorts": [8000],
  "postCreateCommand": "pip install -r requirements.txt"
}
```

`features` は、イメージに後から道具を足すための部品だ。上の例では、Python のイメージに Node.js と GitHub の公式コマンドラインツールを足している。本来ならイメージを自分で作り直さないと入れられないものを、1行書くだけで入れてくれる。公開されている部品は一覧のサイトにまとまっていて、AWS や Kubernetes 向けのコマンド、コンテナの中でさらに Docker を動かすためのものまで用意されている。

`customizations` の中の `extensions` には、コンテナの側に入れておきたい拡張機能の識別子を並べる。ここに書いておけば、別のパソコンで同じ設定を開いたときにも、同じ拡張機能が自動で入る。`forwardPorts` は、コンテナの中で動かしたサーバーの番号を手元に転送する指定で、上の例ならコンテナで 8000 番に立てた開発用のサーバーを、手元のブラウザーから `localhost:8000` で開ける。

`postCreateCommand` は、コンテナを作り終えたあとに1回だけ実行されるコマンドだ。部品の一覧から依存関係を入れる、といった準備をここに書いておくと、開き直すたびに手で打つ必要がなくなる。同じ仲間に、作成時の早い段階で動く `onCreateCommand`、コンテナを起動するたびに動く `postStartCommand`、VS Code がつながるたびに動く `postAttachCommand` もある。順番は作成時の `onCreateCommand`、`updateContentCommand`、`postCreateCommand` の3つが1回ずつ、その後に起動のたびの2つが続く。途中のコマンドが失敗すると後のものは実行されないので、うまく動かないときは作業の記録をさかのぼって、どこで止まったかを確かめるとよい。

一つ注意したいのは、設定ファイルを書き換えても、開いているコンテナにはすぐには反映されないことだ。イメージや features、拡張機能を変えたら、「Dev Containers: Rebuild Container」で作り直す必要がある。保存したのに何も変わらない、というときは、たいていこの作り直しを忘れている。

## イメージで足りなくなったらDockerfileへ、データベースが要るならComposeへ

<figure class="photo photo--left">
<a href="https://containers.dev/" target="_blank" rel="noopener"><img src="/images/devcontainers/containers.jpg" alt="港の岸壁に白い冷凍コンテナが何段にも積み上げられ、手前には川の水面が広がっている" width="220" height="124" loading="lazy"></a>
<figcaption>規格のそろった箱なら、中身が違っても同じように積んで運べる。開発環境のコンテナも、設定ファイルという共通の規格で持ち運ばれる<span class="credit">Photo: AgainErick / <a href="https://commons.wikimedia.org/wiki/File:Shipping_container_stacks_-_Port_of_Rotterdam_-_2014_-_2.jpg" target="_blank" rel="noopener">CC BY-SA 4.0</a></span></figcaption>
</figure>

既製のイメージと features で足りるうちは、`image` の1行で済ませるのがいちばん楽だ。ただ、OS のパッケージをいくつも足したい、社内で使う証明書を入れたい、といった要望が増えてくると、設定ファイルだけでは書き切れなくなる。そのときは `.devcontainer` フォルダーに Dockerfile を置き、`image` の代わりに `"build": { "dockerfile": "Dockerfile" }` と書く。Dockerfile の最初の行で公式の Dev Containers 向けイメージを土台に指定しておけば、`vscode` ユーザーなどの便利な下ごしらえはそのまま引き継げる。Dockerfile の中身は手元で組み立てられ、変えていない部分は前回の結果が使い回されるので、2回目以降の作り直しは速い。

アプリがデータベースやキャッシュのサーバーを必要とする場合は、Docker Compose を使う。`dockerComposeFile` に Compose の設定ファイルを、`service` に VS Code がつなぐ相手のサービス名を、`workspaceFolder` にコンテナの中での作業場所を書く。こうすると、アプリ用のコンテナとデータベース用のコンテナがまとめて立ち上がり、VS Code はアプリ側のコンテナの中に入る。データベースを手元のパソコンに常駐させずに済むのは、この方式のいちばんの利点だと感じている。

どの方式を選んでも、`features` や `extensions`、`postCreateCommand` の書き方は変わらない。最初は `image` で始め、必要になった時点で Dockerfile や Compose に移る、という順番で十分だ。

## Windowsでつまずきやすい3つの点

Windows で Dev Containers を使うと、手順どおりなのに思ったように動かない場面がいくつかある。私が気になったのは次の3つだ。

1つ目は速さだ。プロジェクトを C ドライブのいつものフォルダーに置いたままコンテナで開くと、ファイルの読み書きが Windows と Linux のあいだの共有を通るため、部品のインストールやファイルの変更の監視が目に見えて遅くなる。対策は二つあり、一つは WSL2 の中(Linux 側のホームフォルダー)にリポジトリを置いて、そこから開くこと。もう一つは「Dev Containers: Clone Repository in Container Volume...」を使い、リポジトリを Docker のボリュームという専用の置き場に直接取り込むことだ。後者は手元のフォルダーにファイルが見えなくなる代わりに、速さの面ではいちばん有利になる。

2つ目は改行コードだ。Windows で取り出したファイルは改行が CRLF になっていることがあり、そのままコンテナで実行するとシェルスクリプトの1行目が正しく読めず、「そんなインタープリターは無い」という意味のエラーで止まる。リポジトリの直下に `.gitattributes` を置き、`* text=auto eol=lf` と1行書いておけば、改行が LF にそろう。すでに取り出したファイルは、設定のあとに取り出し直す必要がある。

3つ目は Git の認証だ。Dev Containers は手元の `.gitconfig` を自動でコンテナにコピーし、手元で設定してある認証情報の保存の仕組みもコンテナから使えるようにしてくれる。SSH の鍵についても、手元で鍵を預かっている常駐プログラム(`ssh-agent`)にコンテナの側から問い合わせる形で使えるので、鍵のファイルそのものをコンテナへ写す必要はない。ただし、手元でその常駐プログラムが動いていて、鍵が登録されていることが前提になる。Windows ではこのサービスが標準で止まっていることがあるので、コンテナの中で `git push` が鍵を見つけられないときは、まず手元でサービスを起動し、`ssh-add` で鍵を登録しておくとよい。

## 同じ設定ファイルが、手元の外でも使える

`devcontainer.json` は VS Code だけのものではなく、「Development Container Specification」という公開された仕様に沿って書かれている。そのため、同じファイルが GitHub Codespaces でもそのまま読まれる。手元のパソコンで作った開発環境を、ブラウザーから開くクラウド上の環境で同じように立ち上げられるということだ。

コマンドラインから使える「Dev Container CLI」もあり、`npm install -g @devcontainers/cli` で入れたあと、`devcontainer up --workspace-folder .` と打てば、VS Code を開かずに同じコンテナを立ち上げられる。自動テストの仕組みの中で、開発者と同じ環境を使って試験を動かす、といった使い方ができる。

ここまでを振り返ると、Dev Containers で覚えることは意外と少ない。4行の設定ファイルでコンテナを開き、足りないものを features と extensions に書き足し、変えたら作り直す。この3つが手に馴染めば、新しい言語を試すたびにパソコンへ何かを積み上げる必要はなくなる。試し終わったら、左下のボタンから手元に戻り、コンテナを消すだけだ。

Python の仮想環境はプロジェクトごとに部品の置き場を分ける仕組みだったが、Dev Containers はそれをもう一段広げて、処理系や OS の道具まで含めて箱に入れる仕組みだと言える。両者の違いは[Pythonの仮想環境、venvとuvの違いは「箱」と「記録」の分担にある](/posts/python-venv-uv-first-environment-2026/)で触れた話の延長として読むと分かりやすいと思う。まずは練習用のフォルダーを一つ作り、4行の `devcontainer.json` を置いて、コンテナで開き直すところから始めてみてほしい。

## 関連記事
- [GitHub CLIでプルリクエストを出す朝、CIを待つ昼、マージする夕方。ghだけで回す一日](/posts/gh-cli-pull-request-terminal-guide-2026/)(コンテナ内でもghで作業を完結させたいときに)
- [GitHub Actionsの最初の1本は、pushで動かすか時刻で動かすかを決めるところから](/posts/github-actions-schedule-push-guide-2026/)(同じ環境を別の機械で動かす話)
- [GitHub Pages で技術・理論記事を読む](https://kingsworksub-jpg.github.io/)
- [Amebaブログ版はこちら](https://ameblo.jp/sfd0501/)
- 今夜はウイスキー・カルチャーの記事やジャズ・映画のエッセイも公開予定です → [note はこちら](https://note.com/shining_finger01)

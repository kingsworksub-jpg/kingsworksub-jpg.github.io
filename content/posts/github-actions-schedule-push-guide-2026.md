---
title: "GitHub Actionsの最初の1本は、pushで動かすか時刻で動かすかを決めるところから"
description: "GitHub Actionsで定型作業を自動化するとき、最初に決めるのはpush起点か定時実行か。両者の違い、cronのタイムゾーン指定や遅延・60日停止の注意、手動実行と権限の書き方、最初のワークフローを置くまでを順に整理した。"
images: ["/images/og/github-actions-schedule-push-guide-2026.jpg"]
ogImageWidth: 1200
ogImageHeight: 630
date: 2026-10-24T07:30:00+09:00
scheduled_time: "07:30"
categories: ["tech"]
tags: ["GitHub Actions", "GitHub", "自動化", "cron", "CI/CD", "YAML"]
draft: false
---

毎週同じ手順でファイルを集計する、記事を書いたらサイトを作り直して公開する、毎朝決まった時刻に外部のデータを取りに行く。こうした定型作業は、一度手順が固まってしまえば、人がやる必要はあまりない。GitHub Actions は、そういう作業を GitHub のリポジトリに置いた設定ファイルひとつで機械に任せられる仕組みだ。

ただ、使い始めの段階でつまずきやすいのは、YAML の書き方よりも「いつ動かすか」の決め方だと思う。GitHub Actions には、コードを push したときに動かす方法と、決まった時刻に動かす方法がある。どちらも同じファイルに書けて見た目はよく似ているのに、動く条件も、どのコードを使うかも、失敗のしかたも違う。ここを混ぜたまま作り始めると、「動くはずの時刻に動かない」「同じ処理が二重に走る」といった、原因の分かりにくい不具合に出会うことになる。

この記事では、push 起点と定時実行の違いをはっきりさせたうえで、手動で動かす方法と権限の書き方を加え、最初のワークフローを1本置くところまでを順に見ていく。

## GitHub Actionsは、リポジトリに置く「段取り表」

<figure class="photo photo--left">
<a href="https://docs.github.com/ja/actions" target="_blank" rel="noopener"><img src="/images/gh-actions/programmer.jpg" alt="机の上のデスクトップパソコンに向かい、エディターに書かれたコードを見ながらキーボードを打つ人" width="220" height="147" loading="lazy"></a>
<figcaption>手元で何度も繰り返している手順は、そのままワークフローの材料になる<span class="credit">Photo: Joonspoon / <a href="https://commons.wikimedia.org/wiki/File:Programmer_writing_code_with_Unit_Tests.jpg" target="_blank" rel="noopener">CC BY-SA 4.0</a></span></figcaption>
</figure>

GitHub Actions は、2018年10月に GitHub のイベントで発表され、2019年11月に誰でも使える正式版になった。もともとはテストやビルドを自動で回す道具として広まったが、中身は「きっかけが起きたら、用意した機械の上で決めた手順を実行する」という汎用の仕組みなので、開発とは関係の薄い定型作業にもそのまま使える。

設定はリポジトリの `.github/workflows/` というフォルダーに置く YAML ファイルで書き、この1ファイルを「ワークフロー」と呼ぶ。ワークフローの中身は大きく三つに分かれていて、`on` に動き出すきっかけを書き、`jobs` に実行する仕事の単位を書き、各ジョブの `steps` に具体的な手順を上から順に並べる。手順には、自分で書いたコマンドを `run` で実行するものと、ほかの人が用意した部品(アクション)を `uses` で呼び出すものの二種類がある。

ジョブが実際に動くのは、GitHub が用意する使い捨ての仮想マシンの上だ。これを「ランナー」と呼び、`runs-on: ubuntu-latest` のように OS を指定する。ランナーは毎回まっさらな状態で起動し、ジョブが終われば消える。前回の実行で作ったファイルは残らないので、必要なものは毎回リポジトリから取り出し、結果は保存先へ書き出す、という前提で手順を組むことになる。

料金の面では、公開リポジトリなら標準のランナーは無料で使える。非公開リポジトリでも、無料プランで月2,000分までの実行時間が含まれている。1回数十秒で終わる定型作業なら、毎日動かしても枠を使い切ることはまずないと思う。

## push起点は「変わったときだけ」動く

まず push 起点のほうから見ていく。`on: push` と書いたワークフローは、そのリポジトリにコミットが push されるたびに動く。このブログの本家も、記事を書いて main ブランチに push すると、サイトを組み立てて公開するワークフローが走る仕組みになっている。

push 起点のよいところは、作業の結果と実行のきっかけが一対一で結びついている点だ。どのコミットで動いたのかがはっきりしていて、ワークフローは push されたそのコミットの中身を使って実行される。失敗したときも、直前に何を変えたかを見れば原因の見当がつきやすい。

そのままだと、README の誤字を直しただけでも重い処理が走ってしまうので、条件を絞るのが普通だ。

```yaml
on:
  push:
    branches: [main]
    paths:
      - 'content/**'
      - 'static/**'
```

`branches` で対象のブランチを、`paths` で対象のファイルの場所を指定すると、条件に合う変更が含まれる push のときだけ動く。逆に、特定の場所の変更だけを除外したいなら `paths-ignore` を使う。ただし同じきっかけに `paths` と `paths-ignore` を両方書くことはできないので、どちらか一方に寄せて考える。

push 起点でひとつ覚えておきたいのは、ワークフローの中からリポジトリへ push したコミットでは、次のワークフローが動かないという点だ。ワークフローの中で使える標準の認証情報 `GITHUB_TOKEN` で行った push は、無限に連鎖するのを防ぐために、新しい実行のきっかけにならない仕様になっている。「自動で整形して push したら公開のワークフローも走るはず」と期待すると、ここで止まる。続けて動かしたいなら、後で触れる手動実行のきっかけを呼ぶか、一つのワークフローの中で続きの手順まで済ませてしまうほうが分かりやすい。

## 定時実行は「時刻が来たら」動く

<figure class="photo photo--right">
<a href="https://docs.github.com/ja/actions/reference/workflows-and-actions/events-that-trigger-workflows" target="_blank" rel="noopener"><img src="/images/gh-actions/time-clock.jpg" alt="壁に並んだタイムカードの棚の前で、帽子をかぶった年配の男性がタイムレコーダーにカードを差し込んでいる白黒写真" width="220" height="278" loading="lazy"></a>
<figcaption>1921年、74歳の誕生日にタイムレコーダーを押すトーマス・エジソン。決まった時刻に決まった記録を残す仕組みは、今も形を変えて働いている<span class="credit">Photo: Library of Congress / <a href="https://commons.wikimedia.org/wiki/File:Thomas_Alva_Edison,_1847-1931,_punching_time_clock_on_his_74th_birthday_anniversary,_February_11,_1921,_standing,_rear_view_LCCN2005687286.jpg" target="_blank" rel="noopener">Public domain</a></span></figcaption>
</figure>

もう一方の定時実行は、`on: schedule` に cron と呼ばれる書式で時刻を書く。cron は「分 時 日 月 曜日」の五つの欄を空白で区切って並べる書き方で、たとえば `30 6 * * 1-5` なら「月曜から金曜の6時30分」という意味になる。`*` は「どの値でもよい」、`1-5` は範囲、`*/15` のようにスラッシュを使うと間隔を表す。最も短い間隔は5分に1回までだ。

長いあいだ、この時刻は世界標準時(UTC)でしか書けなかった。日本時間の朝7時に動かしたいなら、9時間引いて前日の22時と書く必要があり、曜日までずれるので書き間違いの原因になっていた。現在は cron の横に `timezone` を添えて、地域の名前で時間帯を指定できるようになっている。

```yaml
on:
  schedule:
    - cron: '17 7 * * 1'
      timezone: "Asia/Tokyo"
```

これで「日本時間の毎週月曜7時17分」になる。`timezone` を書かなければ、従来どおり UTC として扱われる。夏時間のある地域を指定した場合、夏時間に切り替わって存在しなくなる時刻の予定は、次の有効な時刻にずらして実行される。日本では関係しないが、海外の時間帯に合わせて動かすときは覚えておくとよい。

定時実行が push 起点と大きく違うのは、どのコードで動くかだ。定時実行は、常に「既定のブランチの最新のコミット」で動く。作業用のブランチで cron の設定を書き換えても、既定のブランチに取り込むまでは何も変わらない。試しに書いた設定がいつまでも動かない、というときは、まずここを疑うとよい。

## 定時実行は、時刻どおりに動くとは限らない

定時実行には、push 起点にはない注意点が三つある。

一つめは遅れだ。GitHub が混み合う時間帯には定時実行が遅れることがあり、特に毎時0分は負荷が高くなる。負荷が十分に高ければ、待ち行列に入った実行が取りやめになることもある。多くの人が「毎時0分」「毎日0時」に予定を入れるので、その瞬間に実行が集中するのだと思う。上の例で7時ちょうどではなく7時17分にしたのはこのためで、分の欄を半端な数にしておくだけで、遅れや取りこぼしに出会う可能性を下げられる。数分の遅れも許されない作業なら、そもそも GitHub Actions の定時実行には向いていないと考えたほうがよい。

二つめは自動停止だ。公開リポジトリでは、60日間リポジトリに何の動きもないと、定時実行のワークフローが自動的に無効になる。放っておいても毎日動いてくれると思っていたら、2か月後にいつの間にか止まっていた、ということが起こりうる。止まったワークフローは、リポジトリの Actions のタブから有効に戻せる。定時実行の結果をリポジトリにコミットする作りなら、そのコミット自体が動きとして数えられるので止まりにくい。

三つめは実行時間の上限だ。GitHub が用意するランナーでは、一つのジョブは最長6時間で打ち切られる。何も書かなければ `timeout-minutes` の既定値も360分なので、処理が固まったまま止まらないと、その間ずっと実行時間を消費し続けることになる。定時実行は人が見ていない時間に動くことが多いので、ふだんの所要時間に余裕を持たせた値を `timeout-minutes` に書いておくと安心だ。

## 手動実行と権限、最初から書いておきたい2つ

push 起点でも定時実行でも、もう一つ加えておくと便利なのが手動実行のきっかけ `workflow_dispatch` だ。これを `on` に足しておくと、Actions のタブに「Run workflow」のボタンが現れ、好きなときに実行できる。定時実行のワークフローを作ったばかりのとき、次の予定時刻まで待たずに動作を確かめられるので、私は最初から必ず書くようにしている。`inputs` を添えれば、実行のたびに対象の日付や件数のような値を渡すこともできる。

もう一つは権限だ。ワークフローの中では `GITHUB_TOKEN` という認証情報が自動で用意され、リポジトリの読み書きに使える。2023年2月以降に作られたリポジトリでは、この権限は既定で読み取りだけになっている。結果をコミットしたいなど、書き込みが必要な作業なら、ワークフローに `permissions` を書いて必要な分だけ広げる。

```yaml
permissions:
  contents: write
```

逆に、読むだけの作業なら `contents: read` と明示しておけば、うっかり書き込む手順を足しても失敗で気づける。外部のサービスに接続するためのパスワードやトークンは、ワークフローに直接書かず、リポジトリの設定画面から「Secrets」に登録して `${{ secrets.名前 }}` の形で読み込む。公開リポジトリに鍵を直書きしてしまう事故は、この一手間でほぼ防げる。

同じワークフローが重なって走るのを避けたいときは `concurrency` を使う。同じグループ名の実行は同時に一つしか動かなくなるので、定時実行と手動実行が重なったときや、push が立て続けに来たときの二重処理を防げる。

## 最初の1本を置く

ここまでの内容をまとめて、毎週月曜の朝にリポジトリ内の Python スクリプトを動かすワークフローを1本書くと、次のようになる。

```yaml
name: weekly-report

on:
  schedule:
    - cron: '17 7 * * 1'
      timezone: "Asia/Tokyo"
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: weekly-report

jobs:
  report:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: '3.13'
      - run: python scripts/report.py
```

<figure class="photo photo--left">
<a href="https://docs.github.com/ja/actions/concepts/runners/github-hosted-runners" target="_blank" rel="noopener"><img src="/images/gh-actions/server-rack.jpg" alt="データセンターの床にしゃがみ、ラックの前に置いたノートパソコンを見ながら配線を確かめる技術者の後ろ姿" width="220" height="146" loading="lazy"></a>
<figcaption>ワークフローが動くランナーも、どこかのデータセンターに並ぶ機械の上で起動しては消えていく<span class="credit">Photo: Derrick Coetzee / <a href="https://commons.wikimedia.org/wiki/File:Technician_with_laptop_working_on_server_rack_at_NERSC.jpg" target="_blank" rel="noopener">CC0</a></span></figcaption>
</figure>

手順の一つめ `actions/checkout` は、ランナーの上にリポジトリの中身を取り出すアクションで、ほぼすべてのワークフローの先頭に置く。まっさらなランナーには何もないので、これを忘れるとスクリプトが見つからずに失敗する。二つめの `actions/setup-python` は、指定した版の Python を用意する。どちらも GitHub が公式に配布しているアクションで、2026年10月時点ではどちらも v7 が最新だ。古い記事の例をそのまま写すと v3 や v4 のような古い版を指定していることがあるので、使う前に各アクションの公開ページで最新の版を確かめておくとよい。

このファイルを `.github/workflows/weekly-report.yml` として既定のブランチに push したら、Actions のタブを開き、左の一覧から weekly-report を選んで「Run workflow」を押す。数十秒でジョブが終わり、各手順の出力がその場で読める。ここで成功してから月曜の朝を待てば、定時実行が動いたかどうかも同じ画面で確かめられる。

push 起点にしたいなら、`on` の中身を前半の例のように `push` に入れ替えるだけでよい。迷ったときの目安として、私は「何かを変えたら必ずやること」は push 起点、「何も変えなくても定期的にやること」は定時実行、と分けて考えている。サイトの公開は前者、外部データの取得や集計は後者だ。両方の性格を持つ作業なら、一つのワークフローに両方のきっかけを書いてもかまわない。

## 自動化を育てるときの順番

最初の1本が動いたら、手順を一気に増やしたくなるが、少しずつ足していくほうが結局は早いと思う。手元で何度も繰り返してきたコマンドを一行ずつ `run` に移し、そのたびに手動実行で確かめる。失敗したときにどの行で落ちたかがすぐ分かるので、原因を探す時間が短くて済む。

もう一つ、時刻に関わる不具合は、GitHub Actions の外でも起きる。このブログも以前、サイトを組み立てる道具が日付を世界標準時で読むせいで、朝に書いた記事が9時まで公開されないという問題に出会った。その顛末は[Hugoで当日の記事が朝9時まで出ない。日付をUTCで読むtimeZoneの既定とbuildFuture](/posts/hugo-timezone-buildfuture-notes/)にまとめている。cron に `timezone` を書けるようになっても、動かすスクリプトや道具の側がどの時間帯で動いているかは別の話なので、日付を扱う作業を自動化するときは、両方を確かめておくと安心だ。

定型作業を機械に任せる一番の利点は、手順が文章として残ることだと感じている。ワークフローのファイルを読めば、何をいつどの順番でやっているかが誰にでも分かる。半年後の自分にとっても、それは頼りになる段取り表になる。

## 関連記事
- [VS CodeのDev ContainersでPCを汚さない開発環境を作る、devcontainer.jsonは4行から](/posts/vscode-dev-containers-docker-guide-2026/)(手元の環境をCIと揃えたいときに)
- [git worktreeで作業フォルダをブランチの数だけ持つ備忘録](/posts/git-worktree-multiple-branches-notes/)(ブランチごとの作業フォルダでワークフローを試すとき)
- [GitHub Pages で技術・理論記事を読む](https://kingsworksub-jpg.github.io/)
- [Amebaブログ版はこちら](https://ameblo.jp/sfd0501/)
- 今夜はウイスキー・カルチャーの記事やジャズ・映画のエッセイも公開予定です → [note はこちら](https://note.com/shining_finger01)

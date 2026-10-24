---
title: "git worktreeで作業フォルダをブランチの数だけ持つ、stashと切り替えをやめるための備忘録"
description: "git worktreeはブランチごとに別の作業フォルダを作り、切り替えやstashの手間を減らす機能だ。add・list・removeの基本から、共有されるもの、フォルダを消したり移したりしたときの直し方まで、Git 2.55で確かめた。"
images: ["/images/og/git-worktree-multiple-branches-notes.jpg"]
ogImageWidth: 1200
ogImageHeight: 630
date: 2026-10-18T23:00:00+09:00
categories: ["notes"]
tags: ["Git", "git worktree", "ブランチ", "バージョン管理", "Windows"]
draft: false
scheduled_time: "23:00"
---

新しい機能のブランチで作業している途中に、本番側の小さな不具合を直してほしいと頼まれる。これまでは、書きかけの変更を`git stash`で退避し、`git switch main`で切り替え、直してコミットし、元のブランチに戻って`git stash pop`する、という手順を踏んでいた。そのたびにエディタは開いていたファイルを読み直し、ビルドの成果物は古いブランチの状態のまま残り、退避したことを忘れてstashが溜まっていく。小さな修正のはずが、戻ってきたときに何をしていたか思い出すところから始まるのが嫌だった。

この切り替えそのものをやめられるのが`git worktree`だ。1つのリポジトリに作業フォルダを何本でも足せて、フォルダごとに別のブランチを開いておける。修正を頼まれたら、別のフォルダに移って直すだけで済み、書きかけの作業には指一本触れない。仕組みと使い方、それに後片付けでつまずきやすい点を、手元のWindows 11に入っているGit 2.55.0で一通り試したので、その結果をまとめておく。

## worktreeは作業フォルダを増やす機能で、リポジトリは1つのまま

<figure class="photo photo--left">
<a href="https://git-scm.com/docs/git-worktree" target="_blank" rel="noopener"><img src="/images/git-worktree/branching-workflow.png" alt="mainから枝分かれしたブランチで開発し、マージリクエストを経てmainへ戻る流れを描いた図" width="220" height="81" loading="lazy"></a>
<figcaption>mainから枝を切り、作業してmainへ戻す。worktreeを使うと、この枝ごとに別のフォルダを持てる<span class="credit">Photo: TheresNoTime / <a href="https://commons.wikimedia.org/wiki/File:Basic_git_branching_workflow_(GitLab).png" target="_blank" rel="noopener">CC BY-SA 4.0</a></span></figcaption>
</figure>

ふつうのクローンは、`.git`フォルダ(履歴やブランチの情報が入っている本体)が1つと、ファイルを編集するための作業フォルダが1つ、という組み合わせになっている。ブランチを切り替えると、この作業フォルダの中身が丸ごと書き換わる。同じリポジトリを2つの場所で開きたければ、もう1回クローンするのがこれまでのやり方だったが、それだと履歴が2倍の容量になり、片方で作ったブランチをもう片方から見るにはpushとfetchを挟む必要がある。

worktreeは、`.git`の本体は1つのまま、作業フォルダだけを追加する。最初からある作業フォルダを「メインのワークツリー」、後から足したものを「リンクされたワークツリー」と呼ぶ。追加したフォルダの直下にあるのは`.git`フォルダではなく、`.git`という名前の小さなテキストファイルで、中身は1行だけだった。

```text
gitdir: C:/Users/norio/AppData/Local/Temp/wtlab/repo/.git/worktrees/repo-feature
```

指している先は、メインのリポジトリの`.git/worktrees/`の下に作られた管理用のフォルダだ。ここにそのワークツリー専用の`HEAD`(今どのブランチを開いているか)と`index`(ステージングの状態)が置かれ、`commondir`というファイルには本体への相対パス`../..`が、`gitdir`というファイルには逆向きに作業フォルダ側の`.git`ファイルの場所が書かれている。行きと帰りの両方向にパスが記録されていることが、後で出てくる「フォルダを動かしたときに壊れる」話の原因になる。

機能としては古く、2015年7月のGit 2.5で入った。当初は追加と掃除くらいしかできず、フォルダを消す`remove`と移す`move`が加わったのは2018年のGit 2.17だ。その後も、空のブランチで作業フォルダを作る`--orphan`がGit 2.42で、パスを相対で記録する`--relative-paths`がGit 2.48で足されている。古い解説記事では、フォルダを手で消して`prune`で片付ける手順が紹介されていることがあるが、今は`remove`で一度に済む。なお、サブモジュールを含むリポジトリでの複数ワークツリーは、公式の説明書きでも対応が不完全とされていて、サブモジュールのあるワークツリーは`move`できない。サブモジュールを多用するリポジトリでは、慎重に試したほうがいい。

## 基本はadd・list・removeの3つで足りる

まずはブランチを1つ、隣のフォルダに開いてみる。リポジトリの中で次のように打つ。

```bash
git worktree add ../repo-feature feature      # 既存のブランチ feature を開く
git worktree add -b hotfix ../repo-hotfix     # 新しいブランチ hotfix を作って開く
git worktree list
```

`list`の出力は、フォルダ、開いているコミット、ブランチ名の3列になる。

```text
C:/Users/norio/AppData/Local/Temp/wtlab/repo         008158a [main]
C:/Users/norio/AppData/Local/Temp/wtlab/repo-feature 008158a [feature]
C:/Users/norio/AppData/Local/Temp/wtlab/repo-hotfix  008158a [hotfix]
```

あとは`cd ../repo-hotfix`で移って、いつも通り編集・コミット・pushすればよい。コミットは本体の`.git`に入るので、メインのフォルダに戻って`git log hotfix`と打てば、もうそこにある。pushもfetchも要らない。

ブランチ名を書かずに`git worktree add ../quickfix`とフォルダだけ渡すと、フォルダ名と同じ`quickfix`というブランチが今のコミットから作られた。もう1つ便利だったのは、手元にはまだ無く、リモートにだけあるブランチの名前を渡した場合だ。クローンしたリポジトリで`git worktree add ../clone-topic topic`とすると、`origin/topic`を追いかける`topic`ブランチが自動で作られ、`branch 'topic' set up to track 'origin/topic'.`と表示された。レビューを頼まれたブランチを開くときは、これがいちばん手数が少ない。

用が済んだら`git worktree remove ../repo-hotfix`で消す。作業フォルダと管理用のフォルダがまとめて消え、ブランチそのものは残る。ここで、まだコミットしていない変更や追跡していないファイルがあると、`contains modified or untracked files, use --force to delete it`と言われて止まる。書きかけの変更をうっかり捨てない仕組みなので、`--force`は中身を確かめてから付けるようにしている。

## 同じブランチは2か所で開けない

試していて最初に引っかかったのがこれだ。`feature`を`repo-feature`で開いたまま、別の場所でも`feature`を開こうとすると拒まれる。

```text
fatal: 'feature' is already used by worktree at 'C:/Users/norio/AppData/Local/Temp/wtlab/repo-feature'
```

`git worktree add`だけでなく、メインのフォルダで`git switch feature`や`git checkout feature`をしても同じメッセージが出た。同じブランチを2つのフォルダで同時に編集してコミットすると、片方のコミットでブランチの先端が動き、もう片方のフォルダは自分の知らないうちに古い状態になってしまう。それを防ぐための制限なので、外さないほうがいい。`git branch -d feature`も`cannot delete branch 'feature' used by worktree at ...`と断られた。ブランチを消したいときは、先にそのワークツリーを消す順番になる。

どうしても同じ中身をもう1つ見たいときは、ブランチではなくコミットを開けばよい。`git worktree add --detach ../repo-view HEAD`とすると、ブランチに属さない状態(detached HEAD)でフォルダが作られ、制限にはかからない。古いバージョンの動きを確かめたり、2つのコミットを並べて比べたりするときに使える。コミットはできるが、そのままだとどのブランチにも残らないので、残したくなったら`git switch -c 新しい名前`でブランチにしておく。

## 共有されるものと、フォルダごとに別のもの

<figure class="photo photo--right">
<a href="https://www.amazon.co.jp/dp/4297153939?tag=nakimoto1-22" target="_blank" rel="noopener sponsored nofollow"><img src="/images/git-worktree/branches-example.png" alt="複数のブランチとマージが色付きの線で描かれた、Gitのコミット履歴のグラフ表示" width="220" height="60" loading="lazy"></a>
<figcaption>どのワークツリーから`git log --graph`を見ても、同じ1本の履歴が出てくる<span class="credit">Photo: Self / <a href="https://commons.wikimedia.org/wiki/File:Git_branches_example.png" target="_blank" rel="noopener">Public domain</a></span></figcaption>
</figure>

本体が1つなので、コミット、ブランチ、タグ、リモートの設定は全部のワークツリーで共通になる。あるフォルダで作ったブランチは、別のフォルダからすぐに見えるし、どこかで`git fetch`すれば全部のフォルダに反映される。一方で、今どのブランチを開いているか、ステージングの状態、それに作業フォルダに置かれたファイルそのものは、フォルダごとに独立している。

意外だったのはstashの扱いだ。stashは履歴と同じ場所に記録されるので、ワークツリーをまたいで共有される。`repo-feature`で`git stash`したものを、メインのフォルダで`git stash list`すると`stash@{0}: WIP on feature: ...`とそのまま見えた。便利な場面もあるが、フォルダごとに退避場所が分かれていると思っていると、別のフォルダで`git stash pop`して違う作業の変更を持ってきてしまう。worktreeを使い始めてからは、そもそもstashをほとんど使わなくなったので、自分の場合は大きな問題にはならなかった。

| 項目 | ワークツリー間で | 補足 |
|---|---|---|
| コミット・ブランチ・タグ | 共有 | どのフォルダで作ってもすぐに見える |
| リモートとfetchの結果 | 共有 | 1か所でfetchすれば全部に反映 |
| stash | 共有 | 別のフォルダのstashも`stash list`に出る |
| 設定(`.git/config`) | 共有 | フォルダ別にしたいときは下の方法で |
| 開いているブランチ(HEAD) | フォルダごと | 同じブランチは2か所で開けない |
| ステージングの状態 | フォルダごと | `git add`はそのフォルダだけに効く |
| 追跡していないファイル | フォルダごと | `node_modules`やビルド結果は作り直しになる |

最後の行は実務でいちばん効いてくる。新しいワークツリーには、Gitが管理しているファイルしか入らない。依存パッケージやビルドの成果物、`.env`のような追跡対象外の設定ファイルは空っぽなので、フォルダを作るたびにインストールやビルドをやり直すことになる。依存が重いプロジェクトでは、ワークツリーを作っては消すより、`main`用・作業用・レビュー用のように数本を決めて使い回すほうが楽だった。

設定をワークツリーごとに変えたい場合は、`git config extensions.worktreeConfig true`を一度だけ実行しておく。そのうえで`git config --worktree キー 値`と書くと、値は`.git/worktrees/<名前>/config.worktree`という別のファイルに入り、そのフォルダでだけ効く。手元でも、`repo-feature`の管理用フォルダに`config.worktree`ができ、中に指定した値だけが書かれていることを確かめた。

## フォルダを手で消したときは、pruneで片付ける

<figure class="photo photo--left">
<a href="https://www.amazon.co.jp/dp/4297153939?tag=nakimoto1-22" target="_blank" rel="noopener sponsored nofollow"><img src="/images/git-worktree/git-gui-error.png" alt="Git Guiのエラーダイアログに、Not a Git repositoryと表示されている画面" width="220" height="110" loading="lazy"></a>
<figcaption>作業フォルダと本体のつながりが切れると、Gitはそこをリポジトリとして認識しなくなる<span class="credit">Photo: Software: Junio Hamano, Linus Torvalds und andere Screenshot: PantheraLeo1359531 / <a href="https://commons.wikimedia.org/wiki/File:20231112_13_44_46-Git_Gui_error.png" target="_blank" rel="noopener">GPLv2</a></span></figcaption>
</figure>

worktreeの後片付けで多い失敗は、`git worktree remove`を使わず、エクスプローラーや`rm -rf`でフォルダを消してしまうことだ。作業フォルダは消えても、本体の`.git/worktrees/`の下には管理用のフォルダが残る。手元でこれをやると、`git worktree list`の該当行の末尾に`prunable`(片付けてよい)という印が付いた。`--porcelain`付きで見ると、理由まで書かれている。

```text
prunable gitdir file points to non-existent location
```

この残骸は`git worktree prune`で消せる。いきなり消すのが不安なら、`-n`(実際には消さない)と`-v`(何をするか表示する)を付けて先に確かめる。

```bash
git worktree prune -n -v
# Removing worktrees/repo-detached: gitdir file points to non-existent location
git worktree prune -v
```

放っておいても、`git gc`が走るときに古い残骸は自動で片付けられる。ただ、残骸があるあいだは、そこで開いていたブランチが「使用中」のまま扱われ、別のフォルダで開こうとすると先ほどの`already used by worktree`で止まる。消したはずのフォルダのせいでブランチが開けないときは、まず`prune`を疑うとよい。

逆に、外付けのドライブやネットワーク上のフォルダにワークツリーを置いていると、つないでいないあいだに「消えた」と判断されて片付けられてしまうおそれがある。そういうフォルダは`git worktree lock --reason "外付けSSD"`で鍵をかけておく。鍵のかかったワークツリーは`prune`の対象から外れ、`remove`しようとしても`cannot remove a locked working tree, lock reason: 外付けSSD`と止まる。外すときは`git worktree unlock`だ。細かい話だが、理由に日本語を書くと、`list --porcelain`の出力では`locked "USB\343\203\241..."`のように8進数でエスケープされた形になった。スクリプトでこの欄を読むなら、理由は英数字にしておくほうが扱いやすい。

## フォルダを移したときは、moveとrepairを使い分ける

ワークツリーの場所を変えたいときは、フォルダを直接動かさずに`git worktree move ../repo-feature ../wt-feature`を使う。行きと帰りの両方のパスが書き直されるので、そのまま使い続けられる。試して気づいたのは、移したあとも管理用のフォルダの名前は`repo-feature`のままだということだ。`list`には新しい場所が出るので困ることはないが、`.git/worktrees/`の中を覗いたときに名前が合わず、少し戸惑った。

メインのワークツリーは`move`で動かせない。`git worktree move . ../x`と打つと`'.' is a main working tree`と断られた。メインのフォルダごと別の場所へ移したり名前を変えたりすると、リンクされたワークツリー側の`.git`ファイルが古い場所を指したままになる。手元でメインのフォルダの名前を変えてから、リンク側で`git status`を打つと、`fatal: not a git repository: (NULL)`と出て何もできなくなった。

これを直すのが`git worktree repair`だ。移した後のメインのフォルダで、リンクされたワークツリーの場所を渡して実行する。

```bash
cd ../repo2
git worktree repair ../wt-feature
# repair: .git file broken: C:/Users/norio/AppData/Local/Temp/wtlab/wt-feature
```

これで`.git`ファイルが新しい場所を指すように書き直され、リンク側の`git status`も元通りになった。リンクされたワークツリーのほうを手で動かしてしまった場合も、そのフォルダの中で`git worktree repair`を打てば、本体側の記録が直る。

フォルダの組をまとめて動かすことが多いなら、最初から相対パスで記録させておく手もある。`git worktree add --relative-paths ../rel -b relb`とすると、`.git`ファイルの中身が`gitdir: ../repo/.git/worktrees/rel`のような相対パスになり、本体の設定に`extensions.relativeWorktrees = true`が書き込まれた。メインとリンクの両方を含む親フォルダごと別の場所へ移してみると、絶対パスで作ったワークツリーは`not a git repository`で壊れたのに対し、相対パスで作ったほうはそのまま動いた。ただし、片方だけを動かしたり名前を変えたりすれば、相対パスでもつながりは切れる。また、手元では相対パスのワークツリーに`repair`をかけると、絶対パスに書き戻された。相対パスを使い続けたいなら、`git config worktree.useRelativePaths true`を設定してから`repair`するのがよさそうだ。なお、この拡張を有効にしたリポジトリは、相対パスに対応していない古いGitからは開けなくなる点にも注意が要る。

## 空のブランチを横に並べる、--orphanの使いどころ

もう1つ覚えておくと便利なのが`--orphan`だ。`git worktree add --orphan -b gh-pages ../repo-pages`とすると、履歴を1つも持たない新しいブランチが、空の作業フォルダとして作られる。`list`ではコミットの欄が`0000000`になり、まだ何もコミットされていないことが分かる。

静的サイトのビルド結果だけを置く`gh-pages`のようなブランチは、ソースのブランチと中身がまったく違う。ふつうに切り替えると、作業フォルダの中身が総入れ替えになって落ち着かない。ワークツリーで横に並べておけば、ソース側でビルドした結果を隣のフォルダにコピーしてコミットするだけで済む。ドキュメントだけのブランチや、試作用の使い捨てのブランチを作るときにも使える。

## 自分の使い方と、コマンドの早見表

試した結果をふまえて、今はこういう決まりで使っている。まず、ワークツリーはリポジトリのフォルダの中ではなく隣に置き、名前は`リポジトリ名-ブランチ名`にそろえる。リポジトリの中に作ると、エディタの検索やファイル監視が両方のフォルダを拾ってしまい、かえって混乱した。次に、メインのフォルダはいつでも`main`をきれいな状態で開いておく場所にして、作業は必ずリンクされたワークツリーで行う。急ぎの修正を頼まれたら、`main`のフォルダから`git worktree add -b fix-xxx ../repo-fix-xxx`で枝を切るだけで、書きかけの作業はそのまま残る。

最後に、マージが済んだら`remove`してからブランチを消す。週に1回は`git worktree list`を眺めて、`prunable`の付いた行や、何のために作ったか思い出せないフォルダが無いかを確かめる。ワークツリーは作るのが手軽なぶん、気づくと何本も増えていて、どこで何をしていたか分からなくなるのが唯一の弱点だと感じている。

| やりたいこと | コマンド | メモ |
|---|---|---|
| 既存のブランチを別のフォルダで開く | `git worktree add ../repo-x x` | リモートにだけあるブランチも自動で追跡 |
| 新しいブランチを作って開く | `git worktree add -b x ../repo-x` | 起点を指定するなら末尾にコミットを足す |
| コミットだけを見る | `git worktree add --detach ../view HEAD` | ブランチの重複制限にかからない |
| 一覧を見る | `git worktree list` | `--porcelain`で機械向けの詳しい形式 |
| 片付ける | `git worktree remove ../repo-x` | 未コミットの変更があると止まる |
| 手で消した残骸を掃除する | `git worktree prune -n -v` | `-n`を外すと実際に消す |
| 移す | `git worktree move ../a ../b` | メインのワークツリーは移せない |
| つながりを直す | `git worktree repair <場所>` | 本体かリンクのどちらかを動かした後に |
| 消えないように守る | `git worktree lock --reason "..."` | 外付けドライブに置くとき |

ブランチを切り替えるのではなく、ブランチのある場所へ移動する。考え方を1つ変えるだけで、stashの退避と復元を繰り返す手間がほとんど無くなった。リポジトリを何本もクローンしていた人ほど、試す価値があると思う。

## 関連記事


- [Hugoで当日の記事が朝9時まで出ない。日付をUTCで読むtimeZoneの既定とbuildFuture](/posts/hugo-timezone-buildfuture-notes/)
- [Windowsのシンボリックリンクをmklinkで作る、ジャンクションとの違いとrmdirで消す理由](/posts/windows-symbolic-link-mklink-notes/)
- [PowerShell 5.1がBOMなしUTF-8の.ps1を読み違えるとき、消えるのは引用符と改行だった](/posts/powershell-utf8-bom-notes/)
- [GitHub Actionsの最初の1本は、pushで動かすか時刻で動かすかを決めるところから](/posts/github-actions-schedule-push-guide-2026/)
- 夜はウイスキー・カルチャーの記事やDTM理論の記事も公開しています → [note はこちら](https://note.com/shining_finger01)

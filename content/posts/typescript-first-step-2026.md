---
title: "TypeScriptはJavaScriptに何を足すのか、型注釈とtsconfigの最小構成から"
description: "JavaScriptに型を足すと何が変わるのか。エディタの補完と実行前のエラー検出、型推論の効き方、tsconfigの最小構成、anyに逃げない書き方、既存コードを少しずつ型付けする手順を、TypeScript 7の現状に沿って整理する。"
images: ["/images/og/typescript-first-step-2026.jpg"]
ogImageWidth: 1200
ogImageHeight: 630
date: 2026-11-09T20:00:00+09:00
scheduled_time: "20:00"
categories: ["dev"]
tags: ["TypeScript", "JavaScript", "tsconfig", "型注釈", "開発環境", "フロントエンド"]
draft: false
---

JavaScriptを書き慣れてくると、動かしてから初めて気づく間違いがもどかしくなる。プロパティ名の綴り違い、`undefined` かもしれない値の取り出し、関数に渡す引数の順番。どれも実行するまで分からず、しかもエラーが出る場所は原因から遠く離れていることが多い。TypeScriptは、この「動かす前に気づけたらいいのに」という部分を引き受けるために生まれた言語だ。

とはいえ、いきなり全部を型で固める必要はない。JavaScriptのファイルをそのまま残したまま、型の情報を少しずつ足していくこともできる。この記事では、型を足すと実際に何が変わるのかをエディタの動きから確かめ、最小限の `tsconfig`、よく使う型の書き方、`any` に逃げないための道具、既存コードを段階的に移す手順までを順に見ていく。TypeScriptは2026年7月に7.0が公開され、コンパイラがGoで書き直されて速くなった。ただ、ここで扱う考え方の多くは、その前の版から変わっていない。

## 型を足すと、エディタが先に間違える場所を教えてくれる

<figure class="photo photo--left">
<img src="/images/typescript-first-step/vscode.png" alt="Visual Studio Code の画面。左側にファイル一覧、中央に JavaScript のコード、下側にターミナルの出力が表示されている" width="220" height="124" loading="lazy">
<figcaption>エディタは型の情報を手がかりに、入力の途中で補完を出し、怪しい場所に波線を引く。実行する前の時点で、間違いの候補が画面に出ている<span class="credit">Photo: Cycling2 / CC0</span></figcaption>
</figure>

JavaScriptのファイルを開いて `user.` と打ったとき、エディタが候補を出してくれるのは、それらしい名前を探しているからだ。実際にそのオブジェクトが何を持っているかを知っているわけではないので、存在しないプロパティを補完してしまうこともある。TypeScriptのファイルでは、変数がどんな形の値なのかをコンパイラが把握しているため、候補はその形に沿ったものになる。存在しないプロパティを書けば、保存する前の時点で波線が付く。

この体験の違いは、コードを書く順番を変える。これまでは、書く、実行する、エラーを読む、直す、という往復が必要だった。型があると、往復の何割かがエディタの中だけで済む。関数の呼び出し側と定義側で引数の数や型が食い違っていても、その場で知らせてくれる。変数の名前を変えたとき、直し忘れた場所が色を変えて残るのもありがたい。小さなプロジェクトなら気合いで追えるが、ファイルが十数個を超えると、この「直し忘れの見える化」だけで元が取れる。

型の情報は、ビルドのときに取り除かれる。ブラウザやNode.jsが実際に動かすのは、型注釈の消えたJavaScriptだ。だから型を足しても実行速度が落ちることはなく、逆に型が実行時の安全性を保証してくれるわけでもない。あくまで、書いている最中とビルドの時点で間違いを減らすための仕組みだ、という線引きは最初に押さえておきたい。

## 型注釈は、書かなくても効くところから始まる

<figure class="photo photo--right">
<img src="/images/typescript-first-step/code-screen.jpg" alt="暗い画面に、色分けされたソースコードが斜めに映っている" width="220" height="147" loading="lazy">
<figcaption>型の情報は、補完や警告の材料としてエディタの中に常駐する。ファイルを保存するたびにコンパイラが全体を見直す<span class="credit">Photo: Sai Kiran Anagani _imkiran / CC0</span></figcaption>
</figure>

TypeScriptの型は、すべてを自分で書くものではない。右辺の値から明らかなときは、コンパイラが型を推測してくれる。これを型推論と呼ぶ。

```ts
const price = 1200;        // number
const label = "coffee";    // "coffee" という文字列リテラル型
let total = 0;             // number
```

`const` で宣言した文字列は、その値そのものの型になる。`let` だと再代入できるので、より広い `string` になる。この違いは、あとで選択肢を限定したいときに効いてくる。とはいえ、最初のうちは「書かなくても分かるところは書かない」で問題ない。型注釈を付けるのは、関数の引数のように、右辺からは決められない場所だけでよい。

```ts
function withTax(price: number, rate = 0.1): number {
  return Math.floor(price * (1 + rate));
}
```

引数に型を書いておくと、呼び出す側で文字列を渡したときにエラーになる。戻り値の型は書かなくても推論されるが、チームで読むコードでは書いておくほうが意図が伝わる。`strict` を有効にすると、型を書いていない引数は暗黙の `any` としてエラーになる。最初のうちはこのエラーがうるさく感じるかもしれないが、どの引数に型を付ければよいかを教えてくれていると思えばよい。

TypeScriptのコードは、そのままではブラウザもNode.jsも読めない。`tsc` でJavaScriptに変換する必要がある。プロジェクトに導入するときは、開発用の依存として `typescript` を入れ、`npx tsc` を実行する。TypeScript 7では、この `tsc` がGoで書かれたネイティブの実行ファイルになっていて、大規模なプロジェクトでも待ち時間がかなり短くなった。エディタ側も、従来の独自プロトコルからLSPに移り、VS Codeとのやり取りが標準的な形になっている。

## tsconfigは、増やしすぎないほうがいい

`tsc --init` を実行すると、TypeScript 7では短い設定ファイルが生成される。以前の版のように、コメントだらけの長いひな型が延々と続くことはない。2026年11月時点の7.0.2が出す内容は、おおよそ次のようなものだ。

```json
{
  "compilerOptions": {
    "target": "esnext",
    "module": "nodenext",
    "strict": true,
    "skipLibCheck": true,
    "sourceMap": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noUncheckedSideEffectImports": true
  },
  "include": ["src"]
}
```

実際のファイルにはコメント用のキーは入らない。`rootDir` と `outDir` はコメントアウトされた状態で置かれているので、出力先を分けたくなったら `"rootDir": "./src"` と `"outDir": "./dist"` を有効にする。`include` も自動では入らないため、対象のフォルダーを自分で書く。ここを省くと、設定ファイルのある場所から下にあるファイルがすべて対象になる。

各項目の意味は、次のように整理できる。

- `target` は、出力するJavaScriptの構文の水準。`esnext` にしておけば、最新の構文をそのまま出す。古いブラウザを支える必要があるなら、ビルドの後工程で変換するほうが管理しやすい。
- `module` は、モジュールの形式。`nodenext` はNode.jsの解決規則に従う。TypeScript 7では `amd` や `umd`、`systemjs` といった古い形式は選べなくなった。
- `strict` は、厳しめのチェックをまとめて有効にする。TypeScript 7では既定で `true` なので、明示しなくても効いている。
- `skipLibCheck` は、依存パッケージの型定義ファイルの検査を省く。自分のコードの検査は残るので、ビルド時間を短くするために入れておいてよい。
- `sourceMap` は、出力したJavaScriptから元のTypeScriptへ対応付けるファイルを作る。ブラウザの開発者ツールで元のコードを見ながらデバッグできる。
- `verbatimModuleSyntax` は、型だけのimportと値のimportを区別させる。ビルドツールがファイル単位で変換するときに、型のimportが残って実行時に壊れるのを防ぐ。
- `isolatedModules` は、ファイルを1つずつ独立して変換できる書き方に制限する。Viteやesbuildのような速い変換器と組み合わせるときに必要になる。

`moduleResolution` は、`module` の値から自動で決まることが多い。`nodenext` なら同じ `nodenext` になる。Viteやwebpackのように、拡張子を省略したimportを束ねる道具を使うなら `"bundler"` を指定する。`nodenext` はNode.jsでそのまま動かすことを想定していて、ESMでは相対importに拡張子が必要になる。ここを混同すると、エディタでは通るのに実行時に「モジュールが見つからない」となる。

設定で迷ったら、増やすより減らすほうがよい。`types` に何かを足したり、`paths` で別名を付けたりすると、それだけ解決の規則が増える。最初は `target`、`module`、`strict`、`include` の4つで足りる。必要になった設定を、そのとき理由と一緒に足していくほうが、あとから読んだときに分かりやすい。

## 型の書き方は、まず4つ覚えれば足りる

<figure class="photo photo--left">
<img src="/images/typescript-first-step/ts-logo.png" alt="青い角丸の四角に、白い文字で TS と書かれた TypeScript のロゴ" width="220" height="220" loading="lazy">
<figcaption>型はビルドのときに取り除かれ、残るのはJavaScriptになる。だから導入しても実行環境を選ばない<span class="credit">Image: ™/®Microsoft / Public domain</span></figcaption>
</figure>

型の表現は無数にあるように見えるが、日常的によく使うのは4つだ。オブジェクトの形を表す `interface` と `type`、複数の型のどれかを表すユニオン、省略できるプロパティ、そして型を後から受け取るジェネリクスである。

```ts
type Status = "draft" | "published" | "archived";

interface Article {
  title: string;
  status: Status;
  tags?: string[];
}
```

`interface` はオブジェクトの形を定義する。`type` はそれに加えて、文字列の組み合わせや関数の型など、幅広いものに名前を付けられる。迷ったら `type` で始めて、あとから拡張が必要になったら `interface` にすればよい。`Status` のように取りうる値を文字列で限定しておくと、`"publised"` のような綴り違いを書いた時点でエラーになる。`tags?` の `?` は、そのプロパティが無くてもよいという意味だ。`strictNullChecks` が有効な環境では、`tags` をそのまま使おうとすると「undefinedかもしれない」と警告が出る。これが型のありがたみで、配列の操作をする前に存在を確かめる習慣が付く。

ジェネリクスは、型を引数のように受け取る仕組みだ。配列の先頭を返す関数を、文字列でも数値でも同じ書き方で扱える。

```ts
function first<T>(items: T[]): T | undefined {
  return items[0];
}

const name = first(["a", "b"]);  // string | undefined
const num = first([1, 2, 3]);    // number | undefined
```

`<T>` の部分が型の受け口で、呼び出すときに渡した配列から中身の型が決まる。ライブラリの型定義に出てくる `<T>` は、この仕組みだと思って読めばよい。

TypeScriptの型は「構造的部分型」と呼ばれる考え方で判定される。名前が違っても、持っているプロパティの形が合っていれば同じ型として扱われる。これは柔軟で便利だが、意図しないオブジェクトを受け入れてしまうこともある。とくにオブジェクトのリテラルを直接渡したときだけは、余計なプロパティを警戒してエラーにする「余剰プロパティチェック」が働く。変数に入れてから渡すとそのチェックは外れるので、挙動が違って見えることがある。この違いを知っておくと、なぜ片方だけ通るのかで悩まずに済む。

## anyに逃げないための、unknownとsatisfies

TypeScriptを始めた人が最初にぶつかる誘惑が `any` だ。エラーが出た場所に `any` と書けば、その行は黙る。だが `any` は周囲にも伝染する。`any` を受け取った変数から取り出した値も `any` になり、型の検査が効かない範囲がじわじわ広がっていく。`any` を書きたくなったときは、代わりに `unknown` を使えないか考える。

```ts
function parse(input: unknown): string {
  if (typeof input === "string") {
    return input.trim();
  }
  throw new Error("文字列が必要です");
}
```

`unknown` は「何が来るか分からない」という意味で、`any` と違って、中身を使う前に型を確かめることを強制する。上の例では `typeof input === "string"` と確かめた内側でだけ `trim()` を呼んでいる。このように、条件分岐で型を絞り込むことを型の絞り込み（narrowing）と呼ぶ。`typeof` のほか、`in` 演算子でプロパティの有無を見たり、`instanceof` でクラスの実体を確かめたりできる。

複数の形が混ざる値は、共通の目印を持たせた「判別可能なユニオン」にすると扱いやすい。

```ts
type Shape =
  | { kind: "circle"; radius: number }
  | { kind: "square"; side: number };

function area(shape: Shape): number {
  switch (shape.kind) {
    case "circle":
      return Math.PI * shape.radius ** 2;
    case "square":
      return shape.side ** 2;
    default: {
      const exhaustive: never = shape;
      return exhaustive;
    }
  }
}
```

`kind` という共通のプロパティで分岐すると、それぞれの分岐で使えるプロパティが変わる。`default` に到達したときの `shape` は `never` になり、新しい形を追加して分岐を書き忘れると、ここでエラーになる。`never` は「値が存在しない」ことを表す型で、到達しないはずの場所を検査するのに使える。

`any` の代わりにもう一つ便利なのが `satisfies` だ。オブジェクトが特定の型を満たしているかを検査しつつ、推論された狭い型を保ってくれる。型注釈の `:` を付けると型が広がってしまう場面で、`satisfies` は元の情報を残す。

```ts
const config = {
  entry: "./src/index.ts",
  format: "esm",
} satisfies { entry: string; format: "esm" | "cjs" };

config.format; // "esm" のまま
```

`satisfies` はTypeScript 4.9で入った。`as const` も似た目的で使える。`as const` を付けた配列やオブジェクトは、値がリテラルのまま固定され、配列は読み取り専用のタプルになる。設定値の一覧を定義して、そこから型を作りたいときに向いている。

## 既存のJavaScriptは、ファイルを分けたまま型を足せる

すべてを書き直す必要はない。`.js` のファイルを `.ts` に改名するのが一番手っ取り早いが、いきなり全部を変えるとエラーが一度に押し寄せる。まずは `allowJs` と `checkJs` を有効にして、JavaScriptのまま型の検査を始める方法がある。

```json
{
  "compilerOptions": {
    "allowJs": true,
    "checkJs": true,
    "noEmit": true
  }
}
```

`allowJs` は `.js` ファイルをTypeScriptのプロジェクトに含める設定、`checkJs` はそのファイルにも型の検査を適用する設定だ。個別のファイルだけ検査したいときは、ファイルの先頭に `// @ts-check` を1行書く。反対に、どうしても今は直せないファイルには `// @ts-nocheck` を付けて検査から外せる。外したファイルは、あとで直す予定として一覧にしておくとよい。

移行は、依存の少ないファイルから進める。定数や小さな関数だけのファイルは型を付けやすく、そこで得た型が呼び出し側の推論にも効く。逆に、外部のAPIを直接叩くファイルは、返ってくる値の形が実行時にしか分からないので後回しにしやすい。新しいファイルは最初から `.ts` で作り、古いファイルは触ったついでに型を足していく。この「触ったら直す」だけでも、半年もすればかなりの範囲が型付きになる。

`strict` をいきなり有効にすると、既存のコードでは大量のエラーが出る。TypeScript 7では `strict` が既定で有効だが、移行の間だけ `"strict": false` にして、`noImplicitAny` や `strictNullChecks` を1つずつ有効にしていくこともできる。エラーの数を手に負える量に保ちながら進めるのが、途中で心が折れないコツだ。

## 型で見つかる範囲と、見つからない範囲

型を付けても、実行時のエラーがすべて消えるわけではない。外部のAPIから返ってきたJSONは、型を書いても実行時にその形である保証はない。`JSON.parse` の戻り値は `any` なので、そのまま信じると型の検査をすり抜ける。境界の部分では、値が本当に期待した形かを確かめる処理を書くか、スキーマ検証の仕組みを挟む必要がある。

`as` による型アサーションも、使いすぎると危ない。コンパイラに対して「この値はこの型だ」と宣言するだけで、実際に確かめてはくれない。`as` を書いた場所は、間違っていてもエラーにならない。どうしても必要な場面はあるが、`any` と同じくらい慎重に扱いたい。

型定義が無いライブラリを使うと、importした時点でエラーになることがある。多くの有名なライブラリは `@types/` の名前で型定義が公開されていて、開発用の依存として入れれば解決する。型定義が無い場合は、最小限の宣言ファイルを自分で書くか、`unknown` として受け取って必要な部分だけ絞り込む。

型が保証するのは、あくまで「コードの上での整合性」だ。実際のデータがその形かどうかは、別の問題として扱う。この線引きを忘れなければ、型は頼りになる道具になる。

## まとめ

JavaScriptに型を足すと、エディタの補完が正確になり、実行する前に間違いの候補が見えるようになる。型の情報はビルドで取り除かれるので、実行環境を選ばず、速度も落ちない。導入は `typescript` を入れて `tsc --init` を実行するところから始められ、設定は `target`、`module`、`strict`、`include` の4つで足りる。型の書き方は `interface` と `type`、ユニオン、省略可能なプロパティ、ジェネリクスを押さえれば、日常のコードの大半は表現できる。

`any` を書きたくなったら `unknown` と絞り込みを思い出し、オブジェクトの形を検査したいときは `satisfies` を使う。既存のJavaScriptは `allowJs` と `checkJs` でそのまま検査を始め、触ったファイルから `.ts` に変えていけばよい。TypeScript 7でコンパイラが速くなったこともあり、待ち時間を理由に導入をためらう場面は減った。まずは1つのファイルに型を付けて、エディタの反応がどう変わるかを確かめるところから始めたい。

## 関連記事・おすすめメディア

- [GitHub CLIでプルリクエストを出す朝、CIを待つ昼、マージする夕方](/posts/gh-cli-pull-request-terminal-guide-2026/)
- [GitHub Actionsの最初の1本は、pushで動かすか時刻で動かすかを決めるところから](/posts/github-actions-schedule-push-guide-2026/)
- [【本陣】GitHub Pages で全ての専門記事・深掘りデータベースを読む](https://kingsworksub-jpg.github.io/)
- [Amebaブログ版（ドリンク・酒の科学とレシピ）はこちら](https://blog.ameba.jp/)
- [note版（厳選ノウハウ・裏側）はこちら](https://note.com/shining_finger01)
- [Pythonの仮想環境、venvとuvの違いは「箱」と「記録」の分担にある](/posts/python-venv-uv-first-environment-2026/)
- [VS CodeのDev ContainersでPCを汚さない開発環境を作る](/posts/vscode-dev-containers-docker-guide-2026/)
- 今夜は音楽・カルチャー系の記事も公開予定です → [note はこちら](https://note.com/shining_finger01)

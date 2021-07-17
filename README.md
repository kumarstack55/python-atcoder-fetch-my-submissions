# python-atcoder-fetch-my-submissions

各問題ごとにACなコードを得る。

## 概要

リポジトリの下の `atcoder-submissions` に、
コンテストごと、問題ごとにディレクトリを作り、
問題について各言語ごとの結果がACな最新のコードを保存します。

## アーキテクチャ

1. AtCoder Problems から過去提出を得ます。
1. AtCoder から提出コードを得ます。

## 実行方法

```sh
poetry install
./run.ps1
```

## 参考資料

次の情報を参考にしました：

* AtCoderの提出コードを取得し、GitHubにプッシュする
    * https://zenn.dev/tishii2479/articles/6b381fb86e0369
# jev-playground

[TypeSafe AI](https://typesafe.ai/) の評価モデル **Jev** を、架空のデータで試すための個人用プレイグラウンドです。
本番に組み込む前に、プロンプト（state と questions）の書き方、答えの確信度、レイテンシ、費用を確かめる目的で使います。

Jev は文章を生成せず、`choice`（選択）・`score`（段階評価）・`noul`（Yes/No の確率）の型付きの答えを返すモデルです。
詳しくは [公式ブログ](https://typesafe.ai/blog/introducing-system-one-models-and-jev) を参照してください。

> [!IMPORTANT]
> 公開リポジトリのため、個人情報・機密情報・実データは入れません。
> コミットする前に [公開リポジトリとしての取り扱い](docs/public-repository-policy.md) を読んでください。

## 使い方

必要なもの: [uv](https://docs.astral.sh/uv/)、Jev の API キー。

```bash
git clone https://github.com/sa-ha/jev-playground.git
cd jev-playground
uv sync
uv run pre-commit install            # 個人情報チェックのフックを有効にする

cp .env.example .env                 # TYPESAFE_API_KEY=<あなたのキー> を書く（コミットされない）

uv run jev-playground validate scenarios/*.yaml                                  # 形式だけ検証
uv run --env-file .env jev-playground run scenarios/support_triage.yaml          # Jev で実行して集計
```

シナリオの書き方と出力の見方は [docs/scenarios.md](docs/scenarios.md) にあります。

## ライセンス

[MIT](LICENSE)

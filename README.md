# jev-playground

[TypeSafe AI](https://typesafe.ai/) の評価モデル **Jev** を、架空のデータで試すためのプレイグラウンドです。
YAML に書いたシナリオ（入力・質問・期待する答え）を Jev に送り、答え・確率・確信度・レイテンシ・トークン数を記録して集計します。

> [!IMPORTANT]
> このリポジトリは**公開リポジトリ**です。個人情報・機密情報・実データは一切入れません。
> コミットする前に、必ず下の「[公開リポジトリとしての取り扱い](#公開リポジトリとしての取り扱い)」を読んでください。

## Jev とは

Jev は文章を生成しない「System One」モデルです。入力（`state`）と質問（`questions`）を受け取り、型の決まった答えを返します。

| 質問の型 | 返るもの | 向いている用途 |
|---|---|---|
| `choice` | 選択肢のキー（最大255個）と、選択肢ごとの確率・確信度 | 分類、振り分け |
| `score` | 2〜10段階のスコア（小数）と、段階ごとの確率・確信度 | 緊急度・品質の段階評価 |
| `noul` | 「はい」の確率（0〜1） | Yes/No のゲート、フィルタ |

確信度が閾値以上の答えは自動で処理し、閾値未満だけを人や大きな LLM に回す、という使い方を想定しています。
詳しくは [公式ブログ](https://typesafe.ai/blog/introducing-system-one-models-and-jev) を参照してください。

## セットアップ

必要なもの: [uv](https://docs.astral.sh/uv/)、git、Jev の API キー。

```bash
git clone https://github.com/sa-ha/jev-playground.git
cd jev-playground
uv sync

# コミット前・push 前の自動チェックを有効にする（必須）
uv run pre-commit install
# グローバルに core.hooksPath を設定していて「Cowardly refusing」と出る場合は、代わりに次を実行する
#   GIT_CONFIG_GLOBAL=/dev/null uv run pre-commit install && git config --local core.hooksPath .git/hooks

# API キーを設定する（.env はコミットされません）
cp .env.example .env
# .env を開き、TYPESAFE_API_KEY=<あなたのキー> の形で書く
```

## 使い方

```bash
# シナリオの形式だけを検証する（API は呼ばない）
uv run jev-playground validate scenarios/*.yaml

# シナリオを Jev で実行し、集計を表示して results/ に保存する
uv run --env-file .env jev-playground run scenarios/support_triage.yaml

# モデルを固定版に切り替えて比較する
uv run --env-file .env jev-playground run scenarios/support_triage.yaml --model jev-latest
```

終了コードは、成功が `0`、一部のケースで呼び出しが失敗した場合が `1`、シナリオや設定の誤りが `2` です。

### 出力されるもの

- ケースごとの答え、確信度、期待値との一致（✓ / ✗）、レイテンシ
- 質問ごとの正答率
- 確信度の閾値（0.5 / 0.7 / 0.9 とシナリオの閾値）ごとの、自動処理率・自動処理分の正答率・エスカレーション件数
- レイテンシの中央値・平均・最大、入力トークン合計、概算費用

生のレスポンスを含む全結果は `results/<シナリオID>-<UTC時刻>.jsonl` に保存されます。`results/` はコミットされません。

## シナリオの書き方

`scenarios/support_triage.yaml` が見本です。

```yaml
scenarioId: support-triage          # 結果ファイル名に使う ID
description: 説明
model: jev-latest                   # 省略時は jev-latest
confidenceThreshold: 0.7            # 自動処理とみなす確信度。省略時は 0.7

questions:
  topic:                            # 質問名（答えのキーにもなる）
    type: choice
    instructions: この問い合わせの主な用件はどれですか？
    criteria:                       # 選択肢キー → 説明
      billing: 料金・請求に関すること
      bug: 不具合
  severity:
    type: score
    instructions: 緊急度はどの程度ですか？
    criteria:                       # 低い順に 2〜10 段階
      - 急ぎではない
      - 緊急
  escalate:
    type: noul
    instructions: 人の担当者がすぐに対応すべきですか？
    criteria:                       # 省略可
      "true": すぐに対応すべき
      "false": 自動返信で足りる

cases:
  - caseId: double-charge
    state: 今月の利用料が2回引き落とされています。   # 架空の文章だけを書く
    expected:                       # 省略した質問は採点しない
      topic: billing                # choice は選択肢キー
      severity: 1                   # score は段階番号（0 始まり）
      escalate: true                # noul は true / false
```

採点のルール:

- `choice`: 選ばれたキーが期待値と同じなら正解
- `score`: スコアを四捨五入した段階番号が期待値と同じなら正解
- `noul`: 確率 0.5 以上を「はい」とみなし、期待値と同じなら正解。確信度は `max(p, 1 - p)` として扱う

## 公開リポジトリとしての取り扱い

このリポジトリは誰でも閲覧でき、git の履歴も含めて一度公開された内容は完全には取り消せません。
以下のルールを**すべてのファイル・コミットメッセージ・ブランチ名・Issue・PR** に適用します。

### 載せてはいけないもの

| 種類 | 例 |
|---|---|
| 個人情報 | 本名、住所、電話番号、個人のメールアドレス、顔写真、生年月日、アカウント ID と結びつく情報 |
| 秘密情報 | API キー、トークン、パスワード、秘密鍵、`.env` の中身、認証付きの URL |
| 実データ | 実際のチャット・メール・問い合わせ・顧客データ・会話ログ（一部の抜粋や言い換えも不可） |
| 業務・案件の情報 | 取引先や勤務先の名前、案件名、社内システム名、社内の URL やホスト名、契約・料金の情報 |
| 要配慮情報 | 医療・健康・信条・犯罪歴などの情報（架空であっても実在の人物を連想させるもの） |
| 環境の情報 | 自分のホームディレクトリの絶対パス、社内・自宅ネットワークの IP アドレス、マシン名 |
| 不適切な内容 | 性的・暴力的・差別的な内容、第三者の著作物の無断転載 |
| Jev の実行結果 | `results/` の中身（架空データ由来でも、生レスポンスはコミットしない） |

### 使ってよい例示用の値

シナリオやテストで人名・連絡先などが必要な場合は、次の値だけを使います。

| 種類 | 使ってよい値 |
|---|---|
| 人名 | 山田太郎、佐藤花子 など明らかに例示とわかる名前。「顧客A」「利用者B」でもよい |
| 会社・サービス名 | 「サンプル株式会社」「サンプル家計簿アプリ」など架空のもの |
| メールアドレス | `@example.com` / `@example.org` / `@example.net` のアドレス |
| 電話番号 | `090-0000-0000`、`03-0000-0000` のように後半がすべて 0 のもの |
| 郵便番号 | `〒000-0000` |
| パス | `/home/user/...`、または相対パス |
| IP アドレス | `192.0.2.x`（ドキュメント用に予約された範囲） |

### 自動チェック

次の3か所で、同じ検査を自動で行います。どれかで引っかかったコミットや PR は取り込みません。

| タイミング | 内容 |
|---|---|
| コミット前（pre-commit） | [gitleaks](https://github.com/gitleaks/gitleaks) による秘密情報の検出、`scripts/check_sensitive.py` による個人情報の検出、コミット用メールが noreply か |
| push 前（pre-push） | 全ファイルと全コミットの作成者メールを検査 |
| GitHub Actions（push・PR ごと） | gitleaks で履歴全体を検査、`check_sensitive.py` で全ファイルと全コミットを検査、テストの実行 |

`scripts/check_sensitive.py` が検出するもの:

- 例示用ドメイン・GitHub の noreply 以外のメールアドレス
- 例示用以外の電話番号・郵便番号
- 例示用以外の名前を含むホームディレクトリの絶対パス（Linux・macOS・Windows）
- プライベート IP アドレス
- API キー・トークンの形をした文字列
- 拒否リストに登録した語

検出した値は、ログでは先頭の数文字だけを残して伏せます。

### 拒否リスト（ローカル専用）

社名・案件名・本名・ハンドル名など、自分にとって公開できない語は、リポジトリの直下に `.sensitive-denylist.txt` を作って1行に1語ずつ書きます。
このファイルは `.gitignore` 済みで、**コミットされません**（一覧そのものが機密になるため）。

```text
# 公開できない語を1行に1語（大文字小文字は区別しない）
サンプル株式会社
sample-project
```

GitHub Actions でも同じ語を検査したい場合は、リポジトリの Settings → Secrets and variables → Actions に、`SENSITIVE_DENYLIST` という名前で同じ内容（改行区切り）を登録します。

### コミット作成者のメールアドレス

公開リポジトリでは、コミットに記録されたメールアドレスも誰でも見られます。このリポジトリでは GitHub の noreply アドレスだけを使います。

```bash
# このリポジトリだけに設定する（<ID> と <ユーザー名> は GitHub の Settings → Emails に表示される値）
git config user.email "<ID>+<ユーザー名>@users.noreply.github.com"
```

あわせて、GitHub の Settings → Emails で次の2つを有効にしておくことを推奨します。

- Keep my email addresses private
- Block command line pushes that expose my email

### push 前の手動確認

自動チェックは正規表現によるもので、表記ゆれ（全角数字、スペース区切りの電話番号、言い換えた固有名詞など）は見逃すことがあります。push の前に、差分を自分の目でも確認してください。

```bash
git diff --staged                 # これからコミットする内容
git log -p origin/main..HEAD      # これから push する内容
```

確認する観点:

- [ ] シナリオの文章は架空のもので、実際の出来事や実在の人物・組織を連想させないか
- [ ] コミットメッセージやブランチ名に、案件名や社名が入っていないか
- [ ] エラーメッセージの貼り付けに、絶対パス・ホスト名・キーが混ざっていないか
- [ ] スクリーンショットや画像を追加していないか（追加する場合は写り込みを確認）

### 万一載せてしまった場合

1. **秘密情報（API キーなど）の場合は、まずキーを失効させて再発行します。** 履歴を消しても、すでに誰かに取得されている可能性があるためです。
2. 該当のコミットが未 push なら、`git commit --amend` や `git rebase -i` で取り除きます。
3. push 済みなら、[git filter-repo](https://github.com/newren/git-filter-repo) で履歴から取り除き、force push します。
4. GitHub 上のキャッシュ（PR の差分、フォーク）に残る場合があるため、必要に応じて [GitHub Support に削除を依頼](https://docs.github.com/ja/site-policy/content-removal-policies/github-private-information-removal-policy) します。

## 開発

```bash
uv run pytest                                          # テスト
uv run pre-commit run --all-files                      # コミット前チェックを全ファイルに実行
uv run python scripts/check_sensitive.py --all --check-authors   # 個人情報チェックだけを実行
```

構成:

```text
src/jev_playground/
  scenario.py   シナリオ YAML の読み込みと検証
  client.py     Jev API の呼び出し（公式 SDK のラッパー）と答えの正規化
  runner.py     シナリオの実行、期待値との照合、結果の保存
  report.py     正答率・閾値ごとの自動処理率・費用の集計
  cli.py        コマンドライン入口
scenarios/      シナリオ（架空データのみ）
scripts/check_sensitive.py   個人情報・機密情報の検査
```

## ライセンス

[MIT](LICENSE)

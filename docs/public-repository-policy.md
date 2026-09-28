# 公開リポジトリとしての取り扱い

このリポジトリは誰でも閲覧でき、git の履歴も含めて一度公開された内容は完全には取り消せません。
以下のルールを**すべてのファイル・コミットメッセージ・ブランチ名・Issue・PR** に適用します。

## 載せてはいけないもの

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

## 使ってよい例示用の値

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

## 自動チェック

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

手動で実行する場合:

```bash
uv run python scripts/check_sensitive.py --all --check-authors
```

### フックの有効化

```bash
uv run pre-commit install
```

グローバルに `core.hooksPath` を設定していて「Cowardly refusing」と出る場合は、代わりに次を実行します。

```bash
GIT_CONFIG_GLOBAL=/dev/null uv run pre-commit install && git config --local core.hooksPath .git/hooks
```

## 拒否リスト（ローカル専用）

社名・案件名・本名・ハンドル名など、自分にとって公開できない語は、リポジトリの直下に `.sensitive-denylist.txt` を作って1行に1語ずつ書きます。
このファイルは `.gitignore` 済みで、**コミットされません**（一覧そのものが機密になるため）。

```text
# 公開できない語を1行に1語（大文字小文字は区別しない）
サンプル株式会社
sample-project
```

GitHub Actions でも同じ語を検査したい場合は、リポジトリの Settings → Secrets and variables → Actions に、`SENSITIVE_DENYLIST` という名前で同じ内容（改行区切り）を登録します。

## コミット作成者のメールアドレス

公開リポジトリでは、コミットに記録されたメールアドレスも誰でも見られます。このリポジトリでは GitHub の noreply アドレスだけを使います。

```bash
# このリポジトリだけに設定する（<ID> と <ユーザー名> は GitHub の Settings → Emails に表示される値）
git config user.email "<ID>+<ユーザー名>@users.noreply.github.com"
```

あわせて、GitHub の Settings → Emails で次の2つを有効にしておくことを推奨します。

- Keep my email addresses private
- Block command line pushes that expose my email

## push 前の手動確認

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

## 万一載せてしまった場合

1. **秘密情報（API キーなど）の場合は、まずキーを失効させて再発行します。** 履歴を消しても、すでに誰かに取得されている可能性があるためです。
2. 該当のコミットが未 push なら、`git commit --amend` や `git rebase -i` で取り除きます。
3. push 済みなら、[git filter-repo](https://github.com/newren/git-filter-repo) で履歴から取り除き、force push します。
4. GitHub 上のキャッシュ（PR の差分、フォーク）に残る場合があるため、必要に応じて [GitHub Support に削除を依頼](https://docs.github.com/ja/site-policy/content-removal-policies/github-private-information-removal-policy) します。

# シナリオの書き方

シナリオは `scenarios/` に置く YAML ファイルです。`scenarios/support_triage.yaml` が見本です。
中身は架空の合成データだけにします（[公開リポジトリとしての取り扱い](public-repository-policy.md)）。

## 書式

```yaml
scenarioId: support-triage          # 結果ファイル名に使う ID
description: 説明
model: jev-latest                   # 省略時は jev-latest
confidenceThreshold: 0.7            # 自動処理とみなす確信度。省略時は 0.7

questions:
  topic:                            # 質問名（答えのキーにもなる）
    type: choice
    instructions: この問い合わせの主な用件はどれですか？
    criteria:                       # 選択肢キー → 説明（1〜255件）
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

## 採点のルール

- `choice`: 選ばれたキーが期待値と同じなら正解
- `score`: スコアを四捨五入した段階番号が期待値と同じなら正解
- `noul`: 確率 0.5 以上を「はい」とみなし、期待値と同じなら正解。確信度は `max(p, 1 - p)` として扱う

## 出力

`run` を実行すると、次の内容を表示します。

- ケースごとの答え、確信度、期待値との一致（✓ / ✗）、レイテンシ
- 質問ごとの正答率
- 確信度の閾値（0.5 / 0.7 / 0.9 とシナリオの閾値）ごとの、自動処理率・自動処理分の正答率・エスカレーション件数
- レイテンシの中央値・平均・最大、入力トークン合計、概算費用

生のレスポンスを含む全結果は `results/<シナリオID>-<UTC時刻>.jsonl` に保存されます。`results/` はコミットされません。

終了コードは、成功が `0`、一部のケースで呼び出しが失敗した場合が `1`、シナリオや設定の誤りが `2` です。

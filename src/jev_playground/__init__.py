"""jev-playground パッケージ。

概要:
    TypeSafe AI の評価モデル Jev に対して、YAML で定義したシナリオ（state・questions・期待値）を
    実行し、答え・確率・確信度・レイテンシ・トークン数を記録・集計する。

主な仕様:
    - scenario: シナリオ YAML の読み込みと検証
    - client: Jev API 呼び出し（公式 SDK のラッパー）
    - runner: シナリオ実行と結果の保存
    - report: 正答率・閾値ごとの自動処理率の集計
    - cli: コマンドライン入口

制限事項:
    - シナリオには架空の合成データのみを入れる（docs/public-repository-policy.md を参照）。
"""

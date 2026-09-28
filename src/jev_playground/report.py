"""実行結果を集計し、人が読めるテキストのレポートを作るモジュール。

概要:
    CaseResult のリストから、質問ごとの正答率と、確信度の閾値ごとの
    「自動処理率（閾値以上の割合）」「自動処理した分の正答率」を計算する。
    あわせてレイテンシと入力トークン数、概算費用を出す。

主な仕様:
    - 閾値は 0.5 / 0.7 / 0.9 とシナリオの confidenceThreshold を、重複を除いて昇順に並べる。
    - 自動処理しなかった分（閾値未満）は、人や大きな LLM へ回す想定の件数として扱う。
    - 概算費用は「入力トークン数 × 単価」で計算する（出力は無料）。

制限事項:
    - 単価 INPUT_PRICE_PER_MILLION_TOKENS_USD は 2026年9月時点の公開価格。変わったら更新する。
    - 失敗したケースは正答率・自動処理率の分母から除き、件数だけを別に出す。
"""

from __future__ import annotations

import dataclasses
import statistics

from jev_playground.runner import CaseResult
from jev_playground.scenario import Scenario

INPUT_PRICE_PER_MILLION_TOKENS_USD: float = 0.042
"""入力100万トークンあたりの価格（米ドル、2026年9月時点の公開価格）。"""

BASE_THRESHOLDS: tuple[float, ...] = (0.5, 0.7, 0.9)
"""常にレポートに含める確信度の閾値。"""


@dataclasses.dataclass(frozen=True)
class ThresholdStat:
    """ある質問・ある閾値での集計値。

    Attributes:
        threshold (float): 確信度の閾値。
        autoCount (int): 確信度が閾値以上だった件数（自動処理する件数）。
        autoCorrectCount (int): 自動処理した中で正解だった件数。
        escalateCount (int): 閾値未満だった件数（人や大きな LLM へ回す件数）。
    """

    threshold: float
    autoCount: int
    autoCorrectCount: int
    escalateCount: int


@dataclasses.dataclass(frozen=True)
class QuestionStat:
    """1つの質問の集計値。

    Attributes:
        questionName (str): 質問名。
        judgedCount (int): 採点した件数（期待値があり、呼び出しに成功した件数）。
        correctCount (int): 正解だった件数。
        thresholdStats (list[ThresholdStat]): 閾値ごとの集計。
    """

    questionName: str
    judgedCount: int
    correctCount: int
    thresholdStats: list[ThresholdStat]


def collectThresholds(scenario: Scenario) -> list[float]:
    """レポートに使う閾値の一覧を作る。

    Args:
        scenario (Scenario): 対象のシナリオ。

    Returns:
        list[float]: 重複を除いて昇順に並べた閾値。
    """
    return sorted(set(BASE_THRESHOLDS) | {scenario.confidenceThreshold})


def summarizeQuestion(questionName: str, caseResults: list[CaseResult], thresholds: list[float]) -> QuestionStat:
    """1つの質問について正答率と閾値ごとの集計を行う。

    Args:
        questionName (str): 質問名。
        caseResults (list[CaseResult]): 実行結果。
        thresholds (list[float]): 集計する閾値。

    Returns:
        QuestionStat: 集計値。
    """
    judgedPairs: list[tuple[float, bool]] = []
    for caseResult in caseResults:
        if caseResult.error is not None or questionName not in caseResult.judgments:
            continue
        answer = caseResult.findAnswer(questionName)
        if answer is None:
            continue
        judgedPairs.append((answer.confidence, caseResult.judgments[questionName]))

    thresholdStats = []
    for threshold in thresholds:
        autoPairs = [(confidence, isCorrect) for confidence, isCorrect in judgedPairs if confidence >= threshold]
        thresholdStats.append(
            ThresholdStat(
                threshold=threshold,
                autoCount=len(autoPairs),
                autoCorrectCount=sum(1 for _, isCorrect in autoPairs if isCorrect),
                escalateCount=len(judgedPairs) - len(autoPairs),
            )
        )

    return QuestionStat(
        questionName=questionName,
        judgedCount=len(judgedPairs),
        correctCount=sum(1 for _, isCorrect in judgedPairs if isCorrect),
        thresholdStats=thresholdStats,
    )


def formatRate(numerator: int, denominator: int) -> str:
    """割合を「xx.x% (n/m)」の形の文字列にする。

    Args:
        numerator (int): 分子。
        denominator (int): 分母。

    Returns:
        str: 整形した文字列。分母が0なら「-」。
    """
    if denominator == 0:
        return "- (0/0)"
    return f"{numerator / denominator * 100:.1f}% ({numerator}/{denominator})"


def buildReport(scenario: Scenario, caseResults: list[CaseResult]) -> str:
    """集計結果をテキストのレポートにする。

    Args:
        scenario (Scenario): 対象のシナリオ。
        caseResults (list[CaseResult]): 実行結果。

    Returns:
        str: 改行区切りのレポート。
    """
    thresholds = collectThresholds(scenario)
    failedResults = [caseResult for caseResult in caseResults if caseResult.error is not None]
    succeededResults = [caseResult for caseResult in caseResults if caseResult.error is None]

    lines: list[str] = [
        f"# シナリオ: {scenario.scenarioId}",
        f"モデル: {scenario.model} / ケース数: {len(caseResults)}（成功 {len(succeededResults)}、失敗 {len(failedResults)}）",
        "",
    ]

    for caseResult in caseResults:
        if caseResult.error is not None:
            lines.append(f"- {caseResult.caseId}: 失敗 — {caseResult.error}")
            continue
        answerTexts = []
        for answer in caseResult.answers:
            valueText = f"{answer.value:.3f}" if isinstance(answer.value, float) else answer.value
            mark = ""
            if answer.questionName in caseResult.judgments:
                mark = " ✓" if caseResult.judgments[answer.questionName] else " ✗"
            answerTexts.append(f"{answer.questionName}={valueText}（確信度 {answer.confidence:.2f}）{mark}")
        lines.append(f"- {caseResult.caseId} [{caseResult.latencyMs:.0f}ms]: " + "、".join(answerTexts))

    lines.append("")
    lines.append("## 質問ごとの正答率と、閾値ごとの自動処理")
    for question in scenario.questions:
        stat = summarizeQuestion(question.name, caseResults, thresholds)
        lines.append(f"### {question.name}（{question.type}）: 正答率 {formatRate(stat.correctCount, stat.judgedCount)}")
        for thresholdStat in stat.thresholdStats:
            marker = " ← シナリオの閾値" if thresholdStat.threshold == scenario.confidenceThreshold else ""
            lines.append(
                f"- 閾値 {thresholdStat.threshold:.2f}: "
                f"自動処理 {formatRate(thresholdStat.autoCount, stat.judgedCount)}、"
                f"自動処理分の正答率 {formatRate(thresholdStat.autoCorrectCount, thresholdStat.autoCount)}、"
                f"エスカレーション {thresholdStat.escalateCount} 件{marker}"
            )

    latencies = [caseResult.latencyMs for caseResult in succeededResults if caseResult.latencyMs is not None]
    tokenCounts = [caseResult.inputTokens for caseResult in succeededResults if caseResult.inputTokens is not None]
    lines.append("")
    lines.append("## レイテンシと費用")
    if latencies:
        lines.append(
            f"- レイテンシ: 中央値 {statistics.median(latencies):.0f}ms、"
            f"平均 {statistics.mean(latencies):.0f}ms、最大 {max(latencies):.0f}ms"
        )
    else:
        lines.append("- レイテンシ: 計測値なし")
    totalTokens = sum(tokenCounts)
    estimatedCost = totalTokens / 1_000_000 * INPUT_PRICE_PER_MILLION_TOKENS_USD
    lines.append(
        f"- 入力トークン合計: {totalTokens}（{len(tokenCounts)} 件分）、"
        f"概算費用: ${estimatedCost:.6f}（${INPUT_PRICE_PER_MILLION_TOKENS_USD}/100万トークンで計算）"
    )
    return "\n".join(lines)

"""client の正規化処理、runner の照合・保存、report の集計のテスト。

概要:
    Jev を呼ぶ代わりに、決まった答えを返すテスト用の Evaluator を使って、
    正誤判定・閾値ごとの集計・結果の保存・エラー時の継続を確認する。

制限事項:
    - API は呼ばない。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from jev_playground.client import AnswerRecord, EvaluationResult, JevCallError, maskSecret, normalizeAnswer
from jev_playground.report import buildReport, summarizeQuestion
from jev_playground.runner import roundHalfUp, runScenario, saveResults
from jev_playground.scenario import QuestionSpec, parseScenario


class FixedEvaluator:
    """state に対応する決まった答えを返すテスト用の Evaluator。

    Attributes:
        answersByState (dict[str, list[AnswerRecord] | None]): state → 返す答え。None なら失敗させる。
    """

    def __init__(self, answersByState: dict[str, list[AnswerRecord] | None]) -> None:
        """返す答えを受け取る。

        Args:
            answersByState (dict[str, list[AnswerRecord] | None]): state → 返す答え。None なら失敗させる。
        """
        self.answersByState = answersByState

    def evaluate(self, state: Any, questions: list[QuestionSpec], model: str) -> EvaluationResult:
        """決まった答えを返す。

        Args:
            state (Any): 入力（答えの選択に使う）。
            questions (list[QuestionSpec]): 質問（使わない）。
            model (str): モデル名。

        Returns:
            EvaluationResult: 決まった答え。

        Raises:
            JevCallError: 答えが None に設定されている場合。
        """
        answers = self.answersByState[state]
        if answers is None:
            raise JevCallError("FixedEvaluator.evaluate: テスト用の失敗")
        return EvaluationResult(model=model, answers=answers, latencyMs=100.0, inputTokens=50, rawResponse={"ok": True})


def buildScenario() -> Any:
    """テスト用のシナリオを作る。

    Returns:
        Scenario: 3ケースのシナリオ。
    """
    return parseScenario(
        {
            "scenarioId": "unit",
            "confidenceThreshold": 0.8,
            "questions": {
                "topic": {"type": "choice", "instructions": "用件は？", "criteria": {"a": "A", "b": "B"}},
                "level": {"type": "score", "instructions": "程度は？", "criteria": ["低", "中", "高"]},
                "flag": {"type": "noul", "instructions": "該当する？"},
            },
            "cases": [
                {"caseId": "right", "state": "s1", "expected": {"topic": "a", "level": 2, "flag": True}},
                {"caseId": "wrong", "state": "s2", "expected": {"topic": "a", "level": 0, "flag": False}},
                {"caseId": "broken", "state": "s3", "expected": {"topic": "b"}},
            ],
        },
        pathlib.Path("unit.yaml"),
    )


def buildAnswers(topic: str, topicConfidence: float, level: float, flagProbability: float) -> list[AnswerRecord]:
    """3つの質問の答えを作る。

    Args:
        topic (str): choice の答え。
        topicConfidence (float): choice の確信度。
        level (float): score の答え。
        flagProbability (float): noul の「はい」の確率。

    Returns:
        list[AnswerRecord]: 答えの一覧。
    """
    return [
        AnswerRecord("topic", "choice", topic, topicConfidence, {topic: topicConfidence}),
        AnswerRecord("level", "score", level, 0.9, {"0": 0.05, "1": 0.05, "2": 0.9}),
        normalizeAnswer("flag", {"type": "noul", "noul": flagProbability}),
    ]


def testNormalizeNoulUsesDistanceFromHalfAsConfidence() -> None:
    """noul の確信度が max(p, 1 - p) になることを確認する。"""
    answer = normalizeAnswer("flag", {"type": "noul", "noul": 0.2})
    assert answer.confidence == pytest.approx(0.8)
    assert answer.probabilities == {"true": 0.2, "false": pytest.approx(0.8)}


def testNormalizeRejectsMalformedAnswer() -> None:
    """必要な項目が無い答えが、質問名を含む JevCallError になることを確認する。"""
    with pytest.raises(JevCallError, match="question=topic"):
        normalizeAnswer("topic", {"type": "choice", "confidence": 0.5})


def testMaskSecretHidesValue() -> None:
    """秘密情報がマスクされることを確認する。"""
    assert "abc123" not in maskSecret("key=abc123 failed", "abc123")


def testRoundHalfUp() -> None:
    """四捨五入が偶数丸めにならないことを確認する。"""
    assert roundHalfUp(2.5) == 3
    assert roundHalfUp(1.49) == 1


def testRunScenarioJudgesAndContinuesAfterFailure(tmp_path: pathlib.Path) -> None:
    """正誤判定・失敗時の継続・結果の保存・集計がそろって動くことを確認する。

    Args:
        tmp_path (pathlib.Path): pytest が用意する一時ディレクトリ。
    """
    scenario = buildScenario()
    evaluator = FixedEvaluator(
        {
            "s1": buildAnswers("a", 0.95, 1.6, 0.9),
            "s2": buildAnswers("b", 0.6, 1.2, 0.7),
            "s3": None,
        }
    )

    caseResults = runScenario(scenario, evaluator)

    assert [result.caseId for result in caseResults] == ["right", "wrong", "broken"]
    assert caseResults[0].judgments == {"topic": True, "level": True, "flag": True}
    assert caseResults[1].judgments == {"topic": False, "level": False, "flag": False}
    assert caseResults[2].error is not None and "caseId=broken" in caseResults[2].error

    topicStat = summarizeQuestion("topic", caseResults, [0.5, 0.8])
    assert (topicStat.judgedCount, topicStat.correctCount) == (2, 1)
    assert [(stat.autoCount, stat.autoCorrectCount, stat.escalateCount) for stat in topicStat.thresholdStats] == [
        (2, 1, 0),
        (1, 1, 1),
    ]

    report = buildReport(scenario, caseResults)
    assert "失敗 1" in report
    assert "← シナリオの閾値" in report

    outputPath = saveResults(scenario, caseResults, tmp_path)
    records = [json.loads(line) for line in outputPath.read_text(encoding="utf-8").splitlines()]
    assert [record["caseId"] for record in records] == ["right", "wrong", "broken"]
    assert records[0]["rawResponse"] == {"ok": True}
    assert records[2]["error"] is not None

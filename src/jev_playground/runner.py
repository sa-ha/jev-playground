"""シナリオの全ケースを Jev で評価し、期待値と照合して結果を保存するモジュール。

概要:
    Scenario の各ケースを Evaluator に渡し、答えを期待値と照合した CaseResult を作る。
    結果は1ケース1行の JSONL として results/ 以下に保存する。

主な仕様:
    - 照合ルール:
        - choice: 選ばれたキーが期待値と一致すれば正解。
        - score: 小数のスコアを四捨五入した段階番号が期待値と一致すれば正解。
        - noul: 確率 0.5 以上を「はい」とみなし、期待値（真偽）と一致すれば正解。
    - あるケースで呼び出しに失敗しても、エラーを記録して残りのケースを続ける。
    - 保存ファイル名は「<scenarioId>-<UTC時刻>.jsonl」。

制限事項:
    - 保存先 results/ は .gitignore 済み。架空データ由来でもコミットしない。
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import math
import pathlib
from typing import Any

from jev_playground.client import AnswerRecord, Evaluator, JevCallError
from jev_playground.scenario import CaseSpec, QuestionSpec, Scenario


@dataclasses.dataclass(frozen=True)
class CaseResult:
    """1ケース分の実行結果。

    Attributes:
        caseId (str): ケース ID。
        model (str | None): 実際に使われたモデル名。失敗時は None。
        latencyMs (float | None): レイテンシ（ミリ秒）。失敗時は None。
        inputTokens (int | None): 入力トークン数。返らない・失敗時は None。
        answers (list[AnswerRecord]): 質問ごとの答え。失敗時は空。
        judgments (dict[str, bool]): 質問名 → 正解か。期待値がある質問のみ。
        error (str | None): 失敗時のエラーメッセージ。成功時は None。
        rawResponse (dict[str, Any] | None): Jev の生レスポンス。失敗時は None。
    """

    caseId: str
    model: str | None
    latencyMs: float | None
    inputTokens: int | None
    answers: list[AnswerRecord]
    judgments: dict[str, bool]
    error: str | None
    rawResponse: dict[str, Any] | None

    def findAnswer(self, questionName: str) -> AnswerRecord | None:
        """質問名から答えを取り出す。

        Args:
            questionName (str): 質問名。

        Returns:
            AnswerRecord | None: 該当する答え。無ければ None。
        """
        for answer in self.answers:
            if answer.questionName == questionName:
                return answer
        return None


def roundHalfUp(value: float) -> int:
    """小数を四捨五入して整数にする（Python 標準の round の偶数丸めを避ける）。

    Args:
        value (float): 対象の値。

    Returns:
        int: 四捨五入した整数。
    """
    return int(math.floor(value + 0.5))


def judgeAnswer(question: QuestionSpec, answer: AnswerRecord, expectedValue: str | int | bool) -> bool:
    """1つの答えが期待値と一致するか判定する。

    Args:
        question (QuestionSpec): 質問定義。
        answer (AnswerRecord): Jev の答え。
        expectedValue (str | int | bool): 期待する答え。

    Returns:
        bool: 一致すれば True。

    Raises:
        JevCallError: 質問と答えの型が食い違う場合。
    """
    if question.type != answer.type:
        raise JevCallError(
            f"judgeAnswer: 質問と答えの型が一致しません（question={question.name}、"
            f"質問の型={question.type}、答えの型={answer.type}）"
        )
    if question.type == "choice":
        return answer.value == expectedValue
    if question.type == "score":
        return roundHalfUp(float(answer.value)) == expectedValue
    return (float(answer.value) >= 0.5) == expectedValue


def runCase(scenario: Scenario, case: CaseSpec, evaluator: Evaluator) -> CaseResult:
    """1ケースを評価し、期待値と照合する。

    Args:
        scenario (Scenario): 対象のシナリオ。
        case (CaseSpec): 対象のケース。
        evaluator (Evaluator): 評価を行うもの（通常は JevClient）。

    Returns:
        CaseResult: 実行結果。失敗時は error に詳細が入る。
    """
    try:
        evaluation = evaluator.evaluate(case.state, scenario.questions, scenario.model)
    except JevCallError as error:
        return CaseResult(
            caseId=case.caseId,
            model=None,
            latencyMs=None,
            inputTokens=None,
            answers=[],
            judgments={},
            error=f"runCase(scenarioId={scenario.scenarioId}, caseId={case.caseId}): {error}",
            rawResponse=None,
        )

    answersByName = {answer.questionName: answer for answer in evaluation.answers}
    judgments = {
        questionName: judgeAnswer(scenario.findQuestion(questionName), answersByName[questionName], expectedValue)
        for questionName, expectedValue in case.expected.items()
    }
    return CaseResult(
        caseId=case.caseId,
        model=evaluation.model,
        latencyMs=evaluation.latencyMs,
        inputTokens=evaluation.inputTokens,
        answers=evaluation.answers,
        judgments=judgments,
        error=None,
        rawResponse=evaluation.rawResponse,
    )


def runScenario(scenario: Scenario, evaluator: Evaluator) -> list[CaseResult]:
    """シナリオの全ケースを順に評価する。

    Args:
        scenario (Scenario): 対象のシナリオ。
        evaluator (Evaluator): 評価を行うもの。

    Returns:
        list[CaseResult]: ケースの順に並んだ実行結果。
    """
    return [runCase(scenario, case, evaluator) for case in scenario.cases]


def buildResultRecord(scenario: Scenario, case: CaseSpec, caseResult: CaseResult) -> dict[str, Any]:
    """保存用に1ケース分の結果を辞書にまとめる。

    Args:
        scenario (Scenario): 対象のシナリオ。
        case (CaseSpec): 対象のケース。
        caseResult (CaseResult): 実行結果。

    Returns:
        dict[str, Any]: JSON に変換できる辞書。
    """
    return {
        "scenarioId": scenario.scenarioId,
        "caseId": case.caseId,
        "requestedModel": scenario.model,
        "model": caseResult.model,
        "latencyMs": caseResult.latencyMs,
        "inputTokens": caseResult.inputTokens,
        "state": case.state,
        "expected": case.expected,
        "answers": [dataclasses.asdict(answer) for answer in caseResult.answers],
        "judgments": caseResult.judgments,
        "error": caseResult.error,
        "rawResponse": caseResult.rawResponse,
    }


def saveResults(scenario: Scenario, caseResults: list[CaseResult], resultsDir: str | pathlib.Path) -> pathlib.Path:
    """実行結果を JSONL ファイルに保存する。

    Args:
        scenario (Scenario): 対象のシナリオ。
        caseResults (list[CaseResult]): runScenario の戻り値（ケース順）。
        resultsDir (str | pathlib.Path): 保存先ディレクトリ。無ければ作る。

    Returns:
        pathlib.Path: 保存したファイルのパス。

    Raises:
        OSError: ディレクトリ作成や書き込みに失敗した場合（呼び出し元でパスを表示する）。
    """
    outputDir = pathlib.Path(resultsDir)
    outputDir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    outputPath = outputDir / f"{scenario.scenarioId}-{timestamp}.jsonl"

    casesById = {case.caseId: case for case in scenario.cases}
    with outputPath.open("w", encoding="utf-8") as outputFile:
        for caseResult in caseResults:
            record = buildResultRecord(scenario, casesById[caseResult.caseId], caseResult)
            outputFile.write(json.dumps(record, ensure_ascii=False) + "\n")
    return outputPath

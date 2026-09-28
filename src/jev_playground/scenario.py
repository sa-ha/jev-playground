"""シナリオ定義（YAML）を読み込み、Jev に送れる形か検証するモジュール。

概要:
    1つのシナリオは「共通の質問（questions）」と「複数のケース（cases）」から成る。
    各ケースは Jev に渡す state と、質問ごとの期待する答え（expected）を持つ。

主な仕様:
    - 質問の型は choice / score / noul の3種類。
    - choice: criteria は「選択肢キー → 説明」の辞書（1〜255件）。期待値は選択肢キー。
    - score: criteria は段階説明のリスト（2〜10件、低い順）。期待値は段階の番号（0始まりの整数）。
    - noul: criteria は省略可、または {true: 説明, false: 説明}。期待値は真偽値。
    - expected に書かれていない質問は採点対象外（答えだけ記録する）。

制限事項:
    - 構文と値の範囲だけを検証する。内容が架空データかどうかは scripts/check_sensitive.py で検査する。
"""

from __future__ import annotations

import dataclasses
import pathlib
from typing import Any

import yaml

VALID_QUESTION_TYPES: tuple[str, ...] = ("choice", "score", "noul")
"""使用できる質問の型。"""

MAX_CHOICE_OPTIONS: int = 255
"""choice の選択肢の上限（Jev の仕様）。"""

MIN_SCORE_LEVELS: int = 2
"""score の段階数の下限（Jev の仕様）。"""

MAX_SCORE_LEVELS: int = 10
"""score の段階数の上限（Jev の仕様）。"""

DEFAULT_MODEL: str = "jev-latest"
"""シナリオに model が無い場合に使うモデル名。"""

DEFAULT_CONFIDENCE_THRESHOLD: float = 0.7
"""シナリオに confidenceThreshold が無い場合に使う、自動処理とみなす確信度の閾値。"""


class ScenarioError(ValueError):
    """シナリオ YAML の内容が不正なときに送出する例外。"""


@dataclasses.dataclass(frozen=True)
class QuestionSpec:
    """1つの質問の定義。

    Attributes:
        name (str): 質問名。Jev の questions のキーとレスポンスの answers のキーになる。
        type (str): 質問の型（"choice" / "score" / "noul"）。
        instructions (str): Jev に渡す質問文。
        criteria (dict[str, str] | list[str] | None): 型ごとの選択肢・段階・真偽の説明。
    """

    name: str
    type: str
    instructions: str
    criteria: dict[str, str] | list[str] | None


@dataclasses.dataclass(frozen=True)
class CaseSpec:
    """1つのケース（Jev への1リクエスト分）の定義。

    Attributes:
        caseId (str): シナリオ内で一意なケース ID。
        state (str | dict[str, Any] | list[Any]): Jev に渡す入力。架空データのみ。
        expected (dict[str, str | int | bool]): 質問名 → 期待する答え。
    """

    caseId: str
    state: str | dict[str, Any] | list[Any]
    expected: dict[str, str | int | bool]


@dataclasses.dataclass(frozen=True)
class Scenario:
    """シナリオ全体の定義。

    Attributes:
        scenarioId (str): シナリオ ID。結果ファイル名に使う。
        description (str): シナリオの説明。
        model (str): 使用する Jev のモデル名（例: "jev-latest"）。
        confidenceThreshold (float): 自動処理とみなす確信度の閾値（0〜1）。
        questions (list[QuestionSpec]): 全ケース共通の質問。
        cases (list[CaseSpec]): ケースの一覧。
        sourcePath (pathlib.Path): 読み込み元の YAML ファイルのパス。
    """

    scenarioId: str
    description: str
    model: str
    confidenceThreshold: float
    questions: list[QuestionSpec]
    cases: list[CaseSpec]
    sourcePath: pathlib.Path

    def findQuestion(self, questionName: str) -> QuestionSpec:
        """質問名から質問定義を取り出す。

        Args:
            questionName (str): 質問名。

        Returns:
            QuestionSpec: 該当する質問定義。

        Raises:
            ScenarioError: 該当する質問が無い場合。
        """
        for question in self.questions:
            if question.name == questionName:
                return question
        raise ScenarioError(
            f"Scenario.findQuestion: 質問 '{questionName}' がシナリオ '{self.scenarioId}' に存在しません"
            f"（定義済み: {[q.name for q in self.questions]}、ファイル: {self.sourcePath}）"
        )


def loadScenario(scenarioPath: str | pathlib.Path) -> Scenario:
    """シナリオ YAML を読み込み、検証済みの Scenario を返す。

    Args:
        scenarioPath (str | pathlib.Path): シナリオ YAML のパス。

    Returns:
        Scenario: 検証済みのシナリオ。

    Raises:
        ScenarioError: ファイルが読めない、または内容が仕様に合わない場合。
    """
    path = pathlib.Path(scenarioPath)
    try:
        rawText = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ScenarioError(f"loadScenario: ファイルを読めません（path={path}）: {error}") from error

    try:
        rawData = yaml.safe_load(rawText)
    except yaml.YAMLError as error:
        raise ScenarioError(f"loadScenario: YAML の構文エラー（path={path}）: {error}") from error

    if not isinstance(rawData, dict):
        raise ScenarioError(
            f"loadScenario: 最上位は辞書である必要があります（path={path}、実際の型={type(rawData).__name__}）"
        )

    return parseScenario(rawData, path)


def parseScenario(rawData: dict[str, Any], sourcePath: pathlib.Path) -> Scenario:
    """YAML から読んだ辞書を検証し、Scenario に変換する。

    Args:
        rawData (dict[str, Any]): YAML の最上位の辞書。
        sourcePath (pathlib.Path): エラーメッセージに出す読み込み元のパス。

    Returns:
        Scenario: 検証済みのシナリオ。

    Raises:
        ScenarioError: 必須項目の欠落、型の誤り、値の範囲外がある場合。
    """
    location = f"path={sourcePath}"

    scenarioId = requireString(rawData, "scenarioId", location)
    description = str(rawData.get("description", ""))
    model = str(rawData.get("model", DEFAULT_MODEL))

    confidenceThreshold = rawData.get("confidenceThreshold", DEFAULT_CONFIDENCE_THRESHOLD)
    if not isinstance(confidenceThreshold, (int, float)) or not 0.0 <= float(confidenceThreshold) <= 1.0:
        raise ScenarioError(
            f"parseScenario: confidenceThreshold は 0〜1 の数値である必要があります"
            f"（{location}、値={confidenceThreshold!r}）"
        )

    rawQuestions = rawData.get("questions")
    if not isinstance(rawQuestions, dict) or not rawQuestions:
        raise ScenarioError(f"parseScenario: questions は1件以上の辞書である必要があります（{location}）")
    questions = [
        parseQuestion(questionName, rawQuestion, location)
        for questionName, rawQuestion in rawQuestions.items()
    ]

    rawCases = rawData.get("cases")
    if not isinstance(rawCases, list) or not rawCases:
        raise ScenarioError(f"parseScenario: cases は1件以上のリストである必要があります（{location}）")
    questionsByName = {question.name: question for question in questions}
    cases = [parseCase(index, rawCase, questionsByName, location) for index, rawCase in enumerate(rawCases)]

    caseIds = [case.caseId for case in cases]
    duplicatedIds = sorted({caseId for caseId in caseIds if caseIds.count(caseId) > 1})
    if duplicatedIds:
        raise ScenarioError(f"parseScenario: caseId が重複しています（{location}、重複={duplicatedIds}）")

    return Scenario(
        scenarioId=scenarioId,
        description=description,
        model=model,
        confidenceThreshold=float(confidenceThreshold),
        questions=questions,
        cases=cases,
        sourcePath=sourcePath,
    )


def parseQuestion(questionName: str, rawQuestion: Any, location: str) -> QuestionSpec:
    """1つの質問定義を検証し、QuestionSpec に変換する。

    Args:
        questionName (str): 質問名（questions のキー）。
        rawQuestion (Any): 質問定義の辞書。
        location (str): エラーメッセージに出す位置情報。

    Returns:
        QuestionSpec: 検証済みの質問定義。

    Raises:
        ScenarioError: 型や criteria が仕様に合わない場合。
    """
    questionLocation = f"{location}、question={questionName}"
    if not isinstance(rawQuestion, dict):
        raise ScenarioError(f"parseQuestion: 質問定義は辞書である必要があります（{questionLocation}）")

    questionType = rawQuestion.get("type")
    if questionType not in VALID_QUESTION_TYPES:
        raise ScenarioError(
            f"parseQuestion: type は {VALID_QUESTION_TYPES} のいずれかである必要があります"
            f"（{questionLocation}、値={questionType!r}）"
        )

    instructions = requireString(rawQuestion, "instructions", questionLocation)
    criteria = rawQuestion.get("criteria")

    if questionType == "choice":
        if not isinstance(criteria, dict) or not 1 <= len(criteria) <= MAX_CHOICE_OPTIONS:
            raise ScenarioError(
                f"parseQuestion: choice の criteria は 1〜{MAX_CHOICE_OPTIONS} 件の辞書である必要があります"
                f"（{questionLocation}）"
            )
        criteria = {str(optionKey): str(optionText) for optionKey, optionText in criteria.items()}
    elif questionType == "score":
        if not isinstance(criteria, list) or not MIN_SCORE_LEVELS <= len(criteria) <= MAX_SCORE_LEVELS:
            raise ScenarioError(
                f"parseQuestion: score の criteria は {MIN_SCORE_LEVELS}〜{MAX_SCORE_LEVELS} 件のリストである必要があります"
                f"（{questionLocation}）"
            )
        criteria = [str(levelText) for levelText in criteria]
    else:
        if criteria is not None:
            if not isinstance(criteria, dict) or not set(criteria).issubset({"true", "false"}):
                raise ScenarioError(
                    f"parseQuestion: noul の criteria は省略するか、キーが true / false の辞書である必要があります"
                    f"（{questionLocation}、キー={list(criteria) if isinstance(criteria, dict) else criteria!r}）"
                )
            criteria = {str(key): str(value) for key, value in criteria.items()}

    return QuestionSpec(name=questionName, type=questionType, instructions=instructions, criteria=criteria)


def parseCase(
    caseIndex: int,
    rawCase: Any,
    questionsByName: dict[str, QuestionSpec],
    location: str,
) -> CaseSpec:
    """1つのケース定義を検証し、CaseSpec に変換する。

    Args:
        caseIndex (int): cases リスト内の位置（エラーメッセージ用）。
        rawCase (Any): ケース定義の辞書。
        questionsByName (dict[str, QuestionSpec]): 質問名 → 質問定義。
        location (str): エラーメッセージに出す位置情報。

    Returns:
        CaseSpec: 検証済みのケース定義。

    Raises:
        ScenarioError: 必須項目の欠落や、期待値が質問の型に合わない場合。
    """
    caseLocation = f"{location}、cases[{caseIndex}]"
    if not isinstance(rawCase, dict):
        raise ScenarioError(f"parseCase: ケース定義は辞書である必要があります（{caseLocation}）")

    caseId = requireString(rawCase, "caseId", caseLocation)
    caseLocation = f"{caseLocation}、caseId={caseId}"

    state = rawCase.get("state")
    if not isinstance(state, (str, dict, list)) or not state:
        raise ScenarioError(
            f"parseCase: state は空でない文字列・辞書・リストのいずれかである必要があります（{caseLocation}）"
        )

    rawExpected = rawCase.get("expected", {})
    if not isinstance(rawExpected, dict):
        raise ScenarioError(f"parseCase: expected は辞書である必要があります（{caseLocation}）")

    expected: dict[str, str | int | bool] = {}
    for questionName, expectedValue in rawExpected.items():
        question = questionsByName.get(questionName)
        if question is None:
            raise ScenarioError(
                f"parseCase: expected に未定義の質問 '{questionName}' があります"
                f"（{caseLocation}、定義済み: {sorted(questionsByName)}）"
            )
        expected[questionName] = validateExpectedValue(question, expectedValue, caseLocation)

    return CaseSpec(caseId=caseId, state=state, expected=expected)


def validateExpectedValue(question: QuestionSpec, expectedValue: Any, caseLocation: str) -> str | int | bool:
    """期待値が質問の型に合っているか検証する。

    Args:
        question (QuestionSpec): 対象の質問定義。
        expectedValue (Any): YAML に書かれた期待値。
        caseLocation (str): エラーメッセージに出す位置情報。

    Returns:
        str | int | bool: 検証済みの期待値。

    Raises:
        ScenarioError: 期待値が型に合わない、または範囲外の場合。
    """
    valueLocation = f"{caseLocation}、question={question.name}、値={expectedValue!r}"

    if question.type == "choice":
        assert isinstance(question.criteria, dict)
        if not isinstance(expectedValue, str) or expectedValue not in question.criteria:
            raise ScenarioError(
                f"validateExpectedValue: choice の期待値は選択肢キー {sorted(question.criteria)} のいずれかである必要があります"
                f"（{valueLocation}）"
            )
        return expectedValue

    if question.type == "score":
        assert isinstance(question.criteria, list)
        levelCount = len(question.criteria)
        if isinstance(expectedValue, bool) or not isinstance(expectedValue, int) or not 0 <= expectedValue < levelCount:
            raise ScenarioError(
                f"validateExpectedValue: score の期待値は 0〜{levelCount - 1} の整数である必要があります（{valueLocation}）"
            )
        return expectedValue

    if not isinstance(expectedValue, bool):
        raise ScenarioError(f"validateExpectedValue: noul の期待値は true / false である必要があります（{valueLocation}）")
    return expectedValue


def requireString(rawData: dict[str, Any], key: str, location: str) -> str:
    """辞書から空でない文字列を取り出す。

    Args:
        rawData (dict[str, Any]): 取り出し元の辞書。
        key (str): キー名。
        location (str): エラーメッセージに出す位置情報。

    Returns:
        str: 取り出した文字列。

    Raises:
        ScenarioError: キーが無い、または空でない文字列ではない場合。
    """
    value = rawData.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ScenarioError(f"requireString: '{key}' は空でない文字列である必要があります（{location}、値={value!r}）")
    return value

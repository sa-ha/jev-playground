"""Jev API を呼び出し、答えを扱いやすい形に正規化するモジュール。

概要:
    公式 SDK（typesafe-sdk）の TypeSafeClient.system_one を呼び、
    レスポンスを AnswerRecord のリストと生レスポンス（dict）に変換する。

主な仕様:
    - API キーは環境変数 TYPESAFE_API_KEY から読む（コードや設定ファイルには書かない）。
    - レイテンシは呼び出し前後の経過時間（ミリ秒）で計測する。
    - noul は確率 p だけが返るため、確信度は max(p, 1 - p) として扱う。
    - 例外は JevCallError に包み、関数名・モデル・質問名・HTTP ステータス・レスポンス本文を含める。
      API キーはメッセージ中でマスクする。

制限事項:
    - SDK のリトライ設定は既定値のまま使う。
    - 画像などテキスト以外の入力は扱わない（Jev の仕様）。
"""

from __future__ import annotations

import dataclasses
import os
import time
from typing import Any, Protocol

from typesafe_sdk import Choice, Noul, Score, TypeSafeAPIError, TypeSafeClient, TypeSafeError
from typesafe_sdk.constants import API_KEY_ENV

from jev_playground.scenario import QuestionSpec

MASKED_TEXT: str = "***MASKED***"
"""秘密情報を置き換える文字列。"""


class JevCallError(RuntimeError):
    """Jev の呼び出しに失敗したときに送出する例外。"""


@dataclasses.dataclass(frozen=True)
class AnswerRecord:
    """1つの質問に対する正規化済みの答え。

    Attributes:
        questionName (str): 質問名。
        type (str): 質問の型（"choice" / "score" / "noul"）。
        value (str | float): choice は選んだキー、score は小数のスコア、noul は「はい」の確率。
        confidence (float): 確信度（0〜1）。noul は max(p, 1 - p)。
        probabilities (dict[str, float]): 選択肢・段階ごとの確率。noul は {"true": p, "false": 1 - p}。
    """

    questionName: str
    type: str
    value: str | float
    confidence: float
    probabilities: dict[str, float]


@dataclasses.dataclass(frozen=True)
class EvaluationResult:
    """1リクエスト分の評価結果。

    Attributes:
        model (str): 実際に使われたモデル名（レスポンスの model）。
        answers (list[AnswerRecord]): 質問ごとの答え。
        latencyMs (float): 呼び出しにかかった時間（ミリ秒）。
        inputTokens (int | None): 入力トークン数。返らない場合は None。
        rawResponse (dict[str, Any]): レスポンス全体（保存用）。
    """

    model: str
    answers: list[AnswerRecord]
    latencyMs: float
    inputTokens: int | None
    rawResponse: dict[str, Any]


class Evaluator(Protocol):
    """state と質問を受け取り評価結果を返すものの共通インターフェース（テストで差し替え可能）。"""

    def evaluate(
        self,
        state: str | dict[str, Any] | list[Any],
        questions: list[QuestionSpec],
        model: str,
    ) -> EvaluationResult:
        """state を質問群で評価する。

        Args:
            state (str | dict[str, Any] | list[Any]): 評価対象の入力。
            questions (list[QuestionSpec]): 質問の一覧。
            model (str): 使用するモデル名。

        Returns:
            EvaluationResult: 評価結果。
        """
        ...


def maskSecret(text: str, secret: str | None) -> str:
    """文字列中の秘密情報をマスクする。

    Args:
        text (str): 対象の文字列。
        secret (str | None): マスクしたい値。None や空文字なら何もしない。

    Returns:
        str: マスク後の文字列。
    """
    if not secret:
        return text
    return text.replace(secret, MASKED_TEXT)


def buildSdkQuestions(questions: list[QuestionSpec]) -> dict[str, Choice | Score | Noul]:
    """QuestionSpec のリストを SDK の質問オブジェクトの辞書に変換する。

    Args:
        questions (list[QuestionSpec]): 質問の一覧。

    Returns:
        dict[str, Choice | Score | Noul]: 質問名 → SDK の質問オブジェクト。

    Raises:
        JevCallError: 未知の質問の型が含まれる場合。
    """
    sdkQuestions: dict[str, Choice | Score | Noul] = {}
    for question in questions:
        if question.type == "choice":
            sdkQuestions[question.name] = Choice(instructions=question.instructions, criteria=question.criteria)
        elif question.type == "score":
            sdkQuestions[question.name] = Score(instructions=question.instructions, criteria=question.criteria)
        elif question.type == "noul":
            sdkQuestions[question.name] = Noul(instructions=question.instructions, criteria=question.criteria)
        else:
            raise JevCallError(
                f"buildSdkQuestions: 未知の質問の型です（question={question.name}、type={question.type!r}）"
            )
    return sdkQuestions


def normalizeAnswer(questionName: str, rawAnswer: dict[str, Any]) -> AnswerRecord:
    """SDK のレスポンス中の1つの答え（dict 化したもの）を AnswerRecord に変換する。

    Args:
        questionName (str): 質問名。
        rawAnswer (dict[str, Any]): 答えの辞書（type・choice/score/noul・confidence・probabilities を含む）。

    Returns:
        AnswerRecord: 正規化済みの答え。

    Raises:
        JevCallError: 答えの型が未知、または必要な項目が無い場合。
    """
    answerType = rawAnswer.get("type")
    try:
        if answerType == "choice":
            return AnswerRecord(
                questionName=questionName,
                type="choice",
                value=str(rawAnswer["choice"]),
                confidence=float(rawAnswer["confidence"]),
                probabilities={str(key): float(value) for key, value in rawAnswer["probabilities"].items()},
            )
        if answerType == "score":
            return AnswerRecord(
                questionName=questionName,
                type="score",
                value=float(rawAnswer["score"]),
                confidence=float(rawAnswer["confidence"]),
                probabilities={str(key): float(value) for key, value in rawAnswer["probabilities"].items()},
            )
        if answerType == "noul":
            yesProbability = float(rawAnswer["noul"])
            return AnswerRecord(
                questionName=questionName,
                type="noul",
                value=yesProbability,
                confidence=max(yesProbability, 1.0 - yesProbability),
                probabilities={"true": yesProbability, "false": 1.0 - yesProbability},
            )
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise JevCallError(
            f"normalizeAnswer: 答えの形式が想定と異なります（question={questionName}、answer={rawAnswer!r}）: {error!r}"
        ) from error

    raise JevCallError(f"normalizeAnswer: 未知の答えの型です（question={questionName}、type={answerType!r}）")


class JevClient:
    """公式 SDK を使って Jev を呼び出す Evaluator の実装。

    Attributes:
        timeoutSeconds (float): 1回の HTTP 操作のタイムアウト（秒）。
    """

    def __init__(self, timeoutSeconds: float = 10.0) -> None:
        """環境変数から API キーを読み、SDK クライアントを用意する。

        Args:
            timeoutSeconds (float): 1回の HTTP 操作のタイムアウト（秒）。

        Raises:
            JevCallError: 環境変数 TYPESAFE_API_KEY が未設定の場合。
        """
        apiKey = os.environ.get(API_KEY_ENV, "").strip()
        if not apiKey:
            raise JevCallError(
                f"JevClient.__init__: 環境変数 {API_KEY_ENV} が未設定です。"
                f"`.env.example` を `.env` にコピーして値を入れ、`uv run --env-file .env ...` で実行してください"
            )
        self._apiKey: str = apiKey
        self.timeoutSeconds: float = timeoutSeconds
        self._sdkClient: TypeSafeClient = TypeSafeClient(api_key=apiKey, timeout=timeoutSeconds)

    def evaluate(
        self,
        state: str | dict[str, Any] | list[Any],
        questions: list[QuestionSpec],
        model: str,
    ) -> EvaluationResult:
        """Jev に state と質問を送り、評価結果を返す。

        Args:
            state (str | dict[str, Any] | list[Any]): 評価対象の入力。
            questions (list[QuestionSpec]): 質問の一覧。
            model (str): 使用するモデル名（例: "jev-latest"）。

        Returns:
            EvaluationResult: 評価結果。

        Raises:
            JevCallError: API 呼び出しに失敗した、またはレスポンスが想定と異なる場合。
        """
        questionNames = [question.name for question in questions]
        sdkQuestions = buildSdkQuestions(questions)

        startTime = time.perf_counter()
        try:
            response = self._sdkClient.system_one(state=state, questions=sdkQuestions, model=model)
        except TypeSafeAPIError as error:
            detail = (
                f"JevClient.evaluate: Jev API がエラーを返しました"
                f"（model={model}、questions={questionNames}、status={error.status}、"
                f"endpoint={error.endpoint}、body={error.body!r}）: {error}"
            )
            raise JevCallError(maskSecret(detail, self._apiKey)) from error
        except TypeSafeError as error:
            detail = (
                f"JevClient.evaluate: Jev の呼び出しに失敗しました"
                f"（model={model}、questions={questionNames}、timeout={self.timeoutSeconds}s）: "
                f"{type(error).__name__}: {error}"
            )
            raise JevCallError(maskSecret(detail, self._apiKey)) from error
        latencyMs = (time.perf_counter() - startTime) * 1000.0

        rawResponse = response.model_dump(mode="json")
        rawAnswers = rawResponse.get("answers", {})
        missingNames = [name for name in questionNames if name not in rawAnswers]
        if missingNames:
            raise JevCallError(
                f"JevClient.evaluate: レスポンスに一部の質問の答えがありません"
                f"（model={model}、不足={missingNames}、受信={sorted(rawAnswers)}）"
            )

        answers = [normalizeAnswer(name, rawAnswers[name]) for name in questionNames]
        usage = rawResponse.get("usage") or {}
        return EvaluationResult(
            model=str(rawResponse.get("model", model)),
            answers=answers,
            latencyMs=latencyMs,
            inputTokens=usage.get("input_tokens"),
            rawResponse=rawResponse,
        )

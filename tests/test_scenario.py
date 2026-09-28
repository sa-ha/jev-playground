"""scenario モジュール（シナリオ YAML の読み込みと検証）のテスト。

概要:
    同梱シナリオが検証を通ること、仕様に合わないシナリオが ScenarioError になることを確認する。

制限事項:
    - API は呼ばない。
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

from jev_playground.scenario import ScenarioError, loadScenario, parseScenario

SCENARIOS_DIR: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent / "scenarios"
"""同梱シナリオのディレクトリ。"""


def buildMinimalScenario() -> dict[str, Any]:
    """検証を通る最小限のシナリオ辞書を作る。

    Returns:
        dict[str, Any]: シナリオ辞書。
    """
    return {
        "scenarioId": "minimal",
        "questions": {
            "topic": {"type": "choice", "instructions": "用件は？", "criteria": {"a": "A", "b": "B"}},
            "level": {"type": "score", "instructions": "程度は？", "criteria": ["低", "高"]},
            "flag": {"type": "noul", "instructions": "該当する？"},
        },
        "cases": [{"caseId": "c1", "state": "本文", "expected": {"topic": "a", "level": 1, "flag": True}}],
    }


@pytest.mark.parametrize("scenarioPath", sorted(SCENARIOS_DIR.glob("*.yaml")), ids=lambda path: path.name)
def testBundledScenariosAreValid(scenarioPath: pathlib.Path) -> None:
    """同梱のシナリオがすべて検証を通ることを確認する。

    Args:
        scenarioPath (pathlib.Path): シナリオのパス。
    """
    scenario = loadScenario(scenarioPath)
    assert scenario.cases


def testMinimalScenarioUsesDefaults() -> None:
    """model と confidenceThreshold を省略すると既定値になることを確認する。"""
    scenario = parseScenario(buildMinimalScenario(), pathlib.Path("minimal.yaml"))
    assert scenario.model == "jev-latest"
    assert scenario.confidenceThreshold == 0.7
    assert [question.name for question in scenario.questions] == ["topic", "level", "flag"]


@pytest.mark.parametrize(
    ("mutate", "expectedMessage"),
    [
        (lambda data: data["questions"]["topic"].update(type="text"), "type は"),
        (lambda data: data["questions"]["level"].update(criteria=["1つだけ"]), "score の criteria"),
        (lambda data: data["questions"]["flag"].update(criteria={"yes": "はい"}), "noul の criteria"),
        (lambda data: data["cases"][0]["expected"].update(topic="z"), "choice の期待値"),
        (lambda data: data["cases"][0]["expected"].update(level=2), "score の期待値"),
        (lambda data: data["cases"][0]["expected"].update(flag="yes"), "noul の期待値"),
        (lambda data: data["cases"][0]["expected"].update(unknown=True), "未定義の質問"),
        (lambda data: data["cases"].append(dict(data["cases"][0])), "重複"),
        (lambda data: data.update(confidenceThreshold=1.5), "confidenceThreshold"),
    ],
)
def testInvalidScenarioRaises(mutate: Any, expectedMessage: str) -> None:
    """仕様に合わないシナリオが、原因を含むメッセージの ScenarioError になることを確認する。

    Args:
        mutate (Any): 最小シナリオを壊す関数。
        expectedMessage (str): エラーメッセージに含まれるべき文字列。
    """
    rawData = buildMinimalScenario()
    mutate(rawData)
    with pytest.raises(ScenarioError, match=expectedMessage):
        parseScenario(rawData, pathlib.Path("broken.yaml"))

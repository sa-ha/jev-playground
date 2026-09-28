"""jev-playground のコマンドライン入口。

概要:
    シナリオ YAML の検証（validate）と、Jev での実行・集計（run）を行う。

主な仕様:
    - `jev-playground validate <scenario.yaml>...`: API を呼ばずにシナリオの形式だけを検証する。
    - `jev-playground run <scenario.yaml> [--model M] [--results-dir D] [--timeout S]`:
      全ケースを Jev で評価し、レポートを表示して結果を JSONL に保存する。
    - 終了コード: 0 = 成功、1 = 一部または全部のケースが失敗、2 = 入力や設定の誤り。

制限事項:
    - API キーは環境変数 TYPESAFE_API_KEY から読む。`uv run --env-file .env jev-playground run ...` を推奨。
"""

from __future__ import annotations

import argparse
import dataclasses
import sys

from jev_playground.client import JevCallError, JevClient
from jev_playground.report import buildReport
from jev_playground.runner import runScenario, saveResults
from jev_playground.scenario import ScenarioError, loadScenario

EXIT_OK: int = 0
"""すべて成功したときの終了コード。"""

EXIT_CASE_FAILED: int = 1
"""一部または全部のケースで呼び出しが失敗したときの終了コード。"""

EXIT_INPUT_ERROR: int = 2
"""シナリオや設定に誤りがあるときの終了コード。"""


def buildArgumentParser() -> argparse.ArgumentParser:
    """コマンドライン引数の定義を作る。

    Returns:
        argparse.ArgumentParser: 引数パーサー。
    """
    parser = argparse.ArgumentParser(
        prog="jev-playground",
        description="TypeSafe AI Jev を架空データのシナリオで検証する",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validateParser = subparsers.add_parser("validate", help="シナリオ YAML の形式を検証する（API は呼ばない）")
    validateParser.add_argument("scenarioPaths", nargs="+", metavar="SCENARIO", help="シナリオ YAML のパス")

    runParser = subparsers.add_parser("run", help="シナリオを Jev で実行し、集計して保存する")
    runParser.add_argument("scenarioPath", metavar="SCENARIO", help="シナリオ YAML のパス")
    runParser.add_argument("--model", default=None, help="シナリオの model を上書きする（例: jev-latest）")
    runParser.add_argument("--results-dir", dest="resultsDir", default="results", help="結果の保存先（既定: results）")
    runParser.add_argument("--timeout", dest="timeoutSeconds", type=float, default=10.0, help="タイムアウト秒（既定: 10）")
    return parser


def commandValidate(scenarioPaths: list[str]) -> int:
    """validate サブコマンドを実行する。

    Args:
        scenarioPaths (list[str]): 検証するシナリオ YAML のパス。

    Returns:
        int: 終了コード。1件でも不正なら EXIT_INPUT_ERROR。
    """
    exitCode = EXIT_OK
    for scenarioPath in scenarioPaths:
        try:
            scenario = loadScenario(scenarioPath)
        except ScenarioError as error:
            print(f"NG {scenarioPath}: {error}", file=sys.stderr)
            exitCode = EXIT_INPUT_ERROR
            continue
        print(f"OK {scenarioPath}: 質問 {len(scenario.questions)} 件、ケース {len(scenario.cases)} 件")
    return exitCode


def commandRun(scenarioPath: str, model: str | None, resultsDir: str, timeoutSeconds: float) -> int:
    """run サブコマンドを実行する。

    Args:
        scenarioPath (str): シナリオ YAML のパス。
        model (str | None): モデル名の上書き。None ならシナリオの値を使う。
        resultsDir (str): 結果の保存先ディレクトリ。
        timeoutSeconds (float): 1回の HTTP 操作のタイムアウト（秒）。

    Returns:
        int: 終了コード。
    """
    try:
        scenario = loadScenario(scenarioPath)
    except ScenarioError as error:
        print(f"commandRun: シナリオが不正です: {error}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    if model is not None:
        scenario = dataclasses.replace(scenario, model=model)

    try:
        jevClient = JevClient(timeoutSeconds=timeoutSeconds)
    except JevCallError as error:
        print(f"commandRun: {error}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    caseResults = runScenario(scenario, jevClient)
    print(buildReport(scenario, caseResults))

    try:
        outputPath = saveResults(scenario, caseResults, resultsDir)
    except OSError as error:
        print(f"commandRun: 結果を保存できませんでした（resultsDir={resultsDir}）: {error}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    print(f"\n結果を保存しました: {outputPath}")

    hasFailure = any(caseResult.error is not None for caseResult in caseResults)
    return EXIT_CASE_FAILED if hasFailure else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """コマンドラインの入口。

    Args:
        argv (list[str] | None): 引数。None なら sys.argv を使う。

    Returns:
        int: 終了コード。
    """
    arguments = buildArgumentParser().parse_args(argv)
    if arguments.command == "validate":
        return commandValidate(arguments.scenarioPaths)
    return commandRun(arguments.scenarioPath, arguments.model, arguments.resultsDir, arguments.timeoutSeconds)


if __name__ == "__main__":
    sys.exit(main())

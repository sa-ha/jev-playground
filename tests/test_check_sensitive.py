"""scripts/check_sensitive.py（個人情報・機密情報の検査）のテスト。

概要:
    公開してはいけない値を検出し、例示用の値は通すことを確認する。

制限事項:
    - このファイル自体が検査対象になるため、検出されるべき値は実行時に文字列を連結して作る。
      ここに直接書かないこと。
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

import pytest

SCRIPT_PATH: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "check_sensitive.py"
"""検査スクリプトのパス。"""


def loadCheckSensitive() -> types.ModuleType:
    """scripts/check_sensitive.py をモジュールとして読み込む。

    Returns:
        types.ModuleType: 読み込んだモジュール。
    """
    specification = importlib.util.spec_from_file_location("check_sensitive", SCRIPT_PATH)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


checkSensitive: types.ModuleType = loadCheckSensitive()
"""テスト対象のモジュール。"""


def join(*parts: str) -> str:
    """文字列を連結する（検出されるべき値をソースに直接書かないため）。

    Args:
        *parts (str): 連結する文字列。

    Returns:
        str: 連結した文字列。
    """
    return "".join(parts)


@pytest.mark.parametrize(
    ("text", "expectedKind"),
    [
        (join("連絡先: taro", "@", "gmail", ".com"), "メールアドレス"),
        (join("電話 090", "-1234-", "5678"), "電話番号"),
        (join("電話 0801", "2345678"), "電話番号"),
        (join("〒150", "-0001"), "郵便番号"),
        (join("/ho", "me/taro/project"), "ホームディレクトリのパス"),
        (join("/Us", "ers/hanako/dev"), "ホームディレクトリのパス"),
        (join("C:", "\\Users\\", "jiro\\Desktop"), "ホームディレクトリのパス"),
        (join("host 192.", "168.1.20"), "プライベート IP アドレス"),
        (join("token gh", "p_", "a" * 36), "トークン（GitHub 形式）"),
        (join("s", "k-", "b" * 40), "API キー（OpenAI 形式）"),
        (join("TYPESAFE_API_KEY", "=", "c" * 24), "API キー（TypeSafe の代入）"),
    ],
)
def testDetectsSensitiveValues(text: str, expectedKind: str) -> None:
    """公開してはいけない値を検出し、ログでは値を伏せることを確認する。

    Args:
        text (str): 検査する文字列。
        expectedKind (str): 検出されるべき種類。
    """
    findings = checkSensitive.scanText(text, "sample.txt", [])
    assert [finding.kind for finding in findings] == [expectedKind]
    assert "…(" in findings[0].maskedValue


@pytest.mark.parametrize(
    "text",
    [
        "連絡先: support@example.com",
        "29799644+sa-ha@users.noreply.github.com",
        "電話 090-0000-0000 / 03-0000-0000",
        "〒000-0000",
        "/home/runner/work と /home/user/project",
        "TYPESAFE_API_KEY=",
        "TYPESAFE_API_KEY=<あなたのキー>",
        "日付 2026-09-28、バージョン 10.0.1",
    ],
)
def testAllowsExampleValues(text: str) -> None:
    """例示用の値は検出しないことを確認する。

    Args:
        text (str): 検査する文字列。
    """
    assert checkSensitive.scanText(text, "sample.txt", []) == []


def testDenylistIsCaseInsensitive() -> None:
    """拒否リストの語を大文字小文字を区別せずに検出することを確認する。"""
    findings = checkSensitive.scanText(join("Project ", "Hoge", "Corp"), "sample.txt", ["hogecorp"])
    assert [finding.kind for finding in findings] == ["拒否リストの語"]


def testNoreplyEmail() -> None:
    """noreply アドレスの判定を確認する。"""
    assert checkSensitive.isNoreplyEmail("1+someone@users.noreply.github.com")
    assert checkSensitive.isNoreplyEmail("noreply@github.com")
    assert not checkSensitive.isNoreplyEmail(join("someone", "@", "gmail.com"))

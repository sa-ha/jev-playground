"""公開リポジトリに個人情報・機密情報が入らないよう検査するスクリプト。

概要:
    ファイルの中身とコミットの作成者を検査し、公開してはいけない情報を見つけたら終了コード 1 で終わる。
    pre-commit（コミット前）、pre-push（push 前）、GitHub Actions（push・PR ごと）から呼ばれる。

主な仕様:
    - 検査するもの（ファイルの中身）:
        - メールアドレス（例示用ドメインと GitHub の noreply アドレスを除く）
        - 日本の電話番号（0000 などの例示用の番号を除く）
        - 郵便番号（〒 付き。000-0000 を除く）
        - ホームディレクトリの絶対パス（Linux・macOS・Windows のユーザーフォルダ。例示用の名前を除く）
        - プライベート IP アドレス（10.x、172.16〜31.x、192.168.x）
        - API キー・トークンの形をした文字列（OpenAI・GitHub・AWS・Slack・Google・TypeSafe の代入）
        - 拒否リストの語（.sensitive-denylist.txt と環境変数 SENSITIVE_DENYLIST。大文字小文字を区別しない）
    - 検査するもの（git）:
        - --check-git-config: このリポジトリの user.email が noreply アドレスか
        - --check-authors: 全コミットの作成者・コミッターのメールが noreply アドレスか
    - 見つけた値はログに全文を出さず、先頭数文字だけを残して伏せる（CI のログから漏れないようにする）。

制限事項:
    - 正規表現による検出のため、表記ゆれ（全角数字、空白区切りの電話番号など）は見逃すことがある。
      最終的な確認は docs/public-repository-policy.md の「push 前の手動確認」で人が行う。
    - 拒否リストは公開できない語（社名・案件名・本名など）を入れるため、リポジトリには含めない。
    - 1MB を超えるファイルと、NUL 文字を含むバイナリファイルは検査しない（その旨を表示する）。
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import pathlib
import re
import subprocess
import sys
from collections.abc import Callable, Iterable

REPOSITORY_ROOT: pathlib.Path = pathlib.Path(__file__).resolve().parent.parent
"""リポジトリのルートディレクトリ。"""

DENYLIST_FILE_NAME: str = ".sensitive-denylist.txt"
"""ローカル専用の拒否リストのファイル名（.gitignore 済み）。"""

DENYLIST_ENV_NAME: str = "SENSITIVE_DENYLIST"
"""拒否リストを改行区切りで渡す環境変数名（CI では GitHub の Secret から渡す）。"""

MAX_FILE_BYTES: int = 1_000_000
"""検査するファイルサイズの上限（バイト）。"""

ALLOWED_EMAIL_DOMAINS: tuple[str, ...] = ("example.com", "example.org", "example.net")
"""例示用として使ってよいメールのドメイン（RFC 2606）。"""

ALLOWED_EMAIL_DOMAIN_SUFFIXES: tuple[str, ...] = (".example", ".test", ".invalid", ".localhost")
"""例示用として使ってよいトップレベルドメイン（RFC 2606）。"""

ALLOWED_EMAIL_ADDRESSES: tuple[str, ...] = ("noreply@github.com", "git@github.com")
"""GitHub が使う、個人を特定しないアドレス。"""

NOREPLY_EMAIL_SUFFIX: str = "@users.noreply.github.com"
"""GitHub の個人用 noreply アドレスの末尾。"""

ALLOWED_HOME_DIRECTORY_NAMES: tuple[str, ...] = ("user", "username", "runner", "you", "example", "me")
"""例示用として使ってよいホームディレクトリ名（runner は GitHub Actions の実行環境）。"""


@dataclasses.dataclass(frozen=True)
class Finding:
    """検出結果1件。

    Attributes:
        location (str): 検出場所（「ファイル:行」やコミット ID）。
        kind (str): 検出した情報の種類。
        maskedValue (str): 一部を伏せた検出値。
    """

    location: str
    kind: str
    maskedValue: str


@dataclasses.dataclass(frozen=True)
class PatternRule:
    """ファイルの中身に適用する検出ルール。

    Attributes:
        kind (str): 検出した情報の種類（表示用）。
        pattern (re.Pattern[str]): 検出する正規表現。
        isAllowed (Callable[[re.Match[str]], bool]): 例示用の値など、許可する一致なら True を返す関数。
    """

    kind: str
    pattern: re.Pattern[str]
    isAllowed: Callable[[re.Match[str]], bool]


def maskValue(value: str) -> str:
    """検出値の先頭だけを残して伏せる。

    Args:
        value (str): 検出値。

    Returns:
        str: 先頭3文字（短い値は1文字）と「…(n文字)」を組み合わせた文字列。
    """
    visibleLength = 3 if len(value) > 6 else 1
    return f"{value[:visibleLength]}…({len(value)}文字)"


def isAllowedEmail(match: re.Match[str]) -> bool:
    """メールアドレスが例示用・GitHub 用として許可されるか判定する。

    Args:
        match (re.Match[str]): メールアドレスの一致。

    Returns:
        bool: 許可されるなら True。
    """
    address = match.group(0).lower()
    domain = address.rsplit("@", 1)[-1]
    return (
        address in ALLOWED_EMAIL_ADDRESSES
        or address.endswith(NOREPLY_EMAIL_SUFFIX)
        or domain in ALLOWED_EMAIL_DOMAINS
        or domain.endswith(ALLOWED_EMAIL_DOMAIN_SUFFIXES)
    )


def isDummyPhoneNumber(match: re.Match[str]) -> bool:
    """電話番号が例示用（市外局番などの後がすべて 0）か判定する。

    Args:
        match (re.Match[str]): 電話番号の一致。

    Returns:
        bool: 例示用なら True（例: 090-0000-0000、03-0000-0000）。
    """
    digits = re.sub(r"\D", "", match.group(0))
    return set(digits[3:]) <= {"0"}


def isDummyPostalCode(match: re.Match[str]) -> bool:
    """郵便番号が例示用（000-0000）か判定する。

    Args:
        match (re.Match[str]): 郵便番号の一致。

    Returns:
        bool: 例示用なら True。
    """
    digits = re.sub(r"\D", "", match.group(0))
    return set(digits) <= {"0"}


def isAllowedHomeDirectory(match: re.Match[str]) -> bool:
    """ホームディレクトリのパスが例示用の名前か判定する。

    Args:
        match (re.Match[str]): パスの一致（グループ "name" にユーザー名が入る）。

    Returns:
        bool: 例示用の名前なら True。
    """
    return match.group("name").lower() in ALLOWED_HOME_DIRECTORY_NAMES


def neverAllowed(match: re.Match[str]) -> bool:
    """常に許可しない（検出したら必ず報告する）ルール用の判定関数。

    Args:
        match (re.Match[str]): 一致（使わない）。

    Returns:
        bool: 常に False。
    """
    return False


PATTERN_RULES: tuple[PatternRule, ...] = (
    PatternRule("メールアドレス", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), isAllowedEmail),
    PatternRule("電話番号", re.compile(r"(?<!\d)0\d{1,4}-\d{1,4}-\d{3,4}(?!\d)"), isDummyPhoneNumber),
    PatternRule("電話番号", re.compile(r"(?<![\d.])0[5789]0\d{8}(?!\d)"), isDummyPhoneNumber),
    PatternRule("郵便番号", re.compile(r"〒\s?\d{3}-?\d{4}"), isDummyPostalCode),
    PatternRule(
        "ホームディレクトリのパス",
        re.compile(r"/(?:home|Users)/(?P<name>[A-Za-z0-9._-]+)"),
        isAllowedHomeDirectory,
    ),
    PatternRule(
        "ホームディレクトリのパス",
        re.compile(r"[A-Za-z]:\\+Users\\+(?P<name>[^\\\s\"']+)"),
        isAllowedHomeDirectory,
    ),
    PatternRule(
        "プライベート IP アドレス",
        re.compile(
            r"(?<![\d.])(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(?![\d.])"
        ),
        neverAllowed,
    ),
    PatternRule("API キー（OpenAI 形式）", re.compile(r"sk-[A-Za-z0-9_-]{20,}"), neverAllowed),
    PatternRule("トークン（GitHub 形式）", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), neverAllowed),
    PatternRule("アクセスキー（AWS 形式）", re.compile(r"AKIA[0-9A-Z]{16}"), neverAllowed),
    PatternRule("トークン（Slack 形式）", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), neverAllowed),
    PatternRule("API キー（Google 形式）", re.compile(r"AIza[0-9A-Za-z_-]{35}"), neverAllowed),
    PatternRule(
        "API キー（TypeSafe の代入）",
        re.compile(r"TYPESAFE_API_KEY\s*[:=]\s*[\"']?[A-Za-z0-9_\-.]{8,}"),
        neverAllowed,
    ),
)
"""ファイルの中身に適用する検出ルールの一覧。"""


def loadDenylist() -> list[str]:
    """ローカルのファイルと環境変数から拒否リストの語を読み込む。

    Returns:
        list[str]: 小文字にした拒否語（空行と # から始まる行を除く）。
    """
    rawLines: list[str] = []
    denylistPath = REPOSITORY_ROOT / DENYLIST_FILE_NAME
    if denylistPath.is_file():
        rawLines.extend(denylistPath.read_text(encoding="utf-8").splitlines())
    rawLines.extend(os.environ.get(DENYLIST_ENV_NAME, "").splitlines())
    return [line.strip().lower() for line in rawLines if line.strip() and not line.strip().startswith("#")]


def scanText(text: str, displayPath: str, denylist: list[str]) -> list[Finding]:
    """文字列を1行ずつ検査する。

    Args:
        text (str): 検査する文字列。
        displayPath (str): 表示用のファイルパス。
        denylist (list[str]): 小文字の拒否語。

    Returns:
        list[Finding]: 検出結果。
    """
    findings: list[Finding] = []
    for lineNumber, line in enumerate(text.splitlines(), start=1):
        location = f"{displayPath}:{lineNumber}"
        for rule in PATTERN_RULES:
            for match in rule.pattern.finditer(line):
                if not rule.isAllowed(match):
                    findings.append(Finding(location, rule.kind, maskValue(match.group(0))))
        lowerLine = line.lower()
        for deniedTerm in denylist:
            if deniedTerm in lowerLine:
                findings.append(Finding(location, "拒否リストの語", maskValue(deniedTerm)))
    return findings


def scanFile(filePath: pathlib.Path, denylist: list[str]) -> tuple[list[Finding], str | None]:
    """1つのファイルを検査する。

    Args:
        filePath (pathlib.Path): 検査するファイル。
        denylist (list[str]): 小文字の拒否語。

    Returns:
        tuple[list[Finding], str | None]: 検出結果と、検査しなかった場合の理由（検査した場合は None）。

    Raises:
        OSError: ファイルを読めない場合（呼び出し元でパスを付けて報告する）。
    """
    if filePath.stat().st_size > MAX_FILE_BYTES:
        return [], f"{MAX_FILE_BYTES} バイトを超えるため検査していません"
    rawBytes = filePath.read_bytes()
    if b"\x00" in rawBytes:
        return [], "バイナリファイルのため検査していません"
    text = rawBytes.decode("utf-8", errors="replace")
    return scanText(text, str(filePath), denylist), None


def runGit(arguments: list[str]) -> str:
    """リポジトリのルートで git コマンドを実行し、標準出力を返す。

    Args:
        arguments (list[str]): git に渡す引数。

    Returns:
        str: 標準出力。

    Raises:
        RuntimeError: git が失敗した場合（コマンドと標準エラーを含める）。
    """
    completed = subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"runGit: git {' '.join(arguments)} が失敗しました"
            f"（終了コード={completed.returncode}）: {completed.stderr.strip()}"
        )
    return completed.stdout


def isNoreplyEmail(emailAddress: str) -> bool:
    """メールアドレスが GitHub の noreply アドレスか判定する。

    Args:
        emailAddress (str): 判定するアドレス。

    Returns:
        bool: noreply アドレスなら True。
    """
    lowerAddress = emailAddress.strip().lower()
    return lowerAddress.endswith(NOREPLY_EMAIL_SUFFIX) or lowerAddress == "noreply@github.com"


def checkGitConfig() -> list[Finding]:
    """このリポジトリで使われる user.email が noreply アドレスか検査する。

    Returns:
        list[Finding]: 問題があれば1件、無ければ空。
    """
    try:
        configuredEmail = runGit(["config", "user.email"]).strip()
    except RuntimeError:
        configuredEmail = ""
    if isNoreplyEmail(configuredEmail):
        return []
    return [Finding("git config user.email", "noreply ではないコミット用メール", maskValue(configuredEmail or "(未設定)"))]


def checkCommitAuthors() -> list[Finding]:
    """全コミットの作成者・コミッターのメールが noreply アドレスか検査する。

    Returns:
        list[Finding]: noreply ではないメールを含むコミットの一覧。コミットが無ければ空。
    """
    try:
        logOutput = runGit(["log", "--all", "--format=%H%x09%ae%x09%ce"])
    except RuntimeError:
        return []
    findings: list[Finding] = []
    for logLine in logOutput.splitlines():
        commitId, authorEmail, committerEmail = logLine.split("\t")
        for role, emailAddress in (("作成者", authorEmail), ("コミッター", committerEmail)):
            if not isNoreplyEmail(emailAddress):
                findings.append(Finding(f"commit {commitId[:12]}", f"noreply ではない{role}のメール", maskValue(emailAddress)))
    return findings


def listTrackedFiles() -> list[pathlib.Path]:
    """git で管理されているファイルの一覧を返す。

    Returns:
        list[pathlib.Path]: ルートからの相対パス。
    """
    return [pathlib.Path(line) for line in runGit(["ls-files"]).splitlines() if line]


def scanFiles(filePaths: Iterable[pathlib.Path], denylist: list[str]) -> list[Finding]:
    """複数のファイルを検査し、検査できなかったファイルは標準エラーに表示する。

    Args:
        filePaths (Iterable[pathlib.Path]): 検査するファイル。
        denylist (list[str]): 小文字の拒否語。

    Returns:
        list[Finding]: 検出結果。読めなかったファイルも検出結果として含める。
    """
    findings: list[Finding] = []
    for filePath in filePaths:
        absolutePath = filePath if filePath.is_absolute() else REPOSITORY_ROOT / filePath
        if not absolutePath.is_file():
            continue
        try:
            fileFindings, skipReason = scanFile(absolutePath, denylist)
        except OSError as error:
            findings.append(Finding(str(filePath), "読み込み失敗", maskValue(str(error))))
            continue
        if skipReason is not None:
            print(f"注意: {filePath}: {skipReason}", file=sys.stderr)
        findings.extend(
            dataclasses.replace(finding, location=finding.location.replace(str(absolutePath), str(filePath)))
            for finding in fileFindings
        )
    return findings


def buildArgumentParser() -> argparse.ArgumentParser:
    """コマンドライン引数の定義を作る。

    Returns:
        argparse.ArgumentParser: 引数パーサー。
    """
    parser = argparse.ArgumentParser(description="個人情報・機密情報が含まれていないか検査する")
    parser.add_argument("files", nargs="*", help="検査するファイル（pre-commit から渡される）")
    parser.add_argument("--all", action="store_true", help="git で管理されている全ファイルを検査する")
    parser.add_argument("--check-git-config", action="store_true", help="user.email が noreply か検査する")
    parser.add_argument("--check-authors", action="store_true", help="全コミットのメールが noreply か検査する")
    return parser


def main(argv: list[str] | None = None) -> int:
    """検査を実行し、結果を表示する。

    Args:
        argv (list[str] | None): 引数。None なら sys.argv を使う。

    Returns:
        int: 問題が無ければ 0、見つかれば 1、実行できなければ 2。
    """
    arguments = buildArgumentParser().parse_args(argv)
    denylist = loadDenylist()

    try:
        targetFiles = listTrackedFiles() if arguments.all else [pathlib.Path(name) for name in arguments.files]
        findings = scanFiles(targetFiles, denylist)
        if arguments.check_git_config:
            findings.extend(checkGitConfig())
        if arguments.check_authors:
            findings.extend(checkCommitAuthors())
    except RuntimeError as error:
        print(f"check_sensitive.main: 検査を実行できませんでした: {error}", file=sys.stderr)
        return 2

    if not findings:
        print(f"check_sensitive: 問題は見つかりませんでした（ファイル {len(targetFiles)} 件、拒否語 {len(denylist)} 件）")
        return 0

    print("check_sensitive: 公開してはいけない可能性のある情報が見つかりました。", file=sys.stderr)
    for finding in findings:
        print(f"  {finding.location}: {finding.kind}: {finding.maskedValue}", file=sys.stderr)
    print("docs/public-repository-policy.md を確認し、値を例示用のものに置き換えてください。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Repository checks shared by pre-commit and CI. Never print secret values."""
import ast
import os
from pathlib import Path
import re
import subprocess
import sys


PATTERNS = [
    rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----",
    rb"(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{30,}",
    rb"sk-(?:proj-)?[A-Za-z0-9_-]{32,}",
    rb"(?:AKIA|ASIA)[A-Z0-9]{16}",
]
CREDENTIAL_FILES = {"auth.json", ".env", "id_rsa", "id_ed25519", "credentials.json"}


def issues(path, content):
    if path.name in CREDENTIAL_FILES or any(re.search(p, content) for p in PATTERNS):
        yield "認証情報の可能性があります"
    if path == Path("bin/codex-auto-resume"):
        for node in ast.walk(ast.parse(content)):
            if not isinstance(node, ast.Call):
                continue
            if any(k.arg == "shell" and not (isinstance(k.value, ast.Constant)
                       and k.value.value is False) for k in node.keywords):
                yield "サブプロセスでシェルが有効です"


def main():
    paths = subprocess.check_output(["git", "ls-files", "-z"]).split(b"\0")
    failed = False
    for raw in filter(None, paths):
        path = Path(os.fsdecode(raw))
        if path.is_symlink():
            print(path, "検査対象のシンボリックリンクを確認してください")
            failed = True
        elif path.is_file():
            for reason in issues(path, path.read_bytes()):
                print(path, reason, file=sys.stderr)
                failed = True
    if failed:
        return 1
    return subprocess.call([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"])


if __name__ == "__main__":
    sys.exit(main())

"""Run the adaptive-zlib distribution's formatting, analysis and tests."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import sysconfig
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("src", "tests", "scripts", "compare_samples.py")


def _run(command: Sequence[str], *, environment: dict[str, str] | None = None) -> None:
    print(f"\n> {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def _module(arguments: Sequence[str]) -> None:
    _run((sys.executable, "-m", *arguments))


def _isort(arguments: Sequence[str]) -> None:
    executable = Path(sysconfig.get_path("scripts")) / (
        "isort.exe" if sys.platform == "win32" else "isort"
    )
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    _run((str(executable), *arguments), environment=environment)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()
    if args.fix:
        _isort(TARGETS)
        _module(("ruff", "check", "--fix", *TARGETS))
        _module(("ruff", "format", *TARGETS))
    _module(("ruff", "check", *TARGETS))
    _module(("ruff", "format", "--check", *TARGETS))
    _isort(("--check-only", *TARGETS))
    _module(("mypy",))
    _module(("pyright",))
    _module(("pytest", "-m", "not distribution"))


if __name__ == "__main__":
    main()

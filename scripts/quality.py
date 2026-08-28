"""Run the repository's formatting, static analysis and test checks."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import sysconfig
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    "src",
    "tests",
    "scripts",
)


def run(command: Sequence[str], *, environment: dict[str, str] | None = None) -> None:
    print(f"\n> {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=ROOT, env=environment, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def run_module(arguments: Sequence[str]) -> None:
    run((sys.executable, "-m", *arguments))


def run_isort(arguments: Sequence[str]) -> None:
    executable = Path(sysconfig.get_path("scripts")) / (
        "isort.exe" if sys.platform == "win32" else "isort"
    )
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    run((str(executable), *arguments), environment=environment)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix", action="store_true", help="Apply safe import and formatting fixes."
    )
    args = parser.parse_args()

    if args.fix:
        run_isort(TARGETS)
        run_module(("ruff", "check", "--fix", *TARGETS))
        run_module(("ruff", "format", *TARGETS))

    run_module(("ruff", "check", *TARGETS))
    run_module(("ruff", "format", "--check", *TARGETS))
    run_isort(("--check-only", *TARGETS))
    run_module(("mypy",))
    run_module(("pyright",))
    run_module(("pytest", "-m", "not distribution"))


if __name__ == "__main__":
    main()

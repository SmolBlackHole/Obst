# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

DEFAULTS_ROOT = Path(__file__).parents[1]
WALKTHROUGH = DEFAULTS_ROOT / "examples" / "api_walkthrough.py"


def test_api_walkthrough_uses_only_public_import_boundaries() -> None:
    tree = ast.parse(WALKTHROUGH.read_text(encoding="utf-8"), filename=WALKTHROUGH)
    imported_obst_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("obst")
    }

    assert imported_obst_modules == {
        "obst.core",
        "obst_defaults.codecs",
        "obst_defaults.packagers",
        "obst_defaults.transforms",
    }


def test_api_walkthrough_runs_from_an_unrelated_working_directory(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [sys.executable, WALKTHROUGH],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Streams: 2" in completed.stdout
    assert "Recipes: 2" in completed.stdout
    assert "Inspection recovery: not_attempted" in completed.stdout
    assert completed.stdout.rstrip().endswith("Round trip byte-identical: True")
    assert not tuple(tmp_path.iterdir())

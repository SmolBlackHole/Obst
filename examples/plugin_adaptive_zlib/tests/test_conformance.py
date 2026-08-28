from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from obst.conformance import (
    load_conformance_suite,
    run_conformance_suite,
)

from obst_example_adaptive_zlib import obst_extensions
from obst_example_adaptive_zlib.conformance import obst_conformance

PROJECT_ROOT = Path(__file__).parents[1]
CONFORMANCE_ROOT = (
    PROJECT_ROOT / "src" / "obst_example_adaptive_zlib" / "conformance_vectors"
)
CONFORMANCE_GENERATOR = PROJECT_ROOT / "scripts" / "build_conformance.py"


def _files(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_checked_in_suite_is_byte_reproducible(tmp_path: Path) -> None:
    subprocess.run(
        [sys.executable, CONFORMANCE_GENERATOR, "--output", tmp_path],
        cwd=PROJECT_ROOT,
        check=True,
    )
    suite = load_conformance_suite(tmp_path)

    assert _files(tmp_path) == _files(CONFORMANCE_ROOT)
    assert load_conformance_suite(CONFORMANCE_ROOT) == suite
    assert obst_conformance() == suite


def test_published_suite_passes_with_the_published_extension() -> None:
    assert run_conformance_suite(obst_conformance(), obst_extensions()).passed

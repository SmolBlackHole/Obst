"""Package-owned conformance checks for the OBST wire format."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from obst.conformance import (
    ContainerStructuralOutcome,
    ContainerStructureCase,
    load_conformance_suite,
    run_conformance_suite,
    write_conformance_suite,
)
from obst.format_conformance import obst_conformance
from scripts.build_conformance import CONFORMANCE_ROOT, build_suite


def _files(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_format_suite_is_reproducible(tmp_path: Path) -> None:
    generated = tmp_path / "format"

    write_conformance_suite(build_suite(), generated)

    assert _files(generated) == _files(CONFORMANCE_ROOT)
    assert load_conformance_suite(generated) == obst_conformance()


def test_format_suite_runs_through_the_public_runner() -> None:
    report = run_conformance_suite(obst_conformance())

    assert report.passed
    assert report.cases


def test_format_suite_covers_every_structural_outcome() -> None:
    cases = obst_conformance().cases

    assert all(type(case) is ContainerStructureCase for case in cases)
    assert {
        case.outcome for case in cases if isinstance(case, ContainerStructureCase)
    } == set(ContainerStructuralOutcome)


def test_format_suite_pins_confirmed_portable_regressions() -> None:
    case_ids = {case.case_id for case in obst_conformance().cases}

    assert {
        "complete-chunk-suffix-removed",
        "extension-id-dual-role",
    } <= case_ids


def test_format_vectors_are_packaged_resources() -> None:
    root = files("obst.conformance").joinpath("corpus")

    assert root.joinpath("index.json").is_file()
    assert obst_conformance() == load_conformance_suite(root)

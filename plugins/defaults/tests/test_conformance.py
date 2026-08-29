from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from obst.conformance import (
    ContainerRecoveryCase,
    load_conformance_suite,
    run_conformance_suite,
)
from obst.core import ExtensionDescriptor

from obst_defaults.bundle import obst_extensions
from obst_defaults.carriers.filesystem import FilesystemCarrierExtension
from obst_defaults.carriers.memory import MemoryCarrierExtension
from obst_defaults.carriers.stdin import StdinCarrierExtension
from obst_defaults.codecs.zlib import ZlibDictionaryExtension, ZlibExtension
from obst_defaults.conformance import obst_conformance
from obst_defaults.files import FileExtension
from obst_defaults.packagers import FixedPackagerExtension
from obst_defaults.transforms.delta8 import Delta8Extension

PROJECT_ROOT = Path(__file__).parents[1]
CONFORMANCE_ROOT = PROJECT_ROOT / "src" / "obst_defaults" / "conformance_vectors"
CONFORMANCE_GENERATOR = PROJECT_ROOT / "scripts" / "build_conformance.py"
REPOSITORY_ROOT = Path(__file__).parents[3]
REPOSITORY_URL_PREFIX = "https://github.com/SmolBlackHole/Obst/blob/main/"


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


def test_published_suite_passes_with_the_published_extensions() -> None:
    report = run_conformance_suite(obst_conformance(), obst_extensions())

    assert report.passed
    assert any(type(case) is ContainerRecoveryCase for case in obst_conformance().cases)


@pytest.mark.parametrize(
    "descriptor",
    (
        ZlibExtension.descriptor,
        ZlibDictionaryExtension.descriptor,
        Delta8Extension.descriptor,
        FileExtension.descriptor,
    ),
)
def test_wire_extension_specification_urls_target_owned_contracts(
    descriptor: ExtensionDescriptor,
) -> None:
    url = descriptor.specification_url
    assert url is not None
    assert url.startswith(REPOSITORY_URL_PREFIX)
    relative_path = url.removeprefix(REPOSITORY_URL_PREFIX)
    assert relative_path.startswith("plugins/defaults/docs/contracts/")
    assert (REPOSITORY_ROOT / relative_path).is_file()


@pytest.mark.parametrize(
    "descriptor",
    (
        FilesystemCarrierExtension.descriptor,
        MemoryCarrierExtension.descriptor,
        StdinCarrierExtension.descriptor,
        FixedPackagerExtension.descriptor,
    ),
)
def test_runtime_extension_specification_urls_target_extension_docs(
    descriptor: ExtensionDescriptor,
) -> None:
    url = descriptor.specification_url
    assert url is not None
    assert url.startswith(REPOSITORY_URL_PREFIX)
    relative_path = url.removeprefix(REPOSITORY_URL_PREFIX)
    page, _, _fragment = relative_path.partition("#")
    assert page.startswith("plugins/defaults/docs/")
    assert "/contracts/" not in page
    assert (REPOSITORY_ROOT / page).is_file()

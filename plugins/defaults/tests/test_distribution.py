from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from importlib.metadata import entry_points, metadata, version
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[1]


def test_installed_distribution_publishes_all_three_plugin_contributions() -> None:
    assert version("obst-defaults") == "0.1.0"
    assert metadata("obst-defaults")["License-Expression"] == "MPL-2.0"
    contributions = {
        (entry.group, entry.name, entry.value)
        for entry in entry_points()
        if entry.name == "obst-defaults"
    }
    assert contributions == {
        (
            "obst.extensions",
            "obst-defaults",
            "obst_defaults.bundle:obst_extensions",
        ),
        (
            "obst.commands",
            "obst-defaults",
            "obst_defaults.commands:obst_commands",
        ),
        (
            "obst.conformance",
            "obst-defaults",
            "obst_defaults.conformance:obst_conformance",
        ),
    }


@pytest.mark.distribution
@pytest.mark.timeout(120)
def test_wheel_contains_license_and_owned_conformance_vectors(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment.update(PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INDEX="1")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            tmp_path,
            PROJECT_ROOT,
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    (wheel,) = tuple(tmp_path.glob("obst_defaults-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        license_names = [
            name for name in names if name.endswith(".dist-info/licenses/LICENSE")
        ]
        assert len(license_names) == 1
        assert archive.read(license_names[0]) == (PROJECT_ROOT / "LICENSE").read_bytes()
        assert "obst_defaults/py.typed" in names
        assert "obst_defaults/conformance_vectors/index.json" in names
        assert not any(
            name.startswith("obst_defaults/conformance_vectors/vectors/")
            for name in names
        )

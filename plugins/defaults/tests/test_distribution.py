# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from importlib.metadata import entry_points, metadata, version
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]


def _environment(config_home: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        OBST_CONFIG_HOME=str(config_home),
        PIP_DISABLE_PIP_VERSION_CHECK="1",
        PIP_NO_INDEX="1",
    )
    return environment


def _venv_python(environment_root: Path) -> Path:
    return environment_root / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )


def _run(
    command: list[str | Path],
    *,
    environment: dict[str, str],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(part) for part in command],
        cwd=cwd,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_installed_distribution_publishes_all_plugin_contributions() -> None:
    assert version("obst-defaults") == "0.2.0"
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
        (
            "obst.resources",
            "obst-defaults",
            "obst_defaults.bundle:obst_resources",
        ),
    }


@pytest.mark.distribution
@pytest.mark.timeout(120)
def test_defaults_supports_a_clean_editable_cli_round_trip(tmp_path: Path) -> None:
    environment_root = tmp_path / "editable"
    config_home = tmp_path / "config"
    environment = _environment(config_home)
    _run(
        [sys.executable, "-m", "venv", "--system-site-packages", environment_root],
        environment=environment,
        cwd=tmp_path,
    )
    python = _venv_python(environment_root)
    _run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-build-isolation",
            "-e",
            REPOSITORY_ROOT,
            "-e",
            PROJECT_ROOT,
        ],
        environment=environment,
        cwd=tmp_path,
    )

    _run(
        [python, "-m", "obst.cli", "plugins", "enable", "obst-defaults"],
        environment=environment,
        cwd=tmp_path,
    )
    extensions = _run(
        [python, "-m", "obst.cli", "extensions"],
        environment=environment,
        cwd=tmp_path,
    )
    assert "obst.zlib@1" in extensions.stdout
    _run(
        [python, "-m", "obst.cli", "plugins", "test", "obst-defaults"],
        environment=environment,
        cwd=tmp_path,
    )

    source = tmp_path / "input.bin"
    container = tmp_path / "round-trip.obst"
    restored = tmp_path / "restored"
    source.write_bytes(b"book-shaped documentation\n" * 4096)
    _run(
        [python, "-m", "obst.cli", "pack", source, "-o", container],
        environment=environment,
        cwd=tmp_path,
    )
    _run(
        [python, "-m", "obst.cli", "inspect", container, "--quiet"],
        environment=environment,
        cwd=tmp_path,
    )
    _run(
        [python, "-m", "obst.cli", "unpack", container, "-o", restored],
        environment=environment,
        cwd=tmp_path,
    )
    assert (restored / source.name).read_bytes() == source.read_bytes()


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

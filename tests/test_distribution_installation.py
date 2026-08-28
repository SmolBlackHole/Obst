"""Installation checks owned by the ``obst`` distribution."""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PROBE = """
from importlib.metadata import metadata, version
from pathlib import Path
import sys

from obst.plugins import PluginManager

assert version("obst") == "0.1.0"
assert metadata("obst")["License-Expression"] == "MPL-2.0"
manager = PluginManager.discover(state_path=Path(sys.argv[1]) / "plugins.json")
assert manager.status("obst-format").installed
assert manager.test("obst-format").passed
"""


def _environment(config_home: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        OBST_CONFIG_HOME=str(config_home),
        PIP_DISABLE_PIP_VERSION_CHECK="1",
        PIP_NO_INDEX="1",
    )
    return environment


def _run(
    command: list[str | Path],
    *,
    environment: dict[str, str],
) -> None:
    subprocess.run(
        [str(part) for part in command],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _venv_python(environment_root: Path) -> Path:
    return environment_root / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )


@pytest.mark.distribution
@pytest.mark.timeout(120)
def test_runtime_supports_an_independent_editable_install(tmp_path: Path) -> None:
    environment_root = tmp_path / "editable"
    config_home = tmp_path / "config"
    environment = _environment(config_home)
    _run(
        [sys.executable, "-m", "venv", "--system-site-packages", environment_root],
        environment=environment,
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
            PROJECT_ROOT,
        ],
        environment=environment,
    )

    _run(
        [python, "-c", RUNTIME_PROBE, config_home],
        environment=environment,
    )
    _run(
        [python, "-m", "obst.cli", "help", "inspect"],
        environment=environment,
    )


@pytest.mark.distribution
@pytest.mark.timeout(120)
def test_runtime_wheel_contains_its_license_and_format_corpus(
    tmp_path: Path,
) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    environment = _environment(tmp_path / "config")
    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            wheelhouse,
            PROJECT_ROOT,
        ],
        environment=environment,
    )

    (wheel,) = tuple(wheelhouse.glob("obst-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        license_names = [
            name for name in names if name.endswith(".dist-info/licenses/LICENSE")
        ]
        assert len(license_names) == 1
        assert archive.read(license_names[0]) == (PROJECT_ROOT / "LICENSE").read_bytes()
        assert "obst/py.typed" in names
        assert "obst/conformance/corpus/index.json" in names
        assert not any(
            name.startswith("obst/conformance/corpus/vectors/") for name in names
        )

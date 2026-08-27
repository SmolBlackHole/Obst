"""Installation and license checks for independently built OBST distributions."""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULTS_ROOT = _PROJECT_ROOT / "plugins" / "defaults"
_EXAMPLE_PLUGIN_ROOT = _PROJECT_ROOT / "examples" / "plugin_adaptive_zlib"
_PROJECTS = (_PROJECT_ROOT, _DEFAULTS_ROOT)
_BUILD_PROJECTS = (*_PROJECTS, _EXAMPLE_PLUGIN_ROOT)
_INSTALLATION_PROBE = """
import sys
from importlib.metadata import metadata, version
from pathlib import Path

from obst.plugins import PluginManager

assert version("obst") == "0.1.0"
assert version("obst-defaults") == "0.1.0"
assert metadata("obst")["License-Expression"] == "MPL-2.0"
assert metadata("obst-defaults")["License-Expression"] == "MPL-2.0"

state_path = Path(sys.argv[1]) / "plugins.json"
manager = PluginManager.discover(state_path=state_path)
status = manager.status("obst-defaults")
assert status.installed
assert not status.enabled
assert "obst_defaults" not in sys.modules

runtime = manager.runtime(("obst-defaults",))
assert runtime.plugin_names == ("obst-defaults",)
assert {command.name for command in runtime.commands} == {"pack", "unpack"}
assert runtime.registry.can_encode("obst.raw@1")
"""
_RUNTIME_ONLY_PROBE = """
from importlib.metadata import PackageNotFoundError, metadata, version

from obst.plugins import PluginManager

assert version("obst") == "0.1.0"
assert metadata("obst")["License-Expression"] == "MPL-2.0"
try:
    version("obst-defaults")
except PackageNotFoundError:
    pass
else:
    raise AssertionError("runtime-only environment unexpectedly contains defaults")
assert PluginManager.discover().catalog() == ()
"""
_EXAMPLE_PLUGIN_PROBE = """
import sys
from importlib.metadata import version
from pathlib import Path

from obst.plugins import PluginManager

assert version("obst-example-adaptive-zlib") == "0.1.0"
manager = PluginManager.discover(state_path=Path(sys.argv[1]) / "plugins.json")
status = manager.status("adaptive-zlib")
assert status.installed
assert not status.enabled
assert "obst_example_adaptive_zlib" not in sys.modules
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
        cwd=_PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _venv_python(environment_root: Path) -> Path:
    return environment_root / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )


def _probe_installation(python: Path, config_home: Path) -> None:
    _run(
        [python, "-c", _INSTALLATION_PROBE, config_home],
        environment=_environment(config_home),
    )


def _probe_runtime_only(python: Path, config_home: Path) -> None:
    environment = _environment(config_home)
    _run([python, "-c", _RUNTIME_ONLY_PROBE], environment=environment)
    _run(
        [python, "-m", "obst.cli", "help", "inspect"],
        environment=environment,
    )
    _run(
        [
            python,
            "-m",
            "obst.cli",
            "inspect",
            _PROJECT_ROOT / "samples" / "apple.obst",
            "--json",
        ],
        environment=environment,
    )


def _probe_example_plugin(python: Path, config_home: Path) -> None:
    _run(
        [python, "-c", _EXAMPLE_PLUGIN_PROBE, config_home],
        environment=_environment(config_home),
    )


def _assert_wheels_include_mpl_license(wheelhouse: Path) -> None:
    expected = (_PROJECT_ROOT / "LICENSE").read_bytes()
    wheels = tuple(wheelhouse.glob("*.whl"))
    assert len(wheels) == len(_BUILD_PROJECTS)
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            license_names = tuple(
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/licenses/LICENSE")
            )
            assert len(license_names) == 1
            assert archive.read(license_names[0]) == expected


@pytest.mark.timeout(120)
def test_runtime_and_defaults_support_editable_installation(tmp_path: Path) -> None:
    environment_root = tmp_path / "editable"
    config_home = tmp_path / "editable-config"
    _run(
        [sys.executable, "-m", "venv", "--system-site-packages", environment_root],
        environment=_environment(config_home),
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
            *(part for project in _PROJECTS for part in ("-e", project)),
        ],
        environment=_environment(config_home),
    )

    _probe_installation(python, config_home)


@pytest.mark.timeout(120)
def test_runtime_and_defaults_wheels_install_together(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    build_environment = _environment(tmp_path / "build-config")
    for project in _BUILD_PROJECTS:
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
                project,
            ],
            environment=build_environment,
        )
    _assert_wheels_include_mpl_license(wheelhouse)

    environment_root = tmp_path / "wheel"
    config_home = tmp_path / "wheel-config"
    _run(
        [sys.executable, "-m", "venv", environment_root],
        environment=_environment(config_home),
    )
    python = _venv_python(environment_root)
    _run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            wheelhouse,
            "obst==0.1.0",
        ],
        environment=_environment(config_home),
    )
    _probe_runtime_only(python, config_home)
    _run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            wheelhouse,
            "obst-example-adaptive-zlib==0.1.0",
        ],
        environment=_environment(config_home),
    )
    _probe_example_plugin(python, config_home)
    _run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            wheelhouse,
            "obst-defaults==0.1.0",
        ],
        environment=_environment(config_home),
    )

    _probe_installation(python, config_home)

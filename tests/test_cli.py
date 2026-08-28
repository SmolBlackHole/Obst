from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

import obst.cli.main as cli_main
from obst.cli.commands import EXIT_INVALID_CONTAINER, EXIT_SUCCESS
from obst.core import (
    BYTES_STREAM_TYPE,
    ContainerWriter,
    Manifest,
    Recipe,
    StageSpec,
    Stream,
)
from obst.plugins import PluginManager


def _empty_manager(tmp_path: Path) -> PluginManager:
    return PluginManager(
        installed={},
        state_path=tmp_path / "plugins.json",
    )


def _install_empty_manager(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _empty_manager(tmp_path)
    monkeypatch.setattr(cli_main, "_plugin_manager", lambda: manager)


def _write_structural_container(path: Path) -> None:
    manifest = Manifest(
        recipes=(Recipe(0, (StageSpec("org.example/missing@1"),)),),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    with path.open("wb") as target:
        ContainerWriter(target, manifest).finish()


def test_help_is_native_and_does_not_require_plugins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_empty_manager(monkeypatch, tmp_path)

    assert cli_main.main(["help"]) == EXIT_SUCCESS

    output = capsys.readouterr().out
    assert "inspect" in output
    assert "plugins" in output
    assert "extensions" in output


def test_inspect_is_available_without_extension_plugins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_empty_manager(monkeypatch, tmp_path)
    container = tmp_path / "structural.obst"
    _write_structural_container(container)

    assert cli_main.main(["inspect", str(container)]) == EXIT_SUCCESS

    output = capsys.readouterr().out
    assert "OBST container 0.1-apple" in output
    assert "Required decoders available" in output
    assert "org.example/missing@1: decoder missing" in output


def test_plugin_catalog_is_inert_and_empty_without_installed_contributions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_empty_manager(monkeypatch, tmp_path)

    assert cli_main.main(["plugins", "list"]) == EXIT_SUCCESS

    output = capsys.readouterr().out
    assert "Metadata only; plugin code was not loaded." in output
    assert "none" in output


def test_extension_inventory_uses_the_empty_runtime_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_empty_manager(monkeypatch, tmp_path)

    assert cli_main.main(["extensions"]) == EXIT_SUCCESS

    output = capsys.readouterr().out
    assert "Extension capabilities" in output
    assert "none" in output


def test_invalid_container_maps_to_the_documented_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_empty_manager(monkeypatch, tmp_path)
    invalid = tmp_path / "invalid.obst"
    invalid.write_bytes(b"not an OBST container")

    assert cli_main.main(["inspect", str(invalid)]) == EXIT_INVALID_CONTAINER

    assert "truncated_container" in capsys.readouterr().err


def test_redirected_utf8_output_keeps_the_human_apple(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_empty_manager(monkeypatch, tmp_path)
    container = tmp_path / "structural.obst"
    _write_structural_container(container)
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)

    assert cli_main.main(["inspect", str(container)]) == EXIT_SUCCESS
    assert "███████" in output.getvalue()

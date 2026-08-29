from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

import obst.cli.main as cli_main
from obst.cli.commands import (
    EXIT_INVALID_CONTAINER,
    EXIT_LIMIT_STATE,
    EXIT_RESOURCE_LIMIT,
    EXIT_SUCCESS,
)
from obst.core import (
    BYTES_STREAM_TYPE,
    ContainerWriter,
    Manifest,
    Recipe,
    StageSpec,
    Stream,
)
from obst.plugins import PluginManager
from tests.support_resources import accounting as _accounting


def _empty_manager(tmp_path: Path) -> PluginManager:
    return PluginManager(
        installed={},
        state_path=tmp_path / "plugins.json",
    )


def _install_empty_manager(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OBST_CONFIG_HOME", str(tmp_path / "config"))
    manager = _empty_manager(tmp_path)
    monkeypatch.setattr(cli_main, "_plugin_manager", lambda: manager)


def _write_structural_container(path: Path) -> None:
    manifest = Manifest(
        recipes=(Recipe(0, (StageSpec("org.example/missing@1"),)),),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    with path.open("wb") as target:
        ContainerWriter(target, manifest, accounting=_accounting()).finish()


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
    assert "limits" in output


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
    assert "OBST container 0.2-apple" in output
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


def test_limit_profiles_can_be_created_selected_and_inspected_as_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_empty_manager(monkeypatch, tmp_path)

    assert cli_main.main(["limits", "create", "tiny", "--json"]) == EXIT_SUCCESS
    capsys.readouterr()
    assert (
        cli_main.main(["limits", "set", "tiny", "container_bytes", "1", "--json"])
        == EXIT_SUCCESS
    )
    capsys.readouterr()
    assert cli_main.main(["limits", "use", "tiny", "--json"]) == EXIT_SUCCESS
    capsys.readouterr()

    assert cli_main.main(["limits", "show", "--json"]) == EXIT_SUCCESS
    document = json.loads(capsys.readouterr().out)
    assert document["profile"] == {
        "active": True,
        "available": True,
        "id": "tiny",
        "mutable": True,
        "source": "custom",
        "summary": "Local custom resource profile.",
    }
    container_limit = next(
        resource
        for resource in document["resources"]
        if resource["id"] == "container_bytes"
    )
    assert container_limit == {
        "available": True,
        "default_maximum": 16 * 1024**3,
        "id": "container_bytes",
        "owner": "core",
        "profile_source": "tiny",
        "resolved_maximum": 1,
        "summary": "Bytes in one complete container.",
    }


def test_active_limit_profile_affects_structural_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_empty_manager(monkeypatch, tmp_path)
    container = tmp_path / "structural.obst"
    _write_structural_container(container)
    assert cli_main.main(["limits", "create", "tiny"]) == EXIT_SUCCESS
    capsys.readouterr()
    assert (
        cli_main.main(["limits", "set", "tiny", "container_bytes", "1"]) == EXIT_SUCCESS
    )
    capsys.readouterr()
    assert cli_main.main(["limits", "use", "tiny"]) == EXIT_SUCCESS
    capsys.readouterr()

    assert cli_main.main(["inspect", str(container)]) == EXIT_RESOURCE_LIMIT
    assert "resource_limit" in capsys.readouterr().err


def test_limit_state_failure_is_not_reported_as_a_plugin_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_empty_manager(monkeypatch, tmp_path)

    assert cli_main.main(["limits", "delete", "default"]) == EXIT_LIMIT_STATE
    error = capsys.readouterr().err
    assert "limit_state" in error
    assert "plugin_error" not in error


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

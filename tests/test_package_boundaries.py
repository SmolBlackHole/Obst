# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Architecture tests for the public package boundaries."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import subprocess
import sys
from pathlib import Path

import obst
import obst.core as core

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CORE_ROOT = _PROJECT_ROOT / "src" / "obst" / "core"
_FORBIDDEN_CORE_DEPENDENCIES = (
    "obst.cli",
    "obst.conformance",
    "obst_defaults",
    "obst.plugins",
)


def test_root_package_exposes_only_version_metadata() -> None:
    assert obst.__all__ == [
        "FormatVersion",
        "format_version",
    ]
    assert not hasattr(obst, "ContainerReader")
    assert not hasattr(obst, "RAW_EXTENSION")


def test_importing_root_does_not_load_cli_or_concrete_extensions() -> None:
    code = """
import sys
import obst

loaded = sorted(
    name
    for name in sys.modules
    if name == "obst.cli"
    or name.startswith("obst.cli.")
    or name == "obst_defaults"
    or name.startswith("obst_defaults.")
)
print("\\n".join(loaded))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "\n"


def test_core_source_does_not_import_cli_or_concrete_extensions() -> None:
    violations: list[str] = []
    for path in sorted(_CORE_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: tuple[str, ...]
            if isinstance(node, ast.Import):
                modules = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules = (node.module,)
            else:
                continue
            for module in modules:
                if module.startswith(_FORBIDDEN_CORE_DEPENDENCIES):
                    violations.append(f"{path.name}:{node.lineno}: {module}")

    assert violations == []


def test_plugin_manager_imports_only_the_public_cli_command_contract() -> None:
    path = _PROJECT_ROOT / "src" / "obst" / "plugins.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)

    assert not any(module.startswith("obst_defaults") for module in imported_modules)
    assert {module for module in imported_modules if module.startswith("obst.cli")} == {
        "obst.cli.commands"
    }


def test_generic_cli_imports_no_first_party_implementation() -> None:
    path = _PROJECT_ROOT / "src" / "obst" / "cli" / "main.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not any(module.startswith("obst_defaults") for module in imported_modules)


def test_registry_types_have_one_public_owner() -> None:
    extensions = importlib.import_module("obst.core.extensions")

    assert core.ExtensionContribution.__module__ == "obst.core.registry"
    assert core.ExtensionRegistry.__module__ == "obst.core.registry"
    assert core.ExtensionRegistryBuilder.__module__ == "obst.core.registry"
    assert not hasattr(extensions, "ExtensionRegistry")
    assert not hasattr(extensions, "ExtensionRegistryBuilder")


def test_core_does_not_expose_adapter_specific_errors() -> None:
    adapter_errors = (
        "ArchiveError",
        "CarrierError",
        "CarrierStateError",
        "ProfileError",
        "FileArchiveError",
        "FileProfileError",
    )

    assert all(not hasattr(core, name) for name in adapter_errors)


def test_production_code_imports_registry_types_from_the_registry_module() -> None:
    violations: list[str] = []
    for path in sorted((_PROJECT_ROOT / "src" / "obst").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != "obst.core.extensions":
                continue
            imported = {alias.name for alias in node.names}
            forbidden = imported & {"ExtensionRegistry", "ExtensionRegistryBuilder"}
            if forbidden:
                names = ", ".join(sorted(forbidden))
                violations.append(
                    f"{path.relative_to(_PROJECT_ROOT)}:{node.lineno}: {names}"
                )

    assert violations == []


def test_removed_module_layout_has_no_compatibility_packages() -> None:
    removed_package_paths = (
        "archivers",
        "carriers",
        "codecs",
        "profiles",
        "transforms",
    )

    assert all(
        not (_PROJECT_ROOT / "src" / "obst" / name / "__init__.py").exists()
        for name in removed_package_paths
    )
    assert not (_CORE_ROOT / "constants.py").exists()


def test_public_core_operations_require_explicit_resource_accounting() -> None:
    operations = (
        core.ChunkDecoder,
        core.ChunkEncoder,
        core.ContainerReader,
        core.ContainerWriter,
        core.RecipeDecoder,
        core.RecipeEncoder,
        core.decode_chunk_once,
        core.decode_recipe,
        core.encode_chunk_once,
        core.encode_recipe,
        core.validate_manifest_resources,
    )

    for operation in operations:
        parameters = inspect.signature(operation).parameters
        assert "accounting" in parameters
        assert parameters["accounting"].default is inspect.Parameter.empty
        assert "policy" not in parameters
        assert "_budget" not in parameters


def test_resource_contracts_have_one_public_owner() -> None:
    resources = importlib.import_module("obst.resources")
    generic_names = (
        "LimitProfile",
        "ResourceAggregation",
        "ResourceCatalog",
        "ResourceContribution",
        "ResourceDefinition",
        "ResourceKind",
        "ResourcePolicy",
        "ResourceUnit",
        "validate_resource_identifier",
    )

    assert all(hasattr(resources, name) for name in generic_names)
    assert all(not hasattr(core, name) for name in generic_names)
    assert core.ResourceAccounting.__module__ == "obst.core.resource_accounting"
    assert core.ResourceLimitError.__module__ == "obst.core.resource_accounting"


def test_removed_resource_modules_have_no_compatibility_path() -> None:
    assert importlib.util.find_spec("obst.limits") is None
    assert importlib.util.find_spec("obst.core.resources") is None


def test_core_operation_layers_do_not_import_private_cross_module_helpers() -> None:
    operation_modules = ("container.py", "packaging.py", "pipeline.py", "streams.py")
    violations: list[str] = []
    for filename in operation_modules:
        path = _CORE_ROOT / filename
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        if "reportPrivateUsage" in source:
            violations.append(f"{filename}: reportPrivateUsage suppression")
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module is None or not node.module.startswith("obst.core."):
                continue
            for imported in node.names:
                if imported.name.startswith("_"):
                    violations.append(
                        f"{filename}:{node.lineno}: {node.module}.{imported.name}"
                    )

    assert violations == []


def test_public_core_exposes_directional_recipe_and_chunk_sessions() -> None:
    assert core.RecipeEncoder.__module__ == "obst.core.pipeline"
    assert core.RecipeDecoder.__module__ == "obst.core.pipeline"
    assert core.ChunkEncoder.__module__ == "obst.core.streams"
    assert core.ChunkDecoder.__module__ == "obst.core.streams"
    assert not hasattr(core, "ContainerDecoder")

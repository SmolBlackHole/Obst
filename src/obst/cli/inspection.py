"""Native CLI inspection over local paths or the standard binary input."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TextIO, cast

from obst.cli.commands import EXIT_SUCCESS, EXIT_UNSUPPORTED
from obst.cli.output import render_inspection_human, render_inspection_json
from obst.cli.presentation import HumanOutputStyle
from obst.core.container import ContainerReader
from obst.core.inspection import (
    ContainerInspection,
    InspectionInterpretationPolicy,
    inspect_container,
)
from obst.core.io import BinaryReader
from obst.core.registry import (
    ExtensionRegistry,
    StageCapability,
    StreamProfileCapability,
)
from obst.core.resource_accounting import ResourceAccounting


def configure_inspect_parser(parser: argparse.ArgumentParser) -> None:
    """Declare the native container-inspection command arguments."""
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="container path, or - for stdin (default: -)",
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--json",
        action="store_true",
        help="emit a stable machine-readable summary",
    )
    output.add_argument(
        "--quiet",
        action="store_true",
        help="emit no summary and communicate only through the exit code",
    )
    parser.add_argument(
        "--require-decodable",
        action="store_true",
        help="fail when a stage required by a payload chunk is unavailable",
    )
    parser.add_argument(
        "--structural",
        action="store_true",
        help="skip all metadata and parameter interpreter callbacks",
    )


def run_inspect(
    args: argparse.Namespace,
    *,
    registry: ExtensionRegistry,
    stdin: BinaryReader,
    stdout: TextIO,
    accounting: ResourceAccounting,
) -> int:
    """Inspect one container without decoding its payload chunks."""
    if args.input == "-":
        inspection = _inspect_source(
            stdin,
            registry=registry,
            accounting=accounting,
            interpret=not args.structural and not args.quiet,
        )
    else:
        with Path(args.input).open("rb") as opened:
            inspection = _inspect_source(
                cast(BinaryReader, opened),
                registry=registry,
                accounting=accounting,
                interpret=not args.structural and not args.quiet,
            )
    if not args.quiet:
        rendered = (
            render_inspection_json(inspection)
            if args.json
            else render_inspection_human(
                inspection,
                style=HumanOutputStyle.for_stream(stdout),
            )
        )
        stdout.write(rendered)
    if args.require_decodable and not inspection.required_decoders_available:
        return EXIT_UNSUPPORTED
    return EXIT_SUCCESS


def _inspect_source(
    source: BinaryReader,
    *,
    registry: ExtensionRegistry,
    accounting: ResourceAccounting,
    interpret: bool,
) -> ContainerInspection:
    reader = ContainerReader(source, accounting=accounting)
    return inspect_container(
        reader,
        registry=registry,
        interpretation_policy=(_interpretation_policy(registry) if interpret else None),
    )


def _interpretation_policy(
    registry: ExtensionRegistry,
) -> InspectionInterpretationPolicy:
    return InspectionInterpretationPolicy(
        frozenset(
            capability.extension_id
            for capability in registry.capabilities()
            if (
                isinstance(capability, StageCapability)
                and capability.parameter_interpreter_available
            )
            or (
                isinstance(capability, StreamProfileCapability)
                and capability.metadata_interpreter_available
            )
        )
    )


__all__ = ["configure_inspect_parser", "run_inspect"]

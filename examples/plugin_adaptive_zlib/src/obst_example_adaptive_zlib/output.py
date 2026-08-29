"""Human and JSON output owned by the adaptive pack example command."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from obst.cli import HumanOutputStyle, format_size

ADAPTIVE_PACK_JSON_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class AdaptivePackResult:
    """Projection of one completed adaptive package."""

    destination: Path
    logical_size: int
    container_size: int
    chunk_count: int


def write_adaptive_pack_result(
    result: AdaptivePackResult,
    *,
    stdout: TextIO,
    json_output: bool = False,
) -> None:
    """Write one completed adaptive package result."""
    if json_output:
        stdout.write(render_adaptive_pack_result_json(result))
        return
    style = HumanOutputStyle.for_stream(stdout)
    stdout.write(
        f"{style.success('Adaptive pack complete')}\n"
        f"{style.field('Logical size', format_size(result.logical_size))}\n"
        f"{style.field('Container size', format_size(result.container_size))}\n"
        f"{style.field('Chunks', f'{result.chunk_count:,}')}\n"
    )


def render_adaptive_pack_result_json(result: AdaptivePackResult) -> str:
    """Render one completed adaptive package as stable JSON."""
    document = {
        "schema_version": ADAPTIVE_PACK_JSON_SCHEMA_VERSION,
        "destination": str(result.destination),
        "logical_size": result.logical_size,
        "container_size": result.container_size,
        "chunks": result.chunk_count,
    }
    return json.dumps(document, indent=4, sort_keys=True) + "\n"


__all__ = [
    "ADAPTIVE_PACK_JSON_SCHEMA_VERSION",
    "AdaptivePackResult",
    "render_adaptive_pack_result_json",
    "write_adaptive_pack_result",
]

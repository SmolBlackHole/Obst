# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Human-readable projections owned by the first-party file commands."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from obst.cli import (
    HumanOutputStyle,
    escape_human_text,
    format_count,
    format_size,
    render_human_table,
)

from obst_defaults.carriers import PublicationCleanupIssue
from obst_defaults.files import FileExtractionCleanupIssue, FileExtractionResult

PACK_JSON_SCHEMA_VERSION = 1
UNPACK_JSON_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class PackCommandMember:
    """One file row in the successful pack command output."""

    name: str
    logical_size: int
    chunk_count: int


@dataclass(frozen=True, slots=True)
class PackCommandResult:
    """Projection of a completed first-party file publication."""

    target: Path
    encoded_size: int
    members: tuple[PackCommandMember, ...]
    cleanup_issues: tuple[PublicationCleanupIssue, ...]


def write_pack_result(
    result: PackCommandResult,
    *,
    stdout: TextIO,
    stderr: TextIO,
    json_output: bool = False,
) -> None:
    """Write one successful first-party pack result."""
    if json_output:
        stdout.write(render_pack_result_json(result))
        _write_cleanup_issues(result.cleanup_issues, stderr=stderr)
        return
    members = result.members
    style = HumanOutputStyle.for_stream(stdout)
    print(style.success(f"Packed {format_count(len(members), 'file')}"), file=stdout)
    print(
        style.field("Destination", escape_human_text(result.target)),
        file=stdout,
    )
    print(style.field("Container size", format_size(result.encoded_size)), file=stdout)
    print(f"\n{style.heading('Files')}", file=stdout)
    print(
        render_human_table(
            ("File", "Size", "Chunks"),
            tuple(
                (
                    style.contributed(escape_human_text(member.name)),
                    format_size(member.logical_size),
                    f"{member.chunk_count:,}",
                )
                for member in members
            ),
            right_align=frozenset({1, 2}),
        ),
        file=stdout,
    )
    _write_cleanup_issues(result.cleanup_issues, stderr=stderr)


def write_unpack_result(
    result: FileExtractionResult,
    *,
    stdout: TextIO,
    stderr: TextIO,
    windows_origin_not_propagated: bool = False,
    json_output: bool = False,
) -> None:
    """Write one successful first-party unpack result."""
    if json_output:
        stdout.write(
            render_unpack_result_json(
                result,
                windows_origin_not_propagated=windows_origin_not_propagated,
            )
        )
        _write_cleanup_issues(result.cleanup_issues, stderr=stderr)
        _write_windows_origin_warning(
            windows_origin_not_propagated,
            stderr=stderr,
        )
        return
    paths = result.paths
    style = HumanOutputStyle.for_stream(stdout)
    print(
        style.success(f"Unpacked {format_count(len(paths), 'file')}"),
        file=stdout,
    )
    print(
        style.field("Destination", escape_human_text(result.output_directory)),
        file=stdout,
    )
    print(f"\n{style.heading('Files')}", file=stdout)
    if not paths:
        print("  none", file=stdout)
    else:
        print(
            render_human_table(
                ("File",),
                tuple(
                    (style.contributed(escape_human_text(path.name)),) for path in paths
                ),
            ),
            file=stdout,
        )
    _write_cleanup_issues(result.cleanup_issues, stderr=stderr)
    _write_windows_origin_warning(windows_origin_not_propagated, stderr=stderr)


def render_pack_result_json(result: PackCommandResult) -> str:
    """Render one completed file package as stable JSON."""
    document = {
        "schema_version": PACK_JSON_SCHEMA_VERSION,
        "destination": str(result.target),
        "container_size": result.encoded_size,
        "files": [
            {
                "name": member.name,
                "logical_size": member.logical_size,
                "chunks": member.chunk_count,
            }
            for member in result.members
        ],
        "cleanup_issues": [
            _cleanup_issue_json(issue) for issue in result.cleanup_issues
        ],
    }
    return json.dumps(document, indent=4, sort_keys=True) + "\n"


def render_unpack_result_json(
    result: FileExtractionResult,
    *,
    windows_origin_not_propagated: bool = False,
) -> str:
    """Render one completed file extraction as stable JSON."""
    document = {
        "schema_version": UNPACK_JSON_SCHEMA_VERSION,
        "destination": str(result.output_directory),
        "files": [
            {
                "name": path.name,
                "path": str(path),
            }
            for path in result.paths
        ],
        "cleanup_issues": [
            _cleanup_issue_json(issue) for issue in result.cleanup_issues
        ],
        "windows_origin_not_propagated": windows_origin_not_propagated,
    }
    return json.dumps(document, indent=4, sort_keys=True) + "\n"


def _cleanup_issue_json(
    issue: PublicationCleanupIssue | FileExtractionCleanupIssue,
) -> dict[str, str]:
    return {
        "resource": str(issue.resource),
        "reason": issue.reason,
    }


def _write_windows_origin_warning(
    windows_origin_not_propagated: bool,
    *,
    stderr: TextIO,
) -> None:
    if not windows_origin_not_propagated:
        return
    warning_style = HumanOutputStyle.for_stream(stderr)
    print(
        f"{warning_style.warning('obst: warning:')} input has Windows Mark "
        "of the Web; extracted files do not inherit it and may be treated "
        "as local files",
        file=stderr,
    )


def _write_cleanup_issues(
    cleanup_issues: tuple[
        PublicationCleanupIssue | FileExtractionCleanupIssue,
        ...,
    ],
    *,
    stderr: TextIO,
) -> None:
    style = HumanOutputStyle.for_stream(stderr)
    for issue in cleanup_issues:
        print(
            f"{style.warning('obst: cleanup_required:')} published output is complete; "
            f"remove {escape_human_text(issue.resource)}: "
            f"{escape_human_text(issue.reason)}",
            file=stderr,
        )


__all__ = [
    "PACK_JSON_SCHEMA_VERSION",
    "UNPACK_JSON_SCHEMA_VERSION",
    "PackCommandMember",
    "PackCommandResult",
    "render_pack_result_json",
    "render_unpack_result_json",
    "write_pack_result",
    "write_unpack_result",
]

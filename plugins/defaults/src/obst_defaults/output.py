"""Human-readable projections owned by the first-party file commands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from obst.cli import (
    HumanOutputStyle,
    escape_human_text,
    format_count,
    format_size,
)
from obst_defaults.carriers import PublicationCleanupIssue
from obst_defaults.files import FileExtractionCleanupIssue, FileExtractionResult


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
) -> None:
    """Write one successful first-party pack result."""
    members = result.members
    style = HumanOutputStyle.for_stream(stdout)
    print(style.success(f"Packed {format_count(len(members), 'file')}"), file=stdout)
    print(
        style.field("Destination", escape_human_text(result.target)),
        file=stdout,
    )
    print(style.field("Container size", format_size(result.encoded_size)), file=stdout)
    print(f"\n{style.heading('Files')}", file=stdout)
    name_width = max(len(escape_human_text(member.name)) for member in members)
    for member in members:
        name = escape_human_text(member.name)
        print(
            f"  {style.identifier(name.ljust(name_width))}  "
            f"{format_size(member.logical_size):>10}  "
            f"{format_count(member.chunk_count, 'chunk')}",
            file=stdout,
        )
    _write_cleanup_issues(result.cleanup_issues, stderr=stderr)


def write_unpack_result(
    result: FileExtractionResult,
    *,
    stdout: TextIO,
    stderr: TextIO,
    windows_origin_not_propagated: bool = False,
) -> None:
    """Write one successful first-party unpack result."""
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
    for path in paths:
        print(f"  {style.identifier(escape_human_text(path.name))}", file=stdout)
    _write_cleanup_issues(result.cleanup_issues, stderr=stderr)
    if windows_origin_not_propagated:
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
    "PackCommandMember",
    "PackCommandResult",
    "write_pack_result",
    "write_unpack_result",
]

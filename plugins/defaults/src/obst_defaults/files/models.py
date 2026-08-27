"""Typed values owned by the first-party portable-file feature."""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Final

_GIB = 1024 * 1024 * 1024


def _require_optional_limit(name: str, value: object) -> None:
    if value is None:
        return
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer or None")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class FileExtractionCleanupIssue:
    """One residual resource left after successful file extraction."""

    resource: str
    reason: str


@dataclass(frozen=True, slots=True)
class FileExtractionResult:
    """Complete filesystem extraction result."""

    output_directory: Path
    paths: tuple[Path, ...]
    cleanup_issues: tuple[FileExtractionCleanupIssue, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class FileExtractionLimits:
    """Filesystem-specific ceilings for one file extraction operation."""

    max_members: int | None = 4_096
    max_member_bytes: int | None = 4 * _GIB
    max_total_bytes: int | None = 16 * _GIB

    def __post_init__(self) -> None:
        for limit_field in fields(self):
            _require_optional_limit(
                limit_field.name,
                getattr(self, limit_field.name),
            )


DEFAULT_FILE_EXTRACTION_LIMITS: Final = FileExtractionLimits()


@dataclass(frozen=True, slots=True)
class FileMaterialization:
    """One regular file planned from a logical stream."""

    name: str

    def __post_init__(self) -> None:
        if type(self.name) is not str:
            raise TypeError("file materialization name must be an exact string")
        if not self.name:
            raise ValueError("file materialization name cannot be empty")


@dataclass(frozen=True, slots=True)
class PortableFileMetadata:
    """Typed local metadata for ``obst.file@1``."""

    name: str

    def __post_init__(self) -> None:
        if type(self.name) is not str:
            raise TypeError("portable file name must be an exact string")


__all__ = [
    "DEFAULT_FILE_EXTRACTION_LIMITS",
    "FileExtractionCleanupIssue",
    "FileExtractionLimits",
    "FileExtractionResult",
    "FileMaterialization",
    "PortableFileMetadata",
]

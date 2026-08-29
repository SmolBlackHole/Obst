"""Typed values owned by the first-party portable-file feature."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
    "FileExtractionCleanupIssue",
    "FileExtractionResult",
    "FileMaterialization",
    "PortableFileMetadata",
]

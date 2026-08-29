"""Public first-party portable-file profile and adapter API."""

from obst_defaults.files.adapter import DEFAULT_FILE_CHUNK_SIZE, FileArchiver
from obst_defaults.files.errors import FileArchiveError, FileProfileError
from obst_defaults.files.models import (
    FileExtractionCleanupIssue,
    FileExtractionResult,
    FileMaterialization,
    PortableFileMetadata,
)
from obst_defaults.files.profile import (
    FileExtension,
    FileMaterializer,
    FileSourceProfile,
)
from obst_defaults.files.resources import FileResource

__all__ = [
    "DEFAULT_FILE_CHUNK_SIZE",
    "FileArchiveError",
    "FileArchiver",
    "FileExtension",
    "FileExtractionCleanupIssue",
    "FileExtractionResult",
    "FileMaterialization",
    "FileMaterializer",
    "FileProfileError",
    "FileResource",
    "FileSourceProfile",
    "PortableFileMetadata",
]

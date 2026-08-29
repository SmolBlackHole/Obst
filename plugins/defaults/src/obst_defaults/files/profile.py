# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Portable file stream-profile contract and first-party implementation."""

from __future__ import annotations

import unicodedata
from typing import Protocol, runtime_checkable

from obst.core.errors import ProviderRejectedError
from obst.core.extensions import (
    ExtensionDescriptor,
    ExtensionKind,
    InspectionField,
    InspectionInterpretation,
    StreamProfileExtension,
)

from obst_defaults.files.errors import FileProfileError
from obst_defaults.files.models import FileMaterialization, PortableFileMetadata

_MAX_FILENAME_BYTES = 255
_INVALID_FILENAME_CHARACTERS = frozenset('<>:"/\\|?*')
_BIDI_CONTROL_CHARACTERS = frozenset(
    {
        "\u061c",
        "\u200e",
        "\u200f",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
    }
)
_RESERVED_FILENAMES = frozenset(
    {
        "aux",
        "con",
        "nul",
        "prn",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
)


@runtime_checkable
class FileSourceProfile(StreamProfileExtension, Protocol):
    """Represent one regular file as one logical stream."""

    def encode_file_name(self, name: str, /) -> bytes:
        """Encode a regular-file name as authoritative stream metadata."""
        ...


@runtime_checkable
class FileMaterializer(StreamProfileExtension, Protocol):
    """Plan one regular file from one logical stream."""

    def plan_file(self, metadata: bytes, /) -> FileMaterialization:
        """Interpret metadata without writing to the filesystem."""
        ...


class FileExtension:
    """Own the complete portable ``obst.file@1`` stream contract."""

    extension_id = "obst.file@1"
    kind = ExtensionKind.STREAM_PROFILE
    descriptor = ExtensionDescriptor(
        display_name="Portable file",
        summary="One portable basename and its exact file bytes.",
        specification_url=(
            "https://github.com/SmolBlackHole/Obst/blob/main/"
            "plugins/defaults/docs/contracts/streams/file.md"
        ),
    )

    def encode_metadata(self, value: PortableFileMetadata, /) -> bytes:
        """Encode one typed portable-file value as canonical metadata."""
        if type(value) is not PortableFileMetadata:
            raise TypeError("value must be exact PortableFileMetadata")
        return normalize_file_name(self.extension_id, value.name).encode("utf-8")

    def decode_metadata(self, metadata: bytes, /) -> PortableFileMetadata:
        """Decode canonical metadata into one typed portable-file value."""
        if type(metadata) is not bytes:
            raise TypeError("metadata must be exact bytes")
        try:
            name = metadata.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProviderRejectedError("file metadata is not valid UTF-8") from exc
        try:
            if unicodedata.normalize("NFC", name) != name:
                raise profile_error(
                    self.extension_id,
                    "file metadata is not normalized as NFC",
                )
            normalized = normalize_file_name(self.extension_id, name)
        except FileProfileError as exc:
            raise ProviderRejectedError(exc.reason) from exc
        return PortableFileMetadata(normalized)

    def encode_file_name(self, name: str, /) -> bytes:
        """Author file metadata for the regular-file source adapter."""
        return self.encode_metadata(PortableFileMetadata(name))

    def plan_file(self, metadata: bytes, /) -> FileMaterialization:
        """Plan one portable regular file from canonical metadata."""
        try:
            decoded = self.decode_metadata(metadata)
        except ProviderRejectedError as exc:
            raise profile_error(self.extension_id, exc.reason) from exc
        return FileMaterialization(decoded.name)

    def interpret_metadata(
        self,
        metadata: bytes,
        /,
    ) -> InspectionInterpretation:
        """Interpret file metadata without changing its authoritative bytes."""
        try:
            name = self.decode_metadata(metadata).name
        except ProviderRejectedError as exc:
            return InspectionInterpretation(error=exc.reason)
        return InspectionInterpretation(
            label=name,
            fields=(InspectionField("name", name),),
        )


def normalize_file_name(profile_id: str, name: str) -> str:
    """Return one canonical portable basename or raise the profile error."""
    normalized = unicodedata.normalize("NFC", name)
    if not normalized or normalized in {".", ".."}:
        raise profile_error(profile_id, "file name must be a non-empty basename")
    if normalized.endswith((" ", ".")):
        raise profile_error(profile_id, "file name cannot end with a space or dot")
    if any(character in _INVALID_FILENAME_CHARACTERS for character in normalized):
        raise profile_error(
            profile_id,
            "file name contains a non-portable path character",
        )
    if any(unicodedata.category(character) == "Cc" for character in normalized):
        raise profile_error(profile_id, "file name contains a control character")
    if any(character in _BIDI_CONTROL_CHARACTERS for character in normalized):
        raise profile_error(
            profile_id,
            "file name contains a bidirectional control character",
        )
    if normalized.split(".", 1)[0].casefold() in _RESERVED_FILENAMES:
        raise profile_error(profile_id, "file name is reserved on Windows")
    try:
        encoded_name = normalized.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise profile_error(
            profile_id,
            "file name is not valid UTF-8",
        ) from exc
    if len(encoded_name) > _MAX_FILENAME_BYTES:
        raise profile_error(
            profile_id,
            f"UTF-8 file name exceeds {_MAX_FILENAME_BYTES} metadata bytes",
        )
    return normalized


def profile_error(profile_id: str, reason: str) -> FileProfileError:
    """Create one file-profile error carrying the authoritative profile ID."""
    return FileProfileError(profile_id, reason)


__all__ = [
    "FileExtension",
    "FileMaterializer",
    "FileSourceProfile",
]

# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Filesystem adapter composition for portable file stream capabilities."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from collections.abc import Generator, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO, cast

from obst.core.container import ContainerReader
from obst.core.errors import (
    ExtensionContractError,
    ExtensionRegistrationError,
)
from obst.core.extensions import ExtensionKind
from obst.core.model import Manifest, validate_extension_id
from obst.core.packaging import (
    LogicalStreamDescriptor,
    LogicalStreamSource,
    RecipeSpec,
)
from obst.core.registry import ExtensionContribution, ExtensionRegistry
from obst.core.resource_accounting import ResourceAccounting
from obst.core.streams import ChunkDecoder

from obst_defaults.cleanup import close_all
from obst_defaults.files.errors import FileArchiveError, FileProfileError
from obst_defaults.files.models import (
    FileExtractionCleanupIssue,
    FileExtractionResult,
    FileMaterialization,
)
from obst_defaults.files.profile import (
    FileMaterializer,
    FileSourceProfile,
    normalize_file_name,
    profile_error,
)
from obst_defaults.files.resources import FileResource

DEFAULT_FILE_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True, slots=True)
class _FileEntry:
    stream_id: int
    name: str


@dataclass(frozen=True, slots=True)
class _FileCapabilities:
    source_profiles: Mapping[str, FileSourceProfile]
    materializers: Mapping[str, FileMaterializer]


@dataclass(frozen=True, slots=True)
class FileArchiver:
    """Adapt regular files through explicitly supplied extension capabilities."""

    registry: ExtensionRegistry
    _source_profiles: Mapping[str, FileSourceProfile] = field(
        init=False,
        repr=False,
    )
    _materializers: Mapping[str, FileMaterializer] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if type(self.registry) is not ExtensionRegistry:
            raise TypeError("registry must be an exact ExtensionRegistry")
        capabilities = _compose_file_capabilities(self.registry.contributions())
        object.__setattr__(self, "_source_profiles", capabilities.source_profiles)
        object.__setattr__(self, "_materializers", capabilities.materializers)

    def can_source(self, profile_id: str) -> bool:
        """Return whether an active profile can author regular-file streams."""
        return profile_id in self._source_profiles

    def can_materialize(self, profile_id: str) -> bool:
        """Return whether an active profile can materialize regular files."""
        return profile_id in self._materializers

    def plan_file(
        self,
        profile_id: str,
        metadata: bytes,
        /,
    ) -> FileMaterialization:
        """Resolve one profile and return its safe regular-file plan."""
        validate_extension_id(profile_id)
        if type(metadata) is not bytes:
            raise TypeError("metadata must be exact bytes")
        materializer = self._materializers.get(profile_id)
        if materializer is None:
            raise FileArchiveError(
                f"stream type {profile_id} has no active file materializer"
            )
        plan = _plan_file(profile_id, materializer, metadata)
        return FileMaterialization(
            normalize_file_name(profile_id, plan.name),
        )

    @contextmanager
    def open_sources(
        self,
        source_paths: Sequence[Path],
        *,
        source_profile_id: str,
        recipe: RecipeSpec,
        chunk_size: int = DEFAULT_FILE_CHUNK_SIZE,
    ) -> Generator[tuple[LogicalStreamSource, ...]]:
        """Open regular files once and expose bounded sources over those handles."""
        validate_extension_id(source_profile_id)
        if type(recipe) is not RecipeSpec:
            raise TypeError("recipe must be an exact RecipeSpec")
        source_profile = self._source_profiles.get(source_profile_id)
        if source_profile is None:
            raise FileArchiveError(
                f"missing file source capability for {source_profile_id}"
            )
        chunk_size = _require_positive_int("chunk_size", chunk_size)
        if not source_paths:
            raise FileArchiveError("at least one input file is required")
        planned: list[tuple[Path, LogicalStreamDescriptor]] = []
        names: set[str] = set()
        for path in source_paths:
            name = normalize_file_name(source_profile_id, path.name)
            comparison_name = name.casefold()
            if comparison_name in names:
                raise FileArchiveError(f"duplicate portable filename: {name}")
            names.add(comparison_name)
            planned.append(
                (
                    path,
                    LogicalStreamDescriptor(
                        stream_type=source_profile_id,
                        metadata=_encode_file_name(
                            source_profile_id,
                            source_profile,
                            name,
                        ),
                        default_recipe=recipe,
                    ),
                )
            )
        opened_files: list[tuple[Path, BinaryIO]] = []
        primary_error: BaseException | None = None
        try:
            sources: list[LogicalStreamSource] = []
            for path, descriptor in planned:
                input_file = _open_regular_file(source_profile_id, path)
                opened_files.append((path, input_file))
                sources.append(
                    LogicalStreamSource(
                        descriptor,
                        _file_chunks(input_file, chunk_size),
                        max_chunk_bytes=chunk_size,
                    )
                )
            yield tuple(sources)
        except BaseException as error:
            primary_error = error
            raise
        finally:
            close_all(
                (
                    (f"input file {path}", input_file)
                    for path, input_file in reversed(opened_files)
                ),
                primary_error=primary_error,
            )

    def extract(
        self,
        reader: ContainerReader,
        output_directory: Path,
        *,
        accounting: ResourceAccounting,
    ) -> FileExtractionResult:
        """Decode and publish every file stream without overwriting a target."""
        if accounting is not reader.accounting:
            raise ValueError("file extraction must share the reader accounting")
        entries = self._entries(reader.manifest)
        accounting.record(
            FileResource.ARCHIVE_MEMBERS,
            len(entries),
            scope="file extraction",
            phase="file_extract",
        )
        output_identity = _prepare_extraction_directory(output_directory)
        targets = tuple(output_directory / entry.name for entry in entries)
        for target in targets:
            if _path_entry_exists(target):
                raise FileArchiveError(f"refusing to overwrite existing file: {target}")

        by_stream_id = {entry.stream_id: entry for entry in entries}
        decoder = ChunkDecoder(
            reader.index,
            self.registry,
            accounting=accounting,
        )
        member_sizes = {entry.stream_id: 0 for entry in entries}
        total_size = 0
        temporary_root = Path(
            tempfile.mkdtemp(
                dir=output_directory,
                prefix=".obst-unpack-",
            )
        )
        primary_error: BaseException | None = None
        cleanup_issues: tuple[FileExtractionCleanupIssue, ...] = ()
        try:
            _require_directory_identity(
                output_directory,
                output_identity,
            )
            temporary_paths = {
                entry.stream_id: temporary_root / entry.name for entry in entries
            }
            for temporary_path in temporary_paths.values():
                temporary_path.touch()

            for chunk in reader.iter_chunks():
                entry = by_stream_id[chunk.stream_id]
                member_size = member_sizes[chunk.stream_id] + chunk.logical_size
                observed_total = total_size + chunk.logical_size
                accounting.record(
                    FileResource.ARCHIVE_MEMBER_BYTES,
                    member_size,
                    scope=entry.name,
                    phase="file_extract",
                )
                accounting.record(
                    FileResource.ARCHIVE_TOTAL_BYTES,
                    chunk.logical_size,
                    scope="file extraction",
                    phase="file_extract",
                )
                decoded = decoder.decode(chunk)
                with temporary_paths[entry.stream_id].open("ab") as output_file:
                    output_file.write(decoded)
                member_sizes[chunk.stream_id] = member_size
                total_size = observed_total

            published: list[Path] = []
            try:
                for entry, target in zip(entries, targets, strict=True):
                    _require_directory_identity(
                        output_directory,
                        output_identity,
                    )
                    _publish_extracted_file(
                        temporary_paths[entry.stream_id],
                        target,
                    )
                    published.append(target)
            except BaseException as error:
                for target in published:
                    try:
                        target.unlink(missing_ok=True)
                    except BaseException as cleanup_error:
                        error.add_note(
                            f"failed to remove partially published file "
                            f"{target}: {cleanup_error}"
                        )
                raise
        except BaseException as error:
            primary_error = error
            raise
        finally:
            try:
                shutil.rmtree(temporary_root)
            except BaseException as cleanup_error:
                if primary_error is None:
                    cleanup_issues = (
                        FileExtractionCleanupIssue(
                            str(temporary_root),
                            str(cleanup_error),
                        ),
                    )
                else:
                    primary_error.add_note(
                        f"failed to remove temporary extraction directory "
                        f"{temporary_root}: {cleanup_error}"
                    )
        return FileExtractionResult(output_directory, targets, cleanup_issues)

    def _entries(self, manifest: Manifest) -> tuple[_FileEntry, ...]:
        entries: list[_FileEntry] = []
        names: set[str] = set()
        for stream in manifest.streams:
            try:
                name = self.plan_file(stream.stream_type, stream.metadata).name
            except FileArchiveError as exc:
                raise FileArchiveError(f"stream {stream.stream_id}: {exc}") from exc
            comparison_name = name.casefold()
            if comparison_name in names:
                raise FileArchiveError(
                    f"duplicate portable filename in archive: {name}"
                )
            names.add(comparison_name)
            entries.append(_FileEntry(stream.stream_id, name))
        return tuple(entries)


def _compose_file_capabilities(
    contributions: tuple[ExtensionContribution, ...],
) -> _FileCapabilities:
    source_profiles: dict[str, FileSourceProfile] = {}
    materializers: dict[str, FileMaterializer] = {}
    for contribution in contributions:
        extension_id = contribution.extension_id
        source_profile = cast(
            FileSourceProfile | None,
            contribution.get_optional_callable_provider(
                "encode_file_name",
                capability="file source",
            ),
        )
        materializer = cast(
            FileMaterializer | None,
            contribution.get_optional_callable_provider(
                "plan_file",
                capability="file materializer",
            ),
        )
        if source_profile is None and materializer is None:
            continue
        if contribution.kind is not ExtensionKind.STREAM_PROFILE:
            capability = (
                "file source" if source_profile is not None else "file materializer"
            )
            raise ExtensionContractError(
                extension_id,
                capability,
                "file capabilities require kind 'stream_profile'",
            )
        _register_file_capability(
            source_profiles,
            extension_id,
            source_profile,
            capability="file source",
        )
        _register_file_capability(
            materializers,
            extension_id,
            materializer,
            capability="file materializer",
        )
    return _FileCapabilities(
        MappingProxyType(source_profiles),
        MappingProxyType(materializers),
    )


def _register_file_capability[T](
    providers: dict[str, T],
    extension_id: str,
    provider: T | None,
    *,
    capability: str,
) -> None:
    if provider is None:
        return
    if extension_id in providers:
        raise ExtensionRegistrationError(extension_id, f"duplicate {capability}")
    providers[extension_id] = provider


def _encode_file_name(
    profile_id: str,
    provider: FileSourceProfile,
    name: str,
) -> bytes:
    try:
        metadata = provider.encode_file_name(name)
    except FileProfileError as exc:
        if exc.profile_id != profile_id:
            raise ExtensionContractError(
                profile_id,
                "file source",
                f"encode_file_name raised FileProfileError for {exc.profile_id}",
            ) from exc
        raise
    except Exception as exc:
        raise ExtensionContractError(
            profile_id,
            "file source",
            f"encode_file_name raised {type(exc).__name__}: {exc}",
        ) from exc
    if type(metadata) is not bytes:
        raise ExtensionContractError(
            profile_id,
            "file source",
            "encode_file_name must return exact bytes",
        )
    return metadata


def _plan_file(
    profile_id: str,
    materializer: FileMaterializer,
    metadata: bytes,
) -> FileMaterialization:
    try:
        plan = materializer.plan_file(metadata)
    except FileProfileError as exc:
        if exc.profile_id != profile_id:
            raise ExtensionContractError(
                profile_id,
                "file materializer",
                f"plan_file raised FileProfileError for {exc.profile_id}",
            ) from exc
        raise
    except Exception as exc:
        raise ExtensionContractError(
            profile_id,
            "file materializer",
            f"plan_file raised {type(exc).__name__}: {exc}",
        ) from exc
    if type(plan) is not FileMaterialization:
        raise ExtensionContractError(
            profile_id,
            "file materializer",
            "plan_file must return an exact FileMaterialization",
        )
    return plan


def _file_chunks(input_file: BinaryIO, chunk_size: int) -> Iterator[bytes]:
    while chunk := input_file.read(chunk_size):
        yield chunk


def _open_regular_file(profile_id: str, path: Path) -> BinaryIO:
    try:
        path_status = os.lstat(path)
    except OSError as exc:
        raise profile_error(
            profile_id,
            f"input is not a regular file: {path}",
        ) from exc
    if _is_redirected_path(path_status):
        raise profile_error(
            profile_id,
            f"symbolic links and reparse points are not supported: {path}",
        )

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(path, flags)
    except OSError as exc:
        raise profile_error(
            profile_id,
            f"input is not a regular file: {path}",
        ) from exc
    try:
        opened_status = os.fstat(file_descriptor)
        if not stat.S_ISREG(opened_status.st_mode):
            raise profile_error(
                profile_id,
                f"input is not a regular file: {path}",
            )
        if _file_identity(path_status) != _file_identity(opened_status):
            raise profile_error(profile_id, f"input changed while opening: {path}")
        return os.fdopen(file_descriptor, "rb")
    except BaseException:
        os.close(file_descriptor)
        raise


def _prepare_extraction_directory(output_directory: Path) -> tuple[int, int]:
    if not _path_entry_exists(output_directory):
        try:
            output_directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            pass
    status = _plain_directory_status(output_directory)
    return _file_identity(status)


def _require_directory_identity(
    output_directory: Path,
    expected_identity: tuple[int, int],
) -> None:
    status = _plain_directory_status(output_directory)
    if _file_identity(status) != expected_identity:
        raise FileArchiveError(
            f"extraction target changed during operation: {output_directory}",
        )


def _plain_directory_status(output_directory: Path) -> os.stat_result:
    try:
        status = os.lstat(output_directory)
    except OSError as exc:
        raise FileArchiveError(
            f"extraction target is not a directory: {output_directory}",
        ) from exc
    if _is_redirected_path(status):
        raise FileArchiveError(
            "symbolic-link and reparse-point extraction targets are not supported: "
            f"{output_directory}",
        )
    if not stat.S_ISDIR(status.st_mode):
        raise FileArchiveError(
            f"extraction target is not a directory: {output_directory}",
        )
    return status


def _path_entry_exists(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


def _is_redirected_path(status: os.stat_result) -> bool:
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(status, "st_file_attributes", 0)
    return stat.S_ISLNK(status.st_mode) or bool(file_attributes & reparse_attribute)


def _file_identity(status: os.stat_result) -> tuple[int, int]:
    return status.st_dev, status.st_ino


def _publish_extracted_file(
    source: Path,
    target: Path,
) -> None:
    try:
        os.link(source, target)
    except FileExistsError as exc:
        raise FileArchiveError(
            f"refusing to overwrite existing file: {target}"
        ) from exc


def _require_positive_int(name: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


__all__ = ["DEFAULT_FILE_CHUNK_SIZE", "FileArchiver"]

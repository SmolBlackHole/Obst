# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Shipped crash-conscious filesystem publication adapter."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Buffer
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from obst.core.extensions import (
    BoundCarrierPublisher,
    BoundCarrierReader,
    ExtensionDescriptor,
    ExtensionKind,
)
from obst.core.io import BinaryReader, BinaryWriter

from obst_defaults.carriers import (
    CarrierError,
    CarrierLifecycleState,
    CarrierStateError,
    PublicationCleanupIssue,
    PublicationReceipt,
    require_carrier_state,
)
from obst_defaults.carriers.failures import raise_carrier_failure


@dataclass(frozen=True, slots=True)
class FilesystemReadRequest:
    """Select one filesystem path containing OBST container bytes."""

    path: Path

    def __post_init__(self) -> None:
        if not isinstance(cast(object, self.path), Path):
            raise TypeError("filesystem read path must be a Path")


@dataclass(frozen=True, slots=True)
class FilesystemPublishRequest:
    """Select one filesystem publication target and overwrite policy."""

    path: Path
    overwrite: bool = False

    def __post_init__(self) -> None:
        if not isinstance(cast(object, self.path), Path):
            raise TypeError("filesystem publication path must be a Path")
        if type(self.overwrite) is not bool:
            raise TypeError("filesystem overwrite policy must be a boolean")


class FilesystemCarrierExtension:
    """Provide filesystem reading and transactional publication."""

    extension_id = "obst.filesystem@1"
    kind = ExtensionKind.CARRIER
    descriptor = ExtensionDescriptor(
        display_name="Filesystem",
        summary="Read or transactionally publish an OBST stream through a path.",
        specification_url=(
            "https://github.com/SmolBlackHole/Obst/blob/main/"
            "plugins/defaults/docs/carriers/filesystem.md"
        ),
    )

    def bind_reader(self, request: FilesystemReadRequest, /) -> BoundCarrierReader:
        if type(request) is not FilesystemReadRequest:
            raise CarrierError("filesystem reader requires FilesystemReadRequest")
        return FilesystemReaderSession(request)

    def bind_publisher(
        self,
        request: FilesystemPublishRequest,
        /,
    ) -> BoundCarrierPublisher[PublicationReceipt[Path]]:
        if type(request) is not FilesystemPublishRequest:
            raise CarrierError("filesystem publisher requires FilesystemPublishRequest")
        return FilesystemPublisherSession(request)


class FilesystemReaderSession:
    """Read one filesystem path through a single bound handle."""

    def __init__(self, request: FilesystemReadRequest) -> None:
        self.request = request
        self._state = CarrierLifecycleState.NEW
        self._file: _BinaryFile | None = None

    def open(self) -> BinaryReader:
        require_carrier_state(self._state, CarrierLifecycleState.NEW, operation="open")
        try:
            source = cast(_BinaryFile, self.request.path.open("rb"))
        except OSError as exc:
            self._state = CarrierLifecycleState.ABORTED
            raise CarrierError(
                f"cannot open input carrier {self.request.path}: {exc}"
            ) from exc
        self._file = source
        self._state = CarrierLifecycleState.OPEN
        return source

    def close(self) -> None:
        if self._state in {
            CarrierLifecycleState.ABORTED,
            CarrierLifecycleState.CLOSED,
        }:
            return
        if self._state is CarrierLifecycleState.NEW:
            self._state = CarrierLifecycleState.CLOSED
            return
        require_carrier_state(
            self._state,
            CarrierLifecycleState.OPEN,
            operation="close",
        )
        assert self._file is not None
        try:
            self._file.close()
        except OSError as exc:
            self._state = CarrierLifecycleState.CLEANUP_REQUIRED
            raise CarrierError(
                f"cannot close input carrier {self.request.path}: {exc}"
            ) from exc
        self._file = None
        self._state = CarrierLifecycleState.CLOSED


class FilesystemPublisherSession:
    """Publish a complete container through a temporary sibling file."""

    def __init__(self, request: FilesystemPublishRequest) -> None:
        self.request = request
        self.target = request.path
        self.overwrite = request.overwrite
        self._state = CarrierLifecycleState.NEW
        self._temporary_path: Path | None = None
        self._file: _SyncFile | None = None

    def open(self) -> BinaryWriter:
        require_carrier_state(self._state, CarrierLifecycleState.NEW, operation="open")
        try:
            if not self.target.parent.is_dir():
                raise CarrierError(
                    f"output directory does not exist: {self.target.parent}"
                )
            if self.target.exists() and not self.overwrite:
                raise CarrierError(f"output already exists: {self.target}")
            temporary = tempfile.NamedTemporaryFile(
                mode="w+b",
                dir=self.target.parent,
                prefix=f".{self.target.name}.",
                suffix=".tmp",
                delete=False,
            )
            output_file = cast(_SyncFile, temporary)
            self._temporary_path = Path(temporary.name)
            self._file = output_file
        except BaseException as error:
            cleanup_errors = self._discard_unpublished()
            raise_carrier_failure(
                "open",
                "output carrier",
                error,
                cleanup_errors,
            )
        self._state = CarrierLifecycleState.OPEN
        return output_file

    def commit(self) -> PublicationReceipt[Path]:
        require_carrier_state(
            self._state,
            CarrierLifecycleState.OPEN,
            operation="commit",
        )
        assert self._file is not None
        assert self._temporary_path is not None
        try:
            self._file.flush()
            os.fsync(self._file.fileno())
            self._file.close()
            self._file = None
        except BaseException as error:
            cleanup_errors = self._discard_unpublished()
            raise_carrier_failure(
                "commit",
                "output carrier",
                error,
                cleanup_errors,
            )
        try:
            source_consumed = _publish_file(
                self._temporary_path,
                self.target,
                overwrite=self.overwrite,
            )
        except BaseException as error:
            cleanup_errors = self._discard_unpublished()
            raise_carrier_failure(
                "commit",
                "output carrier",
                error,
                cleanup_errors,
            )
        if source_consumed:
            self._temporary_path = None
        self._state = CarrierLifecycleState.COMMITTED
        cleanup_issues: tuple[PublicationCleanupIssue, ...] = ()
        try:
            self._cleanup_temporary()
        except OSError as exc:
            assert self._temporary_path is not None
            cleanup_issues = (
                PublicationCleanupIssue(str(self._temporary_path), str(exc)),
            )
        return PublicationReceipt(self.target, cleanup_issues)

    def abort(self) -> None:
        if self._state in {
            CarrierLifecycleState.NEW,
            CarrierLifecycleState.ABORTED,
        }:
            self._state = CarrierLifecycleState.ABORTED
            return
        if self._state is CarrierLifecycleState.COMMITTED:
            raise CarrierStateError("abort", "committed")
        cleanup_errors = self._discard_unpublished()
        if cleanup_errors:
            primary, *secondary = cleanup_errors
            raise_carrier_failure(
                "abort",
                "output carrier",
                primary,
                secondary,
            )

    def _discard_unpublished(self) -> list[BaseException]:
        errors: list[BaseException] = []
        if self._file is not None:
            try:
                self._file.close()
            except BaseException as error:
                errors.append(error)
            else:
                self._file = None
        try:
            self._cleanup_temporary()
        except BaseException as error:
            errors.append(error)
        self._state = (
            CarrierLifecycleState.ABORTED
            if self._file is None and self._temporary_path is None
            else CarrierLifecycleState.CLEANUP_REQUIRED
        )
        return errors

    def _cleanup_temporary(self) -> None:
        if self._temporary_path is not None:
            self._temporary_path.unlink(missing_ok=True)
            self._temporary_path = None


class _SyncFile(Protocol):
    def write(self, data: Buffer, /) -> int: ...

    def flush(self) -> None: ...

    def fileno(self) -> int: ...

    def close(self) -> None: ...


class _BinaryFile(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...

    def close(self) -> None: ...


def _publish_file(source: Path, target: Path, *, overwrite: bool) -> bool:
    if overwrite:
        os.replace(source, target)
        return True
    try:
        os.link(source, target)
    except FileExistsError as exc:
        raise CarrierError(f"refusing to overwrite existing file: {target}") from exc
    return False

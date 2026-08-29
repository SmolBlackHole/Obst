# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Shipped in-memory publication adapter."""

from dataclasses import dataclass
from io import BytesIO

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
    PublicationReceipt,
    require_carrier_state,
)
from obst_defaults.carriers.failures import raise_carrier_failure


@dataclass(frozen=True, slots=True)
class MemoryReadRequest:
    """Provide one immutable byte string containing an OBST container."""

    data: bytes

    def __post_init__(self) -> None:
        if type(self.data) is not bytes:
            raise TypeError("memory carrier data must be exact bytes")


@dataclass(frozen=True, slots=True)
class MemoryPublishRequest:
    """Request one transactionally materialized in-memory byte string."""


class MemoryCarrierExtension:
    """Provide in-memory reading and transactional publication."""

    extension_id = "obst.memory@1"
    kind = ExtensionKind.CARRIER
    descriptor = ExtensionDescriptor(
        display_name="Memory",
        summary="Read or publish a complete OBST stream in memory.",
        specification_url=(
            "https://github.com/SmolBlackHole/Obst/blob/main/"
            "plugins/defaults/docs/carriers/memory.md"
        ),
    )

    def bind_reader(self, request: MemoryReadRequest, /) -> BoundCarrierReader:
        if type(request) is not MemoryReadRequest:
            raise CarrierError("memory reader requires MemoryReadRequest")
        return MemoryReaderSession(request)

    def bind_publisher(
        self,
        request: MemoryPublishRequest,
        /,
    ) -> BoundCarrierPublisher[PublicationReceipt[bytes]]:
        if type(request) is not MemoryPublishRequest:
            raise CarrierError("memory publisher requires MemoryPublishRequest")
        return MemoryPublisherSession(request)


class MemoryReaderSession:
    """Read one immutable in-memory container exactly once."""

    def __init__(self, request: MemoryReadRequest) -> None:
        self.request = request
        self._state = CarrierLifecycleState.NEW
        self._buffer: BytesIO | None = None

    def open(self) -> BinaryReader:
        require_carrier_state(self._state, CarrierLifecycleState.NEW, operation="open")
        try:
            buffer = BytesIO(self.request.data)
        except BaseException:
            self._state = CarrierLifecycleState.ABORTED
            raise
        self._buffer = buffer
        self._state = CarrierLifecycleState.OPEN
        return buffer

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
        assert self._buffer is not None
        self._buffer.close()
        self._buffer = None
        self._state = CarrierLifecycleState.CLOSED


class MemoryPublisherSession:
    """Publish a complete container as an immutable byte string."""

    def __init__(self, request: MemoryPublishRequest) -> None:
        self.request = request
        self._state = CarrierLifecycleState.NEW
        self._buffer: BytesIO | None = None

    def open(self) -> BinaryWriter:
        require_carrier_state(self._state, CarrierLifecycleState.NEW, operation="open")
        try:
            self._buffer = BytesIO()
        except BaseException:
            self._state = CarrierLifecycleState.ABORTED
            raise
        self._state = CarrierLifecycleState.OPEN
        return self._buffer

    def commit(self) -> PublicationReceipt[bytes]:
        require_carrier_state(
            self._state,
            CarrierLifecycleState.OPEN,
            operation="commit",
        )
        assert self._buffer is not None
        try:
            data = self._buffer.getvalue()
            self._buffer.close()
        except BaseException as error:
            cleanup_errors = self._discard_unpublished()
            raise_carrier_failure(
                "commit",
                "memory carrier",
                error,
                cleanup_errors,
            )
        self._buffer = None
        self._state = CarrierLifecycleState.COMMITTED
        return PublicationReceipt(data, ())

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
                "memory carrier",
                primary,
                secondary,
            )

    def _discard_unpublished(self) -> list[BaseException]:
        errors: list[BaseException] = []
        if self._buffer is not None:
            try:
                self._buffer.close()
            except BaseException as error:
                errors.append(error)
            else:
                self._buffer = None
        self._state = (
            CarrierLifecycleState.ABORTED
            if self._buffer is None
            else CarrierLifecycleState.CLEANUP_REQUIRED
        )
        return errors

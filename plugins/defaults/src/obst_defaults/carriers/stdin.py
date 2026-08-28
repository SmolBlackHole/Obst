"""Shipped host-owned standard-input carrier adapter."""

from __future__ import annotations

from dataclasses import dataclass

from obst.core.extensions import BoundCarrierReader, ExtensionDescriptor, ExtensionKind
from obst.core.io import BinaryReader

from obst_defaults.carriers import (
    CarrierError,
    CarrierLifecycleState,
    require_carrier_state,
)


@dataclass(frozen=True, slots=True)
class StdinReadRequest:
    """Bind one host-owned standard-input byte stream."""

    source: BinaryReader


class StdinCarrierExtension:
    """Provide non-owning reads from host-selected standard input."""

    extension_id = "obst.stdin@1"
    kind = ExtensionKind.CARRIER
    descriptor = ExtensionDescriptor(
        display_name="Standard input",
        summary="Read an OBST stream from a host-owned standard-input endpoint.",
        specification_url=(
            "https://github.com/SmolBlackHole/Obst/blob/main/"
            "plugins/defaults/docs/carriers/standard-input.md"
        ),
    )

    def bind_reader(self, request: StdinReadRequest, /) -> BoundCarrierReader:
        if type(request) is not StdinReadRequest:
            raise CarrierError("stdin reader requires StdinReadRequest")
        return StdinReaderSession(request)


class StdinReaderSession:
    """Expose standard input without closing its host-owned reader."""

    def __init__(self, request: StdinReadRequest) -> None:
        self.request = request
        self._state = CarrierLifecycleState.NEW

    def open(self) -> BinaryReader:
        require_carrier_state(self._state, CarrierLifecycleState.NEW, operation="open")
        self._state = CarrierLifecycleState.OPEN
        return self.request.source

    def close(self) -> None:
        if self._state is CarrierLifecycleState.CLOSED:
            return
        if self._state is CarrierLifecycleState.NEW:
            self._state = CarrierLifecycleState.CLOSED
            return
        require_carrier_state(
            self._state,
            CarrierLifecycleState.OPEN,
            operation="close",
        )
        self._state = CarrierLifecycleState.CLOSED

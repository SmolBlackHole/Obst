"""Shipped modulo-256 delta transform for opaque byte streams."""

from __future__ import annotations

from obst.core.extensions import (
    ExtensionDescriptor,
    ExtensionKind,
    require_no_parameters,
    require_stage_output_size,
)


class Delta8Extension:
    """Encode each byte as its modulo-256 difference from the previous byte."""

    extension_id = "obst.delta8@1"
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor(
        display_name="Delta8",
        summary="Modulo-256 delta transform over individual bytes.",
        specification_url=(
            "https://github.com/SmolBlackHole/Obst/blob/main/"
            "docs/contracts/stages/delta8.md"
        ),
    )

    def bind_encoder(self, parameters: bytes, /) -> Delta8Extension:
        require_no_parameters(self.extension_id, parameters)
        return self

    def bind_decoder(self, parameters: bytes, /) -> Delta8Extension:
        require_no_parameters(self.extension_id, parameters)
        return self

    def encode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        require_stage_output_size(
            self.extension_id,
            len(data),
            max_output_size=max_output_size,
            operation="encode",
        )
        output = bytearray(len(data))
        previous = 0
        for index, value in enumerate(data):
            output[index] = (value - previous) & 0xFF
            previous = value
        return bytes(output)

    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        require_stage_output_size(
            self.extension_id,
            len(data),
            max_output_size=max_output_size,
            operation="decode",
        )
        output = bytearray(len(data))
        previous = 0
        for index, delta in enumerate(data):
            value = (previous + delta) & 0xFF
            output[index] = value
            previous = value
        return bytes(output)

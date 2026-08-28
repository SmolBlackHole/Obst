"""Shipped identity extension for untransformed payloads."""

from obst.core.extensions import (
    ExtensionDescriptor,
    ExtensionKind,
    require_no_parameters,
    require_stage_output_size,
)


class RawExtension:
    """First-party provider for the ``obst.raw@1`` extension contract."""

    extension_id = "obst.raw@1"
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor(
        display_name="RAW",
        summary="Identity stage for untransformed bytes.",
        specification_url=(
            "https://github.com/SmolBlackHole/Obst/blob/main/"
            "plugins/defaults/docs/contracts/stages/raw.md"
        ),
    )

    def bind_encoder(self, parameters: bytes, /) -> RawExtension:
        require_no_parameters(self.extension_id, parameters)
        return self

    def bind_decoder(self, parameters: bytes, /) -> RawExtension:
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
        return data

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
        return data

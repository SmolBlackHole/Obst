# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Minimal neutral Extensions used by the ``obst`` runtime tests."""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from obst.core import (
    ExtensionDescriptor,
    InspectionField,
    InspectionInterpretation,
    ProviderRejectedError,
    extend_stage_output,
    require_no_parameters,
    require_stage_output_size,
)
from obst.core.extensions import ExtensionKind


class IdentityExtension:
    """Test-only identity Stage with no plugin-owned semantics."""

    extension_id = "org.example/test-identity@1"
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor(
        display_name="Test identity",
        summary="Return every input byte unchanged.",
        specification_url="https://example.org/obst/identity-v1",
    )

    def bind_encoder(self, parameters: bytes, /) -> IdentityExtension:
        require_no_parameters(self.extension_id, parameters)
        return self

    def bind_decoder(self, parameters: bytes, /) -> IdentityExtension:
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


class DeltaExtension:
    """Test-only reversible byte transform."""

    extension_id = "org.example/delta@1"
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor(
        display_name="Test delta",
        summary="Reversibly difference adjacent bytes for runtime tests.",
        specification_url="https://example.org/obst/delta-v1",
    )

    def bind_encoder(self, parameters: bytes, /) -> DeltaExtension:
        require_no_parameters(self.extension_id, parameters)
        return self

    def bind_decoder(self, parameters: bytes, /) -> DeltaExtension:
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


@dataclass(frozen=True, slots=True)
class CompressionParameters:
    """Typed local parameters for the test compression Stage."""

    level: int

    def __post_init__(self) -> None:
        if type(self.level) is not int:
            raise TypeError("level must be an integer")
        if not 0 <= self.level <= 9:
            raise ValueError("level must be between 0 and 9")


class CompressionExtension:
    """Test-only compression Stage for exercising non-identity pipelines."""

    extension_id = "org.example/compression@1"
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor(
        display_name="Test compression",
        summary="Compress bytes for runtime tests.",
        specification_url="https://example.org/obst/compression-v1",
    )

    def encode_parameters(self, value: CompressionParameters, /) -> bytes:
        if type(value) is not CompressionParameters:
            raise TypeError("value must be exact CompressionParameters")
        return bytes((value.level,))

    def decode_parameters(self, parameters: bytes, /) -> CompressionParameters:
        if type(parameters) is not bytes:
            raise TypeError("parameters must be exact bytes")
        if len(parameters) != 1 or parameters[0] > 9:
            raise ProviderRejectedError("expected one compression-level byte (0..9)")
        return CompressionParameters(parameters[0])

    def interpret_parameters(
        self,
        parameters: bytes,
        /,
    ) -> InspectionInterpretation:
        try:
            value = self.decode_parameters(parameters)
        except ProviderRejectedError as exc:
            return InspectionInterpretation(error=str(exc))
        return InspectionInterpretation(
            fields=(InspectionField("compression_level", value.level),)
        )

    def bind_encoder(self, parameters: bytes, /) -> _CompressionEncoder:
        return _CompressionEncoder(self.decode_parameters(parameters).level)

    def bind_decoder(self, parameters: bytes, /) -> _CompressionDecoder:
        self.decode_parameters(parameters)
        return _CompressionDecoder()


@dataclass(frozen=True, slots=True)
class _CompressionEncoder:
    level: int

    def encode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        output = zlib.compress(data, self.level)
        require_stage_output_size(
            CompressionExtension.extension_id,
            len(output),
            max_output_size=max_output_size,
            operation="encode",
        )
        return output


class _CompressionDecoder:
    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        decoder = zlib.decompressobj()
        output = bytearray()
        try:
            extend_stage_output(
                output,
                decoder.decompress(data),
                stage_id=CompressionExtension.extension_id,
                max_output_size=max_output_size,
                operation="decode",
            )
            extend_stage_output(
                output,
                decoder.flush(),
                stage_id=CompressionExtension.extension_id,
                max_output_size=max_output_size,
                operation="decode",
            )
        except zlib.error as exc:
            raise ProviderRejectedError("invalid compressed payload") from exc
        if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ProviderRejectedError("invalid compressed framing")
        return bytes(output)

"""Shipped zlib-wrapped DEFLATE extensions."""

from __future__ import annotations

import zlib as stdlib_zlib
from dataclasses import dataclass

from obst.core.errors import ProviderRejectedError
from obst.core.extensions import (
    ExtensionDescriptor,
    ExtensionKind,
    InspectionField,
    InspectionInterpretation,
    extend_stage_output,
    require_stage_output_size,
)

_MIN_COMPRESSION_LEVEL = 0
_MAX_COMPRESSION_LEVEL = 9
_MIN_DICTIONARY_SIZE = 1
_MAX_DICTIONARY_SIZE = 32 * 1024
_INPUT_BLOCK_SIZE = 64 * 1024
_FDICT_FLAG = 0x20


def _validate_compression_level(compression_level: int) -> None:
    if type(compression_level) is not int:
        raise TypeError("compression_level must be an integer")
    if not _MIN_COMPRESSION_LEVEL <= compression_level <= _MAX_COMPRESSION_LEVEL:
        raise ValueError("compression_level must be between 0 and 9")


@dataclass(frozen=True, slots=True)
class ZlibParameters:
    """Typed local parameters for ``obst.zlib@1``."""

    compression_level: int

    def __post_init__(self) -> None:
        _validate_compression_level(self.compression_level)


@dataclass(frozen=True, slots=True)
class ZlibDictionaryParameters:
    """Typed local parameters for ``obst.zlib@2``."""

    compression_level: int
    dictionary: bytes

    def __post_init__(self) -> None:
        _validate_compression_level(self.compression_level)
        if type(self.dictionary) is not bytes:
            raise TypeError("dictionary must be bytes")
        if not _MIN_DICTIONARY_SIZE <= len(self.dictionary) <= _MAX_DICTIONARY_SIZE:
            raise ValueError("dictionary must contain between 1 and 32768 bytes")


def _decode_compression_level(parameters: bytes, /, *, stage_id: str) -> int:
    if (
        len(parameters) != 1
        or not _MIN_COMPRESSION_LEVEL <= parameters[0] <= _MAX_COMPRESSION_LEVEL
    ):
        raise ProviderRejectedError(
            f"{stage_id} requires one compression-level byte (0..9)"
        )
    return parameters[0]


class ZlibExtension:
    """Bind ``obst.zlib@1`` parameters to reusable executors."""

    extension_id = "obst.zlib@1"
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor(
        display_name="zlib",
        summary="zlib-wrapped DEFLATE with a declared compression level.",
        specification_url=(
            "https://github.com/SmolBlackHole/Obst/blob/main/"
            "docs/contracts/stages/zlib.md"
        ),
    )

    def encode_parameters(self, value: ZlibParameters, /) -> bytes:
        """Encode one valid ``obst.zlib@1`` parameter block."""
        if type(value) is not ZlibParameters:
            raise TypeError("value must be exact ZlibParameters")
        return bytes((value.compression_level,))

    def decode_parameters(self, parameters: bytes, /) -> ZlibParameters:
        """Decode one valid ``obst.zlib@1`` parameter block."""
        if type(parameters) is not bytes:
            raise TypeError("parameters must be exact bytes")
        return ZlibParameters(
            _decode_compression_level(parameters, stage_id=self.extension_id)
        )

    def bind_encoder(self, parameters: bytes, /) -> _BoundZlibEncoder:
        value = self.decode_parameters(parameters)
        return _BoundZlibEncoder(
            level=value.compression_level,
            dictionary=None,
            stage_id=self.extension_id,
        )

    def bind_decoder(self, parameters: bytes, /) -> _BoundZlibDecoder:
        self.decode_parameters(parameters)
        return _BoundZlibDecoder(
            dictionary=None,
            stage_id=self.extension_id,
            requires_dictionary=False,
        )

    def interpret_parameters(
        self,
        parameters: bytes,
        /,
    ) -> InspectionInterpretation:
        try:
            value = self.decode_parameters(parameters)
        except ProviderRejectedError:
            return InspectionInterpretation(
                error="expected one compression-level byte in the range 0..9"
            )
        return InspectionInterpretation(
            fields=(InspectionField("compression_level", value.compression_level),)
        )


class ZlibDictionaryExtension:
    """Bind ``obst.zlib@2`` parameters to reusable executors."""

    extension_id = "obst.zlib@2"
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor(
        display_name="zlib with preset dictionary",
        summary="zlib-wrapped DEFLATE with a self-described preset dictionary.",
        specification_url=(
            "https://github.com/SmolBlackHole/Obst/blob/main/"
            "docs/contracts/stages/zlib-dictionary.md"
        ),
    )

    def encode_parameters(
        self,
        value: ZlibDictionaryParameters,
        /,
    ) -> bytes:
        """Encode one valid ``obst.zlib@2`` parameter block."""
        if type(value) is not ZlibDictionaryParameters:
            raise TypeError("value must be exact ZlibDictionaryParameters")
        return bytes((value.compression_level,)) + value.dictionary

    def decode_parameters(
        self,
        parameters: bytes,
        /,
    ) -> ZlibDictionaryParameters:
        """Decode one valid ``obst.zlib@2`` parameter block."""
        if type(parameters) is not bytes:
            raise TypeError("parameters must be exact bytes")
        if not 1 + _MIN_DICTIONARY_SIZE <= len(parameters) <= 1 + _MAX_DICTIONARY_SIZE:
            raise ProviderRejectedError(
                f"{self.extension_id} requires a compression-level byte (0..9) "
                "followed by 1..32768 dictionary bytes"
            )
        return ZlibDictionaryParameters(
            _decode_compression_level(parameters[:1], stage_id=self.extension_id),
            parameters[1:],
        )

    def bind_encoder(self, parameters: bytes, /) -> _BoundZlibEncoder:
        value = self.decode_parameters(parameters)
        return _BoundZlibEncoder(
            level=value.compression_level,
            dictionary=value.dictionary,
            stage_id=self.extension_id,
        )

    def bind_decoder(self, parameters: bytes, /) -> _BoundZlibDecoder:
        value = self.decode_parameters(parameters)
        return _BoundZlibDecoder(
            dictionary=value.dictionary,
            stage_id=self.extension_id,
            requires_dictionary=True,
        )

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
            fields=(
                InspectionField("compression_level", value.compression_level),
                InspectionField("dictionary_size", len(value.dictionary)),
                InspectionField(
                    "dictionary_adler32",
                    f"{stdlib_zlib.adler32(value.dictionary) & 0xFFFFFFFF:08x}",
                ),
            )
        )


@dataclass(frozen=True, slots=True)
class _BoundZlibEncoder:
    level: int
    dictionary: bytes | None
    stage_id: str

    def encode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        encoder = (
            stdlib_zlib.compressobj(self.level)
            if self.dictionary is None
            else stdlib_zlib.compressobj(self.level, zdict=self.dictionary)
        )
        output = bytearray()
        for offset in range(0, len(data), _INPUT_BLOCK_SIZE):
            extend_stage_output(
                output,
                encoder.compress(data[offset : offset + _INPUT_BLOCK_SIZE]),
                stage_id=self.stage_id,
                max_output_size=max_output_size,
                operation="encode",
            )
        extend_stage_output(
            output,
            encoder.flush(),
            stage_id=self.stage_id,
            max_output_size=max_output_size,
            operation="encode",
        )
        return bytes(output)


@dataclass(frozen=True, slots=True)
class _BoundZlibDecoder:
    dictionary: bytes | None
    stage_id: str
    requires_dictionary: bool

    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        if self.requires_dictionary:
            assert self.dictionary is not None
            self._validate_dictionary_header(data)
        elif self._uses_preset_dictionary(data):
            raise ProviderRejectedError(f"{self.stage_id} forbids preset dictionaries")
        decoder = (
            stdlib_zlib.decompressobj()
            if self.dictionary is None
            else stdlib_zlib.decompressobj(zdict=self.dictionary)
        )
        try:
            if max_output_size is None:
                output = decoder.decompress(data)
                output += decoder.flush()
            else:
                output = decoder.decompress(data, max_output_size + 1)
                if len(output) > max_output_size or decoder.unconsumed_tail:
                    require_stage_output_size(
                        self.stage_id,
                        max(len(output), max_output_size + 1),
                        max_output_size=max_output_size,
                        operation="decode",
                    )
                remaining = max_output_size - len(output)
                output += decoder.flush(remaining + 1)
        except stdlib_zlib.error as exc:
            raise ProviderRejectedError(f"invalid zlib payload: {exc}") from exc
        if max_output_size is not None and len(output) > max_output_size:
            require_stage_output_size(
                self.stage_id,
                len(output),
                max_output_size=max_output_size,
                operation="decode",
            )
        if not decoder.eof or decoder.unused_data:
            raise ProviderRejectedError("zlib payload has invalid framing")
        return output

    @staticmethod
    def _has_valid_zlib_header(data: bytes) -> bool:
        if len(data) < 2:
            return False
        compression_method = data[0] & 0x0F
        window_size = data[0] >> 4
        return (
            compression_method == 8
            and window_size <= 7
            and (data[0] << 8 | data[1]) % 31 == 0
        )

    @classmethod
    def _uses_preset_dictionary(cls, data: bytes) -> bool:
        return cls._has_valid_zlib_header(data) and data[1] & _FDICT_FLAG != 0

    def _validate_dictionary_header(self, data: bytes) -> None:
        assert self.dictionary is not None
        if not self._has_valid_zlib_header(data):
            raise ProviderRejectedError("invalid zlib payload: invalid header")
        if not self._uses_preset_dictionary(data):
            raise ProviderRejectedError(
                f"{self.stage_id} requires a preset-dictionary zlib stream"
            )
        if len(data) < 6:
            raise ProviderRejectedError(
                "invalid zlib payload: truncated dictionary identifier"
            )
        declared = int.from_bytes(data[2:6], "big")
        expected = stdlib_zlib.adler32(self.dictionary) & 0xFFFFFFFF
        if declared != expected:
            raise ProviderRejectedError(
                f"{self.stage_id} dictionary identifier does not match its parameters"
            )

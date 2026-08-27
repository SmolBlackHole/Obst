"""Adaptive zlib Stage extension implemented only through public OBST APIs."""

from __future__ import annotations

import zlib as stdlib_zlib
from dataclasses import dataclass

from obst.core import (
    ExtensionDescriptor,
    ExtensionKind,
    InspectionField,
    InspectionInterpretation,
    ProviderRejectedError,
    require_stage_output_size,
)

_ALLOWED_WIDTHS = (1, 2, 4, 8, 16)
_WIDTH_TO_MODE = {width: mode for mode, width in enumerate(_ALLOWED_WIDTHS)}
_MODE_TO_WIDTH = {mode: width for width, mode in _WIDTH_TO_MODE.items()}
_WIDTH_TO_MASK = {2: 0x01, 4: 0x02, 8: 0x04, 16: 0x08}
_KNOWN_WIDTH_MASK = sum(_WIDTH_TO_MASK.values())
_MAX_DICTIONARIES = 8
_MAX_DICTIONARY_SIZE = 32 * 1024
_PARAMETER_HEADER_SIZE = 3
_FDICT_FLAG = 0x20


@dataclass(frozen=True, slots=True)
class AdaptiveZlibParameters:
    """Typed local parameters for ``org.example/adaptive-zlib@1``."""

    compression_level: int = 6
    shuffle_widths: tuple[int, ...] = (1, 2, 4, 8)
    dictionaries: tuple[bytes, ...] = ()

    def __post_init__(self) -> None:
        if type(self.compression_level) is not int:
            raise TypeError("compression_level must be an integer")
        if not 0 <= self.compression_level <= 9:
            raise ValueError("compression_level must be between 0 and 9")
        if type(self.shuffle_widths) is not tuple:
            raise TypeError("shuffle_widths must be a tuple")
        if not self.shuffle_widths or self.shuffle_widths[0] != 1:
            raise ValueError("shuffle_widths must include raw width 1 first")
        if any(type(width) is not int for width in self.shuffle_widths):
            raise TypeError("shuffle_widths must contain only integers")
        if tuple(sorted(set(self.shuffle_widths))) != self.shuffle_widths:
            raise ValueError("shuffle_widths must be sorted and unique")
        if any(width not in _ALLOWED_WIDTHS for width in self.shuffle_widths):
            raise ValueError("shuffle_widths may contain only 1, 2, 4, 8 and 16")
        if type(self.dictionaries) is not tuple:
            raise TypeError("dictionaries must be a tuple")
        if len(self.dictionaries) > _MAX_DICTIONARIES:
            raise ValueError("dictionaries cannot contain more than 8 values")
        if any(type(dictionary) is not bytes for dictionary in self.dictionaries):
            raise TypeError("dictionaries must contain only exact bytes")
        if any(
            not 1 <= len(dictionary) <= _MAX_DICTIONARY_SIZE
            for dictionary in self.dictionaries
        ):
            raise ValueError("each dictionary must contain between 1 and 32768 bytes")
        if len(set(self.dictionaries)) != len(self.dictionaries):
            raise ValueError("dictionaries must be unique")


class AdaptiveZlibExtension:
    """Choose a reversible byte layout and zlib dictionary for each chunk."""

    extension_id = "org.example/adaptive-zlib@1"
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor(
        display_name="Adaptive zlib",
        summary=(
            "Chooses one byte-lane layout and optional preset dictionary "
            "for each chunk before zlib compression."
        ),
        specification_url=(
            "https://github.com/SmolBlackHole/Obst/blob/main/"
            "examples/plugin_adaptive_zlib/README.md#stage-contract"
        ),
    )

    def encode_parameters(self, value: AdaptiveZlibParameters, /) -> bytes:
        """Encode one canonical adaptive-zlib parameter block."""
        if type(value) is not AdaptiveZlibParameters:
            raise TypeError("value must be exact AdaptiveZlibParameters")
        width_mask = 0
        for width in value.shuffle_widths:
            width_mask |= _WIDTH_TO_MASK.get(width, 0)
        output = bytearray(
            (value.compression_level, width_mask, len(value.dictionaries))
        )
        for dictionary in value.dictionaries:
            output.extend(len(dictionary).to_bytes(2, "big"))
            output.extend(dictionary)
        return bytes(output)

    def decode_parameters(self, parameters: bytes, /) -> AdaptiveZlibParameters:
        """Validate and decode one exact adaptive-zlib parameter block."""
        if type(parameters) is not bytes:
            raise TypeError("parameters must be exact bytes")
        if len(parameters) < _PARAMETER_HEADER_SIZE:
            raise ProviderRejectedError(
                f"{self.extension_id} parameters require a 3-byte header"
            )
        compression_level, width_mask, dictionary_count = parameters[:3]
        if not 0 <= compression_level <= 9:
            raise ProviderRejectedError("compression level must be between 0 and 9")
        if width_mask & ~_KNOWN_WIDTH_MASK:
            raise ProviderRejectedError("shuffle mask contains unknown width bits")
        if dictionary_count > _MAX_DICTIONARIES:
            raise ProviderRejectedError("dictionary count cannot exceed 8")

        cursor = _PARAMETER_HEADER_SIZE
        dictionaries: list[bytes] = []
        for _ in range(dictionary_count):
            if len(parameters) - cursor < 2:
                raise ProviderRejectedError("truncated dictionary-size field")
            size = int.from_bytes(parameters[cursor : cursor + 2], "big")
            cursor += 2
            if not 1 <= size <= _MAX_DICTIONARY_SIZE:
                raise ProviderRejectedError(
                    "dictionary size must be between 1 and 32768 bytes"
                )
            end = cursor + size
            if end > len(parameters):
                raise ProviderRejectedError("truncated dictionary bytes")
            dictionaries.append(parameters[cursor:end])
            cursor = end
        if cursor != len(parameters):
            raise ProviderRejectedError("trailing adaptive-zlib parameter bytes")

        widths = (
            1,
            *tuple(
                width
                for width in _ALLOWED_WIDTHS[1:]
                if width_mask & _WIDTH_TO_MASK[width]
            ),
        )
        try:
            return AdaptiveZlibParameters(
                compression_level=compression_level,
                shuffle_widths=widths,
                dictionaries=tuple(dictionaries),
            )
        except (TypeError, ValueError) as exc:
            raise ProviderRejectedError(str(exc)) from exc

    def interpret_parameters(
        self,
        parameters: bytes,
        /,
    ) -> InspectionInterpretation:
        """Describe adaptive choices without changing their wire bytes."""
        try:
            value = self.decode_parameters(parameters)
        except ProviderRejectedError as exc:
            return InspectionInterpretation(error=str(exc))
        checksums = ", ".join(
            f"{stdlib_zlib.adler32(dictionary) & 0xFFFFFFFF:08x}"
            for dictionary in value.dictionaries
        )
        return InspectionInterpretation(
            label=(
                f"level {value.compression_level}; "
                f"{len(value.shuffle_widths)} layouts; "
                f"{len(value.dictionaries)} dictionaries"
            ),
            fields=(
                InspectionField("compression_level", value.compression_level),
                InspectionField(
                    "shuffle_widths",
                    ",".join(str(width) for width in value.shuffle_widths),
                ),
                InspectionField("dictionary_count", len(value.dictionaries)),
                InspectionField(
                    "dictionary_bytes",
                    sum(len(dictionary) for dictionary in value.dictionaries),
                ),
                InspectionField("dictionary_adler32", checksums or None),
            ),
        )

    def bind_encoder(
        self,
        parameters: bytes,
        /,
    ) -> _BoundAdaptiveZlibEncoder:
        """Bind adaptive candidates once for repeated chunk encoding."""
        return _BoundAdaptiveZlibEncoder(
            self.extension_id,
            self.decode_parameters(parameters),
        )

    def bind_decoder(
        self,
        parameters: bytes,
        /,
    ) -> _BoundAdaptiveZlibDecoder:
        """Bind declared layouts and dictionaries for deterministic decoding."""
        return _BoundAdaptiveZlibDecoder(
            self.extension_id,
            self.decode_parameters(parameters),
        )


@dataclass(frozen=True, slots=True)
class _BoundAdaptiveZlibEncoder:
    stage_id: str
    parameters: AdaptiveZlibParameters

    def encode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        best: bytes | None = None
        dictionaries: tuple[bytes | None, ...] = (
            None,
            *self.parameters.dictionaries,
        )
        for width in self.parameters.shuffle_widths:
            transformed = self._shuffle(data, width)
            mode = _WIDTH_TO_MODE[width]
            for dictionary_index, dictionary in enumerate(dictionaries):
                payload = self._compress(transformed, dictionary)
                candidate = bytes((mode, dictionary_index)) + payload
                if best is None or self._rank(candidate) < self._rank(best):
                    best = candidate
        assert best is not None
        require_stage_output_size(
            self.stage_id,
            len(best),
            max_output_size=max_output_size,
            operation="encode",
        )
        return best

    def _compress(self, data: bytes, dictionary: bytes | None) -> bytes:
        encoder = (
            stdlib_zlib.compressobj(self.parameters.compression_level)
            if dictionary is None
            else stdlib_zlib.compressobj(
                self.parameters.compression_level,
                zdict=dictionary,
            )
        )
        return encoder.compress(data) + encoder.flush()

    @staticmethod
    def _rank(candidate: bytes) -> tuple[int, int, int]:
        return len(candidate), candidate[0], candidate[1]

    @staticmethod
    def _shuffle(data: bytes, width: int) -> bytes:
        if width == 1:
            return data
        element_count = len(data) // width
        full_size = element_count * width
        output = bytearray(full_size)
        output_index = 0
        for byte_index in range(width):
            for element_index in range(element_count):
                output[output_index] = data[element_index * width + byte_index]
                output_index += 1
        output.extend(data[full_size:])
        return bytes(output)


@dataclass(frozen=True, slots=True)
class _BoundAdaptiveZlibDecoder:
    stage_id: str
    parameters: AdaptiveZlibParameters

    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        if len(data) < 2:
            raise ProviderRejectedError("adaptive-zlib payload header is truncated")
        mode, dictionary_index = data[:2]
        width = _MODE_TO_WIDTH.get(mode)
        if width is None or width not in self.parameters.shuffle_widths:
            raise ProviderRejectedError("payload selects an undeclared shuffle mode")
        if dictionary_index > len(self.parameters.dictionaries):
            raise ProviderRejectedError("payload selects an undeclared dictionary")
        dictionary = (
            None
            if dictionary_index == 0
            else self.parameters.dictionaries[dictionary_index - 1]
        )
        transformed = self._decompress(
            data[2:],
            dictionary=dictionary,
            max_output_size=max_output_size,
        )
        output = self._unshuffle(transformed, width)
        require_stage_output_size(
            self.stage_id,
            len(output),
            max_output_size=max_output_size,
            operation="decode",
        )
        return output

    def _decompress(
        self,
        payload: bytes,
        *,
        dictionary: bytes | None,
        max_output_size: int | None,
    ) -> bytes:
        if dictionary is None:
            if self._uses_preset_dictionary(payload):
                raise ProviderRejectedError(
                    "payload declares no dictionary but zlib requires one"
                )
            decoder = stdlib_zlib.decompressobj()
        else:
            self._validate_dictionary_header(payload, dictionary)
            decoder = stdlib_zlib.decompressobj(zdict=dictionary)
        try:
            if max_output_size is None:
                output = decoder.decompress(payload)
                output += decoder.flush()
            else:
                output = decoder.decompress(payload, max_output_size + 1)
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
        if not decoder.eof or decoder.unused_data:
            raise ProviderRejectedError("zlib payload has invalid framing")
        return output

    @staticmethod
    def _unshuffle(data: bytes, width: int) -> bytes:
        if width == 1:
            return data
        element_count = len(data) // width
        full_size = element_count * width
        output = bytearray(full_size)
        input_index = 0
        for byte_index in range(width):
            for element_index in range(element_count):
                output[element_index * width + byte_index] = data[input_index]
                input_index += 1
        output.extend(data[full_size:])
        return bytes(output)

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

    def _validate_dictionary_header(self, data: bytes, dictionary: bytes) -> None:
        if not self._has_valid_zlib_header(data):
            raise ProviderRejectedError("invalid zlib payload: invalid header")
        if not self._uses_preset_dictionary(data):
            raise ProviderRejectedError(
                "payload selects a dictionary but zlib does not use one"
            )
        if len(data) < 6:
            raise ProviderRejectedError(
                "invalid zlib payload: truncated dictionary identifier"
            )
        declared = int.from_bytes(data[2:6], "big")
        expected = stdlib_zlib.adler32(dictionary) & 0xFFFFFFFF
        if declared != expected:
            raise ProviderRejectedError(
                "zlib dictionary identifier does not match the selected dictionary"
            )


__all__ = ["AdaptiveZlibExtension", "AdaptiveZlibParameters"]

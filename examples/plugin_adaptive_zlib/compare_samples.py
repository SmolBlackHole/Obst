"""Compare adaptive choices on structured bytes and existing OBST containers."""

from __future__ import annotations

import zlib as stdlib_zlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from obst.core import (
    DEFAULT_RESOURCE_POLICY,
    ExtensionRegistry,
    Recipe,
    RecipeDecoder,
    RecipeEncoder,
    ResourceAccounting,
    StageSpec,
)

from obst_example_adaptive_zlib import (
    AdaptiveZlibExtension,
    AdaptiveZlibParameters,
)

_CHUNK_SIZE = 64 * 1024
_MODE_NAMES = {
    0: "raw",
    1: "shuffle2",
    2: "shuffle4",
    3: "shuffle8",
    4: "shuffle16",
}


@dataclass(frozen=True, slots=True)
class Comparison:
    name: str
    logical_size: int
    fixed_payload_size: int
    adaptive_payload_size: int
    parameter_size: int
    choices: tuple[tuple[str, int], ...]
    round_trip_is_byte_identical: bool


def _chunks(data: bytes) -> tuple[bytes, ...]:
    return tuple(
        data[offset : offset + _CHUNK_SIZE]
        for offset in range(0, len(data), _CHUNK_SIZE)
    ) or (b"",)


def _compare(
    name: str,
    logical: bytes,
    parameters: AdaptiveZlibParameters,
) -> Comparison:
    extension = AdaptiveZlibExtension()
    parameter_bytes = extension.encode_parameters(parameters)
    registry = ExtensionRegistry((extension,))
    recipe = Recipe(
        0,
        (StageSpec(extension.extension_id, parameter_bytes),),
    )
    accounting = ResourceAccounting(DEFAULT_RESOURCE_POLICY)
    encoder = RecipeEncoder(registry, accounting=accounting)
    decoder = RecipeDecoder(registry, accounting=accounting)
    encoded_chunks: list[bytes] = []
    recovered_chunks: list[bytes] = []
    choices: Counter[str] = Counter()
    fixed_payload_size = 0
    for chunk in _chunks(logical):
        encoded = encoder.encode(chunk, recipe)
        encoded_chunks.append(encoded)
        recovered_chunks.append(
            decoder.decode(encoded, recipe, expected_size=len(chunk))
        )
        fixed_payload_size += len(
            stdlib_zlib.compress(chunk, parameters.compression_level)
        )
        mode, dictionary_index = encoded[:2]
        choices[f"{_MODE_NAMES[mode]}/dictionary-{dictionary_index}"] += 1
    recovered = b"".join(recovered_chunks)
    return Comparison(
        name=name,
        logical_size=len(logical),
        fixed_payload_size=fixed_payload_size,
        adaptive_payload_size=sum(len(chunk) for chunk in encoded_chunks),
        parameter_size=len(parameter_bytes),
        choices=tuple(sorted(choices.items())),
        round_trip_is_byte_identical=recovered == logical,
    )


def _structured_records() -> bytes:
    return b"".join(
        index.to_bytes(4, "little") + (1_000_000 + index * 3).to_bytes(4, "little")
        for index in range(8192)
    )


def _print(comparison: Comparison) -> None:
    adaptive_total = comparison.adaptive_payload_size + comparison.parameter_size
    difference = adaptive_total - comparison.fixed_payload_size
    relation = f"{abs(difference)} B {'larger' if difference > 0 else 'smaller'}"
    if difference == 0:
        relation = "same size"
    print(comparison.name)
    print(f"  Logical bytes:          {comparison.logical_size}")
    print(f"  Fixed zlib payload:     {comparison.fixed_payload_size}")
    print(f"  Adaptive payload:       {comparison.adaptive_payload_size}")
    print(f"  Adaptive parameters:    {comparison.parameter_size}")
    print(f"  Effective comparison:   {relation}")
    print(
        "  Choices:                "
        + ", ".join(f"{name} x {count}" for name, count in comparison.choices)
    )
    print(f"  Round trip identical:   {comparison.round_trip_is_byte_identical}")


def main() -> None:
    repository = Path(__file__).resolve().parents[2]
    samples = repository / "samples"
    dictionary = (samples / "apple.obst").read_bytes()[: 8 * 1024]
    comparisons = (
        _compare(
            "Synthetic fixed-width records",
            _structured_records(),
            AdaptiveZlibParameters(compression_level=9),
        ),
        _compare(
            "Existing samples/all-fruit.obst as ordinary bytes",
            (samples / "all-fruit.obst").read_bytes(),
            AdaptiveZlibParameters(
                compression_level=9,
                dictionaries=(dictionary,),
            ),
        ),
    )
    for index, comparison in enumerate(comparisons):
        if index:
            print()
        _print(comparison)
    if not all(item.round_trip_is_byte_identical for item in comparisons):
        raise RuntimeError("adaptive-zlib comparison failed its round trip")


if __name__ == "__main__":
    main()

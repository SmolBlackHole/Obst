"""Package, inspect, and recover 2 in-memory OBST byte streams."""

from __future__ import annotations

from io import BytesIO
from typing import cast

from obst.core import (
    BYTES_STREAM_TYPE,
    DEFAULT_RESOURCE_POLICY,
    ContainerReader,
    ExtensionRegistry,
    LogicalStreamDescriptor,
    LogicalStreamSource,
    PackagerProvider,
    RecipeSpec,
    ResourceAccounting,
    StageSpec,
    inspect_container,
    iter_decoded_chunks,
)

from obst_defaults.codecs import RawExtension, ZlibExtension, ZlibParameters
from obst_defaults.packagers import FixedPackageRequest, FixedPackagerExtension
from obst_defaults.transforms import Delta8Extension


def main() -> None:
    """Run one complete carrier-neutral OBST round trip."""
    raw = RawExtension()
    delta8 = Delta8Extension()
    zlib = ZlibExtension()
    fixed = FixedPackagerExtension()

    # Extensions become available only because this host explicitly trusts and
    # registers them. Container bytes never import or download Python code.
    registry = ExtensionRegistry((raw, delta8, zlib, fixed))
    packager = cast(
        PackagerProvider[FixedPackageRequest],
        registry.require_packager_provider(fixed.extension_id),
    )

    raw_recipe = RecipeSpec((StageSpec(raw.extension_id),))
    compressed_recipe = RecipeSpec(
        (
            StageSpec(delta8.extension_id),
            StageSpec(
                zlib.extension_id,
                zlib.encode_parameters(ZlibParameters(9)),
            ),
        )
    )

    logical_streams = (
        b"OBST stores logical bytes, not Python objects.\n" * 4,
        bytes(value // 4 % 256 for value in range(4 * 1024)),
    )
    sources = (
        LogicalStreamSource.from_bytes(
            LogicalStreamDescriptor(BYTES_STREAM_TYPE, b"", raw_recipe),
            logical_streams[0],
            chunk_size=64,
        ),
        LogicalStreamSource.from_bytes(
            LogicalStreamDescriptor(BYTES_STREAM_TYPE, b"", compressed_recipe),
            logical_streams[1],
            chunk_size=512,
        ),
    )

    target = BytesIO()
    package_accounting = ResourceAccounting(DEFAULT_RESOURCE_POLICY)
    operation = packager.prepare_package(
        FixedPackageRequest(registry, sources, package_accounting)
    )
    package = operation.write_to(target)
    container_bytes = target.getvalue()

    # Inspection consumes a reader and validates the complete stored form. It
    # deliberately does not execute decoders, so recovery uses a fresh reader.
    inspection = inspect_container(
        ContainerReader(
            BytesIO(container_bytes),
            accounting=ResourceAccounting(DEFAULT_RESOURCE_POLICY),
        ),
        registry=registry,
    )
    if inspection.encoded_size != len(container_bytes):
        raise RuntimeError("inspection reported the wrong container size")
    if not inspection.required_decoders_available:
        raise RuntimeError("the registry cannot decode every required stage")

    recovered = [bytearray() for _ in logical_streams]
    for chunk, logical_bytes in iter_decoded_chunks(
        ContainerReader(
            BytesIO(container_bytes),
            accounting=ResourceAccounting(DEFAULT_RESOURCE_POLICY),
        ),
        registry,
    ):
        recovered[chunk.stream_id].extend(logical_bytes)
    recovered_streams = tuple(bytes(stream) for stream in recovered)
    round_trip_is_byte_identical = recovered_streams == logical_streams

    print("OBST in-memory API walkthrough")
    print(f"Streams: {inspection.stream_count}")
    print(f"Recipes: {inspection.recipe_count}")
    print(f"Chunks: {package.chunk_count}")
    print(f"Container bytes: {len(container_bytes)}")
    print(f"Logical bytes: {sum(map(len, logical_streams))}")
    print(f"Inspection recovery: {inspection.logical_recovery.value}")
    print(f"Round trip byte-identical: {round_trip_is_byte_identical}")
    if not round_trip_is_byte_identical:
        raise RuntimeError("OBST round trip changed the logical bytes")


if __name__ == "__main__":
    main()

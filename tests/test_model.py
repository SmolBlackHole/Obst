from __future__ import annotations

import struct
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from obst.core import (
    BYTES_STREAM_TYPE,
    ExtensionDeclaration,
    FormatVersion,
    Manifest,
    Recipe,
    ResourceLimits,
    StageSpec,
    Stream,
    format_version,
    validate_manifest_resources,
)
from obst.core.errors import (
    CorruptContainerError,
    InvalidContainerError,
    ResourceLimitError,
    TruncatedContainerError,
    UnsupportedVersionError,
)
from obst.core.manifest import decode_manifest, encode_manifest
from obst.core.wire import ManifestHeader, uint32
from tests.support_extensions import IdentityExtension as RawExtension

_METADATA_STREAM_TYPE = "org.example/data@1"
_PROPERTY_STAGE_IDS = ("org.example/alpha@1", "org.example/beta@2")
_PROPERTY_STREAM_TYPES = (_METADATA_STREAM_TYPE, "org.example/records@2")
_MUTATION_STAGE_ID = "org.example/alpha@1"
_MUTATION_STREAM_TYPE = "org.example/bravo@1"


def _encode_manifest(manifest: Manifest) -> bytes:
    return encode_manifest(manifest)


def test_format_version_owns_numeric_and_human_identity() -> None:
    assert format_version == FormatVersion(major=0, minor=1, codename="apple")
    assert format_version.numeric == (0, 1)
    assert format_version.label == "0.1-apple"


@pytest.mark.parametrize(
    "version",
    (
        pytest.param(
            lambda: FormatVersion(major=256, minor=0, codename="apple"),
            id="major-does-not-fit-u8",
        ),
        pytest.param(
            lambda: FormatVersion(major=0, minor=-1, codename="apple"),
            id="negative-minor",
        ),
        pytest.param(
            lambda: FormatVersion(major=True, minor=0, codename="apple"),
            id="boolean-major",
        ),
        pytest.param(
            lambda: FormatVersion(major=0, minor=1, codename=""),
            id="empty-codename",
        ),
    ),
)
def test_format_version_rejects_invalid_identity(
    version: Callable[[], FormatVersion],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        version()


@dataclass(frozen=True, slots=True)
class _ManifestMutation:
    replacements: tuple[tuple[int, bytes], ...]
    error_type: type[InvalidContainerError]
    message: str


@dataclass(frozen=True, slots=True)
class _ManifestHeaderMutation:
    offset: int
    replacement: bytes
    error_type: type[InvalidContainerError]
    message: str
    repair_checksum: bool = True


@dataclass(frozen=True, slots=True)
class _SizedManifestPart:
    size: int

    def __len__(self) -> int:
        return self.size


def raw_recipe(recipe_id: int) -> Recipe:
    return Recipe(recipe_id, (StageSpec(RawExtension.extension_id),))


def _manifest_offsets(
    manifest: Manifest,
) -> tuple[dict[str, int], dict[int, int], dict[int, int]]:
    offset = ManifestHeader.size
    extension_offsets: dict[str, int] = {}
    for extension in manifest.extensions:
        encoded_id = extension.extension_id.encode("ascii")
        encoded_url = (
            b""
            if extension.specification_url is None
            else extension.specification_url.encode("ascii")
        )
        extension_offsets[extension.extension_id] = offset + 4
        offset += 4 + len(encoded_id) + len(encoded_url)

    recipe_offsets: dict[int, int] = {}
    for recipe in sorted(manifest.recipes, key=lambda item: item.recipe_id):
        recipe_offsets[recipe.recipe_id] = offset
        offset += 8
        for stage in recipe.stages:
            offset += 8 + len(stage.parameters)

    stream_offsets: dict[int, int] = {}
    for stream in sorted(manifest.streams, key=lambda item: item.stream_id):
        stream_offsets[stream.stream_id] = offset
        offset += 16 + len(stream.metadata)

    return extension_offsets, recipe_offsets, stream_offsets


def _rewrite_manifest_checksums(encoded: bytearray) -> None:
    struct.pack_into("<I", encoded, 16, zlib.crc32(encoded[ManifestHeader.size :]))
    struct.pack_into("<I", encoded, 20, zlib.crc32(encoded[:20]))


def _uint32(value: int) -> bytes:
    return struct.pack("<I", value)


_MUTATION_MANIFEST = Manifest(
    recipes=(
        Recipe(1, (StageSpec(_MUTATION_STAGE_ID),)),
        Recipe(7, (StageSpec(_MUTATION_STAGE_ID),)),
    ),
    streams=(
        Stream(2, _MUTATION_STREAM_TYPE, 1),
        Stream(8, _MUTATION_STREAM_TYPE, 7),
    ),
)
_EXTENSION_OFFSETS, _RECIPE_OFFSETS, _STREAM_OFFSETS = _manifest_offsets(
    _MUTATION_MANIFEST
)
_EXTENSION_COUNT = len(_MUTATION_MANIFEST.extensions)
_FIRST_RECIPE_STAGE_OFFSET = _RECIPE_OFFSETS[1] + 8


@st.composite
def _manifests(draw: st.DrawFn) -> Manifest:
    recipe_ids = sorted(
        draw(
            st.lists(
                st.integers(min_value=0, max_value=1000),
                min_size=1,
                max_size=5,
                unique=True,
            )
        )
    )
    recipes: list[Recipe] = []
    for recipe_id in recipe_ids:
        stage_count = draw(st.integers(min_value=1, max_value=3))
        stages = tuple(
            StageSpec(
                draw(st.sampled_from(_PROPERTY_STAGE_IDS)),
                draw(st.binary(max_size=16)),
            )
            for _ in range(stage_count)
        )
        recipes.append(Recipe(recipe_id, stages))

    stream_ids = sorted(
        draw(
            st.lists(
                st.integers(min_value=0, max_value=1000),
                min_size=1,
                max_size=5,
                unique=True,
            )
        )
    )
    streams = tuple(
        Stream(
            stream_id,
            draw(st.sampled_from(_PROPERTY_STREAM_TYPES)),
            draw(st.sampled_from(recipe_ids)),
            draw(st.binary(max_size=16)),
        )
        for stream_id in stream_ids
    )
    return Manifest(recipes=tuple(recipes), streams=streams)


@settings(max_examples=75)
@given(manifest=_manifests())
def test_manifest_binary_codec_round_trips_valid_models(manifest: Manifest) -> None:
    encoded = _encode_manifest(manifest)
    decoded = decode_manifest(
        encoded,
        recipe_count=len(manifest.recipes),
        stream_count=len(manifest.streams),
    )

    assert decoded == manifest
    assert _encode_manifest(decoded) == encoded


def test_manifest_encoding_accepts_exact_budget_and_rejects_one_byte_less() -> None:
    encoded = _encode_manifest(_MUTATION_MANIFEST)

    assert (
        encode_manifest(
            _MUTATION_MANIFEST,
            limits=ResourceLimits(max_manifest_bytes=len(encoded)),
        )
        == encoded
    )
    with pytest.raises(ResourceLimitError) as error:
        encode_manifest(
            _MUTATION_MANIFEST,
            limits=ResourceLimits(max_manifest_bytes=len(encoded) - 1),
        )
    assert error.value.resource == "manifest_bytes"


def test_complete_manifest_size_must_fit_container_header_uint32(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    part = _SizedManifestPart(uint32.maximum - ManifestHeader.size)

    def sized_parts(
        _manifest: Manifest,
        _extension_indexes: dict[str, int],
    ) -> Iterator[bytes]:
        yield cast(bytes, part)

    monkeypatch.setattr(
        "obst.core.manifest._iter_body_parts",
        sized_parts,
    )
    limits = ResourceLimits(max_manifest_bytes=None)

    validate_manifest_resources(_MUTATION_MANIFEST, limits=limits)
    part = _SizedManifestPart(part.size + 1)

    with pytest.raises(ValueError, match="complete manifest size must fit into uint32"):
        validate_manifest_resources(_MUTATION_MANIFEST, limits=limits)


def test_manifest_rejects_duplicate_recipe_and_stream_ids() -> None:
    with pytest.raises(ValueError, match="recipe ids must be unique"):
        Manifest(
            recipes=(raw_recipe(0), raw_recipe(0)),
            streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
        )

    with pytest.raises(ValueError, match="stream ids must be unique"):
        Manifest(
            recipes=(raw_recipe(0),),
            streams=(
                Stream(0, BYTES_STREAM_TYPE, 0),
                Stream(0, BYTES_STREAM_TYPE, 0),
            ),
        )


def test_manifest_rejects_unknown_default_recipe() -> None:
    with pytest.raises(ValueError, match="references unknown default recipe"):
        Manifest(
            recipes=(raw_recipe(0),),
            streams=(Stream(0, BYTES_STREAM_TYPE, 7),),
        )


def test_manifest_encoding_is_canonical_by_id() -> None:
    manifest = Manifest(
        recipes=(raw_recipe(7), raw_recipe(1)),
        streams=(
            Stream(8, _METADATA_STREAM_TYPE, 7, b"eight"),
            Stream(2, _METADATA_STREAM_TYPE, 1, b"two"),
        ),
    )

    encoded = _encode_manifest(manifest)
    decoded = decode_manifest(encoded, recipe_count=2, stream_count=2)

    assert tuple(recipe.recipe_id for recipe in decoded.recipes) == (1, 7)
    assert tuple(stream.stream_id for stream in decoded.streams) == (2, 8)
    assert _encode_manifest(decoded) == encoded


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(
            _ManifestMutation(
                replacements=(
                    (
                        _EXTENSION_OFFSETS[_MUTATION_STREAM_TYPE],
                        _MUTATION_STAGE_ID.encode("ascii"),
                    ),
                ),
                error_type=InvalidContainerError,
                message="extension ids must be unique and sorted",
            ),
            id="duplicate-extension-id",
        ),
        pytest.param(
            _ManifestMutation(
                replacements=(
                    (
                        _EXTENSION_OFFSETS[_MUTATION_STAGE_ID],
                        _MUTATION_STREAM_TYPE.encode("ascii"),
                    ),
                    (
                        _EXTENSION_OFFSETS[_MUTATION_STREAM_TYPE],
                        _MUTATION_STAGE_ID.encode("ascii"),
                    ),
                ),
                error_type=InvalidContainerError,
                message="extension ids must be unique and sorted",
            ),
            id="noncanonical-extension-order",
        ),
        pytest.param(
            _ManifestMutation(
                replacements=((_RECIPE_OFFSETS[7], _uint32(1)),),
                error_type=InvalidContainerError,
                message="recipe ids must be unique",
            ),
            id="duplicate-recipe-id",
        ),
        pytest.param(
            _ManifestMutation(
                replacements=((_RECIPE_OFFSETS[1], _uint32(8)),),
                error_type=InvalidContainerError,
                message="recipes must be sorted by id",
            ),
            id="noncanonical-recipe-order",
        ),
        pytest.param(
            _ManifestMutation(
                replacements=((_STREAM_OFFSETS[8], _uint32(2)),),
                error_type=InvalidContainerError,
                message="stream ids must be unique",
            ),
            id="duplicate-stream-id",
        ),
        pytest.param(
            _ManifestMutation(
                replacements=((_STREAM_OFFSETS[2], _uint32(9)),),
                error_type=InvalidContainerError,
                message="streams must be sorted by id",
            ),
            id="noncanonical-stream-order",
        ),
        pytest.param(
            _ManifestMutation(
                replacements=((_FIRST_RECIPE_STAGE_OFFSET, _uint32(_EXTENSION_COUNT)),),
                error_type=InvalidContainerError,
                message="unknown extension index",
            ),
            id="unknown-stage-extension",
        ),
        pytest.param(
            _ManifestMutation(
                replacements=((_STREAM_OFFSETS[2] + 4, _uint32(_EXTENSION_COUNT)),),
                error_type=InvalidContainerError,
                message="unknown extension index",
            ),
            id="unknown-stream-type-extension",
        ),
        pytest.param(
            _ManifestMutation(
                replacements=((_STREAM_OFFSETS[2] + 8, _uint32(99)),),
                error_type=InvalidContainerError,
                message="references unknown default recipe",
            ),
            id="unknown-default-recipe",
        ),
        pytest.param(
            _ManifestMutation(
                replacements=((_FIRST_RECIPE_STAGE_OFFSET + 4, _uint32(0xFFFFFFFF)),),
                error_type=TruncatedContainerError,
                message="stage parameters",
            ),
            id="oversized-stage-parameters",
        ),
        pytest.param(
            _ManifestMutation(
                replacements=((_STREAM_OFFSETS[2] + 12, _uint32(0xFFFFFFFF)),),
                error_type=TruncatedContainerError,
                message="stream metadata",
            ),
            id="oversized-stream-metadata",
        ),
    ],
)
def test_manifest_wire_rejects_noncanonical_and_invalid_references(
    mutation: _ManifestMutation,
) -> None:
    encoded = bytearray(_encode_manifest(_MUTATION_MANIFEST))
    for offset, replacement in mutation.replacements:
        encoded[offset : offset + len(replacement)] = replacement
    _rewrite_manifest_checksums(encoded)

    with pytest.raises(mutation.error_type, match=mutation.message):
        decode_manifest(bytes(encoded), recipe_count=2, stream_count=2)


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(
            _ManifestHeaderMutation(
                0,
                b"NOPE",
                InvalidContainerError,
                "manifest magic",
            ),
            id="magic",
        ),
        pytest.param(
            _ManifestHeaderMutation(
                4,
                b"\x01",
                UnsupportedVersionError,
                r"manifest version 1\.1",
            ),
            id="version-major",
        ),
        pytest.param(
            _ManifestHeaderMutation(
                5,
                b"\x02",
                UnsupportedVersionError,
                r"manifest version 0\.2",
            ),
            id="version-minor",
        ),
        pytest.param(
            _ManifestHeaderMutation(
                6,
                struct.pack("<H", 0),
                InvalidContainerError,
                "manifest header size",
            ),
            id="header-size",
        ),
        pytest.param(
            _ManifestHeaderMutation(
                8,
                _uint32(0),
                InvalidContainerError,
                "recipe reserved field",
            ),
            id="extension-count",
        ),
        pytest.param(
            _ManifestHeaderMutation(
                12,
                _uint32(0),
                InvalidContainerError,
                "manifest body size",
            ),
            id="body-size",
        ),
        pytest.param(
            _ManifestHeaderMutation(
                16,
                _uint32(0),
                CorruptContainerError,
                "manifest body checksum",
            ),
            id="body-crc",
        ),
        pytest.param(
            _ManifestHeaderMutation(
                20,
                _uint32(0),
                CorruptContainerError,
                "manifest header checksum",
                repair_checksum=False,
            ),
            id="header-crc",
        ),
    ],
)
def test_manifest_header_mutation_matrix(
    mutation: _ManifestHeaderMutation,
) -> None:
    encoded = bytearray(_encode_manifest(_MUTATION_MANIFEST))
    encoded[mutation.offset : mutation.offset + len(mutation.replacement)] = (
        mutation.replacement
    )
    if mutation.repair_checksum:
        struct.pack_into("<I", encoded, 20, zlib.crc32(encoded[:20]))

    with pytest.raises(mutation.error_type, match=mutation.message):
        decode_manifest(bytes(encoded), recipe_count=2, stream_count=2)


def test_manifest_round_trips_declared_extension_specification_urls() -> None:
    specification_url = "https://example.org/specs/raw-v1"
    manifest = Manifest(
        recipes=(raw_recipe(0),),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
        extensions=(
            ExtensionDeclaration(RawExtension.extension_id, specification_url),
        ),
    )

    decoded = decode_manifest(
        _encode_manifest(manifest),
        recipe_count=1,
        stream_count=1,
    )

    assert decoded == manifest
    assert (
        decoded.extension(RawExtension.extension_id).specification_url
        == specification_url
    )
    assert decoded.extension(BYTES_STREAM_TYPE).specification_url is None


def test_manifest_rejects_unreferenced_extension_declarations() -> None:
    with pytest.raises(ValueError, match="extension declaration is not referenced"):
        Manifest(
            recipes=(raw_recipe(0),),
            streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
            extensions=(ExtensionDeclaration("org.example/unused@1"),),
        )


@pytest.mark.parametrize(
    "specification_url",
    [
        "",
        "relative/spec",
        "https://example.org/spec with space",
        "https://example.org/spec\x7f",
        "https://exämple.org",
    ],
)
def test_extension_declaration_rejects_nonportable_specification_urls(
    specification_url: str,
) -> None:
    with pytest.raises(ValueError):
        ExtensionDeclaration(RawExtension.extension_id, specification_url)


def test_extension_declaration_enforces_wire_url_size() -> None:
    specification_url = "https://example.org/" + "a" * 65_536

    with pytest.raises(ValueError, match="cannot exceed 65535 bytes"):
        ExtensionDeclaration(RawExtension.extension_id, specification_url)


@pytest.mark.parametrize(
    ("limits", "message"),
    [
        (ResourceLimits(max_extensions=1), "extensions"),
        (ResourceLimits(max_recipes=1), "recipes"),
        (ResourceLimits(max_streams=1), "streams"),
        (ResourceLimits(max_total_stages=1), "total_stages"),
    ],
)
def test_manifest_decoding_enforces_configured_count_limits(
    limits: ResourceLimits,
    message: str,
) -> None:
    manifest = Manifest(
        recipes=(raw_recipe(0), raw_recipe(1)),
        streams=(
            Stream(0, BYTES_STREAM_TYPE, 0),
            Stream(1, BYTES_STREAM_TYPE, 1),
        ),
    )

    with pytest.raises(ResourceLimitError, match=message):
        decode_manifest(
            _encode_manifest(manifest),
            recipe_count=2,
            stream_count=2,
            limits=limits,
        )


def test_manifest_decoding_accepts_configured_count_boundaries() -> None:
    manifest = Manifest(
        recipes=(raw_recipe(0), raw_recipe(1)),
        streams=(
            Stream(0, BYTES_STREAM_TYPE, 0),
            Stream(1, BYTES_STREAM_TYPE, 1),
        ),
    )

    decoded = decode_manifest(
        _encode_manifest(manifest),
        recipe_count=2,
        stream_count=2,
        limits=ResourceLimits(
            max_extensions=2,
            max_recipes=2,
            max_streams=2,
            max_total_stages=2,
        ),
    )

    assert decoded == manifest


def test_manifest_enforces_per_recipe_stage_limit_in_both_directions() -> None:
    manifest = Manifest(
        recipes=(
            Recipe(
                0,
                (
                    StageSpec(RawExtension.extension_id),
                    StageSpec(RawExtension.extension_id),
                ),
            ),
        ),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    encoded = _encode_manifest(manifest)
    limits = ResourceLimits(max_stages_per_recipe=1)

    with pytest.raises(ResourceLimitError) as encode_error:
        encode_manifest(manifest, limits=limits)
    assert encode_error.value.resource == "stages_per_recipe"

    with pytest.raises(ResourceLimitError) as decode_error:
        decode_manifest(
            encoded,
            recipe_count=1,
            stream_count=1,
            limits=limits,
        )
    assert decode_error.value.resource == "stages_per_recipe"

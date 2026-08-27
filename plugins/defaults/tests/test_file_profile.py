from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from obst.core import (
    Extension,
    ExtensionContractError,
    ExtensionDescriptor,
    ExtensionRegistrationError,
    ExtensionRegistry,
    RecipeSpec,
    StageSpec,
)
from obst.core.extensions import ExtensionKind
from obst_defaults.codecs.raw import RawExtension
from obst_defaults.files import (
    FileArchiveError,
    FileArchiver,
    FileExtension,
    FileMaterialization,
    FileProfileError,
    PortableFileMetadata,
)

_CUSTOM_FILE_ID = "org.example/file@1"
_CUSTOM_FILE_DESCRIPTOR = ExtensionDescriptor(display_name="Example file")


def _raw_recipe() -> RecipeSpec:
    return RecipeSpec((StageSpec(RawExtension.extension_id),))


def _archiver(*extensions: Extension) -> FileArchiver:
    return FileArchiver(ExtensionRegistry(extensions))


class _SourceOnlyFileProfile:
    extension_id = _CUSTOM_FILE_ID
    kind = ExtensionKind.STREAM_PROFILE
    descriptor = _CUSTOM_FILE_DESCRIPTOR

    def encode_file_name(self, name: str, /) -> bytes:
        return f"source:{name}".encode()


class _MaterializerOnlyFileProfile:
    extension_id = _CUSTOM_FILE_ID
    kind = ExtensionKind.STREAM_PROFILE
    descriptor = _CUSTOM_FILE_DESCRIPTOR

    def plan_file(self, metadata: bytes, /) -> FileMaterialization:
        prefix, name = metadata.decode().split(":", 1)
        assert prefix == "source"
        return FileMaterialization(name)


def test_file_extension_owns_both_directional_file_capabilities() -> None:
    extension = FileExtension()
    value = PortableFileMetadata("payload.bin")
    metadata = extension.encode_metadata(value)

    plan = extension.plan_file(metadata)
    interpretation = extension.interpret_metadata(metadata)

    assert extension.extension_id == "obst.file@1"
    assert extension.kind is ExtensionKind.STREAM_PROFILE
    assert metadata == b"payload.bin"
    assert extension.decode_metadata(metadata) == value
    assert extension.encode_file_name(value.name) == metadata
    assert plan == FileMaterialization("payload.bin")
    assert interpretation.label == "payload.bin"
    assert tuple((field.name, field.value) for field in interpretation.fields) == (
        ("name", "payload.bin"),
    )


def test_file_archiver_composes_split_capabilities_by_extension_id() -> None:
    archiver = _archiver(_SourceOnlyFileProfile(), _MaterializerOnlyFileProfile())

    assert archiver.can_source(_CUSTOM_FILE_ID)
    assert archiver.can_materialize(_CUSTOM_FILE_ID)
    assert archiver.plan_file(_CUSTOM_FILE_ID, b"source:payload.bin") == (
        FileMaterialization("payload.bin")
    )


def test_file_archiver_uses_the_registrys_captured_extension_identity() -> None:
    class ShiftingFileProfile:
        kind = ExtensionKind.STREAM_PROFILE
        descriptor = _CUSTOM_FILE_DESCRIPTOR

        def __init__(self) -> None:
            self.identity_reads = 0

        @property
        def extension_id(self) -> str:
            self.identity_reads += 1
            return (
                "org.example/first@1"
                if self.identity_reads == 1
                else "org.example/second@1"
            )

        def encode_file_name(self, name: str, /) -> bytes:
            return f"source:{name}".encode()

    extension = ShiftingFileProfile()
    registry = ExtensionRegistry((extension,))

    archiver = FileArchiver(registry)

    assert extension.identity_reads == 1
    assert archiver.can_source("org.example/first@1")
    assert not archiver.can_source("org.example/second@1")


@pytest.mark.parametrize(
    ("extensions", "capability"),
    (
        (
            (_SourceOnlyFileProfile(), _SourceOnlyFileProfile()),
            "file source",
        ),
        (
            (_MaterializerOnlyFileProfile(), _MaterializerOnlyFileProfile()),
            "file materializer",
        ),
    ),
)
def test_file_archiver_rejects_duplicate_capabilities_per_id(
    extensions: tuple[object, object],
    capability: str,
) -> None:
    with pytest.raises(ExtensionRegistrationError, match=f"duplicate {capability}"):
        _archiver(*cast(tuple[Extension, ...], extensions))


@pytest.mark.parametrize(
    ("member", "capability"),
    (
        ("encode_file_name", "file source"),
        ("plan_file", "file materializer"),
    ),
)
def test_file_archiver_rejects_non_callable_file_capabilities(
    member: str,
    capability: str,
) -> None:
    extension = type(
        "BrokenFileProfile",
        (),
        {
            "extension_id": _CUSTOM_FILE_ID,
            "kind": ExtensionKind.STREAM_PROFILE,
            "descriptor": _CUSTOM_FILE_DESCRIPTOR,
            member: 1,
        },
    )()

    with pytest.raises(ExtensionContractError) as error:
        _archiver(cast(Extension, extension))

    assert error.value.capability == capability
    assert member in error.value.reason


def test_file_archiver_uses_the_callers_profile_and_recipe_policy(
    tmp_path: Path,
) -> None:
    path = tmp_path / "payload.bin"
    path.write_bytes(b"payload")
    source_profile = _SourceOnlyFileProfile()
    archiver = _archiver(source_profile)
    recipe = _raw_recipe()

    with archiver.open_sources(
        (path,),
        source_profile_id=source_profile.extension_id,
        recipe=recipe,
        chunk_size=3,
    ) as sources:
        (source,) = sources
        assert source.descriptor.stream_type == source_profile.extension_id
        assert source.descriptor.metadata == b"source:payload.bin"
        assert source.descriptor.default_recipe is recipe
        assert tuple(source.iter_chunks()) == (b"pay", b"loa", b"d")


def test_file_archiver_reports_a_missing_source_capability(tmp_path: Path) -> None:
    path = tmp_path / "payload.bin"
    path.write_bytes(b"payload")
    archiver = _archiver(_MaterializerOnlyFileProfile())

    with pytest.raises(FileArchiveError, match="missing file source capability"):
        with archiver.open_sources(
            (path,),
            source_profile_id=_CUSTOM_FILE_ID,
            recipe=_raw_recipe(),
        ):
            pass


def test_file_source_rejects_a_non_bytes_provider_result(tmp_path: Path) -> None:
    class BytesSubclass(bytes):
        pass

    class BrokenSource(_SourceOnlyFileProfile):
        def encode_file_name(self, name: str, /) -> bytes:
            return BytesSubclass(name.encode())

    path = tmp_path / "payload.bin"
    path.write_bytes(b"payload")
    archiver = _archiver(BrokenSource())

    with pytest.raises(ExtensionContractError, match="must return exact bytes"):
        with archiver.open_sources(
            (path,),
            source_profile_id=_CUSTOM_FILE_ID,
            recipe=_raw_recipe(),
        ):
            pass


def test_file_materializer_rejects_a_non_plan_provider_result() -> None:
    class BrokenMaterializer(_MaterializerOnlyFileProfile):
        def plan_file(self, metadata: bytes, /) -> FileMaterialization:
            return cast(FileMaterialization, "payload.bin")

    archiver = _archiver(BrokenMaterializer())

    with pytest.raises(
        ExtensionContractError,
        match="must return an exact FileMaterialization",
    ):
        archiver.plan_file(_CUSTOM_FILE_ID, b"source:payload.bin")


def test_file_source_cannot_misattribute_profile_errors(tmp_path: Path) -> None:
    class MisattributingSource(_SourceOnlyFileProfile):
        def encode_file_name(self, name: str, /) -> bytes:
            raise FileProfileError("org.example/wrong@1", "wrong profile")

    archiver = _archiver(MisattributingSource())
    path = tmp_path / "payload.bin"
    path.write_bytes(b"payload")

    with pytest.raises(ExtensionContractError, match="raised FileProfileError for"):
        with archiver.open_sources(
            (path,),
            source_profile_id=_CUSTOM_FILE_ID,
            recipe=_raw_recipe(),
        ):
            pass


def test_file_materializer_cannot_misattribute_profile_errors() -> None:
    class MisattributingMaterializer(_MaterializerOnlyFileProfile):
        def plan_file(self, metadata: bytes, /) -> FileMaterialization:
            raise FileProfileError("org.example/wrong@1", "wrong profile")

    archiver = _archiver(MisattributingMaterializer())

    with pytest.raises(ExtensionContractError, match="raised FileProfileError for"):
        archiver.plan_file(_CUSTOM_FILE_ID, b"source:payload.bin")


@pytest.mark.parametrize(
    "name",
    ["", ".", "..", "../escape", "sub/path", "sub\\path", "CON", "bad?.txt"],
)
def test_file_extension_rejects_unsafe_or_nonportable_names(name: str) -> None:
    with pytest.raises(FileProfileError):
        FileExtension().encode_file_name(name)


def test_file_extension_rejects_noncanonical_metadata() -> None:
    extension = FileExtension()

    with pytest.raises(FileProfileError, match="valid UTF-8"):
        extension.plan_file(b"\xff")
    with pytest.raises(FileProfileError, match="normalized as NFC"):
        extension.plan_file("A\u0308pfel.txt".encode())


@pytest.mark.parametrize(
    "character",
    (
        "\u061c",
        "\u200e",
        "\u200f",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
    ),
)
def test_file_extension_rejects_bidirectional_controls(character: str) -> None:
    with pytest.raises(FileProfileError, match="bidirectional control"):
        FileExtension().encode_file_name(f"safe{character}evil.txt")


def test_file_extension_preserves_non_directional_format_characters() -> None:
    name = "family\u200dname.txt"

    metadata = FileExtension().encode_file_name(name)

    assert metadata.decode("utf-8") == name

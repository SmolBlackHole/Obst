from __future__ import annotations

import zlib

import pytest

from obst.conformance import (
    ConformanceError,
    StageConformanceCase,
    check_plugin_conformance,
    check_stage_conformance,
)
from obst.core import ExtensionDescriptor, ExtensionRegistry
from obst.core.extensions import ExtensionKind
from obst_defaults.codecs.raw import RawExtension
from obst_defaults.codecs.zlib import ZlibExtension
from obst_defaults.transforms.delta8 import Delta8Extension

_SPLIT_STAGE_ID = "org.example/split@1"
_SPLIT_DESCRIPTOR = ExtensionDescriptor(display_name="Split Stage")


class _SplitEncoder:
    extension_id = _SPLIT_STAGE_ID
    kind = ExtensionKind.STAGE
    descriptor = _SPLIT_DESCRIPTOR

    def bind_encoder(self, parameters: bytes, /) -> _SplitEncoder:
        assert parameters == b""
        return self

    def encode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        return data


class _SplitDecoder:
    extension_id = _SPLIT_STAGE_ID
    kind = ExtensionKind.STAGE
    descriptor = _SPLIT_DESCRIPTOR

    def bind_decoder(self, parameters: bytes, /) -> _SplitDecoder:
        assert parameters == b""
        return self

    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        return data


@pytest.mark.parametrize(
    ("extension", "case"),
    (
        (
            RawExtension(),
            StageConformanceCase(
                RawExtension.extension_id,
                b"",
                b"raw",
                b"raw",
                canonical_encoding=True,
            ),
        ),
        (
            Delta8Extension(),
            StageConformanceCase(
                Delta8Extension.extension_id,
                b"",
                b"\x01\x03\x06",
                b"\x01\x02\x03",
                canonical_encoding=True,
            ),
        ),
        (
            ZlibExtension(),
            StageConformanceCase(
                ZlibExtension.extension_id,
                b"\x06",
                b"portable known encoding",
                zlib.compress(b"portable known encoding", 6),
            ),
        ),
    ),
)
def test_stage_conformance_accepts_known_encodings(
    extension: RawExtension | Delta8Extension | ZlibExtension,
    case: StageConformanceCase,
) -> None:
    result = check_stage_conformance(extension, case)

    assert result.canonical_encoding_matched == (
        True if case.canonical_encoding else None
    )


def test_stage_conformance_rejects_a_different_stage_identity() -> None:
    case = StageConformanceCase("org.example/other@1", b"", b"x", b"x")

    with pytest.raises(ConformanceError, match="case names"):
        check_stage_conformance(RawExtension(), case)


def test_stage_conformance_rejects_wrong_known_output() -> None:
    case = StageConformanceCase(
        Delta8Extension.extension_id,
        b"",
        b"wrong",
        b"\x01\x02\x03",
    )

    with pytest.raises(ConformanceError, match="known encoding"):
        check_stage_conformance(Delta8Extension(), case)


def test_stage_conformance_rejects_wrong_canonical_encoding() -> None:
    logical = b"repeated bytes " * 64
    case = StageConformanceCase(
        ZlibExtension.extension_id,
        b"\x09",
        logical,
        zlib.compress(logical, 1),
        canonical_encoding=True,
    )

    with pytest.raises(ConformanceError, match="canonical encoding"):
        check_stage_conformance(ZlibExtension(), case)


def test_plugin_conformance_uses_complementary_providers_from_one_registry() -> None:
    registry = ExtensionRegistry((_SplitEncoder(), _SplitDecoder()))
    case = StageConformanceCase(
        _SPLIT_STAGE_ID,
        b"",
        b"split providers",
        b"split providers",
        canonical_encoding=True,
    )

    report = check_plugin_conformance("split", registry, (case,))

    assert report.passed

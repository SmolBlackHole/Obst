from __future__ import annotations

import json
import zlib
from pathlib import Path

import pytest
from scripts.build_plugin_conformance import (
    ADAPTIVE_ROOT,
    DEFAULTS_ROOT,
    build_adaptive_suite,
    build_default_suite,
)

from obst.conformance import (
    ConformanceError,
    ConformanceSuite,
    StageKnownAnswerCase,
    check_plugin_conformance,
    check_stage_conformance,
    load_conformance_suite,
    write_conformance_suite,
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
            StageKnownAnswerCase(
                "raw",
                RawExtension.extension_id,
                b"",
                b"raw",
                b"raw",
                canonical_encoding=True,
            ),
        ),
        (
            Delta8Extension(),
            StageKnownAnswerCase(
                "delta8",
                Delta8Extension.extension_id,
                b"",
                b"\x01\x03\x06",
                b"\x01\x02\x03",
                canonical_encoding=True,
            ),
        ),
        (
            ZlibExtension(),
            StageKnownAnswerCase(
                "zlib",
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
    case: StageKnownAnswerCase,
) -> None:
    check_stage_conformance(extension, case)


def test_stage_conformance_rejects_a_different_stage_identity() -> None:
    case = StageKnownAnswerCase(
        "other",
        "org.example/other@1",
        b"",
        b"x",
        b"x",
    )

    with pytest.raises(ConformanceError, match="case names"):
        check_stage_conformance(RawExtension(), case)


def test_stage_conformance_rejects_wrong_known_output() -> None:
    case = StageKnownAnswerCase(
        "wrong",
        Delta8Extension.extension_id,
        b"",
        b"wrong",
        b"\x01\x02\x03",
    )

    with pytest.raises(ConformanceError, match="known-answer"):
        check_stage_conformance(Delta8Extension(), case)


def test_stage_conformance_rejects_wrong_canonical_encoding() -> None:
    logical = b"repeated bytes " * 64
    case = StageKnownAnswerCase(
        "wrong-canonical",
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
    suite = ConformanceSuite(
        "split",
        (
            StageKnownAnswerCase(
                "split-known-answer",
                _SPLIT_STAGE_ID,
                b"",
                b"split providers",
                b"split providers",
                canonical_encoding=True,
            ),
        ),
    )

    report = check_plugin_conformance("split", registry, suite)

    assert report.passed


def test_repository_plugin_suites_are_reproducible(tmp_path: Path) -> None:
    for expected, checked_in in (
        (build_default_suite(), DEFAULTS_ROOT),
        (build_adaptive_suite(), ADAPTIVE_ROOT),
    ):
        generated = tmp_path / expected.plugin_name
        write_conformance_suite(expected, generated)
        expected_files = {
            path.relative_to(generated): path.read_bytes()
            for path in generated.rglob("*")
            if path.is_file()
        }
        checked_in_files = {
            path.relative_to(checked_in): path.read_bytes()
            for path in checked_in.rglob("*")
            if path.is_file()
        }
        assert checked_in_files == expected_files
        assert load_conformance_suite(checked_in) == expected


def test_suite_writer_removes_obsolete_vectors(tmp_path: Path) -> None:
    root = tmp_path / "suite"
    obsolete = root / "vectors" / "obsolete.hex"
    obsolete.parent.mkdir(parents=True)
    obsolete.write_text("00\n", encoding="ascii")

    write_conformance_suite(build_adaptive_suite(), root)

    assert not obsolete.exists()


def test_suite_loader_rejects_tampered_vector(tmp_path: Path) -> None:
    root = tmp_path / "suite"
    write_conformance_suite(build_adaptive_suite(), root)
    document = json.loads((root / "index.json").read_text(encoding="utf-8"))
    vector_path = Path(document["cases"][0]["encoded"]["path"])
    (root / vector_path).write_text("00\n", encoding="ascii")

    with pytest.raises(ValueError, match="wrong SHA-256"):
        load_conformance_suite(root)


def test_suite_requires_coverage_for_every_wire_visible_extension() -> None:
    registry = ExtensionRegistry((RawExtension(),))

    with pytest.raises(ConformanceError, match="does not cover Stage bytes"):
        check_plugin_conformance(
            "empty",
            registry,
            ConformanceSuite("empty", ()),
        )

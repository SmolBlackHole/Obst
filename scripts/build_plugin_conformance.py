"""Build deterministic portable conformance suites shipped by repository plugins."""

from __future__ import annotations

import zlib
from pathlib import Path

from obst.conformance import (
    ConformanceSuite,
    StageBindRejectionCase,
    StageDecodeRejectionCase,
    StageKnownAnswerCase,
    StageOutputLimitCase,
    StageParametersCase,
    StreamMetadataCase,
    StreamMetadataRejectionCase,
    write_conformance_suite,
)
from obst.core import InspectionField, InspectionInterpretation

ROOT = Path(__file__).parents[1]
DEFAULTS_ROOT = (
    ROOT / "plugins" / "defaults" / "src" / "obst_defaults" / "conformance_vectors"
)
ADAPTIVE_ROOT = (
    ROOT
    / "examples"
    / "plugin_adaptive_zlib"
    / "src"
    / "obst_example_adaptive_zlib"
    / "conformance_vectors"
)

_ZLIB_LOGICAL = b"portable known encoding"
_ZLIB_ENCODED = bytes.fromhex(
    "789c2bc82f2a494cca4955c8cecb2fcf5348cd4bce4fc9cc4b07006d70090e"
)
_ZLIB_DICTIONARY = b"portable "
_ZLIB_DICTIONARY_LOGICAL = b"portable portable portable"
_ZLIB_DICTIONARY_ENCODED = bytes.fromhex("78bb12e2037a2bc0c900008bfd0a4c")
_ADAPTIVE_PARAMETERS = b"\x06\x07\x00"
_ADAPTIVE_LOGICAL = b"A0A1B0B1C0C1!"
_ADAPTIVE_ENCODED = bytes.fromhex("0100789c737474727276363004414500158002d1")
_ADAPTIVE_DICTIONARY_PARAMETERS = bytes.fromhex("060001000d73656e736f723a76616c75653d")
_ADAPTIVE_DICTIONARY_LOGICAL = b"sensor:value=100\nsensor:value=101\n"
_ADAPTIVE_DICTIONARY_ENCODED = bytes.fromhex(
    "000178bb25a4052f2b46e6181a1870a10918720100da970b94"
)


def build_default_suite() -> ConformanceSuite:
    """Return the static corpus owned by the first-party Extension contracts."""
    return ConformanceSuite(
        "obst-defaults",
        (
            StageKnownAnswerCase(
                "raw-known-answer",
                "obst.raw@1",
                b"",
                b"OBST raw conformance",
                b"OBST raw conformance",
                True,
            ),
            StageKnownAnswerCase(
                "raw-empty",
                "obst.raw@1",
                b"",
                b"",
                b"",
                True,
            ),
            StageBindRejectionCase(
                "raw-parameters-rejected",
                "obst.raw@1",
                b"\x00",
                ("encode", "decode"),
            ),
            StageOutputLimitCase(
                "raw-encode-limit",
                "obst.raw@1",
                "encode",
                b"",
                b"x",
                0,
            ),
            StageOutputLimitCase(
                "raw-decode-limit",
                "obst.raw@1",
                "decode",
                b"",
                b"x",
                0,
            ),
            StageKnownAnswerCase(
                "delta8-known-answer",
                "obst.delta8@1",
                b"",
                b"\x01\x03\x06",
                b"\x01\x02\x03",
                True,
            ),
            StageKnownAnswerCase(
                "delta8-empty",
                "obst.delta8@1",
                b"",
                b"",
                b"",
                True,
            ),
            StageBindRejectionCase(
                "delta8-parameters-rejected",
                "obst.delta8@1",
                b"\x00",
                ("encode", "decode"),
            ),
            StageOutputLimitCase(
                "delta8-encode-limit",
                "obst.delta8@1",
                "encode",
                b"",
                b"x",
                0,
            ),
            StageOutputLimitCase(
                "delta8-decode-limit",
                "obst.delta8@1",
                "decode",
                b"",
                b"x",
                0,
            ),
            StageKnownAnswerCase(
                "zlib-known-answer",
                "obst.zlib@1",
                b"\x06",
                _ZLIB_LOGICAL,
                _ZLIB_ENCODED,
            ),
            StageKnownAnswerCase(
                "zlib-empty",
                "obst.zlib@1",
                b"\x06",
                b"",
                bytes.fromhex("789c030000000001"),
            ),
            StageParametersCase(
                "zlib-parameters",
                "obst.zlib@1",
                b"\x06",
                InspectionInterpretation(
                    fields=(InspectionField("compression_level", 6),)
                ),
            ),
            StageBindRejectionCase(
                "zlib-parameters-rejected",
                "obst.zlib@1",
                b"\x0a",
                ("encode", "decode"),
            ),
            StageDecodeRejectionCase(
                "zlib-payload-rejected",
                "obst.zlib@1",
                b"\x06",
                b"\x78\x9c",
                1024,
            ),
            StageOutputLimitCase(
                "zlib-encode-limit",
                "obst.zlib@1",
                "encode",
                b"\x06",
                b"x",
                0,
            ),
            StageOutputLimitCase(
                "zlib-decode-limit",
                "obst.zlib@1",
                "decode",
                b"\x06",
                _ZLIB_ENCODED,
                0,
            ),
            StageKnownAnswerCase(
                "zlib-dictionary-known-answer",
                "obst.zlib@2",
                b"\x06" + _ZLIB_DICTIONARY,
                _ZLIB_DICTIONARY_LOGICAL,
                _ZLIB_DICTIONARY_ENCODED,
            ),
            StageParametersCase(
                "zlib-dictionary-parameters",
                "obst.zlib@2",
                b"\x06" + _ZLIB_DICTIONARY,
                InspectionInterpretation(
                    fields=(
                        InspectionField("compression_level", 6),
                        InspectionField("dictionary_size", len(_ZLIB_DICTIONARY)),
                        InspectionField(
                            "dictionary_adler32",
                            f"{zlib.adler32(_ZLIB_DICTIONARY) & 0xFFFFFFFF:08x}",
                        ),
                    )
                ),
            ),
            StageBindRejectionCase(
                "zlib-dictionary-parameters-rejected",
                "obst.zlib@2",
                b"\x06",
                ("encode", "decode"),
            ),
            StageDecodeRejectionCase(
                "zlib-dictionary-payload-rejected",
                "obst.zlib@2",
                b"\x06" + _ZLIB_DICTIONARY,
                _ZLIB_DICTIONARY_ENCODED[:-1],
                1024,
            ),
            StageOutputLimitCase(
                "zlib-dictionary-encode-limit",
                "obst.zlib@2",
                "encode",
                b"\x06" + _ZLIB_DICTIONARY,
                b"portable",
                0,
            ),
            StageOutputLimitCase(
                "zlib-dictionary-decode-limit",
                "obst.zlib@2",
                "decode",
                b"\x06" + _ZLIB_DICTIONARY,
                _ZLIB_DICTIONARY_ENCODED,
                0,
            ),
            StreamMetadataCase(
                "file-metadata",
                "obst.file@1",
                b"README.md",
                InspectionInterpretation(
                    label="README.md",
                    fields=(InspectionField("name", "README.md"),),
                ),
            ),
            StreamMetadataRejectionCase(
                "file-path-rejected",
                "obst.file@1",
                b"../escape",
                True,
            ),
            StreamMetadataRejectionCase(
                "file-bidi-rejected",
                "obst.file@1",
                "safe\u202eevil.txt".encode(),
                True,
            ),
        ),
    )


def build_adaptive_suite() -> ConformanceSuite:
    """Return the static corpus owned by the third-party example contract."""
    return ConformanceSuite(
        "adaptive-zlib",
        (
            StageKnownAnswerCase(
                "adaptive-known-answer",
                "org.example/adaptive-zlib@1",
                _ADAPTIVE_PARAMETERS,
                _ADAPTIVE_LOGICAL,
                _ADAPTIVE_ENCODED,
            ),
            StageKnownAnswerCase(
                "adaptive-dictionary-known-answer",
                "org.example/adaptive-zlib@1",
                _ADAPTIVE_DICTIONARY_PARAMETERS,
                _ADAPTIVE_DICTIONARY_LOGICAL,
                _ADAPTIVE_DICTIONARY_ENCODED,
            ),
            StageParametersCase(
                "adaptive-parameters",
                "org.example/adaptive-zlib@1",
                _ADAPTIVE_PARAMETERS,
                InspectionInterpretation(
                    label="level 6; 4 layouts; 0 dictionaries",
                    fields=(
                        InspectionField("compression_level", 6),
                        InspectionField("shuffle_widths", "1,2,4,8"),
                        InspectionField("dictionary_count", 0),
                        InspectionField("dictionary_bytes", 0),
                        InspectionField("dictionary_adler32", None),
                    ),
                ),
            ),
            StageBindRejectionCase(
                "adaptive-parameters-rejected",
                "org.example/adaptive-zlib@1",
                b"",
                ("encode", "decode"),
            ),
            StageDecodeRejectionCase(
                "adaptive-payload-rejected",
                "org.example/adaptive-zlib@1",
                _ADAPTIVE_PARAMETERS,
                b"\x00",
                1024,
            ),
            StageOutputLimitCase(
                "adaptive-encode-limit",
                "org.example/adaptive-zlib@1",
                "encode",
                _ADAPTIVE_PARAMETERS,
                b"x",
                0,
            ),
            StageOutputLimitCase(
                "adaptive-decode-limit",
                "org.example/adaptive-zlib@1",
                "decode",
                _ADAPTIVE_PARAMETERS,
                _ADAPTIVE_ENCODED,
                0,
            ),
        ),
    )


def main() -> None:
    """Regenerate every plugin-owned suite checked into this repository."""
    write_conformance_suite(build_default_suite(), DEFAULTS_ROOT)
    write_conformance_suite(build_adaptive_suite(), ADAPTIVE_ROOT)


if __name__ == "__main__":
    main()

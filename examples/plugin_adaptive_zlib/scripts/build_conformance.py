# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Build the deterministic suite shipped by the adaptive-zlib example."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

from obst.conformance import (
    ConformanceSuite,
    StageBindRejectionCase,
    StageDecodeRejectionCase,
    StageKnownAnswerCase,
    StageOutputLimitCase,
    StageParametersCase,
    write_conformance_suite,
)
from obst.core import InspectionField, InspectionInterpretation

ROOT = Path(__file__).parents[1]
CONFORMANCE_ROOT = ROOT / "src" / "obst_example_adaptive_zlib" / "conformance_vectors"

_PARAMETERS = b"\x06\x07\x00"
_LOGICAL = b"A0A1B0B1C0C1!"
_ENCODED = bytes.fromhex("0100789c737474727276363004414500158002d1")
_DICTIONARY_PARAMETERS = bytes.fromhex("060001000d73656e736f723a76616c75653d")
_DICTIONARY_LOGICAL = b"sensor:value=100\nsensor:value=101\n"
_DICTIONARY_ENCODED = bytes.fromhex(
    "000178bb25a4052f2b46e6181a1870a10918720100da970b94"
)


def build_suite() -> ConformanceSuite:
    """Return the static corpus owned by the adaptive-zlib contract."""
    return ConformanceSuite(
        (
            StageKnownAnswerCase(
                "adaptive-known-answer",
                "org.example/adaptive-zlib@1",
                _PARAMETERS,
                _LOGICAL,
                _ENCODED,
            ),
            StageKnownAnswerCase(
                "adaptive-dictionary-known-answer",
                "org.example/adaptive-zlib@1",
                _DICTIONARY_PARAMETERS,
                _DICTIONARY_LOGICAL,
                _DICTIONARY_ENCODED,
            ),
            StageParametersCase(
                "adaptive-parameters",
                "org.example/adaptive-zlib@1",
                _PARAMETERS,
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
                _PARAMETERS,
                b"\x00",
                1024,
            ),
            StageOutputLimitCase(
                "adaptive-encode-limit",
                "org.example/adaptive-zlib@1",
                "encode",
                _PARAMETERS,
                b"x",
                0,
            ),
            StageOutputLimitCase(
                "adaptive-decode-limit",
                "org.example/adaptive-zlib@1",
                "decode",
                _PARAMETERS,
                _ENCODED,
                0,
            ),
        ),
    )


def main() -> None:
    """Regenerate the adaptive-zlib-owned suite."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=CONFORMANCE_ROOT,
        help="catalog directory to regenerate",
    )
    output = cast(Path, parser.parse_args().output)
    write_conformance_suite(build_suite(), output)


if __name__ == "__main__":
    main()

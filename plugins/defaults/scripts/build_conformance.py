# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Build the deterministic suite shipped by the defaults plugin."""

from __future__ import annotations

import argparse
import io
import zlib
from pathlib import Path
from typing import cast

from obst.conformance import (
    ConformanceSuite,
    ContainerRecoveryCase,
    RecoveredStreamExpectation,
    StageBindRejectionCase,
    StageDecodeRejectionCase,
    StageKnownAnswerCase,
    StageOutputLimitCase,
    StageParametersCase,
    StreamMetadataCase,
    StreamMetadataRejectionCase,
    write_conformance_suite,
)
from obst.core import (
    DEFAULT_RESOURCE_POLICY,
    ContainerWriter,
    ExtensionRegistry,
    InspectionField,
    InspectionInterpretation,
    Manifest,
    Recipe,
    ResourceAccounting,
    StageSpec,
    Stream,
    encode_chunk_once,
)

from obst_defaults.bundle import obst_extensions
from obst_defaults.codecs.zlib import ZlibExtension, ZlibParameters
from obst_defaults.files import FileExtension

ROOT = Path(__file__).parents[1]
CONFORMANCE_ROOT = ROOT / "src" / "obst_defaults" / "conformance_vectors"

_ZLIB_LOGICAL = b"portable known encoding"
_ZLIB_ENCODED = bytes.fromhex(
    "789c2bc82f2a494cca4955c8cecb2fcf5348cd4bce4fc9cc4b07006d70090e"
)
_ZLIB_DICTIONARY = b"portable "
_ZLIB_DICTIONARY_LOGICAL = b"portable portable portable"
_ZLIB_DICTIONARY_ENCODED = bytes.fromhex("78bb12e2037a2bc0c900008bfd0a4c")


def _container_recovery_case() -> ContainerRecoveryCase:
    logical = b"complete defaults-owned recovery vector"
    zlib_extension = ZlibExtension()
    file_extension = FileExtension()
    recipe = Recipe(
        0,
        (
            StageSpec(
                zlib_extension.extension_id,
                zlib_extension.encode_parameters(ZlibParameters(6)),
            ),
        ),
    )
    manifest = Manifest(
        recipes=(recipe,),
        streams=(
            Stream(
                0,
                file_extension.extension_id,
                0,
                file_extension.encode_file_name("conformance.bin"),
            ),
        ),
    )
    target = io.BytesIO()
    accounting = ResourceAccounting(DEFAULT_RESOURCE_POLICY)
    writer = ContainerWriter(target, manifest, accounting=accounting)
    writer.write_chunk(
        encode_chunk_once(
            logical,
            stream_id=0,
            sequence=0,
            recipe=recipe,
            registry=ExtensionRegistry(obst_extensions()),
            accounting=accounting,
        )
    )
    writer.finish()
    return ContainerRecoveryCase(
        "defaults-container-recovery",
        target.getvalue(),
        (zlib_extension.extension_id,),
        (RecoveredStreamExpectation(0, logical),),
    )


def build_default_suite() -> ConformanceSuite:
    """Return the static corpus owned by the first-party Extension contracts."""
    return ConformanceSuite(
        (
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
            _container_recovery_case(),
        ),
    )


def main() -> None:
    """Regenerate the defaults-owned suite."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=CONFORMANCE_ROOT,
        help="catalog directory to regenerate",
    )
    output = cast(Path, parser.parse_args().output)
    write_conformance_suite(build_default_suite(), output)


if __name__ == "__main__":
    main()

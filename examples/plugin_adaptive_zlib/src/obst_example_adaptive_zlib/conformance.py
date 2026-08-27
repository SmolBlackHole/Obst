"""Portable known-answer cases for the adaptive-zlib contract."""

from __future__ import annotations

from obst_example_adaptive_zlib.extension import AdaptiveZlibExtension

from obst.conformance import StageConformanceCase


def adaptive_zlib_conformance() -> tuple[StageConformanceCase, ...]:
    """Return fixed decodings without requiring one canonical encoder choice."""
    return (
        StageConformanceCase(
            stage_id=AdaptiveZlibExtension.extension_id,
            parameters=b"\x06\x07\x00",
            logical=b"A0A1B0B1C0C1!",
            encoded=bytes.fromhex("0100789c737474727276363004414500158002d1"),
            canonical_encoding=False,
        ),
        StageConformanceCase(
            stage_id=AdaptiveZlibExtension.extension_id,
            parameters=bytes.fromhex("060001000d73656e736f723a76616c75653d"),
            logical=b"sensor:value=100\nsensor:value=101\n",
            encoded=bytes.fromhex("000178bb25a4052f2b46e6181a1870a10918720100da970b94"),
            canonical_encoding=False,
        ),
    )


__all__ = ["adaptive_zlib_conformance"]

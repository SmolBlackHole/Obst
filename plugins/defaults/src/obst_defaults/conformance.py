"""Portable known-answer cases owned by the first-party Stage contracts."""

from __future__ import annotations

from obst.conformance import StageConformanceCase


def obst_conformance() -> tuple[StageConformanceCase, ...]:
    """Return portable cases for every Stage contract in this plugin."""
    return (
        StageConformanceCase(
            stage_id="obst.raw@1",
            parameters=b"",
            logical=b"OBST raw conformance",
            encoded=b"OBST raw conformance",
            canonical_encoding=True,
        ),
        StageConformanceCase(
            stage_id="obst.delta8@1",
            parameters=b"",
            logical=b"\x01\x03\x06",
            encoded=b"\x01\x02\x03",
            canonical_encoding=True,
        ),
        StageConformanceCase(
            stage_id="obst.zlib@1",
            parameters=b"\x06",
            logical=b"portable known encoding",
            encoded=bytes.fromhex(
                "789c2bc82f2a494cca4955c8cecb2fcf5348cd4bce4fc9cc4b07006d70090e"
            ),
        ),
        StageConformanceCase(
            stage_id="obst.zlib@2",
            parameters=b"\x06portable ",
            logical=b"portable portable portable",
            encoded=bytes.fromhex("78bb12e2037a2bc0c900008bfd0a4c"),
        ),
    )


__all__ = ["obst_conformance"]

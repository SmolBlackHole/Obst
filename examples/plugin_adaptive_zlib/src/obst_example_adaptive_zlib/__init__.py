"""Installable example of a self-describing adaptive OBST plugin."""

from __future__ import annotations

from obst_example_adaptive_zlib.commands import (
    AdaptivePackCommand,
    obst_commands,
)
from obst_example_adaptive_zlib.conformance import adaptive_zlib_conformance
from obst_example_adaptive_zlib.extension import (
    AdaptiveZlibExtension,
    AdaptiveZlibParameters,
)

from obst.conformance import StageConformanceCase
from obst.core import Extension


def obst_extensions() -> tuple[Extension, ...]:
    """Return every extension exported by this installed plugin."""
    return (AdaptiveZlibExtension(),)


def obst_conformance() -> tuple[StageConformanceCase, ...]:
    """Return portable cases published by this plugin."""
    return adaptive_zlib_conformance()


__all__ = [
    "AdaptivePackCommand",
    "AdaptiveZlibExtension",
    "AdaptiveZlibParameters",
    "obst_commands",
    "obst_conformance",
    "obst_extensions",
]

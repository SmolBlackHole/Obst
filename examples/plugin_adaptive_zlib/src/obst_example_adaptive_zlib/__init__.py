# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Installable example of a self-describing adaptive OBST plugin."""

from __future__ import annotations

from obst.core import Extension

from obst_example_adaptive_zlib.commands import (
    AdaptivePackCommand,
    obst_commands,
)
from obst_example_adaptive_zlib.conformance import obst_conformance
from obst_example_adaptive_zlib.extension import (
    AdaptiveZlibExtension,
    AdaptiveZlibParameters,
)


def obst_extensions() -> tuple[Extension, ...]:
    """Return every extension exported by this installed plugin."""
    return (AdaptiveZlibExtension(),)


__all__ = [
    "AdaptivePackCommand",
    "AdaptiveZlibExtension",
    "AdaptiveZlibParameters",
    "obst_commands",
    "obst_conformance",
    "obst_extensions",
]

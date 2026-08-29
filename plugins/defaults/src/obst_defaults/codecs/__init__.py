# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Shipped reversible codec extensions."""

from obst_defaults.codecs.zlib import (
    ZlibDictionaryExtension,
    ZlibDictionaryParameters,
    ZlibExtension,
    ZlibParameters,
)

__all__ = [
    "ZlibDictionaryExtension",
    "ZlibDictionaryParameters",
    "ZlibExtension",
    "ZlibParameters",
]

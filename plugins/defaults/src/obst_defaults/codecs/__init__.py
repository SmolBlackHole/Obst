"""Shipped reversible codec extensions."""

from obst_defaults.codecs.raw import RawExtension
from obst_defaults.codecs.zlib import (
    ZlibDictionaryExtension,
    ZlibDictionaryParameters,
    ZlibExtension,
    ZlibParameters,
)

__all__ = [
    "RawExtension",
    "ZlibDictionaryExtension",
    "ZlibDictionaryParameters",
    "ZlibExtension",
    "ZlibParameters",
]

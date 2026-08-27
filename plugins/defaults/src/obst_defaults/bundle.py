"""Ordinary plugin factory for the extensions shipped by this distribution."""

from __future__ import annotations

from obst.core import Extension
from obst_defaults.carriers.filesystem import FilesystemCarrierExtension
from obst_defaults.carriers.memory import MemoryCarrierExtension
from obst_defaults.carriers.stdin import StdinCarrierExtension
from obst_defaults.codecs.raw import RawExtension
from obst_defaults.codecs.zlib import ZlibDictionaryExtension, ZlibExtension
from obst_defaults.files import FileExtension
from obst_defaults.packagers.fixed import FixedPackagerExtension
from obst_defaults.transforms.delta8 import Delta8Extension


def obst_extensions() -> tuple[Extension, ...]:
    """Return every registry extension shipped by this distribution."""
    return (
        RawExtension(),
        ZlibExtension(),
        ZlibDictionaryExtension(),
        Delta8Extension(),
        FileExtension(),
        FilesystemCarrierExtension(),
        MemoryCarrierExtension(),
        StdinCarrierExtension(),
        FixedPackagerExtension(),
    )


__all__ = ["obst_extensions"]

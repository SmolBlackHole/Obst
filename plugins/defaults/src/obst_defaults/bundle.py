# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Ordinary plugin factory for the extensions shipped by this distribution."""

from __future__ import annotations

from obst.core import Extension
from obst.resources import ResourceContribution

from obst_defaults.carriers.filesystem import FilesystemCarrierExtension
from obst_defaults.carriers.memory import MemoryCarrierExtension
from obst_defaults.carriers.stdin import StdinCarrierExtension
from obst_defaults.codecs.zlib import ZlibDictionaryExtension, ZlibExtension
from obst_defaults.files import FileExtension, FileResource
from obst_defaults.packagers.fixed import FixedPackagerExtension
from obst_defaults.transforms.delta8 import Delta8Extension


def obst_extensions() -> tuple[Extension, ...]:
    """Return every registry extension shipped by this distribution."""
    return (
        ZlibExtension(),
        ZlibDictionaryExtension(),
        Delta8Extension(),
        FileExtension(),
        FilesystemCarrierExtension(),
        MemoryCarrierExtension(),
        StdinCarrierExtension(),
        FixedPackagerExtension(),
    )


def obst_resources() -> ResourceContribution:
    """Return portable-file resources through the ordinary plugin path."""
    return ResourceContribution(tuple(FileResource))


__all__ = ["obst_extensions", "obst_resources"]

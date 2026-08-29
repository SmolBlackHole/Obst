# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Typed resources owned by the portable-file tooling."""

from obst.resources import (
    ResourceAggregation,
    ResourceDefinition,
    ResourceKind,
    ResourceUnit,
)

_GIB = 1024 * 1024 * 1024


class FileResource(ResourceKind):
    """Local resources measured while adapting portable file streams."""

    ARCHIVE_MEMBERS = ResourceDefinition(
        "obst.file@1/archive_members",
        4_096,
        "Files restored by one extraction operation.",
        ResourceUnit.COUNT,
        ResourceAggregation.TOTAL,
    )
    ARCHIVE_MEMBER_BYTES = ResourceDefinition(
        "obst.file@1/archive_member_bytes",
        4 * _GIB,
        "Logical bytes restored for one file.",
        ResourceUnit.BYTES,
        ResourceAggregation.PEAK,
    )
    ARCHIVE_TOTAL_BYTES = ResourceDefinition(
        "obst.file@1/archive_total_bytes",
        16 * _GIB,
        "Logical file bytes restored by one extraction operation.",
        ResourceUnit.BYTES,
        ResourceAggregation.TOTAL,
    )


__all__ = ["FileResource"]

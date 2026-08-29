# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""OBST package metadata. Public operations live in :mod:`obst.core`."""

from obst.core.wire import FormatVersion, format_version

__all__ = [
    "FormatVersion",
    "format_version",
]

# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""First-party packaging-policy extensions."""

from obst_defaults.packagers.fixed import (
    FixedPackageRequest,
    FixedPackagerExtension,
)

__all__ = [
    "FixedPackageRequest",
    "FixedPackagerExtension",
]

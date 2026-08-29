# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Typed resource-policy fixtures owned by the defaults plugin tests."""

from __future__ import annotations

from obst.core import CoreResource, ResourceAccounting
from obst.resources import LimitProfile, ResourceKind, ResourcePolicy

from obst_defaults.files import FileResource


def policy(*overrides: tuple[ResourceKind, int | None]) -> ResourcePolicy:
    """Build one test-only policy containing Core and defaults resources."""
    return ResourcePolicy(
        tuple(CoreResource) + tuple(FileResource),
        LimitProfile(
            "test",
            "Test-only Core and defaults resource ceilings.",
            overrides,
        ),
    )


def accounting(*overrides: tuple[ResourceKind, int | None]) -> ResourceAccounting:
    """Build one explicit test-only Core and defaults accountant."""
    return ResourceAccounting(policy(*overrides))

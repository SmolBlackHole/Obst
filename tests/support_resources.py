"""Typed resource-policy fixtures shared by Core tests."""

from __future__ import annotations

from obst.core import CoreResource, ResourceAccounting
from obst.resources import LimitProfile, ResourceKind, ResourcePolicy


def policy(*overrides: tuple[ResourceKind, int | None]) -> ResourcePolicy:
    """Build one test-only named policy from typed resource overrides."""
    return ResourcePolicy(
        tuple(CoreResource),
        profile=LimitProfile(
            "test",
            "Test-only resource ceilings.",
            overrides,
        ),
    )


def accounting(*overrides: tuple[ResourceKind, int | None]) -> ResourceAccounting:
    """Build one explicit test-only operation accountant."""
    return ResourceAccounting(policy(*overrides))

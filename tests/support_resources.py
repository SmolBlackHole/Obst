"""Typed resource-policy fixtures shared by Core tests."""

from __future__ import annotations

from obst.core import LimitProfile, ResourceKind, ResourcePolicy


def policy(*overrides: tuple[ResourceKind, int | None]) -> ResourcePolicy:
    """Build one test-only named policy from typed resource overrides."""
    return ResourcePolicy(
        profile=LimitProfile(
            "test",
            "Test-only resource ceilings.",
            overrides,
        )
    )

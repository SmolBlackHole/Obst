"""Typed resource-policy fixtures owned by the defaults plugin tests."""

from __future__ import annotations

from obst.core import CoreResource, LimitProfile, ResourceKind, ResourcePolicy

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

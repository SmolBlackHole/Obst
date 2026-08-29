# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Replaceable runtime adapters for publishing OBST byte streams."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from obst.core.errors import ObstError
from obst.core.extensions import BoundCarrierPublisher, BoundCarrierWriter
from obst.core.packaging import PackageResult, PackageWriteOperation


class CarrierError(ObstError):
    """A carrier endpoint could not open, commit, abort or publish safely."""


class CarrierStateError(CarrierError):
    """A carrier operation was invoked in an invalid lifecycle state."""

    def __init__(self, operation: str, state: str) -> None:
        self.operation = operation
        self.state = state
        super().__init__(f"cannot {operation} carrier in {state} state")


@dataclass(frozen=True, slots=True)
class PublicationCleanupIssue:
    """One residual resource left after a successful publication."""

    resource: str
    reason: str


@dataclass(frozen=True, slots=True)
class PublicationReceipt[Reference]:
    """Carrier-owned reference produced by a successful commit."""

    reference: Reference
    cleanup_issues: tuple[PublicationCleanupIssue, ...]


@dataclass(frozen=True, slots=True)
class PublishedPackage[Publication]:
    """One carrier-neutral package paired with its committed publication."""

    package: PackageResult
    publication: Publication


@dataclass(frozen=True, slots=True)
class WrittenPackage[Result]:
    """One carrier-neutral package paired with streaming completion data."""

    package: PackageResult
    completion: Result


def write_package[Result](
    operation: PackageWriteOperation,
    carrier: BoundCarrierWriter[Result],
) -> WrittenPackage[Result]:
    """Write through a progressively visible carrier and always release it."""
    try:
        target = carrier.open()
        package = operation.write_to(target)
        completion = carrier.finish()
    except BaseException as error:
        try:
            carrier.close()
        except BaseException as close_error:
            error.add_note(f"carrier close also failed: {close_error}")
        raise
    carrier.close()
    return WrittenPackage(package, completion)


def publish_package[Publication](
    operation: PackageWriteOperation,
    carrier: BoundCarrierPublisher[Publication],
) -> PublishedPackage[Publication]:
    """Package to one carrier and commit only after successful completion."""
    try:
        target = carrier.open()
        package = operation.write_to(target)
        publication = carrier.commit()
    except BaseException as error:
        try:
            carrier.abort()
        except BaseException as abort_error:
            error.add_note(f"carrier abort also failed: {abort_error}")
        raise
    return PublishedPackage(package, publication)


class CarrierLifecycleState(Enum):
    NEW = auto()
    OPEN = auto()
    CLEANUP_REQUIRED = auto()
    COMMITTED = auto()
    ABORTED = auto()
    CLOSED = auto()


def require_carrier_state(
    actual: CarrierLifecycleState,
    expected: CarrierLifecycleState,
    *,
    operation: str,
) -> None:
    if actual is not expected:
        raise CarrierStateError(operation, actual.name.lower())


__all__ = [
    "CarrierError",
    "CarrierStateError",
    "PublicationCleanupIssue",
    "PublicationReceipt",
    "PublishedPackage",
    "WrittenPackage",
    "publish_package",
    "write_package",
]

"""Internal cleanup rules shared by first-party adapters."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class Closable(Protocol):
    def close(self) -> None: ...


def close_all(
    resources: Iterable[tuple[str, Closable]],
    *,
    primary_error: BaseException | None,
) -> None:
    """Attempt every close while retaining the operation's primary failure."""
    first_error = primary_error
    for label, resource in resources:
        try:
            resource.close()
        except BaseException as close_error:
            if first_error is None:
                first_error = close_error
            else:
                first_error.add_note(f"failed to close {label}: {close_error}")
    if primary_error is None and first_error is not None:
        raise first_error


__all__ = ["close_all"]

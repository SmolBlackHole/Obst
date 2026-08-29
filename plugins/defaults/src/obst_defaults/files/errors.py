# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Errors owned by the first-party portable-file feature."""

from obst.core.errors import ObstError


class FileProfileError(ObstError):
    """A file profile cannot validate or reconstruct its local value."""

    def __init__(self, profile_id: str, reason: str) -> None:
        self.profile_id = profile_id
        self.reason = reason
        super().__init__(f"{profile_id}: {reason}")


class FileArchiveError(ObstError):
    """The regular-file adapter cannot compose or publish the requested files."""


__all__ = ["FileArchiveError", "FileProfileError"]

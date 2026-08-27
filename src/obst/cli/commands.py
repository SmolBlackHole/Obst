"""Public contracts for plugin-contributed OBST CLI commands."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Protocol, TextIO

from obst.core.errors import ObstError
from obst.core.io import BinaryReader
from obst.core.registry import ExtensionRegistry
from obst.core.resources import ResourceLimits

EXIT_SUCCESS = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_INVALID_CONTAINER = 3
EXIT_UNSUPPORTED = 4
EXIT_IO = 5
EXIT_PIPELINE = 6
EXIT_RESOURCE_LIMIT = 10
EXIT_PLUGIN = 11


class CliCommandError(ObstError):
    """A contributed command mapped a domain failure to the CLI contract."""

    def __init__(self, kind: str, exit_code: int, cause: BaseException) -> None:
        self.kind = kind
        self.exit_code = exit_code
        self.cause = cause
        super().__init__(str(cause))


@dataclass(frozen=True, slots=True)
class CliContext:
    """Operation-local services supplied by the generic CLI host."""

    registry: ExtensionRegistry
    plugin_names: tuple[str, ...]
    stdin: BinaryReader
    stdout: TextIO
    stderr: TextIO
    limits: ResourceLimits


class CliCommand(Protocol):
    """One command contributed by an explicitly activated plugin."""

    name: str
    summary: str

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        """Declare this command's arguments on its host-owned parser."""
        ...

    def run(self, args: argparse.Namespace, context: CliContext) -> int:
        """Execute the parsed command and return a process exit code."""
        ...


__all__ = [
    "EXIT_INTERNAL",
    "EXIT_INVALID_CONTAINER",
    "EXIT_IO",
    "EXIT_PIPELINE",
    "EXIT_PLUGIN",
    "EXIT_RESOURCE_LIMIT",
    "EXIT_SUCCESS",
    "EXIT_UNSUPPORTED",
    "EXIT_USAGE",
    "CliCommand",
    "CliCommandError",
    "CliContext",
]

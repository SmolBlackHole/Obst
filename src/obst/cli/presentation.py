"""Shared safe presentation primitives for host and plugin CLI commands."""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass
from typing import TextIO

_BIDI_CONTROL_CHARACTERS = frozenset(
    {
        "\u061c",  # Arabic letter mark
        "\u200e",  # Left-to-right mark
        "\u200f",  # Right-to-left mark
        "\u202a",  # Left-to-right embedding
        "\u202b",  # Right-to-left embedding
        "\u202c",  # Pop directional formatting
        "\u202d",  # Left-to-right override
        "\u202e",  # Right-to-left override
        "\u2066",  # Left-to-right isolate
        "\u2067",  # Right-to-left isolate
        "\u2068",  # First strong isolate
        "\u2069",  # Pop directional isolate
    }
)
_UNSAFE_HUMAN_CATEGORIES = frozenset({"Cc", "Cs"})
_UNSAFE_HUMAN_SEPARATORS = frozenset({"\u2028", "\u2029"})


@dataclass(frozen=True, slots=True)
class HumanOutputStyle:
    """Optional ANSI presentation selected from one concrete text stream."""

    color: bool = False

    @classmethod
    def for_stream(cls, stream: TextIO) -> HumanOutputStyle:
        """Enable color only for an interactive terminal that permits it."""
        if "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb":
            return cls()
        force_color = os.environ.get("FORCE_COLOR")
        if force_color is not None and force_color not in {"", "0"}:
            return cls(color=True)
        try:
            return cls(color=stream.isatty())
        except AttributeError, OSError:
            return cls()

    def title(self, value: str) -> str:
        return self._apply(value, "1;36")

    def heading(self, value: str) -> str:
        return self._apply(value, "1;36")

    def identifier(self, value: str) -> str:
        return self._apply(value, "36")

    def success(self, value: str) -> str:
        return self._apply(value, "32")

    def warning(self, value: str) -> str:
        return self._apply(value, "33")

    def error(self, value: str) -> str:
        return self._apply(value, "31")

    def muted(self, value: str) -> str:
        return self._apply(value, "2")

    def fruit(self, value: str) -> str:
        """Render the fruit body of the OBST mark."""
        return self._apply(value, "31")

    def leaf(self, value: str) -> str:
        """Render the leaf of the OBST mark."""
        return self._apply(value, "32")

    def stem(self, value: str) -> str:
        """Render the stem of the OBST mark."""
        return self._apply(value, "90")

    def field(
        self,
        label: str,
        value: str,
        *,
        label_width: int = 15,
    ) -> str:
        """Format one indented label/value row with stable visible alignment."""
        return f"  {self.muted(label.ljust(label_width))} {value}"

    def _apply(self, value: str, code: str) -> str:
        if not self.color:
            return value
        return f"\x1b[{code}m{value}\x1b[0m"


PLAIN_HUMAN_OUTPUT = HumanOutputStyle()


def escape_human_text(value: object) -> str:
    """Escape terminal controls without hiding ordinary Unicode text."""
    text = str(value)
    return "".join(_escape_human_character(character) for character in text)


def format_size(size: int) -> str:
    """Format one non-negative byte size for human output."""
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            if unit == "B":
                return f"{size} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def format_count(count: int, singular: str, plural: str | None = None) -> str:
    """Format one count with its singular or plural noun."""
    noun = singular if count == 1 else plural or f"{singular}s"
    return f"{count} {noun}"


def _escape_human_character(character: str) -> str:
    if (
        character not in _BIDI_CONTROL_CHARACTERS
        and character not in _UNSAFE_HUMAN_SEPARATORS
        and unicodedata.category(character) not in _UNSAFE_HUMAN_CATEGORIES
    ):
        return character
    codepoint = ord(character)
    if codepoint <= 0xFFFF:
        return f"\\u{codepoint:04x}"
    return f"\\U{codepoint:08x}"


__all__ = [
    "HumanOutputStyle",
    "escape_human_text",
    "format_count",
    "format_size",
]

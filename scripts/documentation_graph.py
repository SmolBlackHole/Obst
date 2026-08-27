"""Report how every repository Markdown page is reached from README.md."""

from __future__ import annotations

import re
import subprocess
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
ROOT_DOCUMENT = Path("README.md")

_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "build",
        "dist",
        "node_modules",
    }
)
_MARKDOWN_LINK = re.compile(r"!?\[[^]]*]\(([^)]+)\)")
_URL_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_FENCE_END = re.compile(r"^(`{3,})\s*$")


@dataclass(frozen=True, slots=True)
class BrokenDocumentationLink:
    """One local Markdown link that does not resolve to a discovered page."""

    source: Path
    target: str


@dataclass(frozen=True, slots=True)
class DocumentationGraph:
    """Markdown pages, their outgoing edges and unresolved local links."""

    pages: tuple[Path, ...]
    edges: dict[Path, tuple[Path, ...]]
    broken_links: tuple[BrokenDocumentationLink, ...]

    def shortest_paths_from(self, start: Path) -> dict[Path, tuple[Path, ...]]:
        """Return one shortest directed link path to every reachable page."""
        if start not in self.edges:
            raise ValueError(f"documentation root is not a discovered page: {start}")
        paths: dict[Path, tuple[Path, ...]] = {start: (start,)}
        queue = deque((start,))
        while queue:
            source = queue.popleft()
            for target in self.edges[source]:
                if target in paths:
                    continue
                paths[target] = (*paths[source], target)
                queue.append(target)
        return paths


def discover_markdown_pages(root: Path) -> tuple[Path, ...]:
    """Discover tracked and non-ignored project Markdown pages."""
    completed = subprocess.run(
        (
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            "*.md",
        ),
        cwd=root,
        check=True,
        capture_output=True,
    )
    pages: list[Path] = []
    for encoded_path in completed.stdout.split(b"\0"):
        if not encoded_path:
            continue
        relative = Path(encoded_path.decode("utf-8"))
        if any(part in _EXCLUDED_DIRECTORIES for part in relative.parts):
            continue
        if not (root / relative).is_file():
            continue
        pages.append(relative)
    return tuple(sorted(pages, key=Path.as_posix))


def build_documentation_graph(root: Path = ROOT) -> DocumentationGraph:
    """Build the local Markdown link graph for one repository root."""
    pages = discover_markdown_pages(root)
    page_set = frozenset(pages)
    edges: dict[Path, tuple[Path, ...]] = {}
    broken_links: list[BrokenDocumentationLink] = []
    for source in pages:
        targets: set[Path] = set()
        for raw_target in _markdown_link_targets(root / source):
            target = _resolve_markdown_target(root, source, raw_target)
            if target is None:
                continue
            if target not in page_set:
                broken_links.append(BrokenDocumentationLink(source, raw_target))
                continue
            targets.add(target)
        edges[source] = tuple(sorted(targets, key=Path.as_posix))
    return DocumentationGraph(
        pages,
        edges,
        tuple(sorted(broken_links, key=lambda item: (item.source, item.target))),
    )


def _markdown_link_targets(document: Path) -> tuple[str, ...]:
    targets: list[str] = []
    active_fence: str | None = None
    for line in document.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if active_fence is not None:
            closing_fence = _FENCE_END.fullmatch(stripped)
            if closing_fence is not None and len(closing_fence.group(1)) >= len(
                active_fence
            ):
                active_fence = None
            continue
        fence = _opening_fence(stripped)
        if fence is not None:
            active_fence = fence
            continue
        targets.extend(_MARKDOWN_LINK.findall(line))
    if active_fence is not None:
        raise ValueError(f"unclosed Markdown fence in {document}")
    return tuple(targets)


def _opening_fence(line: str) -> str | None:
    if not line.startswith("```"):
        return None
    tick_count = len(line) - len(line.lstrip("`"))
    return "`" * tick_count


def _resolve_markdown_target(
    root: Path,
    source: Path,
    raw_target: str,
) -> Path | None:
    target = _target_path_text(raw_target)
    if target is None:
        return None
    candidate = (root / source.parent / unquote(target)).resolve()
    if candidate.is_dir():
        index = candidate / "README.md"
        if not index.is_file():
            return None
        candidate = index
    if candidate.suffix.lower() != ".md":
        return None
    try:
        return candidate.relative_to(root.resolve())
    except ValueError:
        return None


def _target_path_text(raw_target: str) -> str | None:
    target = raw_target.strip()
    if target.startswith("<"):
        closing = target.find(">")
        if closing == -1:
            return None
        target = target[1:closing]
    else:
        target = target.partition(" ")[0]
    if not target or target.startswith("#") or _URL_SCHEME.match(target):
        return None
    path, _, _fragment = target.partition("#")
    return path or None


def main() -> None:
    graph = build_documentation_graph()
    paths = graph.shortest_paths_from(ROOT_DOCUMENT)
    unreachable = tuple(page for page in graph.pages if page not in paths)

    print(f"Documentation root: {ROOT_DOCUMENT.as_posix()}")
    print(f"Pages: {len(graph.pages)}")
    print(f"Reachable: {len(paths)}")
    print(f"Unreachable: {len(unreachable)}")
    print("\nReachable paths:")
    for page in sorted(paths, key=lambda item: (len(paths[item]), item.as_posix())):
        route = " -> ".join(part.as_posix() for part in paths[page])
        print(f"  {route}")

    if unreachable:
        print("\nUnreachable pages:")
        for page in unreachable:
            print(f"  {page.as_posix()}")

    if graph.broken_links:
        print("\nBroken local Markdown links:")
        for link in graph.broken_links:
            print(f"  {link.source.as_posix()} -> {link.target}")

    if unreachable or graph.broken_links:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

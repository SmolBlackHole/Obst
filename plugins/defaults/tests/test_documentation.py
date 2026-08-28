from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
DOCUMENTATION_ROOT = PROJECT_ROOT / "docs"
DOCUMENTATION_PAGES = tuple(sorted(DOCUMENTATION_ROOT.rglob("*.md")))
PUBLIC_DOCUMENTS = (PROJECT_ROOT / "README.md", *DOCUMENTATION_PAGES)

_MARKDOWN_LINK = re.compile(r"!?\[[^]]*]\(([^)]+)\)")
_MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")
_PARENT_LINK = re.compile(r"^Parent: \[[^]]+]\(([^)]+)\)$")
_URL_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_FENCE_START = re.compile(r"^(`{3,})([^`]*)$")
_FENCE_END = re.compile(r"^(`{3,})\s*$")
_TABLE_OF_CONTENTS_HEADING = "## Table of contents"
_EXECUTABLE_LABEL = "> **Executable documentation:**"


def _document_id(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _prose_lines(document: Path) -> tuple[str, ...]:
    lines: list[str] = []
    active_fence: str | None = None
    for line in document.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if active_fence is not None:
            closing = _FENCE_END.fullmatch(stripped)
            if closing is not None and len(closing.group(1)) >= len(active_fence):
                active_fence = None
            continue
        opening = _FENCE_START.fullmatch(stripped)
        if opening is not None:
            active_fence = opening.group(1)
            continue
        lines.append(line)
    if active_fence is not None:
        raise ValueError(f"unclosed Markdown fence in {document}")
    return tuple(lines)


def _heading_anchors(document: Path) -> set[str]:
    anchors: set[str] = set()
    for line in _prose_lines(document):
        match = _MARKDOWN_HEADING.match(line)
        if match is None:
            continue
        heading = re.sub(r"[^\w\s-]", "", match.group(1).lower())
        anchors.add(re.sub(r"\s+", "-", heading.strip()))
    return anchors


def _has_executable_warning(lines: list[str], fence_index: int) -> bool:
    cursor = fence_index - 1
    while cursor >= 0 and not lines[cursor].strip():
        cursor -= 1
    warning_lines: list[str] = []
    while cursor >= 0 and lines[cursor].lstrip().startswith(">"):
        warning_lines.append(lines[cursor].strip())
        cursor -= 1
    warning_lines.reverse()
    return (
        len(warning_lines) >= 2
        and warning_lines[0] == "> [!WARNING]"
        and warning_lines[1].startswith(_EXECUTABLE_LABEL)
    )


def _python_blocks(document: Path) -> tuple[tuple[str, bool], ...]:
    lines = document.read_text(encoding="utf-8").splitlines()
    blocks: list[tuple[str, bool]] = []
    active_fence: str | None = None
    active_language = ""
    active_lines: list[str] = []
    executable = False
    for line_index, line in enumerate(lines):
        stripped = line.strip()
        if active_fence is None:
            opening = _FENCE_START.fullmatch(stripped)
            if opening is None:
                continue
            active_fence = opening.group(1)
            active_language = opening.group(2).strip().partition(" ")[0]
            active_lines = []
            executable = _has_executable_warning(lines, line_index)
            continue
        closing = _FENCE_END.fullmatch(stripped)
        if closing is not None and len(closing.group(1)) >= len(active_fence):
            if active_language == "python":
                blocks.append(("\n".join(active_lines), executable))
            active_fence = None
            active_language = ""
            active_lines = []
            executable = False
            continue
        active_lines.append(line)
    if active_fence is not None:
        raise ValueError(f"unclosed Markdown fence in {document}")
    return tuple(blocks)


PYTHON_EXAMPLES = tuple(
    (document, index, source, executable)
    for document in PUBLIC_DOCUMENTS
    for index, (source, executable) in enumerate(_python_blocks(document), start=1)
)


@pytest.mark.parametrize("document", PUBLIC_DOCUMENTS, ids=_document_id)
def test_public_markdown_local_links_exist(document: Path) -> None:
    missing: list[str] = []
    for line in _prose_lines(document):
        for target in _MARKDOWN_LINK.findall(line):
            clean_target = target.strip("<>")
            if _URL_SCHEME.match(clean_target):
                continue
            relative_path, _, fragment = clean_target.partition("#")
            target_path = (
                document if not relative_path else document.parent / relative_path
            )
            if target_path.is_dir():
                target_path /= "README.md"
            if not target_path.is_file():
                missing.append(target)
            elif fragment and fragment not in _heading_anchors(target_path):
                missing.append(target)
    assert not missing, f"missing local link targets: {missing}"


@pytest.mark.parametrize("document", DOCUMENTATION_PAGES, ids=_document_id)
def test_documentation_page_has_book_navigation(document: Path) -> None:
    lines = document.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 4
    assert lines[0].startswith("# ")
    assert lines[1] == ""
    match = _PARENT_LINK.fullmatch(lines[2])
    assert match is not None, "expected a Parent link immediately after the title"
    target, _, fragment = match.group(1).partition("#")
    parent = document.parent / target
    assert parent.is_file(), f"missing parent document: {match.group(1)}"
    if fragment:
        assert fragment in _heading_anchors(parent)

    sections = [line for line in lines if line.startswith("## ")]
    main_sections = [line for line in sections if line != _TABLE_OF_CONTENTS_HEADING]
    has_nested_sections = any(line.startswith("### ") for line in lines)
    if document.name != "README.md" and (
        len(main_sections) >= 4 or has_nested_sections
    ):
        assert _TABLE_OF_CONTENTS_HEADING in sections


@pytest.mark.parametrize(
    ("document", "example_index", "source", "executable"),
    PYTHON_EXAMPLES,
    ids=(
        f"{_document_id(document)}::{index}"
        for document, index, _source, _executable in PYTHON_EXAMPLES
    ),
)
def test_python_examples_use_public_symbols(
    document: Path,
    example_index: int,
    source: str,
    executable: bool,
) -> None:
    del executable
    tree = ast.parse(source, filename=f"{_document_id(document)}::{example_index}")
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level != 0 or node.module is None:
            continue
        if not (
            node.module == "obst"
            or node.module.startswith("obst.")
            or node.module == "obst_defaults"
            or node.module.startswith("obst_defaults.")
        ):
            continue
        module = importlib.import_module(node.module)
        for alias in node.names:
            assert alias.name != "*"
            assert hasattr(module, alias.name), (
                f"{node.module} does not publicly expose {alias.name}"
            )


@pytest.mark.parametrize(
    ("document", "example_index", "source"),
    tuple(
        (document, index, source)
        for document, index, source, executable in PYTHON_EXAMPLES
        if executable
    ),
)
@pytest.mark.timeout(5)
def test_explicitly_marked_python_examples_execute(
    document: Path,
    example_index: int,
    source: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    exec(
        compile(
            source,
            f"{_document_id(document)}::{example_index}",
            "exec",
            dont_inherit=True,
        ),
        {"__name__": "__documentation_example__"},
    )

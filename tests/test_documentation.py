from __future__ import annotations

import ast
import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.documentation_graph import discover_markdown_pages

from obst.core import ExtensionDescriptor
from obst_defaults.carriers.filesystem import FilesystemCarrierExtension
from obst_defaults.carriers.memory import MemoryCarrierExtension
from obst_defaults.carriers.stdin import StdinCarrierExtension
from obst_defaults.codecs.raw import RawExtension
from obst_defaults.codecs.zlib import (
    ZlibDictionaryExtension,
    ZlibExtension,
)
from obst_defaults.files import FileExtension
from obst_defaults.packagers import FixedPackagerExtension
from obst_defaults.transforms.delta8 import Delta8Extension

ROOT = Path(__file__).parents[1]
DISCOVERED_MARKDOWN = tuple(
    ROOT / relative_path for relative_path in discover_markdown_pages(ROOT)
)
DOCUMENTATION_PAGES = tuple(
    path for path in DISCOVERED_MARKDOWN if path.is_relative_to(ROOT / "docs")
)
PUBLIC_DOCUMENTS = tuple(
    path
    for path in DISCOVERED_MARKDOWN
    if path in {ROOT / "README.md", ROOT / "ROADMAP.md"}
    or path.is_relative_to(ROOT / "docs")
)
FIRST_PARTY_DESCRIPTORS = (
    RawExtension.descriptor,
    ZlibExtension.descriptor,
    ZlibDictionaryExtension.descriptor,
    Delta8Extension.descriptor,
    FileExtension.descriptor,
)
FIRST_PARTY_RUNTIME_DESCRIPTORS = (
    FilesystemCarrierExtension.descriptor,
    MemoryCarrierExtension.descriptor,
    StdinCarrierExtension.descriptor,
    FixedPackagerExtension.descriptor,
)
_MARKDOWN_LINK = re.compile(r"!?\[[^]]*]\(([^)]+)\)")
_MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")
_PARENT_LINK = re.compile(r"^Parent: \[[^]]+]\(([^)]+)\)$")
_URL_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
_REPOSITORY_SPECIFICATION_PREFIX = "https://github.com/SmolBlackHole/Obst/blob/main/"
_TABLE_OF_CONTENTS_HEADING = "## Table of contents"
_UNSUPPORTED_MERMAID_RENDERER = re.compile(
    r"(?:layout\s*:\s*elk|defaultRenderer\s*:\s*['\"]?elk)",
    re.IGNORECASE,
)
_FENCE_START = re.compile(r"^(`{3,})([^`]*)$")
_FENCE_END = re.compile(r"^(`{3,})\s*$")
_EXECUTABLE_DOCUMENTATION_LABEL = "> **Executable documentation:**"


def _fenced_code_blocks(
    document: Path,
    language: str,
) -> tuple[tuple[str, bool], ...]:
    lines = document.read_text(encoding="utf-8").splitlines()
    blocks: list[tuple[str, bool]] = []
    active_fence: str | None = None
    active_language = ""
    active_lines: list[str] = []
    active_executable = False
    for line_index, line in enumerate(lines):
        stripped = line.strip()
        if active_fence is None:
            match = _FENCE_START.fullmatch(stripped)
            if match is None:
                continue
            active_fence = match.group(1)
            active_language = match.group(2).strip().partition(" ")[0]
            active_lines = []
            active_executable = _has_executable_documentation_warning(
                lines,
                line_index,
            )
            continue
        closing_fence = _FENCE_END.fullmatch(stripped)
        if closing_fence is not None and len(closing_fence.group(1)) >= len(
            active_fence
        ):
            if active_language == language:
                blocks.append(("\n".join(active_lines), active_executable))
            active_fence = None
            active_language = ""
            active_lines = []
            active_executable = False
            continue
        active_lines.append(line)
    if active_fence is not None:
        raise ValueError(f"unclosed Markdown fence in {document}")
    return tuple(blocks)


def _has_executable_documentation_warning(
    lines: list[str],
    fence_index: int,
) -> bool:
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
        and warning_lines[1].startswith(_EXECUTABLE_DOCUMENTATION_LABEL)
    )


PYTHON_CODE_BLOCKS = tuple(
    (document, index, source, executable)
    for document in PUBLIC_DOCUMENTS
    for index, (source, executable) in enumerate(
        _fenced_code_blocks(document, "python"),
        start=1,
    )
)
PYTHON_EXAMPLES = tuple(
    (document, index, source)
    for document, index, source, _executable in PYTHON_CODE_BLOCKS
)
EXECUTABLE_PYTHON_EXAMPLES = tuple(
    (document, index, source)
    for document, index, source, executable in PYTHON_CODE_BLOCKS
    if executable
)


def _document_id(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


@pytest.mark.parametrize("descriptor", FIRST_PARTY_DESCRIPTORS)
def test_first_party_specification_url_targets_local_contract(
    descriptor: ExtensionDescriptor,
) -> None:
    url = descriptor.specification_url
    assert url is not None
    assert url.startswith(_REPOSITORY_SPECIFICATION_PREFIX)

    relative_path = url.removeprefix(_REPOSITORY_SPECIFICATION_PREFIX)
    assert relative_path.startswith("docs/contracts/")
    assert (ROOT / relative_path).is_file()


@pytest.mark.parametrize("descriptor", FIRST_PARTY_RUNTIME_DESCRIPTORS)
def test_first_party_specification_url_targets_local_extension_page(
    descriptor: ExtensionDescriptor,
) -> None:
    url = descriptor.specification_url
    assert url is not None
    assert url.startswith(_REPOSITORY_SPECIFICATION_PREFIX)

    relative_path = url.removeprefix(_REPOSITORY_SPECIFICATION_PREFIX)
    page, _, fragment = relative_path.partition("#")
    assert page.startswith("docs/extensions/")
    target = ROOT / page
    assert target.is_file()
    if fragment:
        assert fragment in _heading_anchors(target)


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
            if not target_path.exists():
                missing.append(target)
                continue
            if (
                fragment
                and target_path.is_file()
                and target_path.suffix.lower() == ".md"
                and fragment not in _heading_anchors(target_path)
            ):
                missing.append(target)
    assert not missing, f"missing local link targets: {missing}"


@pytest.mark.parametrize("document", DOCUMENTATION_PAGES, ids=_document_id)
def test_documentation_page_links_to_parent(document: Path) -> None:
    lines = document.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 3
    assert lines[0].startswith("# ")
    assert lines[1] == ""

    match = _PARENT_LINK.fullmatch(lines[2])
    assert match is not None, "expected a Parent link immediately after the title"
    target, _, fragment = match.group(1).partition("#")
    target_path = document.parent / target
    assert target_path.is_file(), f"missing parent document: {match.group(1)}"
    if fragment:
        assert fragment in _heading_anchors(target_path)


@pytest.mark.parametrize("document", DOCUMENTATION_PAGES, ids=_document_id)
def test_documentation_page_opens_with_introduction_and_useful_toc(
    document: Path,
) -> None:
    lines = document.read_text(encoding="utf-8").splitlines()
    section_indexes = [
        index
        for index, line in enumerate(lines)
        if line.startswith("## ") and line != _TABLE_OF_CONTENTS_HEADING
    ]
    toc_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line == _TABLE_OF_CONTENTS_HEADING
        ),
        None,
    )
    introduction_end = (
        toc_index
        if toc_index is not None
        else section_indexes[0]
        if section_indexes
        else len(lines)
    )
    introduction = [line for line in lines[3:introduction_end] if line.strip()]

    assert introduction, "expected an introduction after the Parent link"
    if len(section_indexes) >= 2:
        assert toc_index is not None, "expected a table of contents"
        assert toc_index < section_indexes[0]
        toc_lines = lines[toc_index + 1 : section_indexes[0]]
        assert any(_MARKDOWN_LINK.search(line) for line in toc_lines), (
            "expected generated links below the table of contents heading"
        )


@pytest.mark.parametrize(
    "document",
    (ROOT / "README.md", ROOT / "ROADMAP.md", *DOCUMENTATION_PAGES),
    ids=_document_id,
)
def test_mermaid_uses_github_supported_renderer(document: Path) -> None:
    contents = document.read_text(encoding="utf-8")
    assert _UNSUPPORTED_MERMAID_RENDERER.search(contents) is None


def test_every_markdown_page_is_reachable_from_root_readme() -> None:
    completed = subprocess.run(
        [sys.executable, ROOT / "scripts" / "documentation_graph.py"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "obst_lab/README.md" not in completed.stdout


def test_public_document_discovery_excludes_private_working_trees() -> None:
    private_roots = (ROOT / "docs" / "audits", ROOT / "docs" / "history")
    assert all(
        not document.is_relative_to(private_root)
        for document in PUBLIC_DOCUMENTS
        for private_root in private_roots
    )


@pytest.mark.parametrize(
    ("document", "example_index", "source"),
    PYTHON_EXAMPLES,
    ids=(
        f"{_document_id(document)}::{example_index}"
        for document, example_index, _source in PYTHON_EXAMPLES
    ),
)
def test_public_python_examples_parse_and_use_real_project_imports(
    document: Path,
    example_index: int,
    source: str,
) -> None:
    tree = ast.parse(
        source,
        filename=f"{_document_id(document)}::python-{example_index}",
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_project_import(alias.name):
                    importlib.import_module(alias.name)
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module is not None
            and _is_project_import(node.module)
        ):
            module = importlib.import_module(node.module)
            for alias in node.names:
                assert alias.name != "*", "documentation must use explicit imports"
                assert hasattr(module, alias.name), (
                    f"{node.module} does not publicly expose {alias.name}"
                )


def _is_project_import(module: str) -> bool:
    return module in {"obst", "obst_defaults"} or module.startswith(
        ("obst.", "obst_defaults.")
    )


def test_public_docs_include_canonical_executable_examples() -> None:
    identities = {
        (_document_id(document), example_index)
        for document, example_index, _source in EXECUTABLE_PYTHON_EXAMPLES
    }
    assert identities == {
        ("docs/core/README.md", 1),
        ("docs/core/recipes.md", 1),
        ("docs/extensions/profiles.md", 1),
        ("docs/extensions/stages.md", 1),
    }


@pytest.mark.parametrize(
    ("prefix", "source", "expected"),
    (
        (
            "> [!WARNING]\n"
            "> **Executable documentation:** This block runs during tests.\n\n",
            "value = 1",
            True,
        ),
        (
            "> [!WARNING]\n> This is only a generic warning.\n\n",
            "value = 1",
            False,
        ),
        (
            "> [!NOTE]\n"
            "> **Executable documentation:** This is the wrong admonition.\n\n",
            "value = 1",
            False,
        ),
        ("", "value = 1", False),
        ("", "# docs-test: execute\nvalue = 1", False),
        (
            "> [!WARNING]\n"
            "> **Executable documentation:** This marker is detached.\n\n"
            "Intervening prose.\n\n",
            "value = 1",
            False,
        ),
    ),
)
def test_executable_documentation_marker_controls_execution_selection(
    tmp_path: Path,
    prefix: str,
    source: str,
    expected: bool,
) -> None:
    document = tmp_path / "example.md"
    document.write_text(
        f"{prefix}```python\n{source}\n```\n",
        encoding="utf-8",
    )

    assert _fenced_code_blocks(document, "python") == ((source, expected),)


def test_unclosed_markdown_fence_is_rejected(tmp_path: Path) -> None:
    document = tmp_path / "unclosed.md"
    document.write_text("```python\nvalue = 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unclosed Markdown fence"):
        _fenced_code_blocks(document, "python")


@pytest.mark.parametrize(
    ("document", "example_index", "source"),
    EXECUTABLE_PYTHON_EXAMPLES,
    ids=(
        f"{_document_id(document)}::{example_index}"
        for document, example_index, _source in EXECUTABLE_PYTHON_EXAMPLES
    ),
)
@pytest.mark.timeout(5)
def test_canonical_public_python_examples_execute(
    document: Path,
    example_index: int,
    source: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    namespace = {"__name__": "__documentation_example__"}
    exec(
        compile(
            source,
            f"{_document_id(document)}::python-{example_index}",
            "exec",
            dont_inherit=True,
        ),
        namespace,
    )


def _prose_lines(document: Path) -> tuple[str, ...]:
    lines: list[str] = []
    in_fence = False
    for line in document.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            lines.append(line)
    return tuple(lines)


def _heading_anchors(document: Path) -> set[str]:
    anchors: set[str] = set()
    for line in _prose_lines(document):
        match = _MARKDOWN_HEADING.match(line)
        if match is None:
            continue
        heading = match.group(1).lower()
        heading = re.sub(r"[^\w\s-]", "", heading)
        anchors.add(re.sub(r"\s+", "-", heading.strip()))
    return anchors

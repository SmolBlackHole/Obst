from __future__ import annotations

import json

from obst.cli.output import (
    render_limit_profile_human,
    render_limit_profile_json,
    render_plugin_conformance_human,
    render_plugin_conformance_json,
)
from obst.cli.presentation import HumanOutputStyle, render_human_table, strip_ansi
from obst.conformance import (
    ConformanceCaseKind,
    ConformanceCaseResult,
    ConformanceReport,
)
from obst.core import ResourceUnit
from obst.limits import (
    LimitProfileSource,
    LimitProfileStatus,
    LimitProfileView,
    ResourceLimitStatus,
)


def test_plugin_conformance_human_output_uses_a_compact_table() -> None:
    report = ConformanceReport(
        (
            ConformanceCaseResult(
                "known-answer",
                "org.example/identity@1",
                ConformanceCaseKind.STAGE_KNOWN_ANSWER,
                True,
                None,
            ),
        )
    )

    rendered = render_plugin_conformance_human("example", report)

    assert "  Plugin          example" in rendered
    assert "  Result          passed" in rendered
    assert "  Case          Result  Kind                Extension" in rendered
    assert (
        "  known-answer  PASS    stage-known-answer  org.example/identity@1" in rendered
    )


def test_plugin_conformance_json_keeps_plugin_context_outside_the_report() -> None:
    report = ConformanceReport(
        (
            ConformanceCaseResult(
                "failure",
                None,
                ConformanceCaseKind.CONTAINER_STRUCTURE,
                False,
                "InvalidContainerError: invalid structure",
            ),
        )
    )

    document = json.loads(render_plugin_conformance_json("format", report))

    assert document["plugin"] == "format"
    assert document["passed"] is False
    assert document["cases"][0]["extension_id"] is None


def test_human_table_aligns_colored_cells_by_visible_width() -> None:
    style = HumanOutputStyle(color=True)

    rendered = render_human_table(
        ("Name", "Value"),
        ((style.contributed("plugin"), "1"), (style.success("core"), "20")),
        right_align=frozenset({1}),
    )

    assert strip_ansi(rendered).splitlines()[-2:] == [
        "  plugin      1",
        "  core       20",
    ]


def test_limit_output_groups_owners_and_formats_typed_byte_units() -> None:
    profile = LimitProfileStatus(
        "default",
        "Default limits.",
        LimitProfileSource.DEFAULT,
        True,
        True,
        False,
    )
    view = LimitProfileView(
        profile,
        (
            ResourceLimitStatus(
                "container_bytes",
                "core",
                16 * 1024**3,
                16 * 1024**3,
                "default",
                "Container bytes.",
                True,
                ResourceUnit.BYTES,
            ),
            ResourceLimitStatus(
                "org.example/file@1/members",
                "org.example/file@1",
                4096,
                4096,
                "default",
                "Members.",
                True,
                ResourceUnit.COUNT,
            ),
        ),
    )

    rendered = render_limit_profile_human(view)
    document = json.loads(render_limit_profile_json(view))

    assert "\nCore\n" in rendered
    assert "container_bytes  16.0 GiB  16.0 GiB" in rendered
    assert "\norg.example/file@1\n" in rendered
    assert "members     4,096    4,096" in rendered
    assert document["resources"][0]["resolved_maximum"] == 16 * 1024**3
    assert "unit" not in document["resources"][0]

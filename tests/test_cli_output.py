from __future__ import annotations

import json

from obst.cli.output import (
    render_plugin_conformance_human,
    render_plugin_conformance_json,
)
from obst.conformance import (
    ConformanceCaseKind,
    ConformanceCaseResult,
    ConformanceReport,
)


def test_plugin_conformance_human_output_uses_aligned_fields() -> None:
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
    assert "  Case            known-answer" in rendered
    assert "  Result          PASS" in rendered
    assert "  Kind            stage-known-answer" in rendered
    assert "  Extension       org.example/identity@1" in rendered


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

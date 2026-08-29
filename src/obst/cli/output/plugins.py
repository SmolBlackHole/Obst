"""Human and JSON output for plugin metadata and conformance."""

from __future__ import annotations

import json
from io import StringIO

from obst.cli.presentation import (
    PLAIN_HUMAN_OUTPUT,
    HumanOutputStyle,
    escape_human_text,
    render_human_table,
    styled_yes_no,
)
from obst.conformance import ConformanceReport
from obst.plugins import (
    COMMAND_ENTRY_POINT_GROUP,
    CONFORMANCE_ENTRY_POINT_GROUP,
    EXTENSION_ENTRY_POINT_GROUP,
    RESOURCE_ENTRY_POINT_GROUP,
    PluginStatus,
)

PLUGIN_CATALOG_JSON_SCHEMA_VERSION = 6
PLUGIN_CONFORMANCE_JSON_SCHEMA_VERSION = 2


def render_plugin_catalog_human(
    plugins: tuple[PluginStatus, ...],
    *,
    style: HumanOutputStyle = PLAIN_HUMAN_OUTPUT,
) -> str:
    """Render inert plugin metadata and activation state without loading code."""
    output = StringIO()
    print(style.title("Extension plugins"), file=output)
    print(style.muted("  Metadata only; plugin code was not loaded."), file=output)
    if not plugins:
        print("\n  none", file=output)
        return output.getvalue()
    for plugin in plugins:
        print(file=output)
        distribution = plugin.distribution_name or "unknown distribution"
        if plugin.distribution_version is not None:
            distribution = f"{distribution} {plugin.distribution_version}"
        print(style.contributed(escape_human_text(plugin.name)), file=output)
        print(
            style.field("Installed", styled_yes_no(style, plugin.installed)),
            file=output,
        )
        print(style.field("Enabled", styled_yes_no(style, plugin.enabled)), file=output)
        if plugin.installed:
            print(
                style.field("Distribution", escape_human_text(distribution)),
                file=output,
            )
        if plugin.summary is not None:
            print(
                style.field("Summary", escape_human_text(plugin.summary)), file=output
            )
        if plugin.documentation_url is not None:
            print(
                style.field(
                    "Documentation", escape_human_text(plugin.documentation_url)
                ),
                file=output,
            )
        for label, reference in (
            ("Extensions", plugin.extension_reference),
            ("Commands", plugin.command_reference),
            ("Conformance", plugin.conformance_reference),
            ("Resources", plugin.resource_reference),
        ):
            if reference is not None:
                print(style.field(label, escape_human_text(reference)), file=output)
    return output.getvalue()


def render_plugin_catalog_json(plugins: tuple[PluginStatus, ...]) -> str:
    """Render inert installed-plugin metadata as stable JSON."""
    document = {
        "schema_version": PLUGIN_CATALOG_JSON_SCHEMA_VERSION,
        "entry_point_groups": {
            "extensions": EXTENSION_ENTRY_POINT_GROUP,
            "commands": COMMAND_ENTRY_POINT_GROUP,
            "conformance": CONFORMANCE_ENTRY_POINT_GROUP,
            "resources": RESOURCE_ENTRY_POINT_GROUP,
        },
        "plugins": [
            {
                "name": plugin.name,
                "installed": plugin.installed,
                "enabled": plugin.enabled,
                "distribution_name": plugin.distribution_name,
                "distribution_version": plugin.distribution_version,
                "summary": plugin.summary,
                "documentation_url": plugin.documentation_url,
                "extension_reference": plugin.extension_reference,
                "command_reference": plugin.command_reference,
                "conformance_reference": plugin.conformance_reference,
                "resource_reference": plugin.resource_reference,
            }
            for plugin in plugins
        ],
    }
    return json.dumps(document, indent=4, sort_keys=True) + "\n"


def render_plugin_conformance_human(
    plugin_name: str,
    report: ConformanceReport,
    *,
    style: HumanOutputStyle = PLAIN_HUMAN_OUTPUT,
) -> str:
    """Render one plugin's portable conformance report for a human."""
    output = StringIO()
    status = "passed" if report.passed else "failed"
    styled_status = style.success(status) if report.passed else style.error(status)
    print(style.title("Plugin conformance"), file=output)
    print(
        style.field("Plugin", style.contributed(escape_human_text(plugin_name))),
        file=output,
    )
    print(style.field("Result", styled_status), file=output)
    print(f"\n{style.heading('Cases')}", file=output)
    rows = tuple(
        (
            style.contributed(escape_human_text(case.case_id)),
            style.success("PASS") if case.passed else style.error("FAIL"),
            escape_human_text(case.kind.value),
            (
                style.contributed(escape_human_text(case.extension_id))
                if case.extension_id is not None
                else "-"
            ),
        )
        for case in report.cases
    )
    print(
        render_human_table(("Case", "Result", "Kind", "Extension"), rows),
        file=output,
    )
    failures = tuple(case for case in report.cases if case.error is not None)
    if failures:
        print(f"\n{style.heading('Errors')}", file=output)
        for case in failures:
            print(
                style.field(
                    escape_human_text(case.case_id),
                    style.error(escape_human_text(case.error)),
                ),
                file=output,
            )
    return output.getvalue()


def render_plugin_conformance_json(
    plugin_name: str,
    report: ConformanceReport,
) -> str:
    """Render one plugin's portable conformance report as stable JSON."""
    document = {
        "schema_version": PLUGIN_CONFORMANCE_JSON_SCHEMA_VERSION,
        "plugin": plugin_name,
        "passed": report.passed,
        "cases": [
            {
                "id": case.case_id,
                "kind": case.kind.value,
                "extension_id": case.extension_id,
                "passed": case.passed,
                "error": case.error,
            }
            for case in report.cases
        ],
    }
    return json.dumps(document, indent=4, sort_keys=True) + "\n"


__all__ = [
    "render_plugin_catalog_human",
    "render_plugin_catalog_json",
    "render_plugin_conformance_human",
    "render_plugin_conformance_json",
]

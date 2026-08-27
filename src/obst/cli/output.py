"""Human and machine-readable CLI output projections."""

from __future__ import annotations

import json
from io import StringIO

from obst.cli.presentation import (
    PLAIN_HUMAN_OUTPUT,
    HumanOutputStyle,
    escape_human_text,
    format_count,
    format_size,
)
from obst.conformance import PluginConformanceReport
from obst.core.extensions import InspectionInterpretation
from obst.core.inspection import (
    ContainerInspection,
    InspectedRecipe,
    InspectedStage,
    RecipeChunkUsage,
)
from obst.core.registry import (
    CarrierCapability,
    ExtensionCapability,
    StageCapability,
    StreamProfileCapability,
)
from obst.plugins import (
    COMMAND_ENTRY_POINT_GROUP,
    CONFORMANCE_ENTRY_POINT_GROUP,
    EXTENSION_ENTRY_POINT_GROUP,
    PluginStatus,
)

INSPECTION_JSON_SCHEMA_VERSION = 6
PLUGIN_CATALOG_JSON_SCHEMA_VERSION = 4
PLUGIN_CONFORMANCE_JSON_SCHEMA_VERSION = 1
EXTENSION_INVENTORY_JSON_SCHEMA_VERSION = 3

_ASCII_APPLE = """                     ███████
                   ██    ██
             ██   █  █████
               █ █ ████

         █████████████████
       █████████████████████

     ████████████████████████
     ████████████████████████

     ████████████████████████
      ███████████████████████

        ███████████████████
          ██████████████"""


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
        print(style.identifier(escape_human_text(plugin.name)), file=output)
        print(
            _human_field(
                style,
                "Installed",
                _styled_yes_no(style, plugin.installed),
            ),
            file=output,
        )
        print(
            _human_field(style, "Enabled", _styled_yes_no(style, plugin.enabled)),
            file=output,
        )
        print(
            _human_field(style, "Default", _styled_yes_no(style, plugin.default)),
            file=output,
        )
        if plugin.installed:
            print(
                _human_field(
                    style,
                    "Distribution",
                    escape_human_text(distribution),
                ),
                file=output,
            )
        if plugin.summary is not None:
            print(
                _human_field(style, "Summary", escape_human_text(plugin.summary)),
                file=output,
            )
        if plugin.documentation_url is not None:
            print(
                _human_field(
                    style,
                    "Documentation",
                    escape_human_text(plugin.documentation_url),
                ),
                file=output,
            )
        if plugin.extension_reference is not None:
            print(
                _human_field(
                    style,
                    "Extensions",
                    escape_human_text(plugin.extension_reference),
                ),
                file=output,
            )
        if plugin.command_reference is not None:
            print(
                _human_field(
                    style,
                    "Commands",
                    escape_human_text(plugin.command_reference),
                ),
                file=output,
            )
        if plugin.conformance_reference is not None:
            print(
                _human_field(
                    style,
                    "Conformance",
                    escape_human_text(plugin.conformance_reference),
                ),
                file=output,
            )
    return output.getvalue()


def render_plugin_catalog_json(
    plugins: tuple[PluginStatus, ...],
) -> str:
    """Render inert installed-plugin metadata as stable JSON."""
    document = {
        "schema_version": PLUGIN_CATALOG_JSON_SCHEMA_VERSION,
        "entry_point_groups": {
            "extensions": EXTENSION_ENTRY_POINT_GROUP,
            "commands": COMMAND_ENTRY_POINT_GROUP,
            "conformance": CONFORMANCE_ENTRY_POINT_GROUP,
        },
        "plugins": [
            {
                "name": plugin.name,
                "installed": plugin.installed,
                "enabled": plugin.enabled,
                "default": plugin.default,
                "distribution_name": plugin.distribution_name,
                "distribution_version": plugin.distribution_version,
                "summary": plugin.summary,
                "documentation_url": plugin.documentation_url,
                "extension_reference": plugin.extension_reference,
                "command_reference": plugin.command_reference,
                "conformance_reference": plugin.conformance_reference,
            }
            for plugin in plugins
        ],
    }
    return json.dumps(document, indent=4, sort_keys=True) + "\n"


def render_plugin_conformance_human(
    report: PluginConformanceReport,
    *,
    style: HumanOutputStyle = PLAIN_HUMAN_OUTPUT,
) -> str:
    """Render one plugin's portable conformance report for a human."""
    output = StringIO()
    status = "passed" if report.passed else "failed"
    styled_status = style.success(status) if report.passed else style.error(status)
    print(style.title("Plugin conformance"), file=output)
    print(
        _human_field(style, "Plugin", escape_human_text(report.plugin_name)),
        file=output,
    )
    print(_human_field(style, "Result", styled_status), file=output)
    print(f"\n{style.heading('Cases')}", file=output)
    for case in report.cases:
        marker = "PASS" if case.passed else "FAIL"
        styled_marker = style.success(marker) if case.passed else style.error(marker)
        print(
            f"  {styled_marker}  {style.identifier(escape_human_text(case.stage_id))}",
            file=output,
        )
        if case.error is not None:
            print(f"        {escape_human_text(case.error)}", file=output)
    return output.getvalue()


def render_plugin_conformance_json(report: PluginConformanceReport) -> str:
    """Render one plugin's portable conformance report as stable JSON."""
    document = {
        "schema_version": PLUGIN_CONFORMANCE_JSON_SCHEMA_VERSION,
        "plugin": report.plugin_name,
        "passed": report.passed,
        "cases": [
            {
                "stage_id": case.stage_id,
                "passed": case.passed,
                "error": case.error,
            }
            for case in report.cases
        ],
    }
    return json.dumps(document, indent=4, sort_keys=True) + "\n"


def render_extension_inventory_human(
    capabilities: tuple[ExtensionCapability, ...],
    *,
    style: HumanOutputStyle = PLAIN_HUMAN_OUTPUT,
) -> str:
    """Render provider-free registry capabilities for a human."""
    output = StringIO()
    print(style.title("Extension capabilities"), file=output)
    if not capabilities:
        print("\n  none", file=output)
        return output.getvalue()
    for capability in capabilities:
        descriptor = capability.descriptor
        print(file=output)
        print(style.identifier(escape_human_text(capability.extension_id)), file=output)
        if descriptor.display_name is not None:
            print(
                _human_field(
                    style,
                    "Name",
                    escape_human_text(descriptor.display_name),
                ),
                file=output,
            )
        if isinstance(capability, StageCapability):
            print(
                _human_field(
                    style,
                    "Stage",
                    "encode "
                    f"{_styled_yes_no(style, capability.encoder_available)}, "
                    "decode "
                    f"{_styled_yes_no(style, capability.decoder_available)}",
                ),
                file=output,
            )
            print(
                _human_field(
                    style,
                    "Parameters",
                    "encode "
                    f"{_styled_yes_no(style, capability.parameter_encoder_available)}, "
                    "decode "
                    f"{_styled_yes_no(style, capability.parameter_decoder_available)}, "
                    "interpret "
                    f"{_styled_yes_no(style, capability.parameter_interpreter_available)}",
                ),
                file=output,
            )
        elif isinstance(capability, StreamProfileCapability):
            print(
                _human_field(style, "Kind", "stream profile"),
                file=output,
            )
            print(
                _human_field(
                    style,
                    "Metadata",
                    "encode "
                    f"{_styled_yes_no(style, capability.metadata_encoder_available)}, "
                    "decode "
                    f"{_styled_yes_no(style, capability.metadata_decoder_available)}, "
                    "interpret "
                    f"{_styled_yes_no(style, capability.metadata_interpreter_available)}",
                ),
                file=output,
            )
        elif isinstance(capability, CarrierCapability):
            print(
                _human_field(
                    style,
                    "Carrier",
                    f"read {_styled_yes_no(style, capability.reader_available)}, "
                    f"write {_styled_yes_no(style, capability.writer_available)}, "
                    "publish "
                    f"{_styled_yes_no(style, capability.publisher_available)}",
                ),
                file=output,
            )
        else:
            print(
                _human_field(
                    style,
                    "Packager",
                    f"prepare {_styled_yes_no(style, capability.provider_available)}",
                ),
                file=output,
            )
        if descriptor.summary is not None:
            print(
                _human_field(style, "Summary", escape_human_text(descriptor.summary)),
                file=output,
            )
        if descriptor.specification_url is not None:
            print(
                _human_field(
                    style,
                    "Specification",
                    escape_human_text(descriptor.specification_url),
                ),
                file=output,
            )
    return output.getvalue()


def render_extension_inventory_json(
    capabilities: tuple[ExtensionCapability, ...],
) -> str:
    """Render provider-free registry capabilities as stable JSON."""
    document = {
        "schema_version": EXTENSION_INVENTORY_JSON_SCHEMA_VERSION,
        "extensions": [_extension_capability_json(value) for value in capabilities],
    }
    return json.dumps(document, indent=4, sort_keys=True) + "\n"


def _extension_capability_json(
    capability: ExtensionCapability,
) -> dict[str, object]:
    document: dict[str, object] = {
        "id": capability.extension_id,
        "kind": capability.kind.name.lower(),
        "display_name": capability.descriptor.display_name,
        "summary": capability.descriptor.summary,
        "specification_url": capability.descriptor.specification_url,
    }
    if isinstance(capability, StageCapability):
        document.update(
            encoder_available=capability.encoder_available,
            decoder_available=capability.decoder_available,
            parameter_encoder_available=capability.parameter_encoder_available,
            parameter_decoder_available=capability.parameter_decoder_available,
            parameter_interpreter_available=(
                capability.parameter_interpreter_available
            ),
        )
    elif isinstance(capability, StreamProfileCapability):
        document.update(
            metadata_encoder_available=capability.metadata_encoder_available,
            metadata_decoder_available=capability.metadata_decoder_available,
            metadata_interpreter_available=(capability.metadata_interpreter_available),
        )
    elif isinstance(capability, CarrierCapability):
        document.update(
            reader_available=capability.reader_available,
            writer_available=capability.writer_available,
            publisher_available=capability.publisher_available,
        )
    else:
        document.update(provider_available=capability.provider_available)
    return document


def render_inspection_human(
    inspection: ContainerInspection,
    *,
    style: HumanOutputStyle = PLAIN_HUMAN_OUTPUT,
) -> str:
    """Render one human-readable container inspection without writing it."""
    decoder_status = "yes"
    if inspection.missing_required_stages:
        decoder_status = escape_human_text(
            f"no ({', '.join(inspection.missing_required_stages)})"
        )
    styled_decoder_status = (
        style.success(decoder_status)
        if inspection.required_decoders_available
        else style.error(decoder_status)
    )
    details = (
        "",
        "",
        "",
        "",
        "",
        style.title(f"OBST container {inspection.version.label}"),
        style.muted("-------------------------"),
        _summary_field(style, "Streams", str(inspection.stream_count)),
        _summary_field(style, "Recipes", str(inspection.recipe_count)),
        _summary_field(style, "Chunks", str(inspection.chunk_count)),
        _summary_field(
            style,
            "Container size",
            format_size(inspection.encoded_size),
        ),
        _summary_field(
            style,
            "Original size",
            f"{format_size(inspection.logical_size)} (committed)",
        ),
        _summary_field(
            style,
            "Compression",
            _format_compression(inspection.encoded_size, inspection.logical_size),
        ),
        _summary_field(
            style,
            "Integrity",
            style.success("valid (terminal commit and encoded CRCs)"),
        ),
        _summary_field(
            style,
            "Required decoders available",
            styled_decoder_status,
        ),
        _summary_field(
            style,
            "Logical recovery",
            style.warning(inspection.logical_recovery.value.replace("_", " ")),
        ),
    )
    apple_lines = _ASCII_APPLE.splitlines()
    apple_width = max(len(line) for line in apple_lines)
    output = StringIO()
    print(
        "\n".join(
            f"{_render_apple_line(index, apple, apple_width, style)}"
            f"     {detail}".rstrip()
            for index, (apple, detail) in enumerate(
                zip(apple_lines, details, strict=True)
            )
        ),
        file=output,
    )
    print(f"\n{style.heading('Streams')}", file=output)
    for stream in inspection.streams:
        declaration = stream.declaration
        label = (
            stream.metadata.label
            if stream.metadata is not None and stream.metadata.label is not None
            else declaration.stream_type
        )
        print(
            f"  {style.identifier(f'[{declaration.stream_id}]')} "
            f"{escape_human_text(label)}",
            file=output,
        )
        print(
            f"      {escape_human_text(declaration.stream_type)} | "
            f"{format_count(stream.chunk_count, 'chunk')} | "
            f"original {format_size(stream.logical_size)} | "
            f"encoded payload {format_size(stream.encoded_payload_size)}",
            file=output,
        )
        print(
            f"      Recipe usage: {_format_recipe_usage(stream.recipe_usage)}",
            file=output,
        )
        if stream.metadata is not None and stream.metadata.error is not None:
            print(
                "      Metadata interpretation: "
                f"{escape_human_text(stream.metadata.error)}",
                file=output,
            )
    print(f"\n{style.heading('Recipes')}", file=output)
    for recipe in inspection.recipes:
        print(
            f"  {style.identifier(f'[{recipe.declaration.recipe_id}]')} "
            f"{style.identifier(escape_human_text(_format_recipe(recipe)))} "
            f"| {format_count(recipe.chunk_count, 'chunk')}",
            file=output,
        )
    resources = inspection.resources
    print(f"\n{style.heading('Resource footprint')}", file=output)
    print(
        f"  Manifest {format_size(resources.manifest_size)} | "
        f"largest chunk {format_size(resources.max_logical_chunk_size)} logical / "
        f"{format_size(resources.max_encoded_chunk_size)} encoded",
        file=output,
    )
    print(
        f"  Stage executions {resources.stage_executions} | "
        f"largest stream {format_size(resources.max_materialized_stream_size)} "
        "if materialized",
        file=output,
    )
    print(f"\n{style.heading('Stage capabilities')}", file=output)
    for stage in inspection.stage_capabilities:
        availability = "available" if stage.decoder_available else "missing"
        label = (
            stage.stage_id
            if stage.display_name is None
            else f"{stage.stage_id} ({stage.display_name})"
        )
        print(
            f"  {style.identifier(escape_human_text(label))}: decoder "
            f"{style.success(availability) if stage.decoder_available else style.error(availability)}",
            file=output,
        )
        recipe_noun = "recipe" if len(stage.declared_recipe_ids) == 1 else "recipes"
        recipe_ids = ", ".join(
            str(recipe_id) for recipe_id in stage.declared_recipe_ids
        )
        print(f"      Declared by {recipe_noun}: {recipe_ids}", file=output)
        print(
            f"      Used by chunks: {_format_recipe_usage(stage.used_chunks_by_recipe)}",
            file=output,
        )
        if stage.summary is not None:
            print(f"      {escape_human_text(stage.summary)}", file=output)
        if stage.declared_specification_url is not None:
            print(
                "      Declared specification: "
                f"{escape_human_text(stage.declared_specification_url)}",
                file=output,
            )
        if stage.local_specification_url is not None:
            print(
                "      Local specification: "
                f"{escape_human_text(stage.local_specification_url)}",
                file=output,
            )
    return output.getvalue()


def _render_apple_line(
    index: int,
    line: str,
    width: int,
    style: HumanOutputStyle,
) -> str:
    padded = line.ljust(width)
    if index == 0:
        return style.leaf(padded)
    if index == 1:
        return style.leaf(padded)
    if index == 2:
        return (
            padded[:13]
            + style.stem(padded[13:15])
            + padded[15:18]
            + style.leaf(padded[18:])
        )
    if index == 3:
        return (
            padded[:15]
            + style.stem(padded[15:16])
            + padded[16:17]
            + style.leaf(padded[17:])
        )
    if line:
        return style.fruit(padded)
    return padded


def render_inspection_json(inspection: ContainerInspection) -> str:
    """Render one schema-versioned JSON inspection without writing it."""
    document = {
        "schema_version": INSPECTION_JSON_SCHEMA_VERSION,
        "format": {
            "name": "OBST",
            "major": inspection.version.major,
            "minor": inspection.version.minor,
            "codename": inspection.version.codename,
            "label": inspection.version.label,
        },
        "streams": inspection.stream_count,
        "recipes": inspection.recipe_count,
        "chunks": inspection.chunk_count,
        "container_size": inspection.encoded_size,
        "original_size": inspection.logical_size,
        "encoded_payload_size": inspection.encoded_payload_size,
        "container_to_original_ratio": inspection.encoded_to_logical_ratio,
        "integrity": "valid",
        "required_decoders_available": inspection.required_decoders_available,
        "missing_required_stages": list(inspection.missing_required_stages),
        "missing_declared_stages": list(inspection.missing_declared_stages),
        "logical_recovery": inspection.logical_recovery.value,
        "interpretation_policy": {
            "extension_ids": sorted(inspection.interpretation_policy.extension_ids),
        },
        "resource_footprint": {
            "manifest_size": inspection.resources.manifest_size,
            "extension_count": inspection.resources.extension_count,
            "recipe_count": inspection.resources.recipe_count,
            "stream_count": inspection.resources.stream_count,
            "total_stage_count": inspection.resources.total_stage_count,
            "max_stages_per_recipe": (inspection.resources.max_stages_per_recipe),
            "container_size": inspection.summary.encoded_size,
            "chunk_count": inspection.summary.chunk_count,
            "max_encoded_chunk_size": (inspection.resources.max_encoded_chunk_size),
            "max_logical_chunk_size": (inspection.resources.max_logical_chunk_size),
            "logical_size": inspection.summary.logical_size,
            "stage_executions": inspection.resources.stage_executions,
            "max_materialized_stream_size": (
                inspection.resources.max_materialized_stream_size
            ),
        },
        "stage_details": [
            {
                "id": stage.stage_id,
                "declared_recipe_ids": list(stage.declared_recipe_ids),
                "used_recipe_ids": list(stage.used_recipe_ids),
                "used_chunks_by_recipe": _recipe_usage_document(
                    stage.used_chunks_by_recipe
                ),
                "required": stage.required,
                "decoder_available": stage.decoder_available,
                "declared_specification_url": (stage.declared_specification_url),
                "display_name": stage.display_name,
                "summary": stage.summary,
                "local_specification_url": stage.local_specification_url,
            }
            for stage in inspection.stage_capabilities
        ],
        "stream_details": [
            {
                "id": stream.declaration.stream_id,
                "type": stream.declaration.stream_type,
                "metadata_hex": stream.declaration.metadata.hex(),
                "metadata_interpretation": _interpretation_document(stream.metadata),
                "default_recipe": stream.declaration.default_recipe_id,
                "chunks": stream.chunk_count,
                "original_size": stream.logical_size,
                "encoded_payload_size": stream.encoded_payload_size,
                "recipe_usage": _recipe_usage_document(stream.recipe_usage),
            }
            for stream in inspection.streams
        ],
        "recipe_details": [
            {
                "id": recipe.declaration.recipe_id,
                "chunks": recipe.chunk_count,
                "stages": [_stage_document(stage) for stage in recipe.stages],
            }
            for recipe in inspection.recipes
        ],
    }
    return json.dumps(document, indent=4, sort_keys=True) + "\n"


def _human_field(
    style: HumanOutputStyle,
    label: str,
    value: str,
    *,
    label_width: int = 15,
) -> str:
    return style.field(label, value, label_width=label_width)


def _summary_field(
    style: HumanOutputStyle,
    label: str,
    value: str,
) -> str:
    return f"{style.muted(label.ljust(29))} {value}"


def _styled_yes_no(style: HumanOutputStyle, value: bool) -> str:
    text = _yes_no(value)
    return style.success(text) if value else style.muted(text)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _format_compression(stored_size: int, original_size: int) -> str:
    ratio = None if original_size == 0 else stored_size / original_size
    if ratio is None:
        return "n/a (empty input)"
    percentage = ratio * 100
    difference = abs(100 - percentage)
    if percentage < 100:
        comparison = f"{difference:.1f}% smaller"
    elif percentage > 100:
        comparison = f"{difference:.1f}% larger"
    else:
        comparison = "same size"
    return f"{comparison} ({percentage:.1f}% of original)"


def _format_recipe(recipe: InspectedRecipe) -> str:
    return " -> ".join(_format_stage(stage) for stage in recipe.stages)


def _format_stage(stage: InspectedStage) -> str:
    details: list[str] = []
    if stage.parameters is not None:
        details.extend(
            f"{escape_human_text(field.name)}={escape_human_text(field.value)}"
            for field in stage.parameters.fields
        )
        if stage.parameters.error is not None:
            details.append(
                f"interpretation_error={escape_human_text(stage.parameters.error)}"
            )
    if not details and stage.spec.parameters:
        details.append(f"parameters={stage.spec.parameters.hex()}")
    if not details:
        return stage.spec.stage_id
    return f"{stage.spec.stage_id}({', '.join(details)})"


def _stage_document(stage: InspectedStage) -> dict[str, object]:
    return {
        "id": stage.spec.stage_id,
        "parameters_hex": stage.spec.parameters.hex(),
        "parameters_interpretation": _interpretation_document(stage.parameters),
    }


def _interpretation_document(
    interpretation: InspectionInterpretation | None,
) -> dict[str, object] | None:
    if interpretation is None:
        return None
    return {
        "label": interpretation.label,
        "fields": {field.name: field.value for field in interpretation.fields},
        "error": interpretation.error,
    }


def _format_recipe_usage(usage: tuple[RecipeChunkUsage, ...]) -> str:
    if not usage:
        return "none"
    total = sum(item.chunk_count for item in usage)
    details = ", ".join(
        f"recipe {item.recipe_id}: {item.chunk_count}" for item in usage
    )
    return f"yes ({total} total; {details})"


def _recipe_usage_document(
    usage: tuple[RecipeChunkUsage, ...],
) -> list[dict[str, int]]:
    return [{"recipe_id": item.recipe_id, "chunks": item.chunk_count} for item in usage]

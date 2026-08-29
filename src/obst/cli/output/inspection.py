"""Human and JSON output for structural container inspection."""

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
from obst.core.extensions import InspectionInterpretation
from obst.core.inspection import (
    ContainerInspection,
    InspectedRecipe,
    InspectedStage,
    RecipeChunkUsage,
)

INSPECTION_JSON_SCHEMA_VERSION = 6

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


def _summary_field(
    style: HumanOutputStyle,
    label: str,
    value: str,
) -> str:
    return f"{style.muted(label.ljust(29))} {value}"


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

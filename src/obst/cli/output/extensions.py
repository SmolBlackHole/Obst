# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Human and JSON output for active extension capabilities."""

from __future__ import annotations

import json
from io import StringIO

from obst.cli.presentation import (
    PLAIN_HUMAN_OUTPUT,
    HumanOutputStyle,
    escape_human_text,
    styled_yes_no,
)
from obst.core.extensions import ExtensionKind
from obst.core.registry import (
    CarrierCapability,
    ExtensionCapability,
    StageCapability,
    StreamProfileCapability,
)

EXTENSION_INVENTORY_JSON_SCHEMA_VERSION = 3


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
    groups = (
        ("Stages", ExtensionKind.STAGE),
        ("Stream profiles", ExtensionKind.STREAM_PROFILE),
        ("Carriers", ExtensionKind.CARRIER),
        ("Packagers", ExtensionKind.PACKAGER),
    )
    for heading, kind in groups:
        selected = tuple(
            capability for capability in capabilities if capability.kind is kind
        )
        if not selected:
            continue
        print(f"\n{style.heading(heading)}", file=output)
        for capability in selected:
            _render_capability(output, capability, style=style)
    return output.getvalue()


def _render_capability(
    output: StringIO,
    capability: ExtensionCapability,
    *,
    style: HumanOutputStyle,
) -> None:
    descriptor = capability.descriptor
    print(file=output)
    print(style.contributed(escape_human_text(capability.extension_id)), file=output)
    if descriptor.display_name is not None:
        print(
            style.field("Name", escape_human_text(descriptor.display_name)), file=output
        )
    if isinstance(capability, StageCapability):
        print(
            style.field(
                "Stage",
                f"encode {styled_yes_no(style, capability.encoder_available)}, "
                f"decode {styled_yes_no(style, capability.decoder_available)}",
            ),
            file=output,
        )
        print(
            style.field(
                "Parameters",
                "encode "
                f"{styled_yes_no(style, capability.parameter_encoder_available)}, "
                "decode "
                f"{styled_yes_no(style, capability.parameter_decoder_available)}, "
                "interpret "
                f"{styled_yes_no(style, capability.parameter_interpreter_available)}",
            ),
            file=output,
        )
    elif isinstance(capability, StreamProfileCapability):
        print(style.field("Kind", "stream profile"), file=output)
        print(
            style.field(
                "Metadata",
                "encode "
                f"{styled_yes_no(style, capability.metadata_encoder_available)}, "
                "decode "
                f"{styled_yes_no(style, capability.metadata_decoder_available)}, "
                "interpret "
                f"{styled_yes_no(style, capability.metadata_interpreter_available)}",
            ),
            file=output,
        )
    elif isinstance(capability, CarrierCapability):
        print(
            style.field(
                "Carrier",
                f"read {styled_yes_no(style, capability.reader_available)}, "
                f"write {styled_yes_no(style, capability.writer_available)}, "
                f"publish {styled_yes_no(style, capability.publisher_available)}",
            ),
            file=output,
        )
    else:
        print(
            style.field(
                "Packager",
                f"prepare {styled_yes_no(style, capability.provider_available)}",
            ),
            file=output,
        )
    if descriptor.summary is not None:
        print(
            style.field("Summary", escape_human_text(descriptor.summary)), file=output
        )
    if descriptor.specification_url is not None:
        print(
            style.field(
                "Specification", escape_human_text(descriptor.specification_url)
            ),
            file=output,
        )


def render_extension_inventory_json(
    capabilities: tuple[ExtensionCapability, ...],
) -> str:
    """Render provider-free registry capabilities as stable JSON."""
    document = {
        "schema_version": EXTENSION_INVENTORY_JSON_SCHEMA_VERSION,
        "extensions": [_capability_json(value) for value in capabilities],
    }
    return json.dumps(document, indent=4, sort_keys=True) + "\n"


def _capability_json(capability: ExtensionCapability) -> dict[str, object]:
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
            parameter_interpreter_available=capability.parameter_interpreter_available,
        )
    elif isinstance(capability, StreamProfileCapability):
        document.update(
            metadata_encoder_available=capability.metadata_encoder_available,
            metadata_decoder_available=capability.metadata_decoder_available,
            metadata_interpreter_available=capability.metadata_interpreter_available,
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


__all__ = ["render_extension_inventory_human", "render_extension_inventory_json"]

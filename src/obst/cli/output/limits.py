"""Human and JSON output for resource limit profiles."""

from __future__ import annotations

import json
from io import StringIO

from obst.cli.presentation import (
    PLAIN_HUMAN_OUTPUT,
    HumanOutputStyle,
    escape_human_text,
    format_integer,
    format_size,
    render_human_table,
    styled_yes_no,
)
from obst.resources import ResourceUnit
from obst.resources.profiles import (
    LimitProfileSource,
    LimitProfileStatus,
    LimitProfileView,
    ResourceLimitStatus,
)

LIMIT_PROFILE_LIST_JSON_SCHEMA_VERSION = 1
LIMIT_PROFILE_JSON_SCHEMA_VERSION = 1


def render_limit_profiles_human(
    profiles: tuple[LimitProfileStatus, ...],
    *,
    style: HumanOutputStyle = PLAIN_HUMAN_OUTPUT,
) -> str:
    """Render built-in, contributed and custom resource profiles."""
    output = StringIO()
    print(style.title("Resource limit profiles"), file=output)
    rows = tuple(
        (
            _styled_profile_id(style, profile),
            _styled_profile_source(style, profile.source),
            styled_yes_no(style, profile.active),
            styled_yes_no(style, profile.available),
            styled_yes_no(style, profile.mutable),
        )
        for profile in profiles
    )
    if not rows:
        print("\n  none", file=output)
        return output.getvalue()
    print(file=output)
    print(
        render_human_table(
            ("Profile", "Source", "Active", "Available", "Mutable"),
            rows,
        ),
        file=output,
    )
    return output.getvalue()


def render_limit_profiles_json(profiles: tuple[LimitProfileStatus, ...]) -> str:
    """Render the named resource-profile inventory as stable JSON."""
    document = {
        "schema_version": LIMIT_PROFILE_LIST_JSON_SCHEMA_VERSION,
        "profiles": [_profile_json(profile) for profile in profiles],
    }
    return json.dumps(document, indent=4, sort_keys=True) + "\n"


def render_limit_profile_human(
    view: LimitProfileView,
    *,
    style: HumanOutputStyle = PLAIN_HUMAN_OUTPUT,
) -> str:
    """Render one profile and its resolved or retained resource ceilings."""
    output = StringIO()
    profile = view.profile
    print(style.title("Resource limit profile"), file=output)
    print(style.field("Profile", _styled_profile_id(style, profile)), file=output)
    print(
        style.field("Source", _styled_profile_source(style, profile.source)),
        file=output,
    )
    print(style.field("Active", styled_yes_no(style, profile.active)), file=output)
    print(
        style.field("Available", styled_yes_no(style, profile.available)), file=output
    )
    if profile.summary is not None:
        print(style.field("Summary", escape_human_text(profile.summary)), file=output)
    print(f"\n{style.heading('Resources')}", file=output)
    if not view.resources:
        print("  none", file=output)
        return output.getvalue()

    owners = sorted(
        {resource.owner for resource in view.resources},
        key=lambda owner: (owner != "core", owner),
    )
    for owner in owners:
        resources = tuple(
            resource for resource in view.resources if resource.owner == owner
        )
        heading = style.success("Core") if owner == "core" else style.contributed(owner)
        print(f"\n{heading}", file=output)
        show_source = any(
            resource.profile_source != profile.profile_id for resource in resources
        )
        show_status = any(not resource.available for resource in resources)
        headers = ["Resource", "Default", "Maximum"]
        if show_source:
            headers.append("Source")
        if show_status:
            headers.append("Status")
        rows: list[tuple[str, ...]] = []
        for resource in resources:
            row = [
                _styled_resource_id(style, resource),
                _render_maximum(resource.default_maximum, resource.unit),
                _render_maximum(resource.resolved_maximum, resource.unit),
            ]
            if show_source:
                row.append(escape_human_text(resource.profile_source))
            if show_status:
                row.append(
                    style.success("available")
                    if resource.available
                    else style.error("unavailable")
                )
            rows.append(tuple(row))
        print(
            render_human_table(
                tuple(headers),
                tuple(rows),
                right_align=frozenset({1, 2}),
            ),
            file=output,
        )
    return output.getvalue()


def render_limit_profile_json(view: LimitProfileView) -> str:
    """Render one resource profile and its ceilings as stable JSON."""
    document = {
        "schema_version": LIMIT_PROFILE_JSON_SCHEMA_VERSION,
        "profile": _profile_json(view.profile),
        "resources": [_resource_json(value) for value in view.resources],
    }
    return json.dumps(document, indent=4, sort_keys=True) + "\n"


def _profile_json(profile: LimitProfileStatus) -> dict[str, object]:
    return {
        "id": profile.profile_id,
        "summary": profile.summary,
        "source": profile.source.value,
        "active": profile.active,
        "available": profile.available,
        "mutable": profile.mutable,
    }


def _resource_json(resource: ResourceLimitStatus) -> dict[str, object]:
    return {
        "id": resource.resource_id,
        "owner": resource.owner,
        "default_maximum": resource.default_maximum,
        "resolved_maximum": resource.resolved_maximum,
        "profile_source": resource.profile_source,
        "summary": resource.summary,
        "available": resource.available,
    }


def _render_maximum(maximum: int | None, unit: ResourceUnit | None) -> str:
    if maximum is None:
        return "none"
    if unit is ResourceUnit.BYTES:
        return format_size(maximum)
    return format_integer(maximum)


def _styled_profile_id(
    style: HumanOutputStyle,
    profile: LimitProfileStatus,
) -> str:
    value = escape_human_text(profile.profile_id)
    if profile.source is LimitProfileSource.DEFAULT:
        return style.success(value)
    if profile.source is LimitProfileSource.PLUGIN:
        return style.contributed(value)
    if profile.source is LimitProfileSource.CUSTOM:
        return style.identifier(value)
    return style.error(value)


def _styled_profile_source(
    style: HumanOutputStyle,
    source: LimitProfileSource,
) -> str:
    value = source.value
    if source is LimitProfileSource.DEFAULT:
        return style.success(value)
    if source is LimitProfileSource.PLUGIN:
        return style.contributed(value)
    if source is LimitProfileSource.CUSTOM:
        return style.identifier(value)
    return style.error(value)


def _styled_resource_id(
    style: HumanOutputStyle,
    resource: ResourceLimitStatus,
) -> str:
    value = escape_human_text(resource.resource_id.rsplit("/", 1)[-1])
    if not resource.available:
        return style.error(value)
    if resource.owner == "core":
        return style.success(value)
    return style.contributed(value)


__all__ = [
    "render_limit_profile_human",
    "render_limit_profile_json",
    "render_limit_profiles_human",
    "render_limit_profiles_json",
]

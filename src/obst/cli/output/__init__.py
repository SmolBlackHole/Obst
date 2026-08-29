"""CLI output projections grouped by host domain."""

from obst.cli.output.extensions import (
    render_extension_inventory_human,
    render_extension_inventory_json,
)
from obst.cli.output.inspection import (
    INSPECTION_JSON_SCHEMA_VERSION,
    render_inspection_human,
    render_inspection_json,
)
from obst.cli.output.limits import (
    render_limit_profile_human,
    render_limit_profile_json,
    render_limit_profiles_human,
    render_limit_profiles_json,
)
from obst.cli.output.plugins import (
    render_plugin_catalog_human,
    render_plugin_catalog_json,
    render_plugin_conformance_human,
    render_plugin_conformance_json,
)

__all__ = [
    "INSPECTION_JSON_SCHEMA_VERSION",
    "render_extension_inventory_human",
    "render_extension_inventory_json",
    "render_inspection_human",
    "render_inspection_json",
    "render_limit_profile_human",
    "render_limit_profile_json",
    "render_limit_profiles_human",
    "render_limit_profiles_json",
    "render_plugin_catalog_human",
    "render_plugin_catalog_json",
    "render_plugin_conformance_human",
    "render_plugin_conformance_json",
]

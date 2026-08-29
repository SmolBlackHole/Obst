# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Public resource contracts for the OBST reference toolchain."""

from obst.resources.policy import (
    DEFAULT_LIMIT_PROFILE,
    LimitProfile,
    ResourceAggregation,
    ResourceCatalog,
    ResourceContribution,
    ResourceDefinition,
    ResourceKind,
    ResourcePolicy,
    ResourceUnit,
    validate_resource_identifier,
)

__all__ = [
    "DEFAULT_LIMIT_PROFILE",
    "LimitProfile",
    "ResourceAggregation",
    "ResourceCatalog",
    "ResourceContribution",
    "ResourceDefinition",
    "ResourceKind",
    "ResourcePolicy",
    "ResourceUnit",
    "validate_resource_identifier",
]

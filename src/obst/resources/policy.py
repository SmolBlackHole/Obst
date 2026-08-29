"""Public resource contracts shared across the OBST toolchain."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import Enum
from types import MappingProxyType
from typing import Final, Self, cast

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

_LOCAL_ID = r"[a-z0-9]+(?:[._-][a-z0-9]+)*"
_EXTENSION_ID = rf"{_LOCAL_ID}(?:/{_LOCAL_ID})?@[1-9][0-9]*"
_IDENTIFIER_PATTERN = re.compile(rf"(?:{_LOCAL_ID}|{_EXTENSION_ID}/{_LOCAL_ID})")
_PROFILE_ID_PATTERN = _IDENTIFIER_PATTERN


def _require_optional_limit(name: str, value: object) -> None:
    if value is None:
        return
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer or None")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


class ResourceUnit(Enum):
    """Human presentation unit for one measured resource."""

    COUNT = "count"
    BYTES = "bytes"


class ResourceAggregation(Enum):
    """How operation-local observations combine for one resource."""

    TOTAL = "total"
    PEAK = "peak"


def validate_resource_identifier(identifier: object) -> str:
    """Validate and return one canonical resource identifier."""
    if type(identifier) is not str:
        raise TypeError("resource identifier must be an exact string")
    if _IDENTIFIER_PATTERN.fullmatch(identifier) is None:
        raise ValueError(f"invalid resource identifier: {identifier!r}")
    return identifier


@dataclass(frozen=True, slots=True)
class ResourceDefinition:
    """Stable identity and accounting semantics for one measured resource."""

    identifier: str
    default_maximum: int | None
    summary: str
    unit: ResourceUnit
    aggregation: ResourceAggregation

    def __post_init__(self) -> None:
        validate_resource_identifier(self.identifier)
        _require_optional_limit("resource default maximum", self.default_maximum)
        if type(self.summary) is not str:
            raise TypeError("resource summary must be an exact string")
        if not self.summary.strip():
            raise ValueError("resource summary cannot be empty")
        if type(self.unit) is not ResourceUnit:
            raise TypeError("resource unit must be an exact ResourceUnit")
        if type(self.aggregation) is not ResourceAggregation:
            raise TypeError("resource aggregation must be an exact ResourceAggregation")


class ResourceKind(Enum):
    """Extensible typed identity for one locally measured resource."""

    definition: ResourceDefinition

    def __new__(cls, definition: ResourceDefinition) -> Self:
        if type(definition) is not ResourceDefinition:
            raise TypeError(
                "resource kind values must be exact ResourceDefinition values"
            )
        member = object.__new__(cls)
        member._value_ = definition.identifier
        member.definition = definition
        return member

    def __str__(self) -> str:
        return self.definition.identifier

    @property
    def default_maximum(self) -> int | None:
        return self.definition.default_maximum

    @property
    def summary(self) -> str:
        return self.definition.summary

    @property
    def unit(self) -> ResourceUnit:
        return self.definition.unit

    @property
    def aggregation(self) -> ResourceAggregation:
        return self.definition.aggregation


@dataclass(frozen=True, slots=True)
class LimitProfile:
    """Named immutable overrides applied over contributed resource defaults."""

    profile_id: str
    summary: str
    overrides: tuple[tuple[ResourceKind, int | None], ...] = ()

    def __post_init__(self) -> None:
        if type(self.profile_id) is not str:
            raise TypeError("limit profile id must be an exact string")
        if _PROFILE_ID_PATTERN.fullmatch(self.profile_id) is None:
            raise ValueError(f"invalid limit profile id: {self.profile_id!r}")
        if type(self.summary) is not str:
            raise TypeError("limit profile summary must be an exact string")
        if not self.summary.strip():
            raise ValueError("limit profile summary cannot be empty")
        if type(self.overrides) is not tuple:
            raise TypeError("limit profile overrides must be an exact tuple")
        seen: set[ResourceKind] = set()
        for item in self.overrides:
            if type(item) is not tuple or len(item) != 2:
                raise TypeError("limit profile overrides must contain exact pairs")
            resource, maximum = item
            if not isinstance(cast(object, resource), ResourceKind):
                raise TypeError("limit profile resources must be ResourceKind members")
            _require_optional_limit("limit profile maximum", maximum)
            if resource in seen:
                raise ValueError(f"duplicate limit profile resource: {resource}")
            seen.add(resource)


DEFAULT_LIMIT_PROFILE: Final = LimitProfile(
    "default",
    "Built-in resource ceilings contributed by the active runtime.",
)


@dataclass(frozen=True, slots=True)
class ResourcePolicy:
    """Resolved immutable ceilings for one known resource catalog and profile."""

    resources: tuple[ResourceKind, ...]
    profile: LimitProfile = DEFAULT_LIMIT_PROFILE
    _maximums: Mapping[ResourceKind, int | None] = dataclass_field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if type(self.resources) is not tuple:
            raise TypeError("resource policy resources must be an exact tuple")
        if type(self.profile) is not LimitProfile:
            raise TypeError("resource policy profile must be an exact LimitProfile")
        by_identifier: dict[str, ResourceKind] = {}
        for resource in self.resources:
            if not isinstance(cast(object, resource), ResourceKind):
                raise TypeError("resource policy entries must be ResourceKind members")
            identifier = str(resource)
            if identifier in by_identifier:
                raise ValueError(f"duplicate resource identifier: {identifier}")
            by_identifier[identifier] = resource
        maximums = {resource: resource.default_maximum for resource in self.resources}
        for resource, maximum in self.profile.overrides:
            if resource not in maximums:
                raise ValueError(
                    f"limit profile {self.profile.profile_id} references unknown "
                    f"resource: {resource}"
                )
            maximums[resource] = maximum
        object.__setattr__(self, "_maximums", MappingProxyType(maximums))

    def maximum(self, resource: ResourceKind, /) -> int | None:
        """Return the resolved maximum for one resource in this policy."""
        if not isinstance(cast(object, resource), ResourceKind):
            raise TypeError("resource must be a ResourceKind member")
        try:
            return self._maximums[resource]
        except KeyError as exc:
            raise KeyError(
                f"resource is not declared by this policy: {resource}"
            ) from exc


@dataclass(frozen=True, slots=True)
class ResourceContribution:
    """Resources and inert named profiles published by one plugin."""

    resources: tuple[ResourceKind, ...] = ()
    profiles: tuple[LimitProfile, ...] = ()

    def __post_init__(self) -> None:
        if type(self.resources) is not tuple:
            raise TypeError("resource contribution resources must be an exact tuple")
        if type(self.profiles) is not tuple:
            raise TypeError("resource contribution profiles must be an exact tuple")
        if not self.resources and not self.profiles:
            raise ValueError("resource contribution cannot be empty")
        if any(
            not isinstance(cast(object, resource), ResourceKind)
            for resource in self.resources
        ):
            raise TypeError(
                "resource contribution entries must be ResourceKind members"
            )
        if any(type(profile) is not LimitProfile for profile in self.profiles):
            raise TypeError(
                "resource contribution profiles must be exact LimitProfile values"
            )


@dataclass(frozen=True, slots=True)
class ResourceCatalog:
    """Immutable resource and named-profile inventory for one plugin runtime."""

    resources: tuple[ResourceKind, ...]
    profiles: tuple[LimitProfile, ...]
    _resources_by_id: Mapping[str, ResourceKind] = dataclass_field(
        init=False,
        repr=False,
        compare=False,
    )
    _profiles_by_id: Mapping[str, LimitProfile] = dataclass_field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if type(self.resources) is not tuple:
            raise TypeError("resource catalog resources must be an exact tuple")
        if type(self.profiles) is not tuple:
            raise TypeError("resource catalog profiles must be an exact tuple")
        resources_by_id: dict[str, ResourceKind] = {}
        for resource in self.resources:
            if not isinstance(cast(object, resource), ResourceKind):
                raise TypeError("resource catalog entries must be ResourceKind members")
            identifier = str(resource)
            if identifier in resources_by_id:
                raise ValueError(f"duplicate resource identifier: {identifier}")
            resources_by_id[identifier] = resource
        profiles_by_id: dict[str, LimitProfile] = {}
        for profile in self.profiles:
            if type(profile) is not LimitProfile:
                raise TypeError(
                    "resource catalog profiles must be exact LimitProfile values"
                )
            if profile.profile_id in profiles_by_id:
                raise ValueError(f"duplicate limit profile id: {profile.profile_id}")
            profiles_by_id[profile.profile_id] = profile
            ResourcePolicy(self.resources, profile)
        if DEFAULT_LIMIT_PROFILE.profile_id not in profiles_by_id:
            raise ValueError("resource catalog must contain the default profile")
        object.__setattr__(
            self,
            "_resources_by_id",
            MappingProxyType(resources_by_id),
        )
        object.__setattr__(
            self,
            "_profiles_by_id",
            MappingProxyType(profiles_by_id),
        )

    def resource(self, identifier: str, /) -> ResourceKind:
        """Resolve one canonical resource identifier."""
        try:
            return self._resources_by_id[identifier]
        except KeyError as exc:
            raise KeyError(f"unknown resource: {identifier}") from exc

    def profile(self, profile_id: str, /) -> LimitProfile:
        """Resolve one named profile."""
        try:
            return self._profiles_by_id[profile_id]
        except KeyError as exc:
            raise KeyError(f"unknown limit profile: {profile_id}") from exc

    def policy(self, profile_id: str = "default", /) -> ResourcePolicy:
        """Resolve one named profile over this catalog's resource set."""
        return ResourcePolicy(self.resources, self.profile(profile_id))

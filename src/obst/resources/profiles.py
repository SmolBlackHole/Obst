"""Local named resource-profile state for an OBST toolchain host."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import cast

from obst.core.errors import ObstError
from obst.resources import (
    LimitProfile,
    ResourceCatalog,
    ResourceKind,
    ResourcePolicy,
    ResourceUnit,
    validate_resource_identifier,
)

LIMIT_STATE_SCHEMA_VERSION = 1


class LimitProfileSource(Enum):
    """Stable provenance category for one visible limit profile."""

    DEFAULT = "default"
    PLUGIN = "plugin"
    CUSTOM = "custom"
    UNAVAILABLE = "unavailable"


class LimitProfileStateError(ObstError):
    """Local named-profile state is invalid or cannot be persisted."""

    def __init__(self, state_path: Path, reason: str) -> None:
        self.state_path = state_path
        self.reason = reason
        super().__init__(f"cannot use limit state {state_path}: {reason}")


@dataclass(frozen=True, slots=True)
class LimitProfileStatus:
    """One built-in, contributed, custom or unavailable profile."""

    profile_id: str
    summary: str | None
    source: LimitProfileSource
    active: bool
    available: bool
    mutable: bool


@dataclass(frozen=True, slots=True)
class ResourceLimitStatus:
    """One resolved or retained resource ceiling shown by the host."""

    resource_id: str
    owner: str
    default_maximum: int | None
    resolved_maximum: int | None
    profile_source: str
    summary: str | None
    available: bool
    unit: ResourceUnit | None


@dataclass(frozen=True, slots=True)
class LimitProfileView:
    """One profile and the resource ceilings visible through it."""

    profile: LimitProfileStatus
    resources: tuple[ResourceLimitStatus, ...]


class LimitProfileManager:
    """Manage inert local overrides and resolve one operation policy."""

    def __init__(
        self,
        *,
        state_path: Path,
        active_profile_id: str,
        profiles: dict[str, dict[str, int | None]],
    ) -> None:
        self._state_path = state_path
        self._active_profile_id = active_profile_id
        self._profiles = profiles

    @classmethod
    def discover(cls, *, state_path: Path | None = None) -> LimitProfileManager:
        """Read local profile state without importing or activating plugins."""
        selected_path = state_path or default_limit_state_path()
        active_profile_id, profiles = _read_limit_state(selected_path)
        return cls(
            state_path=selected_path,
            active_profile_id=active_profile_id,
            profiles=profiles,
        )

    @property
    def state_path(self) -> Path:
        """Return the local profile-state file used by this manager."""
        return self._state_path

    @property
    def active_profile_id(self) -> str:
        """Return the persistently selected profile identifier."""
        return self._active_profile_id

    def profiles(self, catalog: ResourceCatalog) -> tuple[LimitProfileStatus, ...]:
        """Describe available profiles plus retained unavailable selection state."""
        catalog_profiles = {profile.profile_id: profile for profile in catalog.profiles}
        collisions = self._profiles.keys() & catalog_profiles.keys()
        if collisions:
            collision = min(collisions)
            raise LimitProfileStateError(
                self._state_path,
                f"custom profile conflicts with an available profile: {collision}",
            )
        statuses = [
            LimitProfileStatus(
                profile_id=profile.profile_id,
                summary=profile.summary,
                source=(
                    LimitProfileSource.DEFAULT
                    if profile.profile_id == "default"
                    else LimitProfileSource.PLUGIN
                ),
                active=profile.profile_id == self._active_profile_id,
                available=True,
                mutable=False,
            )
            for profile in catalog.profiles
        ]
        statuses.extend(
            LimitProfileStatus(
                profile_id=profile_id,
                summary="Local custom resource profile.",
                source=LimitProfileSource.CUSTOM,
                active=profile_id == self._active_profile_id,
                available=True,
                mutable=True,
            )
            for profile_id in self._profiles
        )
        known_ids = {status.profile_id for status in statuses}
        if self._active_profile_id not in known_ids:
            statuses.append(
                LimitProfileStatus(
                    profile_id=self._active_profile_id,
                    summary=None,
                    source=LimitProfileSource.UNAVAILABLE,
                    active=True,
                    available=False,
                    mutable=False,
                )
            )
        return tuple(sorted(statuses, key=lambda status: status.profile_id))

    def show(
        self,
        catalog: ResourceCatalog,
        profile_id: str | None = None,
    ) -> LimitProfileView:
        """Describe one profile and all available or retained resource ceilings."""
        selected_id = self._active_profile_id if profile_id is None else profile_id
        statuses = {status.profile_id: status for status in self.profiles(catalog)}
        try:
            status = statuses[selected_id]
        except KeyError as exc:
            raise LimitProfileStateError(
                self._state_path,
                f"unknown limit profile: {selected_id}",
            ) from exc
        resources_by_id = {str(resource): resource for resource in catalog.resources}
        custom_overrides = self._profiles.get(selected_id)
        if custom_overrides is None:
            if not status.available:
                return LimitProfileView(status, ())
            policy = catalog.policy(selected_id)
            available_resources = tuple(
                _available_resource_status(
                    resource,
                    policy.maximum(resource),
                    selected_id,
                )
                for resource in catalog.resources
            )
            return LimitProfileView(status, available_resources)

        typed_overrides = _resolve_overrides(custom_overrides, catalog)
        policy = ResourcePolicy(
            catalog.resources,
            LimitProfile(
                selected_id,
                "Local custom resource profile.",
                typed_overrides,
            ),
        )
        resource_statuses = [
            _available_resource_status(
                resource,
                policy.maximum(resource),
                (selected_id if str(resource) in custom_overrides else "default"),
            )
            for resource in catalog.resources
        ]
        resource_statuses.extend(
            ResourceLimitStatus(
                resource_id=resource_id,
                owner=_resource_owner(resource_id),
                default_maximum=None,
                resolved_maximum=maximum,
                profile_source=selected_id,
                summary=None,
                available=False,
                unit=None,
            )
            for resource_id, maximum in custom_overrides.items()
            if resource_id not in resources_by_id
        )
        return LimitProfileView(
            status,
            tuple(
                sorted(
                    resource_statuses,
                    key=lambda resource: resource.resource_id,
                )
            ),
        )

    def policy(self, catalog: ResourceCatalog) -> ResourcePolicy:
        """Resolve the persistently selected profile over one active catalog."""
        custom_overrides = self._profiles.get(self._active_profile_id)
        if custom_overrides is None:
            try:
                return catalog.policy(self._active_profile_id)
            except KeyError as exc:
                raise LimitProfileStateError(
                    self._state_path,
                    f"selected profile is unavailable: {self._active_profile_id}",
                ) from exc
        if any(
            profile.profile_id == self._active_profile_id
            for profile in catalog.profiles
        ):
            raise LimitProfileStateError(
                self._state_path,
                "custom profile conflicts with an available profile: "
                f"{self._active_profile_id}",
            )
        return ResourcePolicy(
            catalog.resources,
            LimitProfile(
                self._active_profile_id,
                "Local custom resource profile.",
                _resolve_overrides(custom_overrides, catalog),
            ),
        )

    def create(self, profile_id: str, catalog: ResourceCatalog) -> LimitProfileStatus:
        """Create one empty local custom profile."""
        _validate_profile_id(profile_id, self._state_path)
        if profile_id == "default":
            raise LimitProfileStateError(
                self._state_path, "default profile is immutable"
            )
        if profile_id in self._profiles or any(
            profile.profile_id == profile_id for profile in catalog.profiles
        ):
            raise LimitProfileStateError(
                self._state_path,
                f"limit profile already exists: {profile_id}",
            )
        updated = {**self._profiles, profile_id: {}}
        _write_limit_state(
            self._state_path,
            self._active_profile_id,
            updated,
        )
        self._profiles = updated
        return self._require_status(profile_id, catalog)

    def set(
        self,
        profile_id: str,
        resource_id: str,
        maximum: int | None,
        catalog: ResourceCatalog,
    ) -> ResourceLimitStatus:
        """Set one explicit local override on a custom profile."""
        if profile_id == "default":
            raise LimitProfileStateError(
                self._state_path, "default profile is immutable"
            )
        try:
            overrides = self._profiles[profile_id]
        except KeyError as exc:
            raise LimitProfileStateError(
                self._state_path,
                f"custom limit profile does not exist: {profile_id}",
            ) from exc
        if type(maximum) is not int and maximum is not None:
            raise TypeError("limit maximum must be an exact integer or None")
        if maximum is not None and maximum < 0:
            raise LimitProfileStateError(
                self._state_path, "limit maximum must be non-negative"
            )
        try:
            catalog.resource(resource_id)
        except KeyError:
            if resource_id not in overrides:
                raise LimitProfileStateError(
                    self._state_path,
                    f"unknown resource: {resource_id}",
                ) from None
        updated_overrides = {**overrides, resource_id: maximum}
        updated = {**self._profiles, profile_id: updated_overrides}
        _write_limit_state(
            self._state_path,
            self._active_profile_id,
            updated,
        )
        self._profiles = updated
        view = self.show(catalog, profile_id)
        return next(
            resource
            for resource in view.resources
            if resource.resource_id == resource_id
        )

    def use(self, profile_id: str, catalog: ResourceCatalog) -> LimitProfileStatus:
        """Persistently select one available built-in, contributed or custom profile."""
        status = self._require_status(profile_id, catalog)
        if not status.available:
            raise LimitProfileStateError(
                self._state_path,
                f"limit profile is unavailable: {profile_id}",
            )
        _write_limit_state(self._state_path, profile_id, self._profiles)
        self._active_profile_id = profile_id
        return self._require_status(profile_id, catalog)

    def delete(self, profile_id: str, catalog: ResourceCatalog) -> None:
        """Delete one inactive local custom profile."""
        if profile_id == "default":
            raise LimitProfileStateError(
                self._state_path, "default profile is immutable"
            )
        if profile_id not in self._profiles:
            raise LimitProfileStateError(
                self._state_path,
                f"custom limit profile does not exist: {profile_id}",
            )
        if profile_id == self._active_profile_id:
            raise LimitProfileStateError(
                self._state_path,
                "cannot delete the active profile; select another profile first",
            )
        updated = {
            existing_id: overrides
            for existing_id, overrides in self._profiles.items()
            if existing_id != profile_id
        }
        _write_limit_state(
            self._state_path,
            self._active_profile_id,
            updated,
        )
        self._profiles = updated
        self.profiles(catalog)

    def _require_status(
        self,
        profile_id: str,
        catalog: ResourceCatalog,
    ) -> LimitProfileStatus:
        try:
            return next(
                status
                for status in self.profiles(catalog)
                if status.profile_id == profile_id
            )
        except StopIteration as exc:
            raise LimitProfileStateError(
                self._state_path,
                f"unknown limit profile: {profile_id}",
            ) from exc


def default_limit_state_path() -> Path:
    """Return the platform-local named-profile state path."""
    override = os.environ.get("OBST_CONFIG_HOME")
    if override:
        return Path(override) / "limits.json"
    if os.name == "nt":
        root = os.environ.get("APPDATA")
        base = Path(root) if root else Path.home() / "AppData" / "Roaming"
        return base / "obst" / "limits.json"
    root = os.environ.get("XDG_CONFIG_HOME")
    base = Path(root) if root else Path.home() / ".config"
    return base / "obst" / "limits.json"


def _available_resource_status(
    resource: ResourceKind,
    maximum: int | None,
    profile_source: str,
) -> ResourceLimitStatus:
    identifier = str(resource)
    return ResourceLimitStatus(
        resource_id=identifier,
        owner=_resource_owner(identifier),
        default_maximum=resource.default_maximum,
        resolved_maximum=maximum,
        profile_source=profile_source,
        summary=resource.summary,
        available=True,
        unit=resource.unit,
    )


def _resource_owner(resource_id: str) -> str:
    owner, separator, _name = resource_id.rpartition("/")
    return owner if separator else "core"


def _resolve_overrides(
    overrides: dict[str, int | None],
    catalog: ResourceCatalog,
) -> tuple[tuple[ResourceKind, int | None], ...]:
    known: list[tuple[ResourceKind, int | None]] = []
    for resource_id, maximum in overrides.items():
        try:
            resource = catalog.resource(resource_id)
        except KeyError:
            continue
        known.append((resource, maximum))
    return tuple(sorted(known, key=lambda item: str(item[0])))


def _validate_profile_id(profile_id: object, state_path: Path) -> None:
    try:
        LimitProfile(cast(str, profile_id), "Local custom resource profile.")
    except (TypeError, ValueError) as exc:
        raise LimitProfileStateError(state_path, str(exc)) from exc


def _validate_resource_id(resource_id: object, state_path: Path) -> str:
    try:
        return validate_resource_identifier(resource_id)
    except (TypeError, ValueError) as exc:
        raise LimitProfileStateError(state_path, str(exc)) from exc


def _read_limit_state(
    state_path: Path,
) -> tuple[str, dict[str, dict[str, int | None]]]:
    try:
        loaded: object = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "default", {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LimitProfileStateError(
            state_path,
            f"cannot read valid JSON: {type(exc).__name__}: {exc}",
        ) from exc
    if type(loaded) is not dict:
        raise LimitProfileStateError(state_path, "document must be a JSON object")
    document = cast(dict[str, object], loaded)
    if set(document) != {"schema_version", "active_profile", "profiles"}:
        raise LimitProfileStateError(
            state_path,
            "document must contain exactly schema_version, active_profile and profiles",
        )
    if (
        type(document["schema_version"]) is not int
        or document["schema_version"] != LIMIT_STATE_SCHEMA_VERSION
    ):
        raise LimitProfileStateError(
            state_path, "unsupported limit-state schema version"
        )
    active_profile = document["active_profile"]
    _validate_profile_id(active_profile, state_path)
    loaded_profiles = document["profiles"]
    if type(loaded_profiles) is not dict:
        raise LimitProfileStateError(state_path, "profiles must be a JSON object")
    profiles: dict[str, dict[str, int | None]] = {}
    profile_order: list[str] = []
    for raw_profile_id, raw_overrides in cast(
        dict[object, object], loaded_profiles
    ).items():
        _validate_profile_id(raw_profile_id, state_path)
        profile_id = cast(str, raw_profile_id)
        profile_order.append(profile_id)
        if profile_id == "default":
            raise LimitProfileStateError(state_path, "default profile is immutable")
        if type(raw_overrides) is not dict:
            raise LimitProfileStateError(
                state_path,
                f"profile {profile_id} overrides must be a JSON object",
            )
        overrides: dict[str, int | None] = {}
        resource_order: list[str] = []
        for raw_resource_id, maximum in cast(
            dict[object, object], raw_overrides
        ).items():
            resource_id = _validate_resource_id(raw_resource_id, state_path)
            resource_order.append(resource_id)
            if type(maximum) is not int and maximum is not None:
                raise LimitProfileStateError(
                    state_path,
                    f"profile {profile_id} maximum for {resource_id} "
                    "must be an integer or null",
                )
            if maximum is not None and maximum < 0:
                raise LimitProfileStateError(
                    state_path,
                    f"profile {profile_id} maximum for {resource_id} "
                    "must be non-negative",
                )
            overrides[resource_id] = maximum
        if resource_order != sorted(overrides):
            raise LimitProfileStateError(
                state_path,
                f"profile {profile_id} resource identifiers must be sorted",
            )
        profiles[profile_id] = overrides
    if profile_order != sorted(profiles):
        raise LimitProfileStateError(state_path, "profile identifiers must be sorted")
    return cast(str, active_profile), profiles


def _write_limit_state(
    state_path: Path,
    active_profile_id: str,
    profiles: dict[str, dict[str, int | None]],
) -> None:
    document = {
        "schema_version": LIMIT_STATE_SCHEMA_VERSION,
        "active_profile": active_profile_id,
        "profiles": {
            profile_id: dict(sorted(overrides.items()))
            for profile_id, overrides in sorted(profiles.items())
        },
    }
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=state_path.parent,
            prefix=f".{state_path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                json.dump(document, output, indent=2, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, state_path)
        finally:
            temporary_path.unlink(missing_ok=True)
    except OSError as exc:
        raise LimitProfileStateError(
            state_path,
            f"cannot persist state: {type(exc).__name__}: {exc}",
        ) from exc


__all__ = [
    "LIMIT_STATE_SCHEMA_VERSION",
    "LimitProfileManager",
    "LimitProfileSource",
    "LimitProfileStateError",
    "LimitProfileStatus",
    "LimitProfileView",
    "ResourceLimitStatus",
    "default_limit_state_path",
]

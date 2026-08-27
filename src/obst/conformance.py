"""Public, runtime-independent helpers for extension conformance tests."""

from __future__ import annotations

from dataclasses import dataclass

from obst.core.errors import ObstError
from obst.core.extensions import Extension, ExtensionKind
from obst.core.model import Recipe, StageSpec
from obst.core.pipeline import decode_recipe, encode_recipe
from obst.core.registry import ExtensionRegistry


class ConformanceError(ObstError):
    """One extension failed a portable conformance case."""


@dataclass(frozen=True, slots=True)
class StageConformanceCase:
    """One known encoding and logical payload for a versioned Stage contract."""

    stage_id: str
    parameters: bytes
    logical: bytes
    encoded: bytes
    canonical_encoding: bool = False

    def __post_init__(self) -> None:
        if type(self.stage_id) is not str:
            raise TypeError("stage_id must be an exact string")
        for name, value in (
            ("parameters", self.parameters),
            ("logical", self.logical),
            ("encoded", self.encoded),
        ):
            if type(value) is not bytes:
                raise TypeError(f"{name} must be exact bytes")
        if type(self.canonical_encoding) is not bool:
            raise TypeError("canonical_encoding must be a boolean")


@dataclass(frozen=True, slots=True)
class StageConformanceResult:
    """Observed encoding produced while checking one Stage case."""

    encoded: bytes
    canonical_encoding_matched: bool | None


@dataclass(frozen=True, slots=True)
class PluginConformanceCaseResult:
    """Outcome of one plugin-published Stage conformance case."""

    stage_id: str
    passed: bool
    error: str | None


@dataclass(frozen=True, slots=True)
class PluginConformanceReport:
    """Renderer-neutral result of testing one installed plugin contribution."""

    plugin_name: str
    cases: tuple[PluginConformanceCaseResult, ...]

    @property
    def passed(self) -> bool:
        """Return whether every published case passed."""
        return all(case.passed for case in self.cases)


def check_stage_conformance(
    extension: Extension,
    case: StageConformanceCase,
) -> StageConformanceResult:
    """Check known decoding, local round trip and optional canonical encoding."""
    registry = ExtensionRegistry((extension,))
    provided_stage_ids = tuple(
        contribution.extension_id
        for contribution in registry.contributions()
        if contribution.kind is ExtensionKind.STAGE
    )
    if provided_stage_ids != (case.stage_id,):
        provided = ", ".join(provided_stage_ids) or "<none>"
        raise ConformanceError(
            f"case names {case.stage_id}, extension provides {provided}"
        )
    return _check_stage_conformance(registry, case)


def _check_stage_conformance(
    registry: ExtensionRegistry,
    case: StageConformanceCase,
) -> StageConformanceResult:
    """Check one Stage case against an already validated capability snapshot."""
    recipe = Recipe(0, (StageSpec(case.stage_id, case.parameters),))
    try:
        decoded = decode_recipe(
            case.encoded,
            recipe,
            registry,
            expected_size=len(case.logical),
        )
    except Exception as exc:
        raise ConformanceError(
            f"known encoding could not be decoded: {type(exc).__name__}: {exc}"
        ) from exc
    if decoded != case.logical:
        raise ConformanceError("known encoding did not recover the expected bytes")
    try:
        observed_encoding = encode_recipe(case.logical, recipe, registry)
        round_trip = decode_recipe(
            observed_encoding,
            recipe,
            registry,
            expected_size=len(case.logical),
        )
    except Exception as exc:
        raise ConformanceError(
            f"local round trip failed: {type(exc).__name__}: {exc}"
        ) from exc
    if round_trip != case.logical:
        raise ConformanceError("locally encoded bytes did not round-trip")
    canonical_match = (
        observed_encoding == case.encoded if case.canonical_encoding else None
    )
    if canonical_match is False:
        raise ConformanceError("encoder did not reproduce the canonical encoding")
    return StageConformanceResult(observed_encoding, canonical_match)


def check_plugin_conformance(
    plugin_name: str,
    registry: ExtensionRegistry,
    cases: tuple[StageConformanceCase, ...],
) -> PluginConformanceReport:
    """Run portable cases against extensions returned by one plugin factory."""
    stage_ids = {
        capability.extension_id
        for capability in registry.capabilities()
        if capability.kind is ExtensionKind.STAGE
    }
    results: list[PluginConformanceCaseResult] = []
    for case in cases:
        if case.stage_id not in stage_ids:
            results.append(
                PluginConformanceCaseResult(
                    case.stage_id,
                    False,
                    "plugin does not provide the Stage named by this case",
                )
            )
            continue
        try:
            _check_stage_conformance(registry, case)
        except ConformanceError as exc:
            results.append(PluginConformanceCaseResult(case.stage_id, False, str(exc)))
        else:
            results.append(PluginConformanceCaseResult(case.stage_id, True, None))
    return PluginConformanceReport(plugin_name, tuple(results))


__all__ = [
    "ConformanceError",
    "PluginConformanceCaseResult",
    "PluginConformanceReport",
    "StageConformanceCase",
    "StageConformanceResult",
    "check_plugin_conformance",
    "check_stage_conformance",
]

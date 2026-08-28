"""Immutable language-neutral extension conformance values."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Literal, Protocol, cast

from obst.core.extensions import InspectionInterpretation
from obst.core.model import validate_extension_id

type StageDirection = Literal["encode", "decode"]

_CASE_ID_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?")


class ConformanceCaseKind(StrEnum):
    """Closed portable case kinds understood by the generic runner."""

    STAGE_KNOWN_ANSWER = "stage-known-answer"
    STAGE_PARAMETERS = "stage-parameters"
    STAGE_BIND_REJECTION = "stage-bind-rejection"
    STAGE_DECODE_REJECTION = "stage-decode-rejection"
    STAGE_OUTPUT_LIMIT = "stage-output-limit"
    STREAM_METADATA = "stream-metadata"
    STREAM_METADATA_REJECTION = "stream-metadata-rejection"
    CONTAINER_STRUCTURE = "container-structure"
    CONTAINER_RECOVERY = "container-recovery"


class ContainerStructuralOutcome(StrEnum):
    """Portable structural result expected for complete container bytes."""

    ACCEPT = "accept"
    INVALID_STRUCTURE = "invalid_structure"
    CORRUPT = "corrupt"
    TRUNCATED = "truncated"
    UNSUPPORTED_VERSION = "unsupported_version"


@dataclass(frozen=True, slots=True)
class StageKnownAnswerCase:
    """Known logical and encoded bytes for one Stage contract."""

    case_id: str
    extension_id: str
    parameters: bytes
    logical: bytes
    encoded: bytes
    canonical_encoding: bool = False
    kind: ClassVar[ConformanceCaseKind] = ConformanceCaseKind.STAGE_KNOWN_ANSWER

    def __post_init__(self) -> None:
        _validate_case_identity(self.case_id, self.extension_id)
        _require_bytes("parameters", self.parameters)
        _require_bytes("logical", self.logical)
        _require_bytes("encoded", self.encoded)
        if type(self.canonical_encoding) is not bool:
            raise TypeError("canonical_encoding must be a boolean")


@dataclass(frozen=True, slots=True)
class StageParametersCase:
    """Canonical typed-parameter and optional interpretation round trip."""

    case_id: str
    extension_id: str
    parameters: bytes
    interpretation: InspectionInterpretation | None = None
    kind: ClassVar[ConformanceCaseKind] = ConformanceCaseKind.STAGE_PARAMETERS

    def __post_init__(self) -> None:
        _validate_case_identity(self.case_id, self.extension_id)
        _require_bytes("parameters", self.parameters)
        if (
            self.interpretation is not None
            and type(self.interpretation) is not InspectionInterpretation
        ):
            raise TypeError(
                "interpretation must be an exact InspectionInterpretation or None"
            )


@dataclass(frozen=True, slots=True)
class StageBindRejectionCase:
    """Parameters that every named Stage binding direction must reject."""

    case_id: str
    extension_id: str
    parameters: bytes
    directions: tuple[StageDirection, ...]
    kind: ClassVar[ConformanceCaseKind] = ConformanceCaseKind.STAGE_BIND_REJECTION

    def __post_init__(self) -> None:
        _validate_case_identity(self.case_id, self.extension_id)
        _require_bytes("parameters", self.parameters)
        _validate_directions(self.directions)


@dataclass(frozen=True, slots=True)
class StageDecodeRejectionCase:
    """Encoded Stage bytes that a decoder must reject."""

    case_id: str
    extension_id: str
    parameters: bytes
    encoded: bytes
    max_output_size: int
    kind: ClassVar[ConformanceCaseKind] = ConformanceCaseKind.STAGE_DECODE_REJECTION

    def __post_init__(self) -> None:
        _validate_case_identity(self.case_id, self.extension_id)
        _require_bytes("parameters", self.parameters)
        _require_bytes("encoded", self.encoded)
        _require_non_negative_integer("max_output_size", self.max_output_size)


@dataclass(frozen=True, slots=True)
class StageOutputLimitCase:
    """One Stage operation that must honor a host output ceiling."""

    case_id: str
    extension_id: str
    direction: StageDirection
    parameters: bytes
    data: bytes
    max_output_size: int
    kind: ClassVar[ConformanceCaseKind] = ConformanceCaseKind.STAGE_OUTPUT_LIMIT

    def __post_init__(self) -> None:
        _validate_case_identity(self.case_id, self.extension_id)
        if self.direction not in ("encode", "decode"):
            raise ValueError("direction must be encode or decode")
        _require_bytes("parameters", self.parameters)
        _require_bytes("data", self.data)
        _require_non_negative_integer("max_output_size", self.max_output_size)


@dataclass(frozen=True, slots=True)
class StreamMetadataCase:
    """Canonical stream metadata and optional interpretation."""

    case_id: str
    extension_id: str
    metadata: bytes
    interpretation: InspectionInterpretation | None = None
    kind: ClassVar[ConformanceCaseKind] = ConformanceCaseKind.STREAM_METADATA

    def __post_init__(self) -> None:
        _validate_case_identity(self.case_id, self.extension_id)
        _require_bytes("metadata", self.metadata)
        if (
            self.interpretation is not None
            and type(self.interpretation) is not InspectionInterpretation
        ):
            raise TypeError(
                "interpretation must be an exact InspectionInterpretation or None"
            )


@dataclass(frozen=True, slots=True)
class StreamMetadataRejectionCase:
    """Stream metadata that typed decoding must reject."""

    case_id: str
    extension_id: str
    metadata: bytes
    require_interpreter_error: bool = False
    kind: ClassVar[ConformanceCaseKind] = ConformanceCaseKind.STREAM_METADATA_REJECTION

    def __post_init__(self) -> None:
        _validate_case_identity(self.case_id, self.extension_id)
        _require_bytes("metadata", self.metadata)
        if type(self.require_interpreter_error) is not bool:
            raise TypeError("require_interpreter_error must be a boolean")


@dataclass(frozen=True, slots=True)
class ContainerStructureCase:
    """Complete OBST bytes with one exact expected structural outcome."""

    case_id: str
    container: bytes
    outcome: ContainerStructuralOutcome
    missing_required_stages: tuple[str, ...] = ()
    kind: ClassVar[ConformanceCaseKind] = ConformanceCaseKind.CONTAINER_STRUCTURE

    def __post_init__(self) -> None:
        _validate_case_id(self.case_id)
        _require_bytes("container", self.container)
        if type(self.outcome) is not ContainerStructuralOutcome:
            raise TypeError("outcome must be an exact ContainerStructuralOutcome")
        _validate_extension_ids(
            "missing_required_stages",
            self.missing_required_stages,
        )
        if (
            self.outcome is not ContainerStructuralOutcome.ACCEPT
            and self.missing_required_stages
        ):
            raise ValueError(
                "rejected container cases cannot declare missing required stages"
            )


@dataclass(frozen=True, slots=True)
class RecoveredStreamExpectation:
    """Expected logical bytes for one stream in a complete container vector."""

    stream_id: int
    logical: bytes

    def __post_init__(self) -> None:
        _require_non_negative_integer("stream_id", self.stream_id)
        _require_bytes("logical", self.logical)


@dataclass(frozen=True, slots=True)
class ContainerRecoveryCase:
    """Complete OBST bytes recovered through an explicitly composed registry."""

    case_id: str
    container: bytes
    required_extensions: tuple[str, ...]
    streams: tuple[RecoveredStreamExpectation, ...]
    kind: ClassVar[ConformanceCaseKind] = ConformanceCaseKind.CONTAINER_RECOVERY

    def __post_init__(self) -> None:
        _validate_case_id(self.case_id)
        _require_bytes("container", self.container)
        if type(self.required_extensions) is not tuple:
            raise TypeError("required_extensions must be a tuple")
        for extension_id in self.required_extensions:
            validate_extension_id(extension_id)
        if tuple(sorted(set(self.required_extensions))) != self.required_extensions:
            raise ValueError("required_extensions must be sorted and unique")
        if type(self.streams) is not tuple or not self.streams:
            raise TypeError("streams must be a non-empty tuple")
        if any(
            type(stream) is not RecoveredStreamExpectation for stream in self.streams
        ):
            raise TypeError(
                "streams must contain exact RecoveredStreamExpectation values"
            )
        stream_ids = tuple(stream.stream_id for stream in self.streams)
        if tuple(sorted(set(stream_ids))) != stream_ids:
            raise ValueError("recovered stream ids must be sorted and unique")


type PortableConformanceCase = (
    StageKnownAnswerCase
    | StageParametersCase
    | StageBindRejectionCase
    | StageDecodeRejectionCase
    | StageOutputLimitCase
    | StreamMetadataCase
    | StreamMetadataRejectionCase
    | ContainerStructureCase
    | ContainerRecoveryCase
)


class _ExtensionCase(Protocol):
    extension_id: str


@dataclass(frozen=True, slots=True)
class ConformanceSuite:
    """One immutable distribution-owned corpus of portable cases."""

    cases: tuple[PortableConformanceCase, ...]

    def __post_init__(self) -> None:
        if type(self.cases) is not tuple:
            raise TypeError("cases must be a tuple")
        allowed = (
            StageKnownAnswerCase,
            StageParametersCase,
            StageBindRejectionCase,
            StageDecodeRejectionCase,
            StageOutputLimitCase,
            StreamMetadataCase,
            StreamMetadataRejectionCase,
            ContainerStructureCase,
            ContainerRecoveryCase,
        )
        if any(type(case) not in allowed for case in self.cases):
            raise TypeError("cases contain an unsupported conformance value")
        case_ids = tuple(case.case_id for case in self.cases)
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("conformance case ids must be unique")


@dataclass(frozen=True, slots=True)
class ConformanceCaseResult:
    """Outcome of one portable plugin conformance case."""

    case_id: str
    extension_id: str | None
    kind: ConformanceCaseKind
    passed: bool
    error: str | None


@dataclass(frozen=True, slots=True)
class ConformanceReport:
    """Renderer-neutral result of executing one conformance suite."""

    cases: tuple[ConformanceCaseResult, ...]

    @property
    def passed(self) -> bool:
        """Return whether every published case passed."""
        return all(case.passed for case in self.cases)


def case_extension_id(case: PortableConformanceCase) -> str | None:
    """Return the directly tested Extension ID, if the case owns one."""
    if type(case) in {ContainerStructureCase, ContainerRecoveryCase}:
        return None
    return cast(_ExtensionCase, case).extension_id


def _validate_case_identity(case_id: str, extension_id: str) -> None:
    _validate_case_id(case_id)
    validate_extension_id(extension_id)


def _validate_case_id(case_id: object) -> None:
    if type(case_id) is not str or _CASE_ID_PATTERN.fullmatch(case_id) is None:
        raise ValueError(
            "case_id must be 1..128 lowercase ASCII letters, digits or '-'"
        )


def _require_bytes(name: str, value: object) -> None:
    if type(value) is not bytes:
        raise TypeError(f"{name} must be exact bytes")


def _require_non_negative_integer(name: str, value: object) -> None:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _validate_directions(directions: object) -> None:
    if type(directions) is not tuple or not directions:
        raise TypeError("directions must be a non-empty tuple")
    typed_directions = cast(tuple[object, ...], directions)
    if any(direction not in ("encode", "decode") for direction in typed_directions):
        raise ValueError("directions may contain only encode and decode")
    canonical = tuple(
        direction for direction in ("encode", "decode") if direction in typed_directions
    )
    if typed_directions != canonical:
        raise ValueError("directions must be canonical and unique")


def _validate_extension_ids(name: str, values: object) -> None:
    if type(values) is not tuple:
        raise TypeError(f"{name} must be a tuple")
    typed_values = cast(tuple[object, ...], values)
    if any(type(value) is not str for value in typed_values):
        raise TypeError(f"{name} must contain exact strings")
    extension_ids = cast(tuple[str, ...], typed_values)
    for extension_id in extension_ids:
        validate_extension_id(extension_id)
    if tuple(sorted(set(extension_ids))) != extension_ids:
        raise ValueError(f"{name} must be sorted and unique")


__all__ = [
    "ConformanceCaseKind",
    "ConformanceCaseResult",
    "ConformanceReport",
    "ConformanceSuite",
    "ContainerRecoveryCase",
    "ContainerStructuralOutcome",
    "ContainerStructureCase",
    "PortableConformanceCase",
    "RecoveredStreamExpectation",
    "StageBindRejectionCase",
    "StageDecodeRejectionCase",
    "StageDirection",
    "StageKnownAnswerCase",
    "StageOutputLimitCase",
    "StageParametersCase",
    "StreamMetadataCase",
    "StreamMetadataRejectionCase",
    "case_extension_id",
]

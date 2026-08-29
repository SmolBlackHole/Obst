"""Public contracts and provider helpers for ID-bearing OBST extensions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Literal, Protocol, cast, runtime_checkable

from obst.core.errors import ProviderRejectedError
from obst.core.model import validate_extension_id, validate_specification_url
from obst.core.resources import (
    CoreResource,
    ResourceLimitError,
    require_resource_limit,
)

if TYPE_CHECKING:
    from obst.core.io import BinaryReader, BinaryWriter
    from obst.core.packaging import PackageWriteOperation

type InspectionValue = str | int | bool | None


class ExtensionKind(Enum):
    """Closed set of extension kinds understood by the runtime registry."""

    STAGE = auto()
    STREAM_PROFILE = auto()
    CARRIER = auto()
    PACKAGER = auto()


@dataclass(frozen=True, slots=True)
class InspectionField:
    """One renderer-neutral field produced by an optional interpreter."""

    name: str
    value: InspectionValue

    def __post_init__(self) -> None:
        _validate_inspection_field(self)


@dataclass(frozen=True, slots=True)
class InspectionInterpretation:
    """Optional meaning layered over authoritative opaque bytes."""

    label: str | None = None
    fields: tuple[InspectionField, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        _validate_inspection_interpretation(self)


@dataclass(frozen=True, slots=True)
class ExtensionDescriptor:
    """Local descriptive metadata for one extension contract."""

    display_name: str | None = None
    summary: str | None = None
    specification_url: str | None = None

    def __post_init__(self) -> None:
        _validate_optional_text("display_name", self.display_name)
        _validate_optional_text("summary", self.summary)
        if self.specification_url is not None:
            validate_specification_url(self.specification_url)


class Extension(Protocol):
    """Self-describing extension identity shared by every extension kind."""

    @property
    def extension_id(self) -> str:
        """Return the canonical language-neutral extension contract ID."""
        ...

    @property
    def descriptor(self) -> ExtensionDescriptor:
        """Return local non-authoritative display and specification metadata."""
        ...

    @property
    def kind(self) -> ExtensionKind:
        """Return the registry kind owned by this extension object."""
        ...


class StageExtension(Extension, Protocol):
    """Identify an extension intended to provide reversible Stage capabilities."""


class StreamProfileExtension(Extension, Protocol):
    """Identify an extension intended to provide stream-profile capabilities."""


class CarrierExtension(Extension, Protocol):
    """Identify an extension intended to provide runtime carrier capabilities."""


class PackagerExtension(Extension, Protocol):
    """Identify an extension intended to provide packaging-policy capabilities."""


@runtime_checkable
class BoundCarrierReader(Protocol):
    """Own one bound carrier input session and its binary endpoint."""

    def open(self) -> BinaryReader:
        """Open and return the binary container source exactly once."""
        ...

    def close(self) -> None:
        """Release the input session without changing container bytes."""
        ...


@runtime_checkable
class BoundCarrierWriter[Result](Protocol):
    """Own one progressively visible carrier output session."""

    def open(self) -> BinaryWriter:
        """Open and return the binary container destination exactly once."""
        ...

    def finish(self) -> Result:
        """Finish a successfully written stream without promising rollback."""
        ...

    def close(self) -> None:
        """Release the session after failure or successful completion."""
        ...


@runtime_checkable
class BoundCarrierPublisher[Publication](Protocol):
    """Own one transactionally published carrier output session."""

    def open(self) -> BinaryWriter:
        """Open an unpublished binary destination exactly once."""
        ...

    def commit(self) -> Publication:
        """Publish the completed output atomically under the carrier contract."""
        ...

    def abort(self) -> None:
        """Discard unpublished output after a failed operation."""
        ...


@runtime_checkable
class CarrierReaderProvider[Request](Protocol):
    """Bind one provider-specific request to a container input session."""

    def bind_reader(self, request: Request, /) -> BoundCarrierReader:
        """Validate the request and return a fresh bound reader session."""
        ...


@runtime_checkable
class CarrierWriterProvider[Request, Result](Protocol):
    """Bind one provider-specific request to a streaming output session."""

    def bind_writer(self, request: Request, /) -> BoundCarrierWriter[Result]:
        """Validate the request and return a fresh bound writer session."""
        ...


@runtime_checkable
class CarrierPublisherProvider[Request, Publication](Protocol):
    """Bind one provider-specific request to a publication transaction."""

    def bind_publisher(
        self,
        request: Request,
        /,
    ) -> BoundCarrierPublisher[Publication]:
        """Validate the request and return a fresh bound publisher session."""
        ...


@runtime_checkable
class PackagerProvider[Request](Protocol):
    """Prepare one provider-specific request for deterministic container writing."""

    def prepare_package(self, request: Request, /) -> PackageWriteOperation:
        """Validate the request and return one prepared write operation."""
        ...


@runtime_checkable
class StageParameterEncoder[Parameters](Protocol):
    """Encode one typed stage-parameter value as authoritative wire bytes."""

    def encode_parameters(self, value: Parameters, /) -> bytes:
        """Return the canonical wire representation of one parameter value."""
        ...


@runtime_checkable
class StageParameterDecoder[Parameters](Protocol):
    """Decode authoritative stage-parameter bytes into a typed local value."""

    def decode_parameters(self, parameters: bytes, /) -> Parameters:
        """Validate and decode one exact parameter block."""
        ...


@runtime_checkable
class StageParameterInterpreter(Protocol):
    """Interpret opaque stage parameters for inspection tooling."""

    def interpret_parameters(
        self,
        parameters: bytes,
        /,
    ) -> InspectionInterpretation:
        """Return optional meaning without changing authoritative bytes."""
        ...


@runtime_checkable
class StreamMetadataEncoder[Metadata](Protocol):
    """Encode one typed stream-metadata value as authoritative wire bytes."""

    def encode_metadata(self, value: Metadata, /) -> bytes:
        """Return the canonical wire representation of one metadata value."""
        ...


@runtime_checkable
class StreamMetadataDecoder[Metadata](Protocol):
    """Decode authoritative stream metadata into a typed local value."""

    def decode_metadata(self, metadata: bytes, /) -> Metadata:
        """Validate and decode one exact metadata block."""
        ...


@runtime_checkable
class StreamMetadataInterpreter(Protocol):
    """Interpret opaque stream metadata for inspection tooling."""

    def interpret_metadata(
        self,
        metadata: bytes,
        /,
    ) -> InspectionInterpretation:
        """Return optional meaning without changing authoritative bytes."""
        ...


@runtime_checkable
class BoundStageEncoder(Protocol):
    """Encode chunks with one already validated set of opaque parameters."""

    def encode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        """Encode one chunk within an output-size ceiling."""
        ...


@runtime_checkable
class BoundStageDecoder(Protocol):
    """Decode chunks with one already validated set of opaque parameters."""

    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        """Decode one chunk within an output-size ceiling."""
        ...


@runtime_checkable
class BoundStageCodec(BoundStageEncoder, BoundStageDecoder, Protocol):
    """Execute both directions for one already bound stage contract."""


@runtime_checkable
class StageEncoderProvider(Protocol):
    """Bind exact opaque parameters to one forward stage executor."""

    def bind_encoder(self, parameters: bytes, /) -> BoundStageEncoder:
        """Validate parameters and return a reusable forward executor."""
        ...


@runtime_checkable
class StageDecoderProvider(Protocol):
    """Bind exact opaque parameters to one inverse stage executor."""

    def bind_decoder(self, parameters: bytes, /) -> BoundStageDecoder:
        """Validate parameters and return a reusable inverse executor."""
        ...


@runtime_checkable
class StageCodecProvider(StageEncoderProvider, StageDecoderProvider, Protocol):
    """Bind both directions of one stage contract."""


def require_no_parameters(stage_id: str, parameters: bytes) -> None:
    """Reject opaque parameters for a stage whose wire contract has none."""
    if parameters:
        raise ProviderRejectedError(f"{stage_id} does not accept parameters")


def require_stage_output_size(
    stage_id: str,
    observed_size: int,
    *,
    max_output_size: int | None,
    operation: Literal["encode", "decode"],
) -> None:
    """Refuse a stage output above the host-supplied output ceiling."""
    validate_extension_id(stage_id)
    if type(observed_size) is not int:
        raise TypeError("observed_size must be an integer")
    if observed_size < 0:
        raise ValueError("observed_size must be non-negative")
    if max_output_size is not None:
        if type(max_output_size) is not int:
            raise TypeError("max_output_size must be an integer or None")
        if max_output_size < 0:
            raise ValueError("max_output_size must be non-negative")
    if operation not in {"encode", "decode"}:
        raise ValueError("operation must be 'encode' or 'decode'")
    try:
        require_resource_limit(
            CoreResource.INTERMEDIATE_BYTES,
            scope=stage_id,
            maximum=max_output_size,
            observed=observed_size,
            phase=f"stage_{operation}",
        )
    except ResourceLimitError as resource_limit:
        raise _ProviderOutputLimitRejected(resource_limit) from resource_limit


def extend_stage_output(
    output: bytearray,
    part: bytes,
    *,
    stage_id: str,
    max_output_size: int | None,
    operation: Literal["encode", "decode"],
) -> None:
    """Append exact bytes after checking the resulting stage output size."""
    if type(output) is not bytearray:
        raise TypeError("output must be an exact bytearray")
    if type(part) is not bytes:
        raise TypeError("part must be exact bytes")
    require_stage_output_size(
        stage_id,
        len(output) + len(part),
        max_output_size=max_output_size,
        operation=operation,
    )
    output.extend(part)


def provider_rejection_resource_limit(
    rejection: ProviderRejectedError,
    /,
) -> ResourceLimitError | None:
    """Return only a core-authored output-limit rejection, without dispatch."""
    if type(rejection) is not _ProviderOutputLimitRejected:
        return None
    return rejection.core_resource_limit


def _validate_optional_text(name: str, value: object) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} cannot be empty")


def _validate_interpretation_fields(value: object) -> None:
    if type(value) is not tuple:
        raise TypeError("inspection interpretation fields must be a tuple")
    items = cast(tuple[object, ...], value)
    for item in items:
        if type(item) is not InspectionField:
            raise TypeError(
                "inspection interpretation fields must contain exact "
                "InspectionField values"
            )
        _validate_inspection_field(item)


def _validate_inspection_field(field: InspectionField) -> None:
    if type(field.name) is not str:
        raise TypeError("inspection field name must be an exact string")
    if not field.name:
        raise ValueError("inspection field name cannot be empty")
    if type(field.value) not in {str, int, bool, type(None)}:
        raise TypeError(
            "inspection field value must be an exact str, int, bool or None"
        )


def _validate_inspection_interpretation(
    interpretation: InspectionInterpretation,
) -> None:
    _validate_interpretation_fields(interpretation.fields)
    names = tuple(field.name for field in interpretation.fields)
    if len(set(names)) != len(names):
        raise ValueError("inspection interpretation field names must be unique")
    for name, value in (
        ("label", interpretation.label),
        ("error", interpretation.error),
    ):
        if value is not None and type(value) is not str:
            raise TypeError(f"inspection interpretation {name} must be an exact string")
        if value == "":
            raise ValueError(f"inspection interpretation {name} cannot be empty")


class _ProviderOutputLimitRejected(ProviderRejectedError):
    """Carry a core-authored stage output ceiling through provider execution."""

    def __init__(self, resource_limit: ResourceLimitError) -> None:
        self.core_resource_limit = resource_limit
        super().__init__(str(resource_limit))

    @property
    def resource_limit(self) -> ResourceLimitError:
        return self.core_resource_limit

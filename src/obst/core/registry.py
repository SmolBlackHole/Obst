"""Explicit composition and immutable lookup of trusted OBST extensions."""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Never, cast

from obst.core.errors import (
    ExtensionContractError,
    ExtensionRegistrationError,
    MissingExtensionCapabilityError,
    MissingStageError,
)
from obst.core.extensions import (
    CarrierPublisherProvider,
    CarrierReaderProvider,
    CarrierWriterProvider,
    Extension,
    ExtensionDescriptor,
    ExtensionKind,
    PackagerProvider,
    StageDecoderProvider,
    StageEncoderProvider,
    StageParameterDecoder,
    StageParameterEncoder,
    StageParameterInterpreter,
    StreamMetadataDecoder,
    StreamMetadataEncoder,
    StreamMetadataInterpreter,
)
from obst.core.model import validate_extension_id

_UNKNOWN_EXTENSION_ID = "<unknown>"

_STAGE_ENCODER = "stage_encoder"
_STAGE_DECODER = "stage_decoder"
_PARAMETER_ENCODER = "parameter_encoder"
_PARAMETER_DECODER = "parameter_decoder"
_PARAMETER_INTERPRETER = "parameter_interpreter"
_METADATA_ENCODER = "metadata_encoder"
_METADATA_DECODER = "metadata_decoder"
_METADATA_INTERPRETER = "metadata_interpreter"
_CARRIER_READER = "carrier_reader"
_CARRIER_WRITER = "carrier_writer"
_CARRIER_PUBLISHER = "carrier_publisher"
_PACKAGER_PROVIDER = "packager_provider"


@dataclass(frozen=True, slots=True)
class _CapabilitySpec:
    key: str
    label: str
    member: str
    duplicate_label: str | None = None


_EXTENSION_KINDS = tuple(ExtensionKind)
_KIND_LABELS: Mapping[ExtensionKind, str] = MappingProxyType(
    {
        ExtensionKind.STAGE: "stage",
        ExtensionKind.STREAM_PROFILE: "stream profile",
        ExtensionKind.CARRIER: "carrier",
        ExtensionKind.PACKAGER: "packager",
    }
)
_CAPABILITY_SPECS: Mapping[ExtensionKind, tuple[_CapabilitySpec, ...]] = (
    MappingProxyType(
        {
            ExtensionKind.STAGE: (
                _CapabilitySpec(
                    _STAGE_ENCODER,
                    "encoder provider",
                    "bind_encoder",
                    "encoder",
                ),
                _CapabilitySpec(
                    _STAGE_DECODER,
                    "decoder provider",
                    "bind_decoder",
                    "decoder",
                ),
                _CapabilitySpec(
                    _PARAMETER_ENCODER,
                    "parameter encoder",
                    "encode_parameters",
                ),
                _CapabilitySpec(
                    _PARAMETER_DECODER,
                    "parameter decoder",
                    "decode_parameters",
                ),
                _CapabilitySpec(
                    _PARAMETER_INTERPRETER,
                    "parameter interpreter",
                    "interpret_parameters",
                ),
            ),
            ExtensionKind.STREAM_PROFILE: (
                _CapabilitySpec(
                    _METADATA_ENCODER,
                    "metadata encoder",
                    "encode_metadata",
                ),
                _CapabilitySpec(
                    _METADATA_DECODER,
                    "metadata decoder",
                    "decode_metadata",
                ),
                _CapabilitySpec(
                    _METADATA_INTERPRETER,
                    "metadata interpreter",
                    "interpret_metadata",
                ),
            ),
            ExtensionKind.CARRIER: (
                _CapabilitySpec(
                    _CARRIER_READER,
                    "carrier reader provider",
                    "bind_reader",
                ),
                _CapabilitySpec(
                    _CARRIER_WRITER,
                    "carrier writer provider",
                    "bind_writer",
                ),
                _CapabilitySpec(
                    _CARRIER_PUBLISHER,
                    "carrier publisher provider",
                    "bind_publisher",
                ),
            ),
            ExtensionKind.PACKAGER: (
                _CapabilitySpec(
                    _PACKAGER_PROVIDER,
                    "packager provider",
                    "prepare_package",
                ),
            ),
        }
    )
)


class ExtensionRegistryBuilder:
    """Compose self-describing extension objects before freezing a registry."""

    def __init__(self, extensions: Iterable[Extension] = ()) -> None:
        self._by_kind = _empty_capability_maps()
        self._contributions: list[ExtensionContribution] = []
        for extension in extensions:
            self.register(extension)

    def register(self, extension: Extension) -> None:
        """Register every capability offered by one extension object."""
        contribution = _register_extension(self._by_kind, extension)
        self._contributions.append(contribution)

    def build(self) -> ExtensionRegistry:
        """Freeze the current capability records into an immutable snapshot."""
        return ExtensionRegistry(
            _RegistrySnapshot(
                by_kind=_copy_capability_maps(self._by_kind),
                contributions=tuple(self._contributions),
            )
        )


class ExtensionRegistry:
    """Immutable runtime lookup for explicitly composed capabilities."""

    __slots__ = ("_by_kind", "_contributions")

    def __init__(
        self,
        extensions: Iterable[Extension] | _RegistrySnapshot = (),
    ) -> None:
        snapshot = (
            extensions
            if isinstance(extensions, _RegistrySnapshot)
            else _compose_extensions(extensions)
        )
        self._by_kind = MappingProxyType(
            {
                kind: MappingProxyType(dict(snapshot.by_kind[kind]))
                for kind in _EXTENSION_KINDS
            }
        )
        self._contributions = tuple(snapshot.contributions)

    def can_encode(self, stage_id: str) -> bool:
        return self._provider(ExtensionKind.STAGE, stage_id, _STAGE_ENCODER) is not None

    def can_decode(self, stage_id: str) -> bool:
        return self._provider(ExtensionKind.STAGE, stage_id, _STAGE_DECODER) is not None

    def require_encoder_provider(self, stage_id: str) -> StageEncoderProvider:
        provider = self._provider(ExtensionKind.STAGE, stage_id, _STAGE_ENCODER)
        if provider is None:
            raise MissingStageError(stage_id, capability="encoder")
        return cast(StageEncoderProvider, provider)

    def require_decoder_provider(self, stage_id: str) -> StageDecoderProvider:
        provider = self._provider(ExtensionKind.STAGE, stage_id, _STAGE_DECODER)
        if provider is None:
            raise MissingStageError(stage_id, capability="decoder")
        return cast(StageDecoderProvider, provider)

    def get_stage_parameter_interpreter(
        self,
        stage_id: str,
    ) -> StageParameterInterpreter | None:
        """Return a stage interpreter without invoking extension code."""
        return cast(
            StageParameterInterpreter | None,
            self._provider(ExtensionKind.STAGE, stage_id, _PARAMETER_INTERPRETER),
        )

    def get_stage_parameter_encoder(
        self,
        stage_id: str,
    ) -> StageParameterEncoder[Never] | None:
        """Return a typed-parameter author without invoking extension code."""
        return cast(
            StageParameterEncoder[Never] | None,
            self._provider(ExtensionKind.STAGE, stage_id, _PARAMETER_ENCODER),
        )

    def get_stage_parameter_decoder(
        self,
        stage_id: str,
    ) -> StageParameterDecoder[object] | None:
        """Return a typed-parameter decoder without invoking extension code."""
        return cast(
            StageParameterDecoder[object] | None,
            self._provider(ExtensionKind.STAGE, stage_id, _PARAMETER_DECODER),
        )

    def get_stream_metadata_interpreter(
        self,
        stream_type: str,
    ) -> StreamMetadataInterpreter | None:
        """Return a stream interpreter without invoking extension code."""
        return cast(
            StreamMetadataInterpreter | None,
            self._provider(
                ExtensionKind.STREAM_PROFILE,
                stream_type,
                _METADATA_INTERPRETER,
            ),
        )

    def get_stream_metadata_encoder(
        self,
        stream_type: str,
    ) -> StreamMetadataEncoder[Never] | None:
        """Return a typed-metadata author without invoking extension code."""
        return cast(
            StreamMetadataEncoder[Never] | None,
            self._provider(
                ExtensionKind.STREAM_PROFILE,
                stream_type,
                _METADATA_ENCODER,
            ),
        )

    def get_stream_metadata_decoder(
        self,
        stream_type: str,
    ) -> StreamMetadataDecoder[object] | None:
        """Return a typed-metadata decoder without invoking extension code."""
        return cast(
            StreamMetadataDecoder[object] | None,
            self._provider(
                ExtensionKind.STREAM_PROFILE,
                stream_type,
                _METADATA_DECODER,
            ),
        )

    def get_carrier_reader_provider(
        self,
        carrier_id: str,
    ) -> CarrierReaderProvider[Never] | None:
        """Return a carrier reader provider without binding a request."""
        return cast(
            CarrierReaderProvider[Never] | None,
            self._provider(ExtensionKind.CARRIER, carrier_id, _CARRIER_READER),
        )

    def require_carrier_reader_provider(
        self,
        carrier_id: str,
    ) -> CarrierReaderProvider[Never]:
        """Return the selected reader provider or fail explicitly."""
        return cast(
            CarrierReaderProvider[Never],
            self._require_runtime_provider(
                ExtensionKind.CARRIER,
                carrier_id,
                _CARRIER_READER,
                "carrier reader",
            ),
        )

    def get_carrier_writer_provider(
        self,
        carrier_id: str,
    ) -> CarrierWriterProvider[Never, object] | None:
        """Return a streaming carrier writer provider without binding a request."""
        return cast(
            CarrierWriterProvider[Never, object] | None,
            self._provider(ExtensionKind.CARRIER, carrier_id, _CARRIER_WRITER),
        )

    def require_carrier_writer_provider(
        self,
        carrier_id: str,
    ) -> CarrierWriterProvider[Never, object]:
        """Return the selected streaming writer provider or fail explicitly."""
        return cast(
            CarrierWriterProvider[Never, object],
            self._require_runtime_provider(
                ExtensionKind.CARRIER,
                carrier_id,
                _CARRIER_WRITER,
                "carrier writer",
            ),
        )

    def get_carrier_publisher_provider(
        self,
        carrier_id: str,
    ) -> CarrierPublisherProvider[Never, object] | None:
        """Return a transactional publisher provider without binding a request."""
        return cast(
            CarrierPublisherProvider[Never, object] | None,
            self._provider(ExtensionKind.CARRIER, carrier_id, _CARRIER_PUBLISHER),
        )

    def require_carrier_publisher_provider(
        self,
        carrier_id: str,
    ) -> CarrierPublisherProvider[Never, object]:
        """Return the selected transactional publisher provider or fail explicitly."""
        return cast(
            CarrierPublisherProvider[Never, object],
            self._require_runtime_provider(
                ExtensionKind.CARRIER,
                carrier_id,
                _CARRIER_PUBLISHER,
                "carrier publisher",
            ),
        )

    def get_packager_provider(
        self,
        packager_id: str,
    ) -> PackagerProvider[Never] | None:
        """Return a packaging-policy provider without preparing an operation."""
        return cast(
            PackagerProvider[Never] | None,
            self._provider(ExtensionKind.PACKAGER, packager_id, _PACKAGER_PROVIDER),
        )

    def require_packager_provider(
        self,
        packager_id: str,
    ) -> PackagerProvider[Never]:
        """Return the selected packager provider or fail explicitly."""
        return cast(
            PackagerProvider[Never],
            self._require_runtime_provider(
                ExtensionKind.PACKAGER,
                packager_id,
                _PACKAGER_PROVIDER,
                "packager provider",
            ),
        )

    def get_descriptor(self, extension_id: str) -> ExtensionDescriptor | None:
        for kind in _EXTENSION_KINDS:
            capabilities = self._by_kind[kind].get(extension_id)
            if capabilities is not None:
                return capabilities.descriptor
        return None

    def capabilities(self) -> tuple[ExtensionCapability, ...]:
        """Return a provider-free, deterministic inventory of this registry."""
        inventory = (
            _inventory_capability(kind, extension_id, capabilities)
            for kind in _EXTENSION_KINDS
            for extension_id, capabilities in self._by_kind[kind].items()
        )
        return tuple(sorted(inventory, key=lambda item: item.extension_id))

    def contributions(self) -> tuple[ExtensionContribution, ...]:
        """Return validated trusted objects with their captured identities."""
        return self._contributions

    def _provider(
        self,
        kind: ExtensionKind,
        extension_id: str,
        capability: str,
    ) -> object | None:
        extension = self._by_kind[kind].get(extension_id)
        return None if extension is None else extension.providers.get(capability)

    def _require_runtime_provider(
        self,
        kind: Literal[ExtensionKind.CARRIER, ExtensionKind.PACKAGER],
        extension_id: str,
        key: str,
        capability: str,
    ) -> object:
        provider = self._provider(kind, extension_id, key)
        if provider is None:
            raise MissingExtensionCapabilityError(
                extension_id,
                capability=capability,
            )
        return provider


@dataclass(frozen=True, slots=True)
class StageCapability:
    """Provider-free availability facts for one registered stage ID."""

    extension_id: str
    kind: Literal[ExtensionKind.STAGE]
    descriptor: ExtensionDescriptor
    encoder_available: bool
    decoder_available: bool
    parameter_encoder_available: bool
    parameter_decoder_available: bool
    parameter_interpreter_available: bool


@dataclass(frozen=True, slots=True)
class StreamProfileCapability:
    """Provider-free availability facts for one registered stream-profile ID."""

    extension_id: str
    kind: Literal[ExtensionKind.STREAM_PROFILE]
    descriptor: ExtensionDescriptor
    metadata_encoder_available: bool
    metadata_decoder_available: bool
    metadata_interpreter_available: bool


@dataclass(frozen=True, slots=True)
class CarrierCapability:
    """Provider-free availability facts for one registered carrier ID."""

    extension_id: str
    kind: Literal[ExtensionKind.CARRIER]
    descriptor: ExtensionDescriptor
    reader_available: bool
    writer_available: bool
    publisher_available: bool


@dataclass(frozen=True, slots=True)
class PackagerCapability:
    """Provider-free availability facts for one registered packager ID."""

    extension_id: str
    kind: Literal[ExtensionKind.PACKAGER]
    descriptor: ExtensionDescriptor
    provider_available: bool


type ExtensionCapability = (
    StageCapability | StreamProfileCapability | CarrierCapability | PackagerCapability
)


@dataclass(frozen=True, slots=True)
class ExtensionContribution:
    """One trusted extension object paired with its validated identity snapshot."""

    extension_id: str
    kind: ExtensionKind
    descriptor: ExtensionDescriptor
    extension: Extension = field(repr=False, compare=False)

    def get_optional_callable_provider(
        self,
        member: str,
        /,
        *,
        capability: str,
    ) -> Extension | None:
        """Return this provider when it exposes a callable optional capability."""
        try:
            inspect.getattr_static(self.extension, member)
        except AttributeError:
            return None
        try:
            operation = getattr(self.extension, member)
        except Exception as exc:
            raise ExtensionContractError(
                self.extension_id,
                capability,
                f"cannot access {member}: {type(exc).__name__}: {exc}",
            ) from exc
        if not callable(operation):
            raise ExtensionContractError(
                self.extension_id,
                capability,
                f"{member} must be callable",
            )
        return self.extension


@dataclass(frozen=True, slots=True)
class _RegisteredCapabilities:
    descriptor: ExtensionDescriptor
    providers: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _RegistrySnapshot:
    by_kind: Mapping[ExtensionKind, Mapping[str, _RegisteredCapabilities]]
    contributions: tuple[ExtensionContribution, ...]


def _empty_capability_maps() -> dict[
    ExtensionKind,
    dict[str, _RegisteredCapabilities],
]:
    return {kind: {} for kind in _EXTENSION_KINDS}


def _copy_capability_maps(
    by_kind: Mapping[ExtensionKind, Mapping[str, _RegisteredCapabilities]],
) -> dict[ExtensionKind, dict[str, _RegisteredCapabilities]]:
    return {kind: dict(by_kind[kind]) for kind in _EXTENSION_KINDS}


def _compose_extensions(extensions: Iterable[Extension]) -> _RegistrySnapshot:
    by_kind = _empty_capability_maps()
    contributions: list[ExtensionContribution] = []
    for extension in extensions:
        contributions.append(_register_extension(by_kind, extension))
    return _RegistrySnapshot(
        by_kind=_copy_capability_maps(by_kind),
        contributions=tuple(contributions),
    )


def _register_extension(
    by_kind: dict[ExtensionKind, dict[str, _RegisteredCapabilities]],
    extension: Extension,
) -> ExtensionContribution:
    contribution = _inspect_contribution(extension)
    _reject_kind_conflict(by_kind, contribution)
    registered = by_kind[contribution.kind]
    existing = registered.get(contribution.extension_id)
    if existing is not None and existing.descriptor != contribution.descriptor:
        raise ExtensionRegistrationError(
            contribution.extension_id,
            "conflicting descriptor",
        )
    providers = {} if existing is None else dict(existing.providers)
    for spec in _CAPABILITY_SPECS[contribution.kind]:
        provider = contribution.get_optional_callable_provider(
            spec.member,
            capability=spec.label,
        )
        if provider is None:
            continue
        if spec.key in providers:
            raise ExtensionRegistrationError(
                contribution.extension_id,
                f"duplicate {spec.duplicate_label or spec.label}",
            )
        providers[spec.key] = provider
    registered[contribution.extension_id] = _RegisteredCapabilities(
        descriptor=contribution.descriptor,
        providers=MappingProxyType(providers),
    )
    return contribution


def _reject_kind_conflict(
    by_kind: Mapping[ExtensionKind, Mapping[str, _RegisteredCapabilities]],
    contribution: ExtensionContribution,
) -> None:
    for kind in _EXTENSION_KINDS:
        if kind != contribution.kind and contribution.extension_id in by_kind[kind]:
            raise ExtensionRegistrationError(
                contribution.extension_id,
                f"the ID is already registered as a {_KIND_LABELS[kind]}",
            )


def _inventory_capability(
    kind: ExtensionKind,
    extension_id: str,
    capabilities: _RegisteredCapabilities,
) -> ExtensionCapability:
    available = capabilities.providers.__contains__
    if kind is ExtensionKind.STAGE:
        return StageCapability(
            extension_id=extension_id,
            kind=kind,
            descriptor=capabilities.descriptor,
            encoder_available=available(_STAGE_ENCODER),
            decoder_available=available(_STAGE_DECODER),
            parameter_encoder_available=available(_PARAMETER_ENCODER),
            parameter_decoder_available=available(_PARAMETER_DECODER),
            parameter_interpreter_available=available(_PARAMETER_INTERPRETER),
        )
    if kind is ExtensionKind.STREAM_PROFILE:
        return StreamProfileCapability(
            extension_id=extension_id,
            kind=kind,
            descriptor=capabilities.descriptor,
            metadata_encoder_available=available(_METADATA_ENCODER),
            metadata_decoder_available=available(_METADATA_DECODER),
            metadata_interpreter_available=available(_METADATA_INTERPRETER),
        )
    if kind is ExtensionKind.CARRIER:
        return CarrierCapability(
            extension_id=extension_id,
            kind=kind,
            descriptor=capabilities.descriptor,
            reader_available=available(_CARRIER_READER),
            writer_available=available(_CARRIER_WRITER),
            publisher_available=available(_CARRIER_PUBLISHER),
        )
    return PackagerCapability(
        extension_id=extension_id,
        kind=kind,
        descriptor=capabilities.descriptor,
        provider_available=available(_PACKAGER_PROVIDER),
    )


def _inspect_contribution(extension: Extension) -> ExtensionContribution:
    extension_id = _require_extension_id(extension)
    descriptor = _require_exact_attribute(
        extension,
        extension_id,
        "descriptor",
        ExtensionDescriptor,
    )
    kind = _require_attribute(extension, extension_id, "kind")
    if type(kind) is not ExtensionKind:
        raise ExtensionContractError(
            extension_id,
            "identity",
            "kind must be an exact ExtensionKind member",
        )
    return ExtensionContribution(extension_id, kind, descriptor, extension)


def _require_extension_id(extension: object) -> str:
    value = _require_attribute(extension, _UNKNOWN_EXTENSION_ID, "extension_id")
    if type(value) is not str:
        raise ExtensionContractError(
            _UNKNOWN_EXTENSION_ID,
            "identity",
            "extension_id must be an exact string",
        )
    try:
        validate_extension_id(value)
    except (TypeError, ValueError) as exc:
        raise ExtensionContractError(value, "identity", str(exc)) from exc
    return value


def _require_exact_attribute[T](
    extension: object,
    extension_id: str,
    member: str,
    expected_type: type[T],
) -> T:
    value = _require_attribute(extension, extension_id, member)
    if type(value) is not expected_type:
        raise ExtensionContractError(
            extension_id,
            "identity",
            f"{member} must be an exact {expected_type.__name__}",
        )
    return value


def _require_attribute(
    extension: object,
    extension_id: str,
    member: str,
) -> object:
    try:
        return getattr(extension, member)
    except Exception as exc:
        raise ExtensionContractError(
            extension_id,
            "identity",
            f"cannot access {member}: {type(exc).__name__}: {exc}",
        ) from exc

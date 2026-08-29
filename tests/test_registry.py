# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

from typing import cast

import pytest

from obst.core import (
    BoundCarrierPublisher,
    BoundCarrierReader,
    BoundCarrierWriter,
    BoundStageDecoder,
    BoundStageEncoder,
    CarrierCapability,
    CoreResource,
    Extension,
    ExtensionContractError,
    ExtensionDescriptor,
    ExtensionKind,
    ExtensionRegistrationError,
    InspectionInterpretation,
    MissingExtensionCapabilityError,
    MissingStageError,
    ObstError,
    PackagerCapability,
    PackageWriteOperation,
    ProviderRejectedError,
    ResourceLimitError,
    StageCapability,
    StreamProfileCapability,
    require_no_parameters,
    require_stage_output_size,
)
from obst.core.registry import ExtensionRegistry, ExtensionRegistryBuilder
from tests.support_extensions import (
    CompressionExtension,
    DeltaExtension,
    IdentityExtension,
)

_CUSTOM_STAGE_ID = "org.example/identity@1"
_CUSTOM_STAGE_DESCRIPTOR = ExtensionDescriptor(
    display_name="Identity",
    summary="Return exact input bytes.",
    specification_url="https://example.org/obst/identity-v1",
)
_PROFILE_ID = "org.example/profile@1"
_PROFILE_DESCRIPTOR = ExtensionDescriptor(display_name="Example profile")
_CARRIER_ID = "org.example/carrier@1"
_CARRIER_DESCRIPTOR = ExtensionDescriptor(display_name="Example carrier")
_PACKAGER_ID = "org.example/packager@1"
_PACKAGER_DESCRIPTOR = ExtensionDescriptor(display_name="Example packager")


def test_runtime_descriptor_is_not_limited_by_manifest_url_width() -> None:
    specification_url = "https://example.org/" + "a" * 65_536

    descriptor = ExtensionDescriptor(specification_url=specification_url)

    assert descriptor.specification_url == specification_url


class _IdentityEncoder:
    def encode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        return data


class _IdentityDecoder:
    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        return data


class _StageIdentity:
    extension_id = _CUSTOM_STAGE_ID
    descriptor = _CUSTOM_STAGE_DESCRIPTOR
    kind = ExtensionKind.STAGE


class _IdentityEncoderExtension(_StageIdentity):
    bind_calls = 0

    def bind_encoder(self, parameters: bytes, /) -> BoundStageEncoder:
        self.bind_calls += 1
        require_no_parameters(self.extension_id, parameters)
        return _IdentityEncoder()


class _IdentityDecoderExtension(_StageIdentity):
    def bind_decoder(self, parameters: bytes, /) -> BoundStageDecoder:
        require_no_parameters(self.extension_id, parameters)
        return _IdentityDecoder()


class _IdentityCodecExtension(_IdentityEncoderExtension, _IdentityDecoderExtension):
    pass


class _ParameterInterpreterExtension(_StageIdentity):
    calls = 0

    def interpret_parameters(
        self,
        parameters: bytes,
        /,
    ) -> InspectionInterpretation:
        self.calls += 1
        raise AssertionError("registry lookup must not invoke extension code")


class _ParameterEncoderExtension(_StageIdentity):
    def encode_parameters(self, value: str, /) -> bytes:
        return value.encode()


class _ParameterDecoderExtension(_StageIdentity):
    def decode_parameters(self, parameters: bytes, /) -> str:
        return parameters.decode()


class _ProfileExtension:
    extension_id = _PROFILE_ID
    descriptor = _PROFILE_DESCRIPTOR
    kind = ExtensionKind.STREAM_PROFILE


class _CarrierExtension:
    extension_id = _CARRIER_ID
    descriptor = _CARRIER_DESCRIPTOR
    kind = ExtensionKind.CARRIER


class _CarrierReaderExtension(_CarrierExtension):
    def bind_reader(self, request: object, /) -> BoundCarrierReader:
        raise AssertionError("registry lookup must not bind a carrier")


class _CarrierWriterExtension(_CarrierExtension):
    def bind_writer(self, request: object, /) -> BoundCarrierWriter[object]:
        raise AssertionError("registry lookup must not bind a carrier")


class _CarrierPublisherExtension(_CarrierExtension):
    def bind_publisher(self, request: object, /) -> BoundCarrierPublisher[object]:
        raise AssertionError("registry lookup must not bind a carrier")


class _PackagerExtension:
    extension_id = _PACKAGER_ID
    descriptor = _PACKAGER_DESCRIPTOR
    kind = ExtensionKind.PACKAGER

    def prepare_package(self, request: object, /) -> PackageWriteOperation:
        raise AssertionError("registry lookup must not prepare a package")


class _MetadataInterpreterExtension(_ProfileExtension):
    calls = 0

    def interpret_metadata(
        self,
        metadata: bytes,
        /,
    ) -> InspectionInterpretation:
        self.calls += 1
        raise AssertionError("registry lookup must not invoke extension code")


class _MetadataEncoderExtension(_ProfileExtension):
    def encode_metadata(self, value: str, /) -> bytes:
        return value.encode()


class _MetadataDecoderExtension(_ProfileExtension):
    def decode_metadata(self, metadata: bytes, /) -> str:
        return metadata.decode()


class _CountingShapeEncoderExtension(_IdentityEncoderExtension):
    member_accesses = 0

    def __getattribute__(self, name: str) -> object:
        if name == "bind_encoder":
            accesses = object.__getattribute__(self, "member_accesses")
            object.__setattr__(self, "member_accesses", accesses + 1)
        return object.__getattribute__(self, name)


class _NonCallableEncoderExtension(_StageIdentity):
    bind_encoder = 2


class _NonCallableDecoderExtension(_StageIdentity):
    bind_decoder = 2


class _NonCallableParameterInterpreterExtension(_StageIdentity):
    interpret_parameters = 2


class _NonCallableParameterEncoderExtension(_StageIdentity):
    encode_parameters = 2


class _NonCallableParameterDecoderExtension(_StageIdentity):
    decode_parameters = 2


class _NonCallableMetadataInterpreterExtension(_ProfileExtension):
    interpret_metadata = 2


class _NonCallableMetadataEncoderExtension(_ProfileExtension):
    encode_metadata = 2


class _NonCallableMetadataDecoderExtension(_ProfileExtension):
    decode_metadata = 2


class _NonCallableCarrierReaderExtension(_CarrierExtension):
    bind_reader = 2


class _NonCallableCarrierWriterExtension(_CarrierExtension):
    bind_writer = 2


class _NonCallableCarrierPublisherExtension(_CarrierExtension):
    bind_publisher = 2


class _NonCallablePackagerExtension:
    extension_id = _PACKAGER_ID
    descriptor = _PACKAGER_DESCRIPTOR
    kind = ExtensionKind.PACKAGER
    prepare_package = 2


@pytest.mark.parametrize(
    ("extension", "stage_id"),
    (
        (IdentityExtension(), IdentityExtension.extension_id),
        (DeltaExtension(), DeltaExtension.extension_id),
        (CompressionExtension(), CompressionExtension.extension_id),
    ),
)
def test_direct_registry_construction_exposes_neutral_test_capabilities(
    extension: Extension,
    stage_id: str,
) -> None:
    registry = ExtensionRegistry((extension,))

    assert registry.can_encode(stage_id)
    assert registry.can_decode(stage_id)
    assert registry.get_descriptor(stage_id) == extension.descriptor


def test_capability_inventory_is_sorted_and_provider_free() -> None:
    registry = ExtensionRegistry(
        (
            _PackagerExtension(),
            _MetadataInterpreterExtension(),
            _MetadataEncoderExtension(),
            _MetadataDecoderExtension(),
            _CarrierPublisherExtension(),
            _CarrierReaderExtension(),
            _CarrierWriterExtension(),
            _IdentityDecoderExtension(),
            _IdentityEncoderExtension(),
            _ParameterEncoderExtension(),
            _ParameterDecoderExtension(),
        )
    )

    capabilities = registry.capabilities()

    assert tuple(capability.extension_id for capability in capabilities) == (
        _CARRIER_ID,
        _CUSTOM_STAGE_ID,
        _PACKAGER_ID,
        _PROFILE_ID,
    )
    carrier, stage, packager, profile = capabilities
    assert isinstance(carrier, CarrierCapability)
    assert carrier.reader_available
    assert carrier.writer_available
    assert carrier.publisher_available
    assert isinstance(stage, StageCapability)
    assert stage.encoder_available
    assert stage.decoder_available
    assert stage.parameter_encoder_available
    assert stage.parameter_decoder_available
    assert not stage.parameter_interpreter_available
    assert isinstance(packager, PackagerCapability)
    assert packager.provider_available
    assert isinstance(profile, StreamProfileCapability)
    assert profile.metadata_encoder_available
    assert profile.metadata_decoder_available
    assert profile.metadata_interpreter_available


def test_builder_snapshots_split_stage_directions_immutably() -> None:
    encoder = _IdentityEncoderExtension()
    builder = ExtensionRegistryBuilder((encoder,))
    encoder_only = builder.build()

    assert encoder_only.can_encode(_CUSTOM_STAGE_ID)
    assert not encoder_only.can_decode(_CUSTOM_STAGE_ID)
    with pytest.raises(MissingStageError, match="missing stage decoder"):
        encoder_only.require_decoder_provider(_CUSTOM_STAGE_ID)

    decoder = _IdentityDecoderExtension()
    builder.register(decoder)
    complete = builder.build()

    assert not encoder_only.can_decode(_CUSTOM_STAGE_ID)
    assert complete.can_decode(_CUSTOM_STAGE_ID)
    assert complete.require_encoder_provider(_CUSTOM_STAGE_ID) is encoder
    assert complete.require_decoder_provider(_CUSTOM_STAGE_ID) is decoder
    assert tuple(
        contribution.extension for contribution in encoder_only.contributions()
    ) == (encoder,)
    assert tuple(
        contribution.extension for contribution in complete.contributions()
    ) == (encoder, decoder)


def test_contribution_exposes_optional_callable_without_invoking_it() -> None:
    extension = _IdentityEncoderExtension()
    contribution = ExtensionRegistry((extension,)).contributions()[0]

    assert contribution.extension_id == _CUSTOM_STAGE_ID
    assert contribution.kind is ExtensionKind.STAGE
    assert contribution.descriptor == _CUSTOM_STAGE_DESCRIPTOR

    assert (
        contribution.get_optional_callable_provider(
            "bind_encoder",
            capability="encoder provider",
        )
        is extension
    )
    assert (
        contribution.get_optional_callable_provider(
            "bind_decoder",
            capability="decoder provider",
        )
        is None
    )
    assert extension.bind_calls == 0


def test_builder_snapshots_complementary_carrier_capabilities_immutably() -> None:
    reader = _CarrierReaderExtension()
    builder = ExtensionRegistryBuilder((reader,))
    reader_only = builder.build()

    assert reader_only.get_carrier_reader_provider(_CARRIER_ID) is reader
    assert reader_only.get_carrier_writer_provider(_CARRIER_ID) is None
    with pytest.raises(
        MissingExtensionCapabilityError,
        match="missing extension carrier writer",
    ):
        reader_only.require_carrier_writer_provider(_CARRIER_ID)

    writer = _CarrierWriterExtension()
    publisher = _CarrierPublisherExtension()
    builder.register(writer)
    builder.register(publisher)
    complete = builder.build()

    assert reader_only.get_carrier_writer_provider(_CARRIER_ID) is None
    assert complete.require_carrier_reader_provider(_CARRIER_ID) is reader
    assert complete.require_carrier_writer_provider(_CARRIER_ID) is writer
    assert complete.require_carrier_publisher_provider(_CARRIER_ID) is publisher


def test_registry_exposes_packager_without_preparing_it() -> None:
    extension = _PackagerExtension()
    registry = ExtensionRegistry((extension,))

    assert registry.get_packager_provider(_PACKAGER_ID) is extension
    assert registry.require_packager_provider(_PACKAGER_ID) is extension
    with pytest.raises(
        MissingExtensionCapabilityError,
        match="missing extension packager provider",
    ):
        registry.require_packager_provider("org.example/missing@1")


def test_runtime_registry_exposes_only_pure_capability_lookups() -> None:
    registry = ExtensionRegistry((IdentityExtension(),))

    assert not hasattr(registry, "register")
    assert not hasattr(registry, "extensions")
    assert not hasattr(registry, "get_stage")
    assert not hasattr(registry, "get_stream_profile")
    assert not hasattr(registry, "interpret_stage_parameters")
    assert not hasattr(registry, "interpret_stream_metadata")


def test_independent_extensions_share_one_registration_path() -> None:
    builder = ExtensionRegistryBuilder((IdentityExtension(),))
    builder.register(_IdentityEncoderExtension())
    registry = builder.build()

    assert registry.can_encode(IdentityExtension.extension_id)
    assert registry.can_encode(_CUSTOM_STAGE_ID)


def test_stage_and_stream_profile_ids_cannot_overlap() -> None:
    class ProfileUsingStageId(_ProfileExtension):
        extension_id = _CUSTOM_STAGE_ID
        descriptor = _CUSTOM_STAGE_DESCRIPTOR

    stage_first = ExtensionRegistryBuilder((_IdentityEncoderExtension(),))
    with pytest.raises(
        ExtensionRegistrationError,
        match="already registered as a stage",
    ):
        stage_first.register(ProfileUsingStageId())
    assert stage_first.build().can_encode(_CUSTOM_STAGE_ID)

    class StageUsingProfileId(_IdentityEncoderExtension):
        extension_id = _PROFILE_ID
        descriptor = _PROFILE_DESCRIPTOR

    profile_first = ExtensionRegistryBuilder((_ProfileExtension(),))
    with pytest.raises(
        ExtensionRegistrationError,
        match="already registered as a stream profile",
    ):
        profile_first.register(StageUsingProfileId())
    assert profile_first.build().get_descriptor(_PROFILE_ID) == _PROFILE_DESCRIPTOR


@pytest.mark.parametrize(
    ("registered", "conflicting", "registered_kind"),
    (
        (_IdentityEncoderExtension(), _CarrierExtension(), "stage"),
        (_ProfileExtension(), _CarrierExtension(), "stream profile"),
        (_CarrierReaderExtension(), _PackagerExtension(), "carrier"),
        (_PackagerExtension(), _CarrierExtension(), "packager"),
    ),
)
def test_extension_id_cannot_cross_any_kind(
    registered: Extension,
    conflicting: Extension,
    registered_kind: str,
) -> None:
    class ConflictingIdentity:
        extension_id = registered.extension_id
        descriptor = registered.descriptor
        kind = conflicting.kind

    builder = ExtensionRegistryBuilder((registered,))
    with pytest.raises(
        ExtensionRegistrationError,
        match=f"already registered as a {registered_kind}",
    ):
        builder.register(cast(Extension, ConflictingIdentity()))


def test_duplicate_capabilities_and_conflicting_descriptors_are_deterministic() -> None:
    builder = ExtensionRegistryBuilder((_IdentityEncoderExtension(),))

    with pytest.raises(ExtensionRegistrationError, match="duplicate encoder"):
        builder.register(_IdentityEncoderExtension())
    with pytest.raises(ExtensionRegistrationError, match="duplicate encoder"):
        builder.register(_IdentityCodecExtension())

    class ConflictingDecoder(_IdentityDecoderExtension):
        descriptor = ExtensionDescriptor(display_name="A different contract")

    with pytest.raises(ExtensionRegistrationError, match="conflicting descriptor"):
        builder.register(ConflictingDecoder())

    registry = builder.build()
    assert registry.can_encode(_CUSTOM_STAGE_ID)
    assert not registry.can_decode(_CUSTOM_STAGE_ID)


@pytest.mark.parametrize(
    ("extension", "capability"),
    (
        (_CarrierReaderExtension(), "carrier reader provider"),
        (_CarrierWriterExtension(), "carrier writer provider"),
        (_CarrierPublisherExtension(), "carrier publisher provider"),
        (_PackagerExtension(), "packager provider"),
    ),
)
def test_runtime_capabilities_are_unique_per_extension_id(
    extension: Extension,
    capability: str,
) -> None:
    builder = ExtensionRegistryBuilder((extension,))

    with pytest.raises(
        ExtensionRegistrationError,
        match=f"duplicate {capability}",
    ):
        builder.register(extension)


@pytest.mark.parametrize(
    ("extension", "capability"),
    (
        (_ParameterEncoderExtension(), "parameter encoder"),
        (_ParameterDecoderExtension(), "parameter decoder"),
        (_MetadataEncoderExtension(), "metadata encoder"),
        (_MetadataDecoderExtension(), "metadata decoder"),
    ),
)
def test_typed_wire_codec_capabilities_are_unique_per_extension_id(
    extension: Extension,
    capability: str,
) -> None:
    builder = ExtensionRegistryBuilder((extension,))

    with pytest.raises(
        ExtensionRegistrationError,
        match=f"duplicate {capability}",
    ):
        builder.register(extension)


def test_registry_validates_bind_shape_once_without_binding() -> None:
    extension = _CountingShapeEncoderExtension()
    builder = ExtensionRegistryBuilder()
    builder.register(extension)
    accesses_after_registration = extension.member_accesses
    assert accesses_after_registration == 1
    assert extension.bind_calls == 0

    registry = builder.build()

    assert extension.member_accesses == accesses_after_registration
    assert extension.bind_calls == 0
    assert registry.require_encoder_provider(_CUSTOM_STAGE_ID) is extension


def test_registry_returns_specialized_interpreters_without_invoking_them() -> None:
    stage = _ParameterInterpreterExtension()
    profile = _MetadataInterpreterExtension()
    registry = ExtensionRegistry((stage, profile))

    assert registry.get_stage_parameter_interpreter(_CUSTOM_STAGE_ID) is stage
    assert registry.get_stream_metadata_interpreter(_PROFILE_ID) is profile
    assert stage.calls == 0
    assert profile.calls == 0


def test_registry_returns_typed_wire_codecs_without_invoking_them() -> None:
    parameter_encoder = _ParameterEncoderExtension()
    parameter_decoder = _ParameterDecoderExtension()
    metadata_encoder = _MetadataEncoderExtension()
    metadata_decoder = _MetadataDecoderExtension()
    registry = ExtensionRegistry(
        (
            parameter_encoder,
            parameter_decoder,
            metadata_encoder,
            metadata_decoder,
        )
    )

    assert registry.get_stage_parameter_encoder(_CUSTOM_STAGE_ID) is parameter_encoder
    assert registry.get_stage_parameter_decoder(_CUSTOM_STAGE_ID) is parameter_decoder
    assert registry.get_stream_metadata_encoder(_PROFILE_ID) is metadata_encoder
    assert registry.get_stream_metadata_decoder(_PROFILE_ID) is metadata_decoder


@pytest.mark.parametrize(
    ("extension", "message"),
    (
        (object(), "cannot access extension_id"),
        (
            type(
                "InvalidId",
                (),
                {
                    "extension_id": "INVALID",
                    "descriptor": _CUSTOM_STAGE_DESCRIPTOR,
                    "kind": "stage",
                },
            )(),
            "invalid OBST extension id",
        ),
        (
            type(
                "InvalidDescriptor",
                (),
                {
                    "extension_id": _CUSTOM_STAGE_ID,
                    "descriptor": object(),
                    "kind": "stage",
                },
            )(),
            "descriptor must be an exact ExtensionDescriptor",
        ),
        (
            type(
                "InvalidKind",
                (),
                {
                    "extension_id": _CUSTOM_STAGE_ID,
                    "descriptor": _CUSTOM_STAGE_DESCRIPTOR,
                    "kind": "codec",
                },
            )(),
            "kind must be an exact ExtensionKind member",
        ),
    ),
    ids=("missing-identity", "invalid-id", "invalid-descriptor", "invalid-kind"),
)
def test_registration_rejects_invalid_extension_identity(
    extension: object,
    message: str,
) -> None:
    with pytest.raises(ExtensionContractError, match=message):
        ExtensionRegistryBuilder().register(cast(Extension, extension))


@pytest.mark.parametrize(
    ("extension", "capability", "member"),
    (
        (_NonCallableEncoderExtension(), "encoder provider", "bind_encoder"),
        (_NonCallableDecoderExtension(), "decoder provider", "bind_decoder"),
        (
            _NonCallableParameterInterpreterExtension(),
            "parameter interpreter",
            "interpret_parameters",
        ),
        (
            _NonCallableParameterEncoderExtension(),
            "parameter encoder",
            "encode_parameters",
        ),
        (
            _NonCallableParameterDecoderExtension(),
            "parameter decoder",
            "decode_parameters",
        ),
        (
            _NonCallableMetadataInterpreterExtension(),
            "metadata interpreter",
            "interpret_metadata",
        ),
        (
            _NonCallableMetadataEncoderExtension(),
            "metadata encoder",
            "encode_metadata",
        ),
        (
            _NonCallableMetadataDecoderExtension(),
            "metadata decoder",
            "decode_metadata",
        ),
        (
            _NonCallableCarrierReaderExtension(),
            "carrier reader provider",
            "bind_reader",
        ),
        (
            _NonCallableCarrierWriterExtension(),
            "carrier writer provider",
            "bind_writer",
        ),
        (
            _NonCallableCarrierPublisherExtension(),
            "carrier publisher provider",
            "bind_publisher",
        ),
        (
            _NonCallablePackagerExtension(),
            "packager provider",
            "prepare_package",
        ),
    ),
)
def test_registration_rejects_non_callable_capability_methods(
    extension: Extension,
    capability: str,
    member: str,
) -> None:
    with pytest.raises(ExtensionContractError) as error:
        ExtensionRegistryBuilder().register(extension)

    assert error.value.extension_id == extension.extension_id
    assert error.value.capability == capability
    assert member in error.value.reason
    assert "must be callable" in error.value.reason


def test_expected_provider_rejection_is_not_a_core_failure() -> None:
    with pytest.raises(ProviderRejectedError) as error:
        require_no_parameters(_CUSTOM_STAGE_ID, b"unexpected")

    assert error.value.reason == ("org.example/identity@1 does not accept parameters")
    assert error.value.resource_limit is None
    assert not isinstance(error.value, ObstError)


def test_stage_output_helper_carries_the_structured_host_limit() -> None:
    with pytest.raises(ProviderRejectedError) as error:
        require_stage_output_size(
            _CUSTOM_STAGE_ID,
            9,
            max_output_size=8,
            operation="encode",
        )

    resource_limit = error.value.resource_limit
    assert isinstance(resource_limit, ResourceLimitError)
    assert resource_limit.resource is CoreResource.INTERMEDIATE_BYTES
    assert resource_limit.scope == _CUSTOM_STAGE_ID
    assert resource_limit.maximum == 8
    assert resource_limit.observed == 9
    assert resource_limit.phase == "stage_encode"

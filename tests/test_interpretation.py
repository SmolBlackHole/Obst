# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import io
from typing import cast

import pytest

from obst.core import (
    BYTES_STREAM_TYPE,
    ContainerReader,
    ContainerWriter,
    ExtensionContractError,
    ExtensionDescriptor,
    ExtensionRegistry,
    InspectionField,
    InspectionInterpretation,
    InspectionInterpretationPolicy,
    Manifest,
    Recipe,
    StageExtension,
    StageSpec,
    Stream,
    inspect_container,
)
from obst.core.extensions import ExtensionKind
from tests.support_resources import accounting as _accounting

_CUSTOM_STAGE_ID = "org.example/interpretation@1"
_CUSTOM_DESCRIPTOR = ExtensionDescriptor()


class _InvalidInterpreterStage:
    extension_id = _CUSTOM_STAGE_ID
    descriptor = _CUSTOM_DESCRIPTOR
    kind = ExtensionKind.STAGE

    def interpret_parameters(
        self,
        parameters: bytes,
        /,
    ) -> InspectionInterpretation:
        return cast(InspectionInterpretation, "not an interpretation")


def _inspect_stage_parameters(
    stage: StageSpec,
    extension: StageExtension,
) -> InspectionInterpretation | None:
    manifest = Manifest(
        recipes=(Recipe(0, (stage,)),),
        streams=(Stream(0, BYTES_STREAM_TYPE, 0),),
    )
    target = io.BytesIO()
    ContainerWriter(target, manifest, accounting=_accounting()).finish()
    inspection = inspect_container(
        ContainerReader(io.BytesIO(target.getvalue()), accounting=_accounting()),
        registry=ExtensionRegistry((extension,)),
        interpretation_policy=InspectionInterpretationPolicy(
            frozenset({stage.stage_id})
        ),
    )
    return inspection.recipes[0].stages[0].parameters


def test_interpreter_return_values_are_checked_during_inspection() -> None:
    with pytest.raises(ExtensionContractError, match="must return") as error:
        _inspect_stage_parameters(
            StageSpec(_CUSTOM_STAGE_ID),
            _InvalidInterpreterStage(),
        )

    assert error.value.extension_id == _CUSTOM_STAGE_ID
    assert error.value.capability == "parameter interpreter"


def test_inspection_values_enforce_exact_renderer_neutral_types() -> None:
    with pytest.raises(TypeError, match="name must be an exact string"):
        InspectionField(cast(str, 7), "value")
    with pytest.raises(TypeError, match="value must be an exact"):
        InspectionField("value", cast(str, ["not scalar"]))
    with pytest.raises(TypeError, match="label must be an exact string"):
        InspectionInterpretation(label=cast(str, 7))


def test_interpreter_nested_values_are_rechecked_during_inspection() -> None:
    field = object.__new__(InspectionField)
    object.__setattr__(field, "name", "unsafe")
    object.__setattr__(field, "value", ["not scalar"])
    interpretation = object.__new__(InspectionInterpretation)
    object.__setattr__(interpretation, "label", None)
    object.__setattr__(interpretation, "fields", (field,))
    object.__setattr__(interpretation, "error", None)

    class InvalidNestedStage:
        extension_id = _CUSTOM_STAGE_ID
        descriptor = _CUSTOM_DESCRIPTOR
        kind = ExtensionKind.STAGE

        def interpret_parameters(
            self,
            parameters: bytes,
            /,
        ) -> InspectionInterpretation:
            return interpretation

    with pytest.raises(ExtensionContractError) as error:
        _inspect_stage_parameters(StageSpec(_CUSTOM_STAGE_ID), InvalidNestedStage())

    assert error.value.extension_id == _CUSTOM_STAGE_ID
    assert error.value.capability == "parameter interpreter"
    assert "invalid InspectionInterpretation" in error.value.reason
    assert isinstance(error.value.__cause__, TypeError)


def test_unexpected_interpreter_errors_keep_extension_context() -> None:
    class ExplodingStage:
        extension_id = _CUSTOM_STAGE_ID
        descriptor = _CUSTOM_DESCRIPTOR
        kind = ExtensionKind.STAGE

        def interpret_parameters(
            self,
            parameters: bytes,
            /,
        ) -> InspectionInterpretation:
            raise RuntimeError("interpreter bug")

    with pytest.raises(ExtensionContractError) as error:
        _inspect_stage_parameters(StageSpec(_CUSTOM_STAGE_ID), ExplodingStage())

    assert error.value.extension_id == _CUSTOM_STAGE_ID
    assert error.value.capability == "parameter interpreter"
    assert error.value.reason == "provider raised RuntimeError: interpreter bug"
    assert isinstance(error.value.__cause__, RuntimeError)

"""Resource limit values and operation accounting."""

from __future__ import annotations

from typing import cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from obst.core import (
    CoreResource,
    LimitProfile,
    ResourceDefinition,
    ResourceKind,
    ResourceLimitError,
    ResourcePolicy,
    ResourceUnit,
    require_resource_limit,
)
from obst.core.resources import ResourceBudget
from tests.support_resources import policy as _policy


class ExampleResource(ResourceKind):
    RECORDS = ResourceDefinition(
        "org.example.records@1/records",
        12,
        "Records handled by the example provider.",
        ResourceUnit.COUNT,
    )


def test_resource_kind_preserves_typed_identity_and_canonical_string() -> None:
    assert str(CoreResource.CHUNKS) == "chunks"
    assert cast(object, CoreResource.CHUNKS) != "chunks"
    assert ExampleResource.RECORDS.default_maximum == 12
    assert ExampleResource.RECORDS.summary.startswith("Records handled")
    assert ExampleResource.RECORDS.unit is ResourceUnit.COUNT


@pytest.mark.parametrize("definition", ["not-a-definition", 1])
def test_resource_kind_rejects_non_definition_values(
    definition: object,
) -> None:
    with pytest.raises(TypeError, match="exact ResourceDefinition"):

        class InvalidResource(  # pyright: ignore[reportUnusedClass]
            ResourceKind
        ):
            VALUE = cast(ResourceDefinition, definition)


@pytest.mark.parametrize("identifier", ["", "Uppercase", "bad/", "/bad"])
def test_resource_definition_rejects_invalid_identifiers(identifier: str) -> None:
    with pytest.raises(ValueError, match="resource identifier"):
        ResourceDefinition(identifier, 1, "Invalid identifier.", ResourceUnit.COUNT)


def test_resource_policy_resolves_defaults_and_profile_overrides() -> None:
    profile = LimitProfile(
        "org.example.records@1/large",
        "Permit more records and disable the chunk ceiling.",
        (
            (ExampleResource.RECORDS, 24),
            (CoreResource.CHUNKS, None),
        ),
    )
    policy = ResourcePolicy(
        tuple(CoreResource) + tuple(ExampleResource),
        profile,
    )

    assert policy.maximum(ExampleResource.RECORDS) == 24
    assert policy.maximum(CoreResource.CHUNKS) is None
    assert policy.maximum(CoreResource.STREAMS) == 65_536


def test_limit_profile_rejects_duplicate_resource_override() -> None:
    with pytest.raises(ValueError, match="duplicate limit profile resource"):
        LimitProfile(
            "org.example.records@1/duplicate",
            "Invalid duplicate overrides.",
            (
                (ExampleResource.RECORDS, 1),
                (ExampleResource.RECORDS, 2),
            ),
        )


def test_resource_policy_rejects_unknown_profile_resource() -> None:
    profile = LimitProfile(
        "org.example.records@1/unknown",
        "References an absent resource.",
        ((ExampleResource.RECORDS, 1),),
    )

    with pytest.raises(ValueError, match="references unknown resource"):
        ResourcePolicy(tuple(CoreResource), profile)


def test_resource_refusal_api_rejects_raw_strings() -> None:
    with pytest.raises(TypeError, match="ResourceKind"):
        require_resource_limit(
            cast(ResourceKind, "chunks"),
            scope="container",
            maximum=0,
            observed=1,
            phase="test",
        )


@pytest.mark.parametrize("value", [-1, True, False, 1.5, "1"])
def test_resource_definition_rejects_invalid_default_maximum(value: object) -> None:
    error = TypeError if type(value) is not int else ValueError
    with pytest.raises(error, match="resource default maximum"):
        ResourceDefinition(
            "org.example.records@1/invalid",
            cast(int, value),
            "Invalid maximum.",
            ResourceUnit.COUNT,
        )


def test_resource_definition_requires_a_typed_unit() -> None:
    with pytest.raises(TypeError, match="exact ResourceUnit"):
        ResourceDefinition(
            "org.example.records@1/untyped",
            1,
            "Invalid untyped resource.",
            cast(ResourceUnit, "count"),
        )


def test_partial_override_retains_every_other_default() -> None:
    policy = _policy((CoreResource.CHUNKS, 7))

    assert policy.maximum(CoreResource.CHUNKS) == 7
    assert (
        policy.maximum(CoreResource.MANIFEST_BYTES)
        == CoreResource.MANIFEST_BYTES.default_maximum
    )


def test_cumulative_budget_accepts_boundary_and_refuses_next_unit() -> None:
    budget = ResourceBudget(_policy((CoreResource.CHUNKS, 2)))

    budget.consume_chunk(phase="inspect")
    budget.consume_chunk(phase="inspect")

    with pytest.raises(ResourceLimitError) as error:
        budget.consume_chunk(phase="inspect")

    assert error.value.resource is CoreResource.CHUNKS
    assert error.value.scope == "container"
    assert error.value.maximum == 2
    assert error.value.observed == 3
    assert error.value.phase == "inspect"


def test_disabled_limit_does_not_refuse_consumption() -> None:
    budget = ResourceBudget(_policy((CoreResource.CHUNKS, None)))

    for _ in range(3):
        budget.consume_chunk(phase="inspect")

    assert budget.chunks == 3


@given(
    maximum=st.integers(min_value=0, max_value=1_000),
    amounts=st.lists(st.integers(min_value=0, max_value=100), max_size=30),
)
def test_cumulative_logical_budget_matches_prefix_sum(
    maximum: int,
    amounts: list[int],
) -> None:
    budget = ResourceBudget(_policy((CoreResource.LOGICAL_BYTES, maximum)))
    accepted = 0

    for amount in amounts:
        observed = accepted + amount
        if observed <= maximum:
            budget.consume_logical_bytes(
                amount,
                scope="property",
                phase="test",
            )
            accepted = observed
        else:
            with pytest.raises(ResourceLimitError) as error:
                budget.consume_logical_bytes(
                    amount,
                    scope="property",
                    phase="test",
                )
            assert error.value.observed == observed
            assert budget.logical_bytes == accepted

    assert budget.logical_bytes == accepted

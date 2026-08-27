"""Resource limit values and operation accounting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from obst.core import DEFAULT_RESOURCE_LIMITS, ResourceLimitError, ResourceLimits
from obst.core.resources import ResourceBudget

_resource_limits = cast(Callable[..., ResourceLimits], ResourceLimits)


@pytest.mark.parametrize("value", [None, 0, 1, 2**64])
def test_every_resource_limit_accepts_supported_values(value: int | None) -> None:
    for field in fields(ResourceLimits):
        limits = _resource_limits(**{field.name: value})
        assert getattr(limits, field.name) == value


@pytest.mark.parametrize("value", [-1, True, False, 1.5, "1"])
def test_every_resource_limit_rejects_invalid_values(value: object) -> None:
    for field in fields(ResourceLimits):
        error = TypeError if type(value) is not int else ValueError
        with pytest.raises(error, match=field.name):
            _resource_limits(**cast(dict[str, Any], {field.name: value}))


def test_partial_override_retains_every_other_default() -> None:
    limits = ResourceLimits(max_chunks=7)

    for field in fields(ResourceLimits):
        expected = (
            7
            if field.name == "max_chunks"
            else getattr(
                DEFAULT_RESOURCE_LIMITS,
                field.name,
            )
        )
        assert getattr(limits, field.name) == expected


def test_cumulative_budget_accepts_boundary_and_refuses_next_unit() -> None:
    budget = ResourceBudget(ResourceLimits(max_chunks=2))

    budget.consume_chunk(phase="inspect")
    budget.consume_chunk(phase="inspect")

    with pytest.raises(ResourceLimitError) as error:
        budget.consume_chunk(phase="inspect")

    assert error.value.resource == "chunks"
    assert error.value.scope == "container"
    assert error.value.maximum == 2
    assert error.value.observed == 3
    assert error.value.phase == "inspect"


def test_disabled_limit_does_not_refuse_consumption() -> None:
    budget = ResourceBudget(ResourceLimits(max_chunks=None))

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
    budget = ResourceBudget(ResourceLimits(max_total_logical_bytes=maximum))
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

# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Cross-operation laws preserved by the core architecture overhaul."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Self

import pytest
from obst.core import (
    BYTES_STREAM_TYPE,
    ContainerReader,
    CoreResource,
    ExtensionDescriptor,
    ExtensionRegistry,
    LogicalStreamDescriptor,
    LogicalStreamSource,
    PackageWriteOperation,
    PipelineError,
    ProviderRejectedError,
    RecipeSpec,
    ResourceAccounting,
    ResourceLimitError,
    StageSpec,
    iter_decoded_chunks,
)
from obst.core.extensions import ExtensionKind

from obst_defaults.carriers import publish_package
from obst_defaults.carriers.filesystem import (
    FilesystemPublisherSession,
    FilesystemPublishRequest,
)
from obst_defaults.packagers.fixed import (
    FixedPackageRequest,
    FixedPackagerExtension,
)
from obst_defaults.transforms.delta8 import Delta8Extension
from support_resources import accounting as _accounting

DELTA8_STAGE_ID = Delta8Extension.extension_id

_IDENTITY_RECIPE = RecipeSpec(())
_DOUBLE_DELTA_RECIPE = RecipeSpec(
    (
        StageSpec(DELTA8_STAGE_ID),
        StageSpec(DELTA8_STAGE_ID),
    )
)


def _registry() -> ExtensionRegistry:
    return ExtensionRegistry((Delta8Extension(),))


def _source(data: bytes, recipe: RecipeSpec) -> LogicalStreamSource:
    return LogicalStreamSource.from_bytes(
        LogicalStreamDescriptor(BYTES_STREAM_TYPE, b"", recipe),
        data,
        chunk_size=1,
    )


def _fixed_operation(
    registry: ExtensionRegistry,
    sources: tuple[LogicalStreamSource, ...],
    *,
    accounting: ResourceAccounting | None = None,
) -> PackageWriteOperation:
    request = FixedPackageRequest(
        registry,
        sources,
        _accounting() if accounting is None else accounting,
    )
    return FixedPackagerExtension().prepare_package(request)


def test_packaging_stage_limit_spans_chunks_and_distinct_recipes() -> None:
    sources = (
        _source(b"ab", _IDENTITY_RECIPE),
        _source(b"cd", _DOUBLE_DELTA_RECIPE),
    )

    with pytest.raises(ResourceLimitError) as caught:
        _fixed_operation(
            _registry(),
            sources,
            accounting=_accounting((CoreResource.STAGE_EXECUTIONS, 3)),
        ).write_to(io.BytesIO())

    assert caught.value.resource is CoreResource.STAGE_EXECUTIONS
    assert caught.value.observed == 4


def test_decoding_stage_limit_spans_chunks_and_distinct_recipes() -> None:
    registry = _registry()
    target = io.BytesIO()
    _fixed_operation(
        registry,
        (
            _source(b"ab", _IDENTITY_RECIPE),
            _source(b"cd", _DOUBLE_DELTA_RECIPE),
        ),
    ).write_to(target)

    with pytest.raises(ResourceLimitError) as caught:
        tuple(
            iter_decoded_chunks(
                ContainerReader(
                    io.BytesIO(target.getvalue()),
                    accounting=_accounting((CoreResource.STAGE_EXECUTIONS, 3)),
                ),
                registry,
            )
        )

    assert caught.value.resource is CoreResource.STAGE_EXECUTIONS
    assert caught.value.observed == 4


def test_provider_execution_failure_aborts_filesystem_publication(
    tmp_path: Path,
) -> None:
    target = tmp_path / "rejected.obst"

    class RejectingExtension:
        extension_id = "org.example/reject-on-execute@1"
        kind = ExtensionKind.STAGE
        descriptor = ExtensionDescriptor()

        def bind_encoder(self, parameters: bytes, /) -> Self:
            assert parameters == b""
            return self

        def encode(
            self,
            data: bytes,
            /,
            *,
            max_output_size: int | None,
        ) -> bytes:
            assert data == b"payload"
            assert list(tmp_path.glob(".rejected.obst.*.tmp"))
            raise ProviderRejectedError("payload rejected")

    extension = RejectingExtension()
    recipe = RecipeSpec((StageSpec(extension.extension_id),))
    source = LogicalStreamSource.from_bytes(
        LogicalStreamDescriptor(BYTES_STREAM_TYPE, b"", recipe),
        b"payload",
        chunk_size=len(b"payload"),
    )

    with pytest.raises(PipelineError) as caught:
        operation = _fixed_operation(ExtensionRegistry((extension,)), (source,))
        publish_package(
            operation,
            FilesystemPublisherSession(FilesystemPublishRequest(target)),
        )

    assert caught.value.stage_id == extension.extension_id
    assert caught.value.direction == "encode"
    assert caught.value.phase == "execute"
    assert caught.value.reason == "payload rejected"
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []

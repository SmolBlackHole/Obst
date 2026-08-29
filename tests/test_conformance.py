# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest

from obst.conformance import (
    ConformanceError,
    ConformanceSuite,
    StageBindRejectionCase,
    StageKnownAnswerCase,
    StageOutputLimitCase,
    load_conformance_suite,
    run_conformance_suite,
    write_conformance_suite,
)
from obst.core import (
    ExtensionDescriptor,
    ProviderRejectedError,
    require_stage_output_size,
)
from obst.core.extensions import ExtensionKind
from tests.support_extensions import IdentityExtension

_CRASHING_STAGE_ID = "org.example/crashing@1"
_LIMIT_STAGE_ID = "org.example/limit@1"


def _identity_suite() -> ConformanceSuite:
    return ConformanceSuite(
        (
            StageKnownAnswerCase(
                "identity-known-answer",
                IdentityExtension.extension_id,
                b"",
                b"portable bytes",
                b"portable bytes",
                canonical_encoding=True,
            ),
            StageBindRejectionCase(
                "identity-rejects-parameters",
                IdentityExtension.extension_id,
                b"unexpected",
                ("encode", "decode"),
            ),
        )
    )


def test_public_runner_executes_an_explicit_provider_suite() -> None:
    report = run_conformance_suite(_identity_suite(), (IdentityExtension(),))

    assert report.passed
    assert tuple(result.case_id for result in report.cases) == (
        "identity-known-answer",
        "identity-rejects-parameters",
    )


def test_suite_catalog_round_trips_without_plugin_identity(tmp_path: Path) -> None:
    suite = _identity_suite()

    write_conformance_suite(suite, tmp_path)

    document = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert document.keys() == {"schema_version", "cases"}
    assert document["schema_version"] == 2
    assert document["cases"][0]["logical"].keys() == {"hex", "sha256"}
    assert tuple(path.name for path in tmp_path.iterdir()) == ("index.json",)
    assert load_conformance_suite(tmp_path) == suite


def test_suite_loader_rejects_tampered_vector(tmp_path: Path) -> None:
    write_conformance_suite(_identity_suite(), tmp_path)
    document = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    document["cases"][0]["logical"]["hex"] = "00"
    (tmp_path / "index.json").write_text(
        json.dumps(document),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="wrong SHA-256"):
        load_conformance_suite(tmp_path)


@pytest.mark.parametrize("encoded", ("0", "AA", "0g", "00 01"))
def test_suite_loader_rejects_noncanonical_inline_hex(
    tmp_path: Path,
    encoded: str,
) -> None:
    write_conformance_suite(_identity_suite(), tmp_path)
    document = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    document["cases"][0]["logical"]["hex"] = encoded
    (tmp_path / "index.json").write_text(
        json.dumps(document),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="canonical lowercase byte pairs"):
        load_conformance_suite(tmp_path)


def test_suite_loader_rejects_the_removed_schema(tmp_path: Path) -> None:
    (tmp_path / "index.json").write_text(
        '{"schema_version": 1, "plugin": "legacy", "cases": []}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="conformance index"):
        load_conformance_suite(tmp_path)


def test_suite_requires_coverage_for_every_owned_stage() -> None:
    with pytest.raises(ConformanceError, match="does not cover Stage bytes"):
        run_conformance_suite(ConformanceSuite(()), (IdentityExtension(),))


class _CrashingStage:
    extension_id = _CRASHING_STAGE_ID
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor()

    def bind_encoder(self, parameters: bytes, /) -> _CrashingStage:
        raise RuntimeError("implementation crashed")

    def bind_decoder(self, parameters: bytes, /) -> _CrashingStage:
        raise RuntimeError("implementation crashed")


def test_unexpected_provider_exception_cannot_pass_a_rejection_case() -> None:
    suite = ConformanceSuite(
        (
            StageKnownAnswerCase(
                "crashing-known-answer",
                _CRASHING_STAGE_ID,
                b"",
                b"x",
                b"x",
                canonical_encoding=True,
            ),
            StageBindRejectionCase(
                "crashing-rejection",
                _CRASHING_STAGE_ID,
                b"invalid",
                ("encode", "decode"),
            ),
        )
    )

    report = run_conformance_suite(suite, (_CrashingStage(),))

    assert not report.passed
    error = report.cases[1].error
    assert error is not None
    assert "RuntimeError: implementation crashed" in error


class _LimitStage:
    extension_id = _LIMIT_STAGE_ID
    kind = ExtensionKind.STAGE
    descriptor = ExtensionDescriptor()

    def bind_encoder(self, parameters: bytes, /) -> _LimitStage:
        if parameters:
            raise ProviderRejectedError("parameters rejected")
        return self

    def bind_decoder(self, parameters: bytes, /) -> _LimitStage:
        if parameters:
            raise ProviderRejectedError("parameters rejected")
        return self

    def encode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        output = data + b"!"
        require_stage_output_size(
            self.extension_id,
            len(output),
            max_output_size=max_output_size,
            operation="encode",
        )
        return output

    def decode(
        self,
        data: bytes,
        /,
        *,
        max_output_size: int | None,
    ) -> bytes:
        output = data[:-1]
        require_stage_output_size(
            self.extension_id,
            len(output),
            max_output_size=max_output_size,
            operation="decode",
        )
        return output


def test_structured_output_limit_is_required_for_a_limit_case() -> None:
    suite = ConformanceSuite(
        (
            StageKnownAnswerCase(
                "limit-known-answer",
                _LIMIT_STAGE_ID,
                b"",
                b"data",
                b"data!",
                canonical_encoding=True,
            ),
            StageOutputLimitCase(
                "limit-enforced",
                _LIMIT_STAGE_ID,
                "encode",
                b"",
                b"data",
                4,
            ),
        )
    )

    assert run_conformance_suite(suite, (_LimitStage(),)).passed

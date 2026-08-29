# SPDX-FileCopyrightText: 2026 SmolBlackHole
#
# SPDX-License-Identifier: MPL-2.0

"""Portable static conformance suites for installed OBST Extensions."""

from obst.conformance.catalog import (
    CONFORMANCE_SUITE_SCHEMA_VERSION,
    load_conformance_suite,
    write_conformance_suite,
)
from obst.conformance.model import (
    ConformanceCaseKind,
    ConformanceCaseResult,
    ConformanceReport,
    ConformanceSuite,
    ContainerRecoveryCase,
    ContainerStructuralOutcome,
    ContainerStructureCase,
    PortableConformanceCase,
    RecoveredStreamExpectation,
    StageBindRejectionCase,
    StageDecodeRejectionCase,
    StageDirection,
    StageKnownAnswerCase,
    StageOutputLimitCase,
    StageParametersCase,
    StreamMetadataCase,
    StreamMetadataRejectionCase,
    case_extension_id,
)
from obst.conformance.runner import (
    ConformanceError,
    run_conformance_suite,
)

__all__ = [
    "CONFORMANCE_SUITE_SCHEMA_VERSION",
    "ConformanceCaseKind",
    "ConformanceCaseResult",
    "ConformanceError",
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
    "load_conformance_suite",
    "run_conformance_suite",
    "write_conformance_suite",
]

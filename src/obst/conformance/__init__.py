"""Portable static conformance suites for installed OBST Extensions."""

from obst.conformance.catalog import (
    CONFORMANCE_SUITE_SCHEMA_VERSION,
    load_conformance_suite,
    write_conformance_suite,
)
from obst.conformance.model import (
    ConformanceCaseKind,
    ConformanceCaseResult,
    ConformanceSuite,
    ContainerRecoveryCase,
    PluginConformanceReport,
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
    check_plugin_conformance,
    check_stage_conformance,
)

__all__ = [
    "CONFORMANCE_SUITE_SCHEMA_VERSION",
    "ConformanceCaseKind",
    "ConformanceCaseResult",
    "ConformanceError",
    "ConformanceSuite",
    "ContainerRecoveryCase",
    "PluginConformanceReport",
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
    "check_plugin_conformance",
    "check_stage_conformance",
    "load_conformance_suite",
    "write_conformance_suite",
]

"""Static JSON and hexadecimal catalogs for plugin-owned conformance suites."""

from __future__ import annotations

import hashlib
import json
import re
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath
from typing import cast

from obst.conformance.model import (
    ConformanceCaseKind,
    ConformanceSuite,
    ContainerRecoveryCase,
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
)
from obst.core.extensions import (
    InspectionField,
    InspectionInterpretation,
    InspectionValue,
)

CONFORMANCE_SUITE_SCHEMA_VERSION = 1

type JsonObject = dict[str, object]

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def load_conformance_suite(root: Traversable) -> ConformanceSuite:
    """Load and validate one static suite rooted at a package resource."""
    try:
        loaded: object = json.loads(
            root.joinpath("index.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"cannot read conformance index: {type(exc).__name__}: {exc}"
        ) from exc
    document = _require_object("conformance index", loaded)
    _require_keys(document, {"schema_version", "plugin", "cases"}, "conformance index")
    if _require_integer(document, "schema_version") != CONFORMANCE_SUITE_SCHEMA_VERSION:
        raise ValueError("unsupported conformance suite schema version")
    plugin_name = _require_string(document, "plugin")
    records = _require_list(document, "cases")
    cases = tuple(
        _load_case(root, _require_object(f"case {index}", value))
        for index, value in enumerate(records)
    )
    return ConformanceSuite(plugin_name, cases)


def write_conformance_suite(suite: ConformanceSuite, root: Path) -> None:
    """Write one suite deterministically and remove obsolete vector files."""
    if not isinstance(root, Path):
        raise TypeError("root must be a Path")
    artifacts: dict[str, bytes] = {}
    records = tuple(_dump_case(case, artifacts) for case in suite.cases)
    document = {
        "schema_version": CONFORMANCE_SUITE_SCHEMA_VERSION,
        "plugin": suite.plugin_name,
        "cases": records,
    }
    artifacts["index.json"] = (
        json.dumps(document, indent=4, sort_keys=True) + "\n"
    ).encode("utf-8")
    expected_paths = {root / PurePosixPath(path) for path in artifacts}
    vector_root = root / "vectors"
    if vector_root.exists():
        for existing in vector_root.rglob("*.hex"):
            if existing not in expected_paths:
                existing.unlink()
    for relative_path, content in artifacts.items():
        target = root / PurePosixPath(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _load_case(root: Traversable, record: JsonObject) -> PortableConformanceCase:
    case_id = _require_string(record, "id")
    try:
        kind = ConformanceCaseKind(_require_string(record, "kind"))
    except ValueError as exc:
        raise ValueError(f"case {case_id} has an unknown kind") from exc
    if kind is ConformanceCaseKind.STAGE_KNOWN_ANSWER:
        _require_keys(
            record,
            {
                "id",
                "kind",
                "extension_id",
                "parameters",
                "logical",
                "encoded",
                "canonical_encoding",
            },
            f"case {case_id}",
        )
        return StageKnownAnswerCase(
            case_id,
            _require_string(record, "extension_id"),
            _load_bytes(root, record, "parameters"),
            _load_bytes(root, record, "logical"),
            _load_bytes(root, record, "encoded"),
            _require_boolean(record, "canonical_encoding"),
        )
    if kind is ConformanceCaseKind.STAGE_PARAMETERS:
        _require_keys(
            record,
            {"id", "kind", "extension_id", "parameters", "interpretation"},
            f"case {case_id}",
        )
        return StageParametersCase(
            case_id,
            _require_string(record, "extension_id"),
            _load_bytes(root, record, "parameters"),
            _load_optional_interpretation(record.get("interpretation")),
        )
    if kind is ConformanceCaseKind.STAGE_BIND_REJECTION:
        _require_keys(
            record,
            {"id", "kind", "extension_id", "parameters", "directions"},
            f"case {case_id}",
        )
        directions = tuple(
            cast(
                StageDirection,
                _require_exact_string(f"case {case_id} direction", value),
            )
            for value in _require_list(record, "directions")
        )
        return StageBindRejectionCase(
            case_id,
            _require_string(record, "extension_id"),
            _load_bytes(root, record, "parameters"),
            directions,
        )
    if kind is ConformanceCaseKind.STAGE_DECODE_REJECTION:
        _require_keys(
            record,
            {"id", "kind", "extension_id", "parameters", "encoded", "max_output_size"},
            f"case {case_id}",
        )
        return StageDecodeRejectionCase(
            case_id,
            _require_string(record, "extension_id"),
            _load_bytes(root, record, "parameters"),
            _load_bytes(root, record, "encoded"),
            _require_integer(record, "max_output_size"),
        )
    if kind is ConformanceCaseKind.STAGE_OUTPUT_LIMIT:
        _require_keys(
            record,
            {
                "id",
                "kind",
                "extension_id",
                "direction",
                "parameters",
                "data",
                "max_output_size",
            },
            f"case {case_id}",
        )
        return StageOutputLimitCase(
            case_id,
            _require_string(record, "extension_id"),
            cast(StageDirection, _require_string(record, "direction")),
            _load_bytes(root, record, "parameters"),
            _load_bytes(root, record, "data"),
            _require_integer(record, "max_output_size"),
        )
    if kind is ConformanceCaseKind.STREAM_METADATA:
        _require_keys(
            record,
            {"id", "kind", "extension_id", "metadata", "interpretation"},
            f"case {case_id}",
        )
        return StreamMetadataCase(
            case_id,
            _require_string(record, "extension_id"),
            _load_bytes(root, record, "metadata"),
            _load_optional_interpretation(record.get("interpretation")),
        )
    if kind is ConformanceCaseKind.STREAM_METADATA_REJECTION:
        _require_keys(
            record,
            {"id", "kind", "extension_id", "metadata", "require_interpreter_error"},
            f"case {case_id}",
        )
        return StreamMetadataRejectionCase(
            case_id,
            _require_string(record, "extension_id"),
            _load_bytes(root, record, "metadata"),
            _require_boolean(record, "require_interpreter_error"),
        )
    assert kind is ConformanceCaseKind.CONTAINER_RECOVERY
    _require_keys(
        record,
        {"id", "kind", "container", "required_extensions", "streams"},
        f"case {case_id}",
    )
    required_extensions = tuple(
        _require_exact_string(f"case {case_id} required extension", value)
        for value in _require_list(record, "required_extensions")
    )
    streams = tuple(
        _load_stream(root, case_id, _require_object("recovered stream", value))
        for value in _require_list(record, "streams")
    )
    return ContainerRecoveryCase(
        case_id,
        _load_bytes(root, record, "container"),
        required_extensions,
        streams,
    )


def _dump_case(
    case: PortableConformanceCase,
    artifacts: dict[str, bytes],
) -> JsonObject:
    record: JsonObject = {"id": case.case_id, "kind": case.kind.value}
    if type(case) is StageKnownAnswerCase:
        record.update(
            extension_id=case.extension_id,
            parameters=_store_bytes(
                case.case_id, "parameters", case.parameters, artifacts
            ),
            logical=_store_bytes(case.case_id, "logical", case.logical, artifacts),
            encoded=_store_bytes(case.case_id, "encoded", case.encoded, artifacts),
            canonical_encoding=case.canonical_encoding,
        )
    elif type(case) is StageParametersCase:
        record.update(
            extension_id=case.extension_id,
            parameters=_store_bytes(
                case.case_id, "parameters", case.parameters, artifacts
            ),
            interpretation=_dump_interpretation(case.interpretation),
        )
    elif type(case) is StageBindRejectionCase:
        record.update(
            extension_id=case.extension_id,
            parameters=_store_bytes(
                case.case_id, "parameters", case.parameters, artifacts
            ),
            directions=case.directions,
        )
    elif type(case) is StageDecodeRejectionCase:
        record.update(
            extension_id=case.extension_id,
            parameters=_store_bytes(
                case.case_id, "parameters", case.parameters, artifacts
            ),
            encoded=_store_bytes(case.case_id, "encoded", case.encoded, artifacts),
            max_output_size=case.max_output_size,
        )
    elif type(case) is StageOutputLimitCase:
        record.update(
            extension_id=case.extension_id,
            direction=case.direction,
            parameters=_store_bytes(
                case.case_id, "parameters", case.parameters, artifacts
            ),
            data=_store_bytes(case.case_id, "data", case.data, artifacts),
            max_output_size=case.max_output_size,
        )
    elif type(case) is StreamMetadataCase:
        record.update(
            extension_id=case.extension_id,
            metadata=_store_bytes(case.case_id, "metadata", case.metadata, artifacts),
            interpretation=_dump_interpretation(case.interpretation),
        )
    elif type(case) is StreamMetadataRejectionCase:
        record.update(
            extension_id=case.extension_id,
            metadata=_store_bytes(case.case_id, "metadata", case.metadata, artifacts),
            require_interpreter_error=case.require_interpreter_error,
        )
    else:
        assert type(case) is ContainerRecoveryCase
        record.update(
            container=_store_bytes(
                case.case_id, "container", case.container, artifacts
            ),
            required_extensions=case.required_extensions,
            streams=tuple(
                {
                    "id": stream.stream_id,
                    "logical": _store_bytes(
                        case.case_id,
                        f"stream-{stream.stream_id}-logical",
                        stream.logical,
                        artifacts,
                    ),
                }
                for stream in case.streams
            ),
        )
    return record


def _load_stream(
    root: Traversable,
    case_id: str,
    record: JsonObject,
) -> RecoveredStreamExpectation:
    _require_keys(record, {"id", "logical"}, f"case {case_id} recovered stream")
    return RecoveredStreamExpectation(
        _require_integer(record, "id"),
        _load_bytes(root, record, "logical"),
    )


def _store_bytes(
    case_id: str,
    field: str,
    value: bytes,
    artifacts: dict[str, bytes],
) -> JsonObject:
    path = f"vectors/{case_id}.{field}.hex"
    artifacts[path] = (value.hex() + "\n").encode("ascii")
    return {"path": path, "sha256": hashlib.sha256(value).hexdigest()}


def _load_bytes(root: Traversable, record: JsonObject, field: str) -> bytes:
    reference = _require_object(field, record.get(field))
    _require_keys(reference, {"path", "sha256"}, f"{field} reference")
    path = _require_string(reference, "path")
    pure_path = PurePosixPath(path)
    if (
        pure_path.is_absolute()
        or not pure_path.parts
        or any(part in {"", ".", ".."} for part in pure_path.parts)
        or "\\" in path
    ):
        raise ValueError(f"{field} path must be a canonical relative POSIX path")
    expected_sha256 = _require_string(reference, "sha256")
    if _SHA256_PATTERN.fullmatch(expected_sha256) is None:
        raise ValueError(f"{field} sha256 must be lowercase hexadecimal")
    try:
        text = root.joinpath(*pure_path.parts).read_text(encoding="ascii")
        value = bytes.fromhex(text)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"cannot read {field} vector {path}: {exc}") from exc
    if hashlib.sha256(value).hexdigest() != expected_sha256:
        raise ValueError(f"{field} vector {path} has a wrong SHA-256")
    return value


def _dump_interpretation(
    interpretation: InspectionInterpretation | None,
) -> JsonObject | None:
    if interpretation is None:
        return None
    return {
        "label": interpretation.label,
        "fields": tuple(
            {"name": field.name, "value": field.value}
            for field in interpretation.fields
        ),
        "error": interpretation.error,
    }


def _load_optional_interpretation(value: object) -> InspectionInterpretation | None:
    if value is None:
        return None
    document = _require_object("interpretation", value)
    _require_keys(document, {"label", "fields", "error"}, "interpretation")
    label = _require_optional_string(document, "label")
    error = _require_optional_string(document, "error")
    fields = tuple(
        _load_interpretation_field(_require_object("interpretation field", item))
        for item in _require_list(document, "fields")
    )
    return InspectionInterpretation(label=label, fields=fields, error=error)


def _load_interpretation_field(document: JsonObject) -> InspectionField:
    _require_keys(document, {"name", "value"}, "interpretation field")
    value = document["value"]
    if value is not None and type(value) not in (str, int, bool):
        raise TypeError("interpretation field value has an unsupported JSON type")
    return InspectionField(
        _require_string(document, "name"),
        cast(InspectionValue, value),
    )


def _require_object(scope: str, value: object) -> JsonObject:
    if type(value) is not dict:
        raise TypeError(f"{scope} must be an object")
    return cast(JsonObject, value)


def _require_keys(document: JsonObject, expected: set[str], scope: str) -> None:
    if set(document) != expected:
        raise ValueError(f"{scope} must contain exactly {', '.join(sorted(expected))}")


def _require_list(document: JsonObject, field: str) -> list[object]:
    value = document.get(field)
    if type(value) is not list:
        raise TypeError(f"{field} must be an array")
    return cast(list[object], value)


def _require_string(document: JsonObject, field: str) -> str:
    return _require_exact_string(field, document.get(field))


def _require_exact_string(scope: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{scope} must be a string")
    return value


def _require_optional_string(document: JsonObject, field: str) -> str | None:
    value = document.get(field)
    if value is not None and type(value) is not str:
        raise TypeError(f"{field} must be a string or null")
    return value


def _require_boolean(document: JsonObject, field: str) -> bool:
    value = document.get(field)
    if type(value) is not bool:
        raise TypeError(f"{field} must be a boolean")
    return value


def _require_integer(document: JsonObject, field: str) -> int:
    value = document.get(field)
    if type(value) is not int:
        raise TypeError(f"{field} must be an integer")
    return value


__all__ = [
    "CONFORMANCE_SUITE_SCHEMA_VERSION",
    "load_conformance_suite",
    "write_conformance_suite",
]

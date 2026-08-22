from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
TRACE_SCHEMA_PATH = ROOT / "schemas" / "trace-event.schema.json"
SCHEMA_VERSION = "bb-trace-events/v1"
OBSERVER_SCHEMA_VERSION = "bb-guest-cpu-observer/v1"
CATEGORIES = {"resource", "access", "sync", "graphics", "timing"}
CATEGORY_KINDS = {
    "resource": {"create", "destroy"},
    "access": {"guest_cpu", "host_gpu"},
    "sync": {"barrier", "fence", "submit"},
    "graphics": {"draw", "dispatch", "present"},
    "timing": {"cpu_span", "gpu_span"},
}
OBSERVER_MECHANISM_BUILD_PATHS = {
    "access_violation": "non_userfaultfd",
    "userfaultfd_write_protect": "enable_userfaultfd",
}
OBSERVABLE_CAPABILITY_STATES = {"observable", "negative_validated"}


class TraceContractError(ValueError):
    pass


def _reject_duplicate(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TraceContractError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def loads_strict(text: str):
    def reject_constant(value):
        raise TraceContractError(f"non-finite JSON constant: {value}")

    return json.loads(text, object_pairs_hook=_reject_duplicate, parse_constant=reject_constant)


def load_strict(path: Path):
    return loads_strict(path.read_text(encoding="utf-8"))


def _sha256_repository_text(path: Path) -> str:
    """Hash repository text canonically across Git working-tree line endings."""
    canonical = path.read_text(encoding="utf-8").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def baseline_id_for(material) -> str:
    payload = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def validate_schema(document):
    try:
        import jsonschema
    except ModuleNotFoundError as exc:
        raise TraceContractError("jsonschema is required for schema validation") from exc

    schema = load_strict(TRACE_SCHEMA_PATH)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    if errors:
        location = "/".join(str(part) for part in errors[0].absolute_path) or "<root>"
        raise TraceContractError(f"schema validation failed at {location}: {errors[0].message}")
    return document


def _validate_bound_provenance(material) -> None:
    producer = material["producer"]
    producer_id = producer["producer_id"]

    actual_schema_sha256 = _sha256_repository_text(TRACE_SCHEMA_PATH)
    if producer["schema_sha256"] != actual_schema_sha256:
        raise TraceContractError("schema_sha256 does not match repository trace schema")

    if producer_id == "bb-trace-event-model":
        actual_producer_sha256 = _sha256_repository_text(Path(__file__))
        if producer["producer_sha256"] != actual_producer_sha256:
            raise TraceContractError("producer_sha256 does not match repository trace event model")

    if material["evidence_class"] == "runtime" and producer_id != "shadps4-bb-instrumentation":
        raise TraceContractError(
            "runtime evidence requires shadps4-bb-instrumentation producer provenance"
        )


def _validate_observer_capability(capability, direction: str) -> None:
    state = capability["state"]
    evidence_sha256 = capability.get("evidence_sha256")
    coverage_oracle_sha256 = capability.get("coverage_oracle_sha256")

    if state == "unknown":
        if coverage_oracle_sha256 is not None:
            raise TraceContractError(
                f"{direction} observer capability cannot bind a coverage oracle while state is unknown"
            )
        return

    if evidence_sha256 is None:
        raise TraceContractError(
            f"{direction} observer capability {state!r} requires independent evidence_sha256"
        )

    if state == "negative_validated":
        if coverage_oracle_sha256 is None:
            raise TraceContractError(
                f"{direction} negative_validated observer capability requires coverage_oracle_sha256"
            )
    elif coverage_oracle_sha256 is not None:
        raise TraceContractError(
            f"{direction} coverage_oracle_sha256 is only valid for negative_validated capability"
        )


def _validate_observer_provenance(material):
    observer = material.get("observer")
    if observer is None:
        return None

    if observer["schema_version"] != OBSERVER_SCHEMA_VERSION:
        raise TraceContractError("unsupported guest CPU observer schema_version")

    mechanism = observer["fault_mechanism"]
    expected_build_path = OBSERVER_MECHANISM_BUILD_PATHS.get(mechanism)
    if observer["build_path"] != expected_build_path:
        raise TraceContractError("guest CPU observer fault mechanism/build path mismatch")

    capabilities = observer["capabilities"]
    _validate_observer_capability(capabilities["read"], "read")
    _validate_observer_capability(capabilities["write"], "write")

    if (
        mechanism == "userfaultfd_write_protect"
        and capabilities["read"]["state"] != "unknown"
    ):
        raise TraceContractError(
            "userfaultfd_write_protect direct-read capability remains unknown in observer v1"
        )

    return observer


def _required_access_directions(access: str) -> tuple[str, ...]:
    if access == "read":
        return ("read",)
    if access == "write":
        return ("write",)
    if access == "read_write":
        return ("read", "write")
    raise TraceContractError(f"unsupported guest CPU access direction: {access!r}")


def _validate_runtime_guest_cpu_event(event, observer) -> None:
    if observer is None:
        raise TraceContractError(
            "runtime guest_cpu events require versioned observer provenance"
        )

    coverage = event["coverage"]
    if coverage == "unknown":
        return

    capabilities = observer["capabilities"]
    directions = _required_access_directions(event["access"])

    if coverage in {"observed", "ambiguous"}:
        for direction in directions:
            if capabilities[direction]["state"] not in OBSERVABLE_CAPABILITY_STATES:
                raise TraceContractError(
                    f"runtime guest_cpu {coverage} requires observable {direction} capability"
                )
        return

    if coverage == "unobserved":
        for direction in directions:
            capability = capabilities[direction]
            if capability["state"] != "negative_validated":
                raise TraceContractError(
                    f"runtime guest_cpu coverage=unobserved requires negative_validated {direction} capability"
                )
            if capability.get("coverage_oracle_sha256") is None:
                raise TraceContractError(
                    f"runtime guest_cpu coverage=unobserved requires {direction} coverage oracle"
                )


def _validate_event_contract(event) -> None:
    category = event["category"]
    kind = event["kind"]
    legal_kinds = CATEGORY_KINDS.get(category)
    if legal_kinds is None or kind not in legal_kinds:
        raise TraceContractError(f"event kind {kind!r} is invalid for category {category!r}")

    if category == "access":
        if "access" not in event or "coverage" not in event:
            raise TraceContractError("access events require access and coverage")
    else:
        if "access" in event or "coverage" in event:
            raise TraceContractError("access and coverage are only valid on access events")

    if category == "timing":
        if "duration_ns" not in event:
            raise TraceContractError("timing events require duration_ns")
    elif "duration_ns" in event:
        raise TraceContractError("duration_ns is only valid on timing events")

    if kind == "create":
        if "size_bytes" not in event:
            raise TraceContractError("resource create events require size_bytes")
    elif "size_bytes" in event:
        raise TraceContractError("size_bytes is only valid on resource create events")


def validate_semantics(document, *, expected_baseline_id: str | None = None):
    if document.get("schema_version") != SCHEMA_VERSION:
        raise TraceContractError("unsupported schema_version")

    provenance = document["provenance"]
    material = provenance["material"]
    actual_baseline_id = baseline_id_for(material)
    if provenance["baseline_id"] != actual_baseline_id:
        raise TraceContractError("baseline_id does not match provenance material")
    if expected_baseline_id is not None and actual_baseline_id != expected_baseline_id:
        raise TraceContractError("trace baseline does not match expected baseline")
    _validate_bound_provenance(material)
    observer = _validate_observer_provenance(material)

    capture = document["capture"]
    limits = capture["limits"]
    sampling = capture["sampling"]
    if sampling["mode"] == "all" and sampling["every_n"] != 1:
        raise TraceContractError("sampling mode 'all' requires every_n=1")

    events = document["events"]
    if len(events) > limits["max_events"]:
        raise TraceContractError("event count exceeds max_events")

    previous_seq = -1
    previous_timestamp = -1
    allowed = set(capture["filter"])
    for event in events:
        if event["category"] not in CATEGORIES or event["category"] not in allowed:
            raise TraceContractError("event category is not enabled by capture filter")
        _validate_event_contract(event)
        if event["seq"] != previous_seq + 1:
            raise TraceContractError("event seq must be contiguous from zero")
        if event["timestamp_ns"] < previous_timestamp:
            raise TraceContractError("timestamps must be monotonic")
        if material["evidence_class"] == "runtime" and event["kind"] == "guest_cpu":
            _validate_runtime_guest_cpu_event(event, observer)
        previous_seq = event["seq"]
        previous_timestamp = event["timestamp_ns"]

    summary = document["summary"]
    if summary["recorded_events"] != len(events):
        raise TraceContractError("recorded_events must equal serialized event count")
    if summary["buffer_high_water_bytes"] > limits["max_buffer_bytes"]:
        raise TraceContractError("buffer high-water mark exceeds configured bound")

    return document


def validate_document(path: Path, *, expected_baseline_id: str | None = None):
    document = load_strict(path)
    validate_schema(document)
    return validate_semantics(document, expected_baseline_id=expected_baseline_id)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate a bounded BB trace event stream")
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--expected-baseline-id",
        help="fail closed unless provenance material hashes to this exact baseline id",
    )
    args = parser.parse_args()
    validate_document(args.path, expected_baseline_id=args.expected_baseline_id)
    print("trace event contract valid")

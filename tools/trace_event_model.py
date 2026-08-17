from __future__ import annotations

import hashlib
import json
from pathlib import Path


SCHEMA_VERSION = "bb-trace-events/v1"
CATEGORIES = {"resource", "access", "sync", "graphics", "timing"}


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

    schema = load_strict(Path(__file__).parents[1] / "schemas" / "trace-event.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    if errors:
        location = "/".join(str(part) for part in errors[0].absolute_path) or "<root>"
        raise TraceContractError(f"schema validation failed at {location}: {errors[0].message}")
    return document


def validate_semantics(document, *, expected_baseline_id: str | None = None):
    if document.get("schema_version") != SCHEMA_VERSION:
        raise TraceContractError("unsupported schema_version")

    provenance = document["provenance"]
    actual_baseline_id = baseline_id_for(provenance["material"])
    if provenance["baseline_id"] != actual_baseline_id:
        raise TraceContractError("baseline_id does not match provenance material")
    if expected_baseline_id is not None and actual_baseline_id != expected_baseline_id:
        raise TraceContractError("trace baseline does not match expected baseline")

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
        if event["seq"] != previous_seq + 1:
            raise TraceContractError("event seq must be contiguous from zero")
        if event["timestamp_ns"] < previous_timestamp:
            raise TraceContractError("timestamps must be monotonic")
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

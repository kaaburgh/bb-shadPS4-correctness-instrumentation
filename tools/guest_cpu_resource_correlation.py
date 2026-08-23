from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


SCHEMA_VERSION = "bb-guest-cpu-resource-correlation/v1"
MAX_U64 = (1 << 64) - 1
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "guest-cpu-resource-correlation.schema.json"


class CorrelationError(ValueError):
    pass


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CorrelationError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def load_strict(path: Path):
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                CorrelationError(f"non-finite JSON constant: {value}")
            ),
        )
    except json.JSONDecodeError as exc:
        raise CorrelationError(f"invalid JSON: {exc}") from exc


def _load_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_schema(document):
    schema = _load_schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.path) or "<root>"
        raise CorrelationError(f"schema validation failed at {location}: {first.message}")


def _end_exclusive(start: int, size: int, *, label: str) -> int:
    if size <= 0:
        raise CorrelationError(f"{label} size must be positive")
    if start > MAX_U64 - (size - 1):
        raise CorrelationError(f"{label} range exceeds unsigned 64-bit address space")
    return start + size


def correlate(document):
    validate_schema(document)
    if document["schema_version"] != SCHEMA_VERSION:
        raise CorrelationError(f"unsupported schema version: {document['schema_version']}")

    seen_ids = set()
    normalized = []
    for resource in document["live_resources"]:
        resource_id = resource["resource_id"]
        if resource_id in seen_ids:
            raise CorrelationError(f"duplicate live resource id: {resource_id}")
        seen_ids.add(resource_id)
        start = resource["guest_address"]
        end = _end_exclusive(start, resource["size_bytes"], label=resource_id)
        normalized.append((resource_id, start, end))

    access = document["access"]
    access_start = access["guest_address"]
    access_end = _end_exclusive(access_start, access["size_bytes"], label="access")

    candidates = sorted(
        resource_id
        for resource_id, start, end in normalized
        if start <= access_start and access_end <= end
    )

    if len(candidates) == 1:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unique",
            "resource_id": candidates[0],
            "candidate_resource_ids": candidates,
        }
    if not candidates:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "unmapped",
            "resource_id": None,
            "candidate_resource_ids": [],
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ambiguous",
        "resource_id": None,
        "candidate_resource_ids": candidates,
    }


def analyze(path: Path):
    return correlate(load_strict(path))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Correlate one accepted guest-CPU access to live resource ranges"
    )
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.path), indent=2, sort_keys=True))

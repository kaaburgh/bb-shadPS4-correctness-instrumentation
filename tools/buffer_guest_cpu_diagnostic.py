#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

if __package__:
    from tools.buffer_resource_id_binding import BindingError, bind_lifetimes
    from tools.guest_cpu_resource_correlation import CorrelationError, correlate
else:
    from buffer_resource_id_binding import BindingError, bind_lifetimes
    from guest_cpu_resource_correlation import CorrelationError, correlate


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "buffer-guest-cpu-diagnostic.schema.json"
TRACE_SCHEMA_PATH = ROOT / "schemas" / "trace-event.schema.json"
SCHEMA_VERSION = "bb-buffer-guest-cpu-diagnostic/v1"
CORRELATION_SCHEMA_VERSION = "bb-guest-cpu-resource-correlation/v1"
BINDING_SCHEMA_VERSION = "bb-buffer-resource-id-binding/v1"
MAX_U64 = (1 << 64) - 1


class DiagnosticError(ValueError):
    pass


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DiagnosticError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def load_strict(path: Path):
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                DiagnosticError(f"non-finite JSON constant: {value}")
            ),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise DiagnosticError(str(exc)) from exc


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_contract(document) -> None:
    schema = _load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.absolute_path) or "<root>"
        raise DiagnosticError(f"schema validation failed at {location}: {first.message}")


def _trace_event_validator() -> Draft202012Validator:
    trace_schema = _load_json(TRACE_SCHEMA_PATH)
    event_schema = {
        "$schema": trace_schema["$schema"],
        "$defs": trace_schema["$defs"],
        "$ref": "#/$defs/event",
    }
    Draft202012Validator.check_schema(event_schema)
    return Draft202012Validator(event_schema, format_checker=FormatChecker())


def _checked_access_end(address: int, size: int, where: str) -> int:
    if address > MAX_U64 - (size - 1):
        raise DiagnosticError(f"{where} range exceeds unsigned 64-bit address space")
    return address + size


def _validate_sequence_domain(document) -> None:
    lifecycle_seqs = {event["seq"] for event in document["lifecycle_events"]}
    if len(lifecycle_seqs) != len(document["lifecycle_events"]):
        raise DiagnosticError("lifecycle sequence values must be unique")

    previous_access_seq = -1
    for index, access in enumerate(document["accepted_accesses"]):
        seq = access["seq"]
        if seq <= previous_access_seq:
            raise DiagnosticError("accepted-access seq must be strictly increasing")
        previous_access_seq = seq
        if seq in lifecycle_seqs:
            raise DiagnosticError(
                f"shared sequence domain collision at accepted_accesses[{index}].seq={seq}"
            )
        _checked_access_end(
            access["guest_address"], access["size_bytes"], f"accepted_accesses[{index}]"
        )


def _binding_document(document) -> dict:
    return {
        "schema_version": BINDING_SCHEMA_VERSION,
        "complete": document["complete_lifecycle"],
        "first_resource_ordinal": document["first_resource_ordinal"],
        "events": document["lifecycle_events"],
    }


def _live_resources(bindings: list[dict], seq: int) -> list[dict]:
    live = []
    for binding in bindings:
        end_seq = binding["end_seq"]
        if binding["start_seq"] < seq and (end_seq is None or seq < end_seq):
            live.append(
                {
                    "resource_id": binding["resource_id"],
                    "guest_address": binding["guest_address"],
                    "size_bytes": binding["size_bytes"],
                }
            )
    return live


def _validate_trace_event(event: dict, validator: Draft202012Validator) -> None:
    errors = sorted(validator.iter_errors(event), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.absolute_path) or "<root>"
        raise DiagnosticError(f"emitted trace event invalid at {location}: {first.message}")
    if event["category"] != "access" or event["kind"] != "guest_cpu":
        raise DiagnosticError("emitted event must be an access/guest_cpu trace event")
    if event["coverage"] != "observed":
        raise DiagnosticError("unique accepted access must emit coverage=observed")


def produce(document: dict) -> dict:
    _validate_contract(document)
    if document["schema_version"] != SCHEMA_VERSION or document["document_kind"] != "input":
        raise DiagnosticError("unsupported diagnostic input contract")
    _validate_sequence_domain(document)

    try:
        bound = bind_lifetimes(_binding_document(document))
    except BindingError as exc:
        raise DiagnosticError(f"buffer lifecycle binding failed: {exc}") from exc

    trace_validator = _trace_event_validator()
    events = []
    diagnostics = []
    unmapped = 0
    ambiguous = 0

    for access in document["accepted_accesses"]:
        correlation_input = {
            "schema_version": CORRELATION_SCHEMA_VERSION,
            "live_resources": _live_resources(bound["bindings"], access["seq"]),
            "access": {
                "guest_address": access["guest_address"],
                "size_bytes": access["size_bytes"],
            },
        }
        try:
            result = correlate(correlation_input)
        except CorrelationError as exc:
            raise DiagnosticError(f"accepted-access correlation failed at seq {access['seq']}: {exc}") from exc

        if result["status"] == "unique":
            event = {
                "seq": access["seq"],
                "timestamp_ns": access["timestamp_ns"],
                "category": "access",
                "kind": "guest_cpu",
                "correlation": {"resource_id": result["resource_id"]},
                "access": access["access"],
                "coverage": "observed",
            }
            _validate_trace_event(event, trace_validator)
            events.append(event)
            continue

        if result["status"] == "unmapped":
            unmapped += 1
        elif result["status"] == "ambiguous":
            ambiguous += 1
        else:
            raise DiagnosticError(f"unsupported correlation status: {result['status']!r}")

        diagnostics.append(
            {
                "seq": access["seq"],
                "timestamp_ns": access["timestamp_ns"],
                "guest_address": access["guest_address"],
                "size_bytes": access["size_bytes"],
                "access": access["access"],
                "status": result["status"],
                "candidate_resource_ids": result["candidate_resource_ids"],
            }
        )

    output = {
        "schema_version": SCHEMA_VERSION,
        "document_kind": "output",
        "complete_lifecycle": document["complete_lifecycle"],
        "next_resource_ordinal": bound["next_resource_ordinal"],
        "resource_bindings": bound["bindings"],
        "events": events,
        "diagnostics": diagnostics,
        "summary": {
            "accepted_accesses": len(document["accepted_accesses"]),
            "emitted_events": len(events),
            "unmapped": unmapped,
            "ambiguous": ambiguous,
        },
    }
    if len(events) + len(diagnostics) != len(document["accepted_accesses"]):
        raise DiagnosticError("producer accounting does not cover every accepted access")
    _validate_contract(output)
    return output


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <buffer-guest-cpu-diagnostic-input.json>", file=sys.stderr)
        return 2
    try:
        result = produce(load_strict(Path(argv[1])))
    except DiagnosticError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

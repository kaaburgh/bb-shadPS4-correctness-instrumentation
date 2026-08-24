#!/usr/bin/env python3
"""Validate and reconstruct deterministic raw-fault -> GPU-mapped acceptance pairings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "bb-guest-cpu-fault-pairing/v1"
MAX_U64 = (1 << 64) - 1
MAX_OBSERVATIONS = 1_000_000
_THREAD_PREFIX = "thread:"


class PairingError(ValueError):
    pass


def _require_exact_keys(obj: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(obj)
    if actual != expected:
        raise PairingError(
            f"{label} fields mismatch: expected {sorted(expected)}, got {sorted(actual)}"
        )


def _require_u64(value: Any, label: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PairingError(f"{label} must be an integer")
    minimum = 1 if positive else 0
    if not minimum <= value <= MAX_U64:
        raise PairingError(f"{label} must be in [{minimum}, {MAX_U64}]")
    return value


def _require_thread_id(value: Any) -> str:
    if not isinstance(value, str):
        raise PairingError("thread_id must be a string")
    if not value.startswith(_THREAD_PREFIX):
        raise PairingError("thread_id must match thread:[0-9]{8}")
    digits = value[len(_THREAD_PREFIX) :]
    if len(digits) != 8 or not digits.isdigit():
        raise PairingError("thread_id must match thread:[0-9]{8}")
    return value


def validate_input(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise PairingError("document must be an object")
    _require_exact_keys(
        document, {"schema_version", "document_kind", "complete", "observations"}, "document"
    )
    if document["schema_version"] != SCHEMA_VERSION:
        raise PairingError("unsupported schema_version")
    if document["document_kind"] != "input":
        raise PairingError("document_kind must be 'input'")
    if not isinstance(document["complete"], bool):
        raise PairingError("complete must be a boolean")

    observations = document["observations"]
    if not isinstance(observations, list):
        raise PairingError("observations must be an array")
    if len(observations) > MAX_OBSERVATIONS:
        raise PairingError("observation limit exceeded")

    previous_seq = -1
    previous_timestamp = -1
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            raise PairingError(f"observation[{index}] must be an object")
        event_type = observation.get("type")
        if event_type == "raw_fault":
            expected = {
                "type", "seq", "timestamp_ns", "thread_id", "guest_address", "access"
            }
        elif event_type == "accepted_access":
            expected = {
                "type", "seq", "timestamp_ns", "thread_id", "guest_address",
                "size_bytes", "access"
            }
        else:
            raise PairingError(f"observation[{index}] has unsupported type")
        _require_exact_keys(observation, expected, f"observation[{index}]")

        seq = _require_u64(observation["seq"], f"observation[{index}].seq")
        timestamp = _require_u64(
            observation["timestamp_ns"], f"observation[{index}].timestamp_ns"
        )
        _require_thread_id(observation["thread_id"])
        address = _require_u64(
            observation["guest_address"], f"observation[{index}].guest_address"
        )
        if observation["access"] not in {"read", "write"}:
            raise PairingError(f"observation[{index}].access must be read or write")
        if seq <= previous_seq:
            raise PairingError("observation seq must be strictly increasing")
        if timestamp < previous_timestamp:
            raise PairingError("observation timestamp_ns must be monotonic")
        previous_seq = seq
        previous_timestamp = timestamp

        if event_type == "accepted_access":
            size = _require_u64(
                observation["size_bytes"], f"observation[{index}].size_bytes", positive=True
            )
            if address + size > MAX_U64 + 1:
                raise PairingError(
                    "accepted access range overflows unsigned 64-bit address space"
                )
    return document


def reconstruct(document: Any) -> dict[str, Any]:
    validated = validate_input(document)
    pending: dict[str, list[dict[str, Any]]] = {}
    pairings: list[dict[str, Any]] = []
    paired_accesses: list[dict[str, Any]] = []
    raw_fault_count = 0
    accepted_count = 0

    for observation in validated["observations"]:
        thread_pending = pending.setdefault(observation["thread_id"], [])
        if observation["type"] == "raw_fault":
            raw_fault_count += 1
            thread_pending.append(observation)
            continue

        accepted_count += 1
        candidates = [
            fault
            for fault in thread_pending
            if fault["guest_address"] == observation["guest_address"]
            and fault["access"] == observation["access"]
        ]
        if len(candidates) == 1:
            raw = candidates[0]
            pairings.append(
                {
                    "accepted_seq": observation["seq"],
                    "status": "paired",
                    "raw_seq": raw["seq"],
                }
            )
            paired_accesses.append(
                {
                    "seq": observation["seq"],
                    "timestamp_ns": observation["timestamp_ns"],
                    "guest_address": observation["guest_address"],
                    "size_bytes": observation["size_bytes"],
                    "access": observation["access"],
                }
            )
            thread_pending.remove(raw)
        elif not candidates:
            pairings.append({"accepted_seq": observation["seq"], "status": "unmatched"})
        else:
            pairings.append(
                {
                    "accepted_seq": observation["seq"],
                    "status": "ambiguous",
                    "candidate_raw_seqs": [fault["seq"] for fault in candidates],
                }
            )

    unpaired = sorted(
        fault["seq"] for thread_pending in pending.values() for fault in thread_pending
    )
    summary = {
        "raw_faults": raw_fault_count,
        "accepted_accesses": accepted_count,
        "paired": sum(pairing["status"] == "paired" for pairing in pairings),
        "unmatched": sum(pairing["status"] == "unmatched" for pairing in pairings),
        "ambiguous": sum(pairing["status"] == "ambiguous" for pairing in pairings),
        "unpaired_raw_faults": len(unpaired),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "document_kind": "output",
        "complete": validated["complete"],
        "pairings": pairings,
        "paired_accesses": paired_accesses,
        "unpaired_raw_seqs": unpaired,
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    document = json.loads(args.input.read_text(encoding="utf-8"))
    json.dump(reconstruct(document), __import__("sys").stdout, indent=2, sort_keys=True)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

SCHEMA_VERSION = "bb-buffer-resource-id-binding/v1"
MAX_U64 = (1 << 64) - 1
MAX_EVENTS = 1_000_000
MAX_RESOURCE_ORDINAL = 99_999_999


class BindingError(ValueError):
    pass


def _load_strict(path: Path) -> dict:
    def hook(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise BindingError(f"duplicate JSON member: {key}")
            obj[key] = value
        return obj

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=hook)
    except (OSError, json.JSONDecodeError) as exc:
        raise BindingError(str(exc)) from exc
    if not isinstance(value, dict):
        raise BindingError("top-level document must be an object")
    return value


def _expect_exact_keys(obj: dict, expected: set[str], where: str) -> None:
    actual = set(obj)
    if actual != expected:
        raise BindingError(f"{where} fields mismatch: expected {sorted(expected)}, got {sorted(actual)}")


def _u64(value, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BindingError(f"{name} must be an integer")
    minimum = 1 if positive else 0
    if not minimum <= value <= MAX_U64:
        raise BindingError(f"{name} outside unsigned 64-bit range")
    return value


def _resource_ordinal(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_RESOURCE_ORDINAL:
        raise BindingError("first_resource_ordinal outside trace resource-ID namespace")
    return value


def _buffer_id(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
        raise BindingError("buffer_id outside unsigned 32-bit range")
    return value


def _checked_end(address: int, size: int, where: str) -> int:
    end = address + size
    if end > MAX_U64 + 1:
        raise BindingError(f"{where} range overflows unsigned 64-bit address space")
    return end


def bind_lifetimes(document: dict) -> dict:
    _expect_exact_keys(document, {"schema_version", "complete", "first_resource_ordinal", "events"}, "document")
    if document["schema_version"] != SCHEMA_VERSION:
        raise BindingError(f"unsupported schema_version: {document['schema_version']!r}")
    if not isinstance(document["complete"], bool):
        raise BindingError("complete must be boolean")
    next_resource_ordinal = _resource_ordinal(document["first_resource_ordinal"])
    events = document["events"]
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise BindingError("events must be a bounded array")

    active: dict[int, dict] = {}
    bindings: list[dict] = []
    previous_seq = -1

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise BindingError(f"events[{index}] must be an object")
        _expect_exact_keys(event, {"seq", "buffer_id", "guest_address", "size_bytes", "live"}, f"events[{index}]")
        seq = _u64(event["seq"], f"events[{index}].seq")
        if seq <= previous_seq:
            raise BindingError("lifecycle seq must be strictly increasing")
        previous_seq = seq
        buffer_id = _buffer_id(event["buffer_id"])
        address = _u64(event["guest_address"], f"events[{index}].guest_address")
        size = _u64(event["size_bytes"], f"events[{index}].size_bytes", positive=True)
        _checked_end(address, size, f"events[{index}]")
        live = event["live"]
        if not isinstance(live, bool):
            raise BindingError(f"events[{index}].live must be boolean")

        if live:
            if buffer_id in active:
                raise BindingError(f"buffer_id {buffer_id} registered while already live")
            if next_resource_ordinal > MAX_RESOURCE_ORDINAL:
                raise BindingError("resource_id namespace exhausted")
            binding = {
                "buffer_id": buffer_id,
                "resource_id": f"res:{next_resource_ordinal:08d}",
                "guest_address": address,
                "size_bytes": size,
                "start_seq": seq,
                "end_seq": None,
            }
            next_resource_ordinal += 1
            active[buffer_id] = binding
            bindings.append(binding)
        else:
            binding = active.get(buffer_id)
            if binding is None:
                raise BindingError(f"buffer_id {buffer_id} unregistered without active lifetime")
            if binding["guest_address"] != address or binding["size_bytes"] != size:
                raise BindingError(f"buffer_id {buffer_id} unregister range does not match active lifetime")
            binding["end_seq"] = seq
            del active[buffer_id]

    if document["complete"] and active:
        raise BindingError(f"complete lifecycle stream ended with live buffer_ids: {sorted(active)}")

    return {
        "schema_version": "bb-buffer-resource-id-bindings/v1",
        "complete": document["complete"],
        "next_resource_ordinal": next_resource_ordinal,
        "bindings": bindings,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <lifecycle.json>", file=sys.stderr)
        return 2
    try:
        result = bind_lifetimes(_load_strict(Path(argv[1])))
    except BindingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

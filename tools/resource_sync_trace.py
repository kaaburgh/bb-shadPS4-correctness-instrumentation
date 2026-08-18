from __future__ import annotations

import json
from pathlib import Path

try:
    from tools import trace_event_model
except ModuleNotFoundError:
    import trace_event_model


class ResourceTraceError(ValueError):
    pass


def reconstruct(document):
    trace_event_model.validate_schema(document)
    trace_event_model.validate_semantics(document)

    resources = {}
    active = set()

    def state_for(resource_id):
        return resources.setdefault(
            resource_id,
            {
                "resource_id": resource_id,
                "create_seq": None,
                "destroy_seq": None,
                "accesses": [],
                "sync": [],
                "graphics": [],
                "guest_cpu_coverage_states": [],
            },
        )

    for event in document["events"]:
        resource_id = event["correlation"].get("resource_id")
        if resource_id is None:
            continue

        state = state_for(resource_id)
        kind = event["kind"]

        if event["category"] == "resource" and kind == "create":
            if resource_id in active or state["create_seq"] is not None:
                raise ResourceTraceError(f"duplicate create for {resource_id}")
            state["create_seq"] = event["seq"]
            active.add(resource_id)
            continue

        if event["category"] == "resource" and kind == "destroy":
            if resource_id not in active:
                raise ResourceTraceError(f"destroy without active lifetime for {resource_id}")
            state["destroy_seq"] = event["seq"]
            active.remove(resource_id)
            continue

        if resource_id not in active:
            raise ResourceTraceError(f"event outside active lifetime for {resource_id}")

        record = {
            "seq": event["seq"],
            "timestamp_ns": event["timestamp_ns"],
            "kind": kind,
            "correlation": dict(event["correlation"]),
        }
        if "access" in event:
            record["access"] = event["access"]
        if "coverage" in event:
            record["coverage"] = event["coverage"]

        if event["category"] == "access":
            state["accesses"].append(record)
            if kind == "guest_cpu":
                coverage = event.get("coverage", "unknown")
                if coverage not in state["guest_cpu_coverage_states"]:
                    state["guest_cpu_coverage_states"].append(coverage)
        elif event["category"] == "sync":
            state["sync"].append(record)
        elif event["category"] == "graphics":
            state["graphics"].append(record)

    for resource_id, state in resources.items():
        if state["create_seq"] is None:
            raise ResourceTraceError(f"resource has no create event: {resource_id}")
        if state["destroy_seq"] is None:
            state["lifetime_state"] = "open"
        else:
            state["lifetime_state"] = "closed"
        if not state["guest_cpu_coverage_states"]:
            state["guest_cpu_coverage_states"] = ["unknown"]

    return {
        "schema_version": "bb-resource-sync-reconstruction/v1",
        "trace_baseline_id": document["provenance"]["baseline_id"],
        "resources": [resources[key] for key in sorted(resources)],
        "limitations": [
            "synthetic reconstruction does not prove target runtime observer coverage",
            "absence of guest_cpu access events is not evidence for GPU-only classification",
        ],
    }


def analyze(path: Path):
    return reconstruct(trace_event_model.load_strict(path))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Reconstruct resource/access/sync timelines")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.path), indent=2, sort_keys=True))

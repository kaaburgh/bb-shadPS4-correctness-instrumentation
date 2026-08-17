#!/usr/bin/env python3
"""Validate BB-COR1 correctness inventory cases."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "correctness-case.schema.json"


class CorrectnessCaseError(ValueError):
    pass


def load_strict(path: Path) -> Mapping[str, Any]:
    def reject_constant(value: str) -> None:
        raise CorrectnessCaseError(f"non-finite JSON number: {value}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CorrectnessCaseError(f"unable to read correctness case: {error}") from error
    if not isinstance(value, dict):
        raise CorrectnessCaseError("correctness case must be a JSON object")
    return value


def _runtime_evidence(case: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [entry for entry in case["provenance"]["evidence"] if entry["class"] == "runtime"]


def _has_controlled_host_contrast(runtime: list[Mapping[str, Any]]) -> bool:
    hosts_by_non_host_baseline: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for entry in runtime:
        baseline = entry["baseline"]
        target = baseline["target_manifest_sha256"]
        host = baseline["host_manifest_sha256"]
        if target is None or host is None:
            continue
        key = (
            baseline["source_repository"],
            baseline["source_commit"],
            target,
        )
        hosts_by_non_host_baseline[key].add(host)
    return any(len(hosts) >= 2 for hosts in hosts_by_non_host_baseline.values())


def validate_case(case: Mapping[str, Any], schema_path: Path = SCHEMA_PATH) -> None:
    try:
        import jsonschema
    except ImportError as error:
        raise CorrectnessCaseError("jsonschema is required for correctness-case validation") from error
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(case)

    evidence = case["provenance"]["evidence"]
    classes = {entry["class"] for entry in evidence}
    runtime = _runtime_evidence(case)
    for entry in runtime:
        baseline = entry["baseline"]
        if baseline["target_manifest_sha256"] is None or baseline["host_manifest_sha256"] is None:
            raise CorrectnessCaseError("runtime evidence requires exact target and host baseline references")

    reproduction = case["reproduction"]
    status = reproduction["status"]
    quality = reproduction["quality"]
    scenario_id = reproduction["scenario_id"]
    if status == "reported_only":
        if runtime:
            raise CorrectnessCaseError("reported_only cannot contain runtime evidence")
        if quality != "none" or scenario_id is not None:
            raise CorrectnessCaseError("reported_only requires quality=none and scenario_id=null")
    elif status in {"reproduced", "not_reproduced", "stale"}:
        if not runtime:
            raise CorrectnessCaseError(f"{status} status requires runtime evidence")
        if quality not in {"bounded", "repeatable"} or scenario_id is None:
            raise CorrectnessCaseError(
                f"{status} status requires bounded or repeatable quality and a scenario_id"
            )

    classification = case["classification"]
    kind = classification["kind"]
    ownership_kinds = {"generic_bug", "backend_specific", "driver_specific", "title_specific"}
    if kind in ownership_kinds:
        if not classification["semantic_seam"]:
            raise CorrectnessCaseError(f"{kind} requires an established semantic_seam")
        if not (classes & {"static", "runtime"}):
            raise CorrectnessCaseError(
                f"{kind} requires static or runtime evidence, not only reported/synthetic/assumed evidence"
            )
    if kind in {"backend_specific", "driver_specific"} and not _has_controlled_host_contrast(runtime):
        raise CorrectnessCaseError(
            f"{kind} requires at least two exact host baselines while source repository, "
            "source commit, target manifest, and case scenario remain fixed"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path, nargs="+")
    args = parser.parse_args()
    for path in args.case:
        validate_case(load_strict(path))
        print(f"valid: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

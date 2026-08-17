#!/usr/bin/env python3
"""Validate BB-COR1 correctness inventory cases."""
from __future__ import annotations

import argparse
import json
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


def validate_case(case: Mapping[str, Any], schema_path: Path = SCHEMA_PATH) -> None:
    try:
        import jsonschema
    except ImportError as error:
        raise CorrectnessCaseError("jsonschema is required for correctness-case validation") from error
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(case)

    classes = {entry["class"] for entry in case["provenance"]["evidence"]}
    reproduction = case["reproduction"]
    if reproduction["status"] == "reproduced" and "runtime" not in classes:
        raise CorrectnessCaseError("reproduced status requires runtime evidence")
    if reproduction["status"] == "reported_only" and "runtime" in classes:
        raise CorrectnessCaseError("reported_only cannot contain runtime evidence")
    if reproduction["status"] == "reproduced" and reproduction["quality"] in {"none", "partial"}:
        raise CorrectnessCaseError("reproduced status requires bounded or repeatable reproduction quality")

    classification = case["classification"]
    if classification["kind"] == "generic_bug":
        if not classification["semantic_seam"]:
            raise CorrectnessCaseError("generic_bug requires an established semantic_seam")
        if not (classes & {"static", "runtime"}):
            raise CorrectnessCaseError("generic_bug requires static or runtime evidence, not only reported/synthetic/assumed evidence")


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

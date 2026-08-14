#!/usr/bin/env python3
"""Validate and compare Bloodborne target identity manifests.

JSON Schema validates the serialized shape.  This module adds the v1 semantic
invariants that JSON Schema cannot express: duplicate-member rejection,
modification-order closure, and unknown-aware three-way comparison.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "bloodborne-target-manifest.schema.json"
_MISSING = object()


class ManifestError(ValueError):
    """Raised when a manifest cannot be interpreted safely."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def loads_strict(text: str) -> Any:
    """Parse JSON while rejecting duplicate object members."""
    try:
        return json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as error:
        raise ManifestError(f"invalid JSON: {error}") from error


def _reject_constant(name: str) -> Any:
    raise ManifestError(f"non-finite JSON constant is not valid JSON: {name}")


def load_strict(path: Path) -> Any:
    try:
        return loads_strict(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ManifestError(f"unable to read {path}") from error


def _jsonschema_validator(schema: Mapping[str, Any]):
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ModuleNotFoundError as error:
        raise ManifestError("jsonschema==4.25.1 is required for manifest validation") from error

    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_semantics(manifest: Mapping[str, Any]) -> None:
    """Validate v1 cross-field invariants after JSON Schema validation."""
    configuration = manifest["configuration"]
    modifications = configuration["active_modifications"]
    order = configuration["modification_order"]["value"]
    for setting in configuration["settings"].values():
        _setting_value(setting)
    if len(order) != len(modifications) or set(order) != set(modifications):
        raise ManifestError(
            "modification_order must contain every active modification ID exactly once"
        )

    unknown_fields = set(manifest["identity_completeness"]["unknown_fields"])
    for pointer in unknown_fields:
        _pointer_tokens(pointer)
    if (
        "/configuration/active_modifications" in unknown_fields
        and "/configuration/modification_order" not in unknown_fields
    ):
        raise ManifestError(
            "an unknown active-modification set also makes modification_order unknown"
        )


def validate_manifest(
    manifest: Mapping[str, Any], *, schema_path: Path = SCHEMA_PATH
) -> None:
    """Validate an already strictly parsed manifest mapping."""
    schema = load_strict(schema_path)
    validator = _jsonschema_validator(schema)
    errors = sorted(
        validator.iter_errors(manifest),
        key=lambda error: tuple(str(token) for token in error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = "/" + "/".join(str(token) for token in first.absolute_path)
        raise ManifestError(f"schema validation failed at {location}: {first.message}")
    validate_semantics(manifest)


def validate_document(text: str, *, schema_path: Path = SCHEMA_PATH) -> dict[str, Any]:
    """Strictly parse and validate a manifest document in one safe operation."""
    manifest = loads_strict(text)
    if not isinstance(manifest, dict):
        raise ManifestError("manifest document must contain a JSON object")
    validate_manifest(manifest, schema_path=schema_path)
    return manifest


def validate_file(path: Path, *, schema_path: Path = SCHEMA_PATH) -> dict[str, Any]:
    """Read, strictly parse, and validate one manifest file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ManifestError(f"unable to read {path}") from error
    return validate_document(text, schema_path=schema_path)


def _escape_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    if not pointer.startswith("/"):
        raise ManifestError(f"invalid JSON Pointer: {pointer}")
    tokens = pointer[1:].split("/")
    if any("~" in token.replace("~1", "").replace("~0", "") for token in tokens):
        raise ManifestError(f"invalid JSON Pointer escape: {pointer}")
    return tuple(token.replace("~1", "/").replace("~0", "~") for token in tokens)


def _pointers_overlap(left: str, right: str) -> bool:
    left_tokens = _pointer_tokens(left)
    right_tokens = _pointer_tokens(right)
    common = min(len(left_tokens), len(right_tokens))
    return left_tokens[:common] == right_tokens[:common]


def _artifact_value(artifact: Mapping[str, Any]) -> tuple[str, int]:
    return artifact["sha256"], artifact["size_bytes"]


def _setting_value(setting: Mapping[str, Any]) -> tuple[str, Any]:
    value = setting["value"]
    if isinstance(value, bool):
        return "boolean", value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ManifestError("non-finite numeric setting value is not allowed")
        return "number", value
    if isinstance(value, str):
        return "string", value
    raise ManifestError("setting value must be boolean, number, or string")


def _material_projection(manifest: Mapping[str, Any]) -> dict[str, Any]:
    build = manifest["build"]
    content = manifest["content"]
    configuration = manifest["configuration"]
    tree = content["resolved_tree"]
    projection: dict[str, Any] = {
        "/target/title_id/value": manifest["target"]["title_id"]["value"],
        "/build/eboot": _artifact_value(build["eboot"]),
        "/build/param_sfo": _artifact_value(build["param_sfo"]),
        "/content/resolved_tree": (
            tree["algorithm"],
            tree["sha256"],
            tree["file_count"],
            tree["total_bytes"],
        ),
        "/configuration/modification_order/value": tuple(
            configuration["modification_order"]["value"]
        ),
    }
    for key, setting in configuration["settings"].items():
        pointer = f"/configuration/settings/{_escape_pointer_token(key)}"
        projection[pointer] = _setting_value(setting)
    for identifier, modification in configuration["active_modifications"].items():
        pointer = f"/configuration/active_modifications/{_escape_pointer_token(identifier)}"
        projection[pointer] = (
            modification["kind"],
            *_artifact_value(modification["artifact"]),
        )
    return projection


def _path_is_unknown(manifest: Mapping[str, Any], path: str) -> bool:
    return any(
        _pointers_overlap(path, unknown)
        for unknown in manifest["identity_completeness"]["unknown_fields"]
    )


def compare_validated(left: Mapping[str, Any], right: Mapping[str, Any]) -> str:
    """Return same, different, or indeterminate for two validated v1 manifests."""
    left_projection = _material_projection(left)
    right_projection = _material_projection(right)
    known_difference = False
    uncertain_difference = False
    for path in sorted(set(left_projection) | set(right_projection)):
        if left_projection.get(path, _MISSING) == right_projection.get(path, _MISSING):
            continue
        if _path_is_unknown(left, path) or _path_is_unknown(right, path):
            uncertain_difference = True
        else:
            known_difference = True

    if known_difference:
        return "different"
    if uncertain_difference:
        return "indeterminate"
    if (
        left["identity_completeness"]["state"] == "complete"
        and right["identity_completeness"]["state"] == "complete"
    ):
        return "same"
    return "indeterminate"


def compare_manifests(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    schema_path: Path = SCHEMA_PATH,
) -> str:
    validate_manifest(left, schema_path=schema_path)
    validate_manifest(right, schema_path=schema_path)
    return compare_validated(left, right)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate one manifest")
    validate.add_argument("manifest", type=Path)
    compare = subparsers.add_parser("compare", help="compare two manifests")
    compare.add_argument("left", type=Path)
    compare.add_argument("right", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.command == "validate":
            validate_file(args.manifest, schema_path=args.schema)
            print("valid")
            return 0
        result = compare_manifests(
            load_strict(args.left), load_strict(args.right), schema_path=args.schema
        )
        print(result)
        return {"same": 0, "different": 1, "indeterminate": 2}[result]
    except ManifestError as error:
        print(f"error: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.shadps4_source_baseline import COMMIT as _PINNED_COMMIT
from tools.shadps4_source_baseline import REPOSITORY as _PINNED_REPOSITORY

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import graphics_pipeline_key_surface

MODEL_VERSION = "bb-graphics-identity/v2"
PINNED_SOURCE = {
    "repository": _PINNED_REPOSITORY,
    "commit": _PINNED_COMMIT,
}
PIPELINE_KEY_SURFACE = Path("docs/instrumentation/graphics-pipeline-key-surface.json")
LOGICAL_STAGES = {
    "vertex",
    "tessellation_control",
    "tessellation_eval",
    "geometry",
    "fragment",
    "compute",
}
ATTACHMENT_ROLES = {"color", "depth", "stencil"}
PIPELINE_FAMILY_STATE_KEYS = {
    "primitive_type",
    "polygon_mode",
    "clip_space",
    "num_samples",
    "depth_samples",
    "color_formats",
    "depth_format",
    "stencil_format",
}


class GraphicsIdentityError(ValueError):
    pass


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _identity(kind: str, value) -> str:
    digest = hashlib.sha256(_canonical({"kind": kind, "value": value})).hexdigest()
    return f"{kind}:sha256:{digest}"


def _require_exact_keys(value: dict, required: set[str], optional: set[str] | None = None) -> None:
    optional = optional or set()
    if not isinstance(value, dict):
        raise GraphicsIdentityError("expected object")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing:
        raise GraphicsIdentityError(f"missing keys: {sorted(missing)}")
    if extra:
        raise GraphicsIdentityError(f"unexpected keys: {sorted(extra)}")


def _require_text(value, field: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 96:
        raise GraphicsIdentityError(f"{field} must be a bounded non-empty string")


def _require_integer(value, *, bits: int, signed: bool, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise GraphicsIdentityError(f"{field} must be an integer")
    if signed:
        minimum = -(1 << (bits - 1))
        maximum = (1 << (bits - 1)) - 1
    else:
        minimum = 0
        maximum = (1 << bits) - 1
    if value < minimum or value > maximum:
        raise GraphicsIdentityError(f"{field} is outside its {bits}-bit canonical domain")


def _validate_canonical_value(value, rule: dict, field: str) -> None:
    kind = rule["kind"]
    if kind in {"unsigned_integer", "raw_bit_pattern", "enum_unsigned_integer"}:
        _require_integer(value, bits=rule["bits"], signed=False, field=field)
        if "values" in rule and value not in rule["values"]:
            raise GraphicsIdentityError(f"{field} is outside the canonical enum domain")
        return
    if kind == "enum_signed_integer_array":
        if not isinstance(value, list) or len(value) != rule["length"]:
            raise GraphicsIdentityError(f"{field} must contain exactly {rule['length']} entries")
        for index, item in enumerate(value):
            _require_integer(item, bits=rule["bits"], signed=True, field=f"{field}[{index}]")
        return
    if kind in {"unsigned_integer_array", "raw_bit_pattern_array", "enum_unsigned_integer_array"}:
        if not isinstance(value, list) or len(value) != rule["length"]:
            raise GraphicsIdentityError(f"{field} must contain exactly {rule['length']} entries")
        for index, item in enumerate(value):
            _require_integer(item, bits=rule["bits"], signed=False, field=f"{field}[{index}]")
            if "values" in rule and item not in rule["values"]:
                raise GraphicsIdentityError(f"{field}[{index}] is outside the canonical enum domain")
        return
    if kind == "record_array":
        if not isinstance(value, list) or len(value) != rule["length"]:
            raise GraphicsIdentityError(f"{field} must contain exactly {rule['length']} records")
        expected = {component["name"] for component in rule["fields"]}
        for index, record in enumerate(value):
            _require_exact_keys(record, expected)
            for component in rule["fields"]:
                _validate_canonical_value(
                    record[component["name"]],
                    component,
                    f"{field}[{index}].{component['name']}",
                )
        return
    raise GraphicsIdentityError(f"unsupported canonicalization kind for {field}: {kind}")


def _load_pipeline_surface() -> tuple[dict, str]:
    try:
        document = json.loads(PIPELINE_KEY_SURFACE.read_text(encoding="utf-8"))
        summary = graphics_pipeline_key_surface.validate(document)
    except (OSError, json.JSONDecodeError, graphics_pipeline_key_surface.PipelineKeySurfaceError) as exc:
        raise GraphicsIdentityError(f"canonical pipeline key surface is unavailable or invalid: {exc}") from exc
    if not summary["pipeline_identity_ready"]:
        raise GraphicsIdentityError("canonical pipeline identity surface is incomplete")
    digest = hashlib.sha256(_canonical(document)).hexdigest()
    return document, f"sha256:{digest}"


def _validate_pipeline_key(pipeline_key: dict, surface_document: dict) -> dict:
    fields = surface_document["fields"]
    expected_names = tuple(field["name"] for field in fields)
    _require_exact_keys(pipeline_key, set(expected_names))
    for field in fields:
        if field["exact_canonicalization"] != "complete" or "canonicalization" not in field:
            raise GraphicsIdentityError(f"canonical pipeline identity is not ready for field {field['name']}")
        _validate_canonical_value(
            pipeline_key[field["name"]],
            field["canonicalization"],
            f"pipeline_key.{field['name']}",
        )
    return {name: pipeline_key[name] for name in expected_names}


def derive(document: dict) -> dict:
    _require_exact_keys(
        document,
        {"model_version", "source", "shaders", "pipeline_state", "pipeline_key", "render_state"},
    )
    if document["model_version"] != MODEL_VERSION:
        raise GraphicsIdentityError("unsupported model_version")
    if document["source"] != PINNED_SOURCE:
        raise GraphicsIdentityError("source must match the pinned BB-BL1 baseline exactly")

    shaders = document["shaders"]
    if not isinstance(shaders, list) or not shaders:
        raise GraphicsIdentityError("shaders must be a non-empty list")
    normalized_shaders = []
    seen_stages = set()
    for shader in shaders:
        _require_exact_keys(shader, {"logical_stage", "stage_hash"})
        stage = shader["logical_stage"]
        stage_hash = shader["stage_hash"]
        if stage not in LOGICAL_STAGES:
            raise GraphicsIdentityError(f"unsupported logical_stage: {stage}")
        if stage in seen_stages:
            raise GraphicsIdentityError(f"duplicate logical_stage: {stage}")
        if not isinstance(stage_hash, str) or len(stage_hash) != 16:
            raise GraphicsIdentityError("stage_hash must be 16 lowercase hexadecimal characters")
        try:
            int(stage_hash, 16)
        except ValueError as exc:
            raise GraphicsIdentityError("stage_hash must be hexadecimal") from exc
        if stage_hash.lower() != stage_hash:
            raise GraphicsIdentityError("stage_hash must be lowercase")
        seen_stages.add(stage)
        semantic = {"source": PINNED_SOURCE, "logical_stage": stage, "stage_hash": stage_hash}
        normalized_shaders.append({**shader, "shader_identity": _identity("shader", semantic)})
    normalized_shaders.sort(key=lambda item: item["logical_stage"])

    pipeline_state = document["pipeline_state"]
    _require_exact_keys(pipeline_state, PIPELINE_FAMILY_STATE_KEYS)
    for field in ("primitive_type", "polygon_mode", "clip_space", "depth_format", "stencil_format"):
        _require_text(pipeline_state[field], f"pipeline_state.{field}")
    for field in ("num_samples", "depth_samples"):
        if not isinstance(pipeline_state[field], int) or pipeline_state[field] <= 0 or pipeline_state[field] > 64:
            raise GraphicsIdentityError(f"pipeline_state.{field} must be an integer in [1, 64]")
    color_formats = pipeline_state["color_formats"]
    if not isinstance(color_formats, list) or len(color_formats) > 8:
        raise GraphicsIdentityError("pipeline_state.color_formats must contain at most 8 entries")
    for value in color_formats:
        _require_text(value, "pipeline_state.color_formats[]")

    pipeline_family_semantic = {
        "source": PINNED_SOURCE,
        "shader_identities": [item["shader_identity"] for item in normalized_shaders],
        "state_projection": pipeline_state,
    }

    surface_document, surface_digest = _load_pipeline_surface()
    canonical_pipeline_key = _validate_pipeline_key(document["pipeline_key"], surface_document)
    pipeline_semantic = {
        "source": PINNED_SOURCE,
        "key_surface_version": surface_document["schema_version"],
        "key_surface_sha256": surface_digest,
        "canonical_key": canonical_pipeline_key,
    }

    render_state = document["render_state"]
    _require_exact_keys(render_state, {"width", "height", "layers", "attachments"})
    for field in ("width", "height", "layers"):
        if not isinstance(render_state[field], int) or render_state[field] <= 0:
            raise GraphicsIdentityError(f"render_state.{field} must be a positive integer")
    attachments = render_state["attachments"]
    if not isinstance(attachments, list) or len(attachments) > 10:
        raise GraphicsIdentityError("render_state.attachments must contain at most 10 entries")
    normalized_attachments = []
    color_indices = set()
    seen_depth = False
    seen_stencil = False
    for attachment in attachments:
        _require_exact_keys(attachment, {"role", "format", "samples", "load_op", "store_op"}, {"index"})
        role = attachment["role"]
        if role not in ATTACHMENT_ROLES:
            raise GraphicsIdentityError(f"unsupported attachment role: {role}")
        if role == "color":
            index = attachment.get("index")
            if not isinstance(index, int) or index < 0 or index > 7:
                raise GraphicsIdentityError("color attachment requires index in [0, 7]")
            if index in color_indices:
                raise GraphicsIdentityError("duplicate color attachment index")
            color_indices.add(index)
        elif "index" in attachment:
            raise GraphicsIdentityError("depth/stencil attachment must not have index")
        elif role == "depth":
            if seen_depth:
                raise GraphicsIdentityError("duplicate depth attachment")
            seen_depth = True
        else:
            if seen_stencil:
                raise GraphicsIdentityError("duplicate stencil attachment")
            seen_stencil = True
        _require_text(attachment["format"], "attachment.format")
        if not isinstance(attachment["samples"], int) or attachment["samples"] <= 0 or attachment["samples"] > 64:
            raise GraphicsIdentityError("attachment samples must be an integer in [1, 64]")
        if attachment["load_op"] not in {"load", "clear"}:
            raise GraphicsIdentityError("load_op must be load or clear")
        if attachment["store_op"] != "store":
            raise GraphicsIdentityError("pinned BeginRendering seam currently uses store")
        normalized_attachments.append(dict(attachment))
    normalized_attachments.sort(key=lambda item: (item["role"], item.get("index", -1)))
    render_semantic = {
        "source": PINNED_SOURCE,
        "width": render_state["width"],
        "height": render_state["height"],
        "layers": render_state["layers"],
        "attachments": normalized_attachments,
    }

    return {
        "model_version": MODEL_VERSION,
        "source": PINNED_SOURCE,
        "shaders": normalized_shaders,
        "pipeline_family_identity": _identity("pipeline-family", pipeline_family_semantic),
        "pipeline_identity": _identity("pipeline", pipeline_semantic),
        "pipeline_key_surface_version": surface_document["schema_version"],
        "pipeline_key_surface_sha256": surface_digest,
        "render_identity": _identity("render", render_semantic),
        "pipeline_state": pipeline_state,
        "pipeline_key": canonical_pipeline_key,
        "render_state": {**render_state, "attachments": normalized_attachments},
    }


def derive_path(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        document = json.load(stream)
    return derive(document)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Derive safe deterministic BB graphics identities")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(json.dumps(derive_path(args.path), sort_keys=True, indent=2))
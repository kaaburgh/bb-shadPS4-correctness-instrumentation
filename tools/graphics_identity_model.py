from __future__ import annotations

import hashlib
import json
from pathlib import Path

MODEL_VERSION = "bb-graphics-identity/v1"
PINNED_SOURCE = {
    "repository": "https://github.com/shadps4-emu/shadPS4",
    "commit": "28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64",
}
LOGICAL_STAGES = {
    "vertex",
    "tessellation_control",
    "tessellation_eval",
    "geometry",
    "fragment",
    "compute",
}
ATTACHMENT_ROLES = {"color", "depth", "stencil"}


class GraphicsIdentityError(ValueError):
    pass


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _identity(kind: str, value) -> str:
    digest = hashlib.sha256(_canonical({"kind": kind, "value": value})).hexdigest()
    return f"{kind}:sha256:{digest}"


def _require_exact_keys(value: dict, required: set[str], optional: set[str] = set()) -> None:
    if not isinstance(value, dict):
        raise GraphicsIdentityError("expected object")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing:
        raise GraphicsIdentityError(f"missing keys: {sorted(missing)}")
    if extra:
        raise GraphicsIdentityError(f"unexpected keys: {sorted(extra)}")


def derive(document: dict) -> dict:
    _require_exact_keys(document, {"model_version", "source", "shaders", "pipeline_state", "render_state"})
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
    if not isinstance(pipeline_state, dict) or not pipeline_state:
        raise GraphicsIdentityError("pipeline_state must be a non-empty semantic projection")
    if any(key.startswith("_") for key in pipeline_state):
        raise GraphicsIdentityError("private/raw implementation fields are not allowed")
    pipeline_semantic = {
        "source": PINNED_SOURCE,
        "shader_identities": [item["shader_identity"] for item in normalized_shaders],
        "state": pipeline_state,
    }

    render_state = document["render_state"]
    _require_exact_keys(render_state, {"width", "height", "layers", "attachments"})
    for field in ("width", "height", "layers"):
        if not isinstance(render_state[field], int) or render_state[field] <= 0:
            raise GraphicsIdentityError(f"render_state.{field} must be a positive integer")
    attachments = render_state["attachments"]
    if not isinstance(attachments, list):
        raise GraphicsIdentityError("render_state.attachments must be a list")
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
        if not isinstance(attachment["format"], str) or not attachment["format"]:
            raise GraphicsIdentityError("attachment format must be a non-empty string")
        if not isinstance(attachment["samples"], int) or attachment["samples"] <= 0:
            raise GraphicsIdentityError("attachment samples must be positive")
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
        "pipeline_identity": _identity("pipeline", pipeline_semantic),
        "render_identity": _identity("render", render_semantic),
        "pipeline_state": pipeline_state,
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

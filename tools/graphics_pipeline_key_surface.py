from __future__ import annotations

import json
from pathlib import Path

SCHEMA_VERSION = "bb-graphics-pipeline-key-surface/v1"
PINNED_SOURCE = {
    "repository": "https://github.com/shadps4-emu/shadPS4",
    "commit": "28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64",
    "path": "src/video_core/renderer_vulkan/vk_graphics_pipeline.h",
}
PINNED_EQUALITY = {"operator": "memcmp", "extent": "sizeof(GraphicsPipelineKey)"}
EXPECTED_FIELDS = (
    "stage_hashes",
    "vertex_buffer_formats",
    "patch_control_points",
    "num_color_attachments",
    "color_buffers",
    "blend_controls",
    "write_masks",
    "cb_shader_mask",
    "logic_op",
    "num_samples",
    "depth_samples",
    "color_samples",
    "mrt_mask",
    "z_format",
    "stencil_format",
    "depth_clamp_enable",
    "prim_type",
    "polygon_mode",
    "clip_space",
    "provoking_vtx_last",
    "depth_clip_enable",
)
FAMILY_RELATIONS = {"direct", "derived", "omitted"}
CANONICALIZATION_STATES = {"missing", "complete"}


class PipelineKeySurfaceError(ValueError):
    pass


def validate(document: dict) -> dict:
    if not isinstance(document, dict) or set(document) != {"schema_version", "source", "equality", "fields"}:
        raise PipelineKeySurfaceError("document must contain exactly schema_version, source, equality, fields")
    if document["schema_version"] != SCHEMA_VERSION:
        raise PipelineKeySurfaceError("unsupported schema_version")
    if document["source"] != PINNED_SOURCE:
        raise PipelineKeySurfaceError("source must match the pinned BB-BL1 baseline and source path")
    if document["equality"] != PINNED_EQUALITY:
        raise PipelineKeySurfaceError("equality must match pinned GraphicsPipelineKey bytewise equality")

    fields = document["fields"]
    if not isinstance(fields, list):
        raise PipelineKeySurfaceError("fields must be a list")
    names = []
    relation_counts = {relation: 0 for relation in sorted(FAMILY_RELATIONS)}
    complete = 0
    for field in fields:
        if not isinstance(field, dict) or set(field) != {
            "name",
            "shape",
            "family_relation",
            "exact_canonicalization",
        }:
            raise PipelineKeySurfaceError("each field must use the exact v1 field schema")
        name = field["name"]
        shape = field["shape"]
        relation = field["family_relation"]
        canonicalization = field["exact_canonicalization"]
        if not isinstance(name, str) or not name:
            raise PipelineKeySurfaceError("field name must be non-empty text")
        if not isinstance(shape, str) or not shape or len(shape) > 128:
            raise PipelineKeySurfaceError(f"field {name} has invalid bounded shape")
        if relation not in FAMILY_RELATIONS:
            raise PipelineKeySurfaceError(f"field {name} has invalid family_relation")
        if canonicalization not in CANONICALIZATION_STATES:
            raise PipelineKeySurfaceError(f"field {name} has invalid exact_canonicalization")
        names.append(name)
        relation_counts[relation] += 1
        complete += canonicalization == "complete"

    if len(names) != len(set(names)):
        raise PipelineKeySurfaceError("duplicate GraphicsPipelineKey field")
    if tuple(names) != EXPECTED_FIELDS:
        missing = [name for name in EXPECTED_FIELDS if name not in names]
        extra = [name for name in names if name not in EXPECTED_FIELDS]
        raise PipelineKeySurfaceError(
            f"field inventory must match pinned declaration order; missing={missing}, extra={extra}"
        )

    total = len(EXPECTED_FIELDS)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": PINNED_SOURCE,
        "equality": PINNED_EQUALITY,
        "field_count": total,
        "family_relation_counts": relation_counts,
        "exact_canonicalized_fields": complete,
        "exact_missing_fields": total - complete,
        "pipeline_identity_ready": complete == total,
    }


def validate_path(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return validate(json.load(stream))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate pinned GraphicsPipelineKey identity surface")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_path(args.path), sort_keys=True, indent=2))

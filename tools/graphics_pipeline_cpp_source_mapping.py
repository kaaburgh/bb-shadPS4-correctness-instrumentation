#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.shadps4_source_baseline import COMMIT as _PINNED_COMMIT
from tools.shadps4_source_baseline import REPOSITORY as _PINNED_REPOSITORY

SCHEMA_VERSION = "bb-graphics-pipeline-cpp-source-mapping/v1"
SOURCE_REPOSITORY = _PINNED_REPOSITORY
SOURCE_COMMIT = _PINNED_COMMIT
SURFACE_VERSION = "bb-graphics-pipeline-key-surface/v12"
SURFACE_DIGEST_ENCODING = "utf-8-lf"

EXPECTED_FIELD_RULES = {
    "stage_hashes": ("array_unsigned_cast", "static_cast<std::uint64_t>(key.stage_hashes[i])"),
    "vertex_buffer_formats": ("array_enum_signed_cast", "static_cast<std::int32_t>(key.vertex_buffer_formats[i])"),
    "patch_control_points": ("unsigned_cast", "static_cast<std::uint32_t>(key.patch_control_points)"),
    "num_color_attachments": ("unsigned_cast", "static_cast<std::uint32_t>(key.num_color_attachments)"),
    "color_buffers": ("record_array", "key.color_buffers[i]"),
    "blend_controls": ("record_array", "key.blend_controls[i]"),
    "write_masks": ("array_raw_bits", "static_cast<std::uint32_t>(key.write_masks[i])"),
    "cb_shader_mask": ("raw_member", "static_cast<std::uint32_t>(key.cb_shader_mask.raw)"),
    "logic_op": ("enum_unsigned_cast", "static_cast<std::uint32_t>(key.logic_op)"),
    "num_samples": ("unsigned_cast", "static_cast<std::uint32_t>(key.num_samples)"),
    "depth_samples": ("unsigned_cast", "static_cast<std::uint32_t>(key.depth_samples)"),
    "color_samples": ("array_unsigned_cast", "static_cast<std::uint32_t>(key.color_samples[i])"),
    "mrt_mask": ("unsigned_cast", "static_cast<std::uint32_t>(key.mrt_mask)"),
    "z_format": ("bitfield_enum_cast", "static_cast<std::uint32_t>(key.z_format)"),
    "stencil_format": ("bitfield_enum_cast", "static_cast<std::uint32_t>(key.stencil_format)"),
    "depth_clamp_enable": ("bitfield_unsigned_cast", "static_cast<std::uint32_t>(key.depth_clamp_enable)"),
    "prim_type": ("bitfield_enum_cast", "static_cast<std::uint32_t>(key.prim_type)"),
    "polygon_mode": ("bitfield_enum_cast", "static_cast<std::uint32_t>(key.polygon_mode)"),
    "clip_space": ("bitfield_enum_cast", "static_cast<std::uint32_t>(key.clip_space)"),
    "provoking_vtx_last": ("bitfield_enum_cast", "static_cast<std::uint32_t>(key.provoking_vtx_last)"),
    "depth_clip_enable": ("bitfield_unsigned_cast", "static_cast<std::uint32_t>(key.depth_clip_enable)"),
}

EXPECTED_RECORD_EXPRESSIONS = {
    "color_buffers": {
        "data_format": "static_cast<std::uint32_t>(src.data_format)",
        "num_format": "static_cast<std::uint32_t>(src.num_format)",
        "num_conversion": "static_cast<std::uint32_t>(src.num_conversion)",
        "export_format": "static_cast<std::uint32_t>(src.export_format)",
        "swizzle": "{static_cast<std::uint32_t>(src.swizzle.r),static_cast<std::uint32_t>(src.swizzle.g),static_cast<std::uint32_t>(src.swizzle.b),static_cast<std::uint32_t>(src.swizzle.a)}",
    },
    "blend_controls": {
        "color_src_factor": "static_cast<std::uint32_t>(src.color_src_factor)",
        "color_func": "static_cast<std::uint32_t>(src.color_func)",
        "color_dst_factor": "static_cast<std::uint32_t>(src.color_dst_factor)",
        "alpha_src_factor": "static_cast<std::uint32_t>(src.alpha_src_factor)",
        "alpha_func": "static_cast<std::uint32_t>(src.alpha_func)",
        "alpha_dst_factor": "static_cast<std::uint32_t>(src.alpha_dst_factor)",
        "separate_alpha_blend": "static_cast<std::uint32_t>(src.separate_alpha_blend)",
        "enable": "static_cast<std::uint32_t>(src.enable)",
        "disable_rop3": "static_cast<std::uint32_t>(src.disable_rop3)",
    },
}


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def _names(items: list[dict], label: str) -> list[str]:
    names = [item.get("name") for item in items]
    if any(not isinstance(name, str) or not name for name in names):
        raise ValueError(f"{label}: every entry requires a non-empty name")
    if len(names) != len(set(names)):
        raise ValueError(f"{label}: duplicate names")
    return names


def _canonical_text_bytes(data: bytes) -> bytes:
    text = data.decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _validate_exact_mapping_rule(field: dict) -> None:
    name = field["name"]
    expected_mode, expected_expression = EXPECTED_FIELD_RULES[name]
    if field.get("mode") != expected_mode:
        raise ValueError(f"{name}: mapping mode mismatch")
    if field.get("expression") != expected_expression:
        raise ValueError(f"{name}: mapping expression mismatch")

    allowed_keys = {"name", "mode", "expression", "source_declaration"}
    expected_records = EXPECTED_RECORD_EXPRESSIONS.get(name)
    if expected_records is not None:
        allowed_keys.add("record_fields")
    extra_keys = set(field) - allowed_keys
    if extra_keys:
        raise ValueError(f"{name}: unexpected mapping keys: {sorted(extra_keys)}")

    if expected_records is None:
        return
    record_fields = field.get("record_fields")
    if not isinstance(record_fields, list):
        raise ValueError(f"{name}: record mapping missing")
    for record_field in record_fields:
        record_name = record_field["name"]
        if set(record_field) != {"name", "expression"}:
            raise ValueError(f"{name}.{record_name}: unexpected record mapping keys")
        if record_field.get("expression") != expected_records.get(record_name):
            raise ValueError(f"{name}.{record_name}: record mapping expression mismatch")


def validate_mapping(mapping: dict, surface: dict, graphics_header: str, runtime_header: str, color_header: str, surface_bytes: bytes) -> dict:
    if mapping.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported mapping schema_version")
    source = mapping.get("source")
    if source != {
        "repository": SOURCE_REPOSITORY,
        "commit": SOURCE_COMMIT,
        "graphics_key_path": "src/video_core/renderer_vulkan/vk_graphics_pipeline.h",
        "ps_color_buffer_path": "src/shader_recompiler/runtime_info.h",
        "blend_control_path": "src/video_core/amdgpu/regs_color.h",
    }:
        raise ValueError("mapping source provenance mismatch")

    canonical_surface = mapping.get("canonical_surface", {})
    if canonical_surface.get("schema_version") != SURFACE_VERSION:
        raise ValueError("canonical surface version mismatch")
    if canonical_surface.get("digest_encoding") != SURFACE_DIGEST_ENCODING:
        raise ValueError("canonical surface digest encoding mismatch")
    actual_surface_digest = "sha256:" + hashlib.sha256(_canonical_text_bytes(surface_bytes)).hexdigest()
    if canonical_surface.get("sha256") != actual_surface_digest:
        raise ValueError(
            f"canonical surface digest mismatch: expected {canonical_surface.get('sha256')}, "
            f"actual {actual_surface_digest}"
        )
    if surface.get("schema_version") != SURFACE_VERSION:
        raise ValueError("loaded canonical surface version mismatch")
    if surface.get("source", {}).get("commit") != SOURCE_COMMIT:
        raise ValueError("canonical surface source commit mismatch")

    mappings = mapping.get("fields")
    surface_fields = surface.get("fields")
    if not isinstance(mappings, list) or not isinstance(surface_fields, list):
        raise ValueError("fields must be arrays")
    mapping_names = _names(mappings, "mapping fields")
    surface_names = _names(surface_fields, "surface fields")
    if set(mapping_names) != set(surface_names) or len(mapping_names) != 21:
        raise ValueError("mapping must cover the exact 21-field canonical surface")
    if set(mapping_names) != set(EXPECTED_FIELD_RULES):
        raise ValueError("mapping fields do not match the pinned exact source rules")

    surface_by_name = {entry["name"]: entry for entry in surface_fields}
    for field in mappings:
        name = field["name"]
        _validate_exact_mapping_rule(field)
        declaration = field.get("source_declaration")
        if not isinstance(declaration, str) or declaration not in graphics_header:
            raise ValueError(f"{name}: pinned GraphicsPipelineKey declaration not found")
        if surface_by_name[name].get("exact_canonicalization") != "complete":
            raise ValueError(f"{name}: canonical surface is not complete")
        canonical = surface_by_name[name].get("canonicalization", {})
        record_fields = field.get("record_fields")
        if canonical.get("kind") == "record_array":
            if not isinstance(record_fields, list):
                raise ValueError(f"{name}: record mapping missing")
            expected = [entry["name"] for entry in canonical.get("fields", [])]
            actual = _names(record_fields, f"{name} record fields")
            if actual != expected:
                raise ValueError(f"{name}: record field order/name mismatch")
        elif record_fields is not None:
            raise ValueError(f"{name}: unexpected record_fields")

    required_runtime_tokens = [
        "struct PsColorBuffer {",
        "AmdGpu::DataFormat data_format : 6;",
        "AmdGpu::NumberFormat num_format : 4;",
        "AmdGpu::NumberConversion num_conversion : 3;",
        "AmdGpu::ShaderExportFormat export_format : 4;",
        "AmdGpu::CompMapping swizzle;",
    ]
    for token in required_runtime_tokens:
        if token not in runtime_header:
            raise ValueError(f"pinned PsColorBuffer source token missing: {token}")

    required_blend_tokens = [
        "struct BlendControl {",
        "BlendFactor color_src_factor : 5;",
        "BlendFunc color_func : 3;",
        "BlendFactor color_dst_factor : 5;",
        "u32 : 3;",
        "BlendFactor alpha_src_factor : 5;",
        "BlendFunc alpha_func : 3;",
        "BlendFactor alpha_dst_factor : 5;",
        "u32 separate_alpha_blend : 1;",
        "u32 enable : 1;",
        "u32 disable_rop3 : 1;",
    ]
    for token in required_blend_tokens:
        if token not in color_header:
            raise ValueError(f"pinned BlendControl source token missing: {token}")

    return {
        "schema_version": SCHEMA_VERSION,
        "source_commit": SOURCE_COMMIT,
        "canonical_surface": SURFACE_VERSION,
        "field_count": len(mapping_names),
        "field_names": sorted(mapping_names),
        "source_mapping_ready": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mapping", type=Path)
    parser.add_argument("--surface", type=Path, default=Path("docs/instrumentation/graphics-pipeline-key-surface.json"))
    parser.add_argument("--graphics-key-header", type=Path, required=True)
    parser.add_argument("--runtime-info-header", type=Path, required=True)
    parser.add_argument("--regs-color-header", type=Path, required=True)
    args = parser.parse_args()

    surface_bytes = args.surface.read_bytes()
    result = validate_mapping(
        _load(args.mapping),
        json.loads(surface_bytes.decode("utf-8")),
        args.graphics_key_header.read_text(encoding="utf-8"),
        args.runtime_info_header.read_text(encoding="utf-8"),
        args.regs_color_header.read_text(encoding="utf-8"),
        surface_bytes,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

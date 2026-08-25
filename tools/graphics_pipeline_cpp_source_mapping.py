#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCHEMA_VERSION = "bb-graphics-pipeline-cpp-source-mapping/v1"
SOURCE_REPOSITORY = "https://github.com/shadps4-emu/shadPS4"
SOURCE_COMMIT = "28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64"
SURFACE_VERSION = "bb-graphics-pipeline-key-surface/v12"


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
    actual_surface_digest = "sha256:" + hashlib.sha256(surface_bytes).hexdigest()
    if canonical_surface.get("sha256") != actual_surface_digest:
        raise ValueError("canonical surface digest mismatch")
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

    surface_by_name = {entry["name"]: entry for entry in surface_fields}
    for field in mappings:
        name = field["name"]
        if not isinstance(field.get("expression"), str) or not field["expression"]:
            raise ValueError(f"{name}: mapping expression missing")
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

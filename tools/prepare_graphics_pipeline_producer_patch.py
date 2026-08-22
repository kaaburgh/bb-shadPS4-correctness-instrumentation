#!/usr/bin/env python3
"""Prepare a deterministic source patch for the pinned GetGraphicsPipeline diagnostic seam."""

from __future__ import annotations

import argparse
import difflib
from pathlib import Path

PINNED_SOURCE_COMMIT = "28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64"
PINNED_SOURCE_PATH = "src/video_core/renderer_vulkan/vk_pipeline_cache.cpp"

_NEEDLE = """    const auto [it, is_new] = graphics_pipelines.try_emplace(graphics_key);\n    if (is_new) {\n"""

_INSERT = """    const auto [it, is_new] = graphics_pipelines.try_emplace(graphics_key);\n\n    // BB diagnostic integration seam. Off by default: only an instrumentation build that\n    // explicitly defines the hook can consume the exact key plus post-lookup result.\n#ifdef SHADPS4_BB_GRAPHICS_PIPELINE_OBSERVE\n    SHADPS4_BB_GRAPHICS_PIPELINE_OBSERVE(graphics_key, is_new);\n#endif\n\n    if (is_new) {\n"""


class PatchPreparationError(ValueError):
    pass


def prepare_source(source: str, source_commit: str) -> str:
    if source_commit != PINNED_SOURCE_COMMIT:
        raise PatchPreparationError(
            f"unsupported source commit: expected {PINNED_SOURCE_COMMIT}, got {source_commit}"
        )
    count = source.count(_NEEDLE)
    if count != 1:
        raise PatchPreparationError(
            f"expected exactly one pinned GetGraphicsPipeline seam, found {count}"
        )
    if "SHADPS4_BB_GRAPHICS_PIPELINE_OBSERVE" in source:
        raise PatchPreparationError("diagnostic seam already present")
    return source.replace(_NEEDLE, _INSERT, 1)


def make_patch(source: str, patched: str) -> str:
    before = source.splitlines(keepends=True)
    after = patched.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            before,
            after,
            fromfile=f"a/{PINNED_SOURCE_PATH}",
            tofile=f"b/{PINNED_SOURCE_PATH}",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.read_text(encoding="utf-8")
    patched = prepare_source(source, args.source_commit)
    patch = make_patch(source, patched)
    if not patch:
        raise PatchPreparationError("prepared patch is unexpectedly empty")
    args.output.write_text(patch, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

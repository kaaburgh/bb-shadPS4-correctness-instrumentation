#!/usr/bin/env python3
"""Prepare a deterministic source patch for the pinned GetGraphicsPipeline diagnostic seam."""

from __future__ import annotations

import argparse
import difflib
import hashlib
from pathlib import Path

PINNED_SOURCE_COMMIT = "28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64"
PINNED_SOURCE_PATH = "src/video_core/renderer_vulkan/vk_pipeline_cache.cpp"
PINNED_SOURCE_BLOB_SHA = "b39f1c30bfb00d1f21a082da48369ba95ce31368"

_NEEDLE = """    const auto [it, is_new] = graphics_pipelines.try_emplace(graphics_key);\n    if (is_new) {\n"""

_INSERT = """    const auto [it, is_new] = graphics_pipelines.try_emplace(graphics_key);\n\n    // BB diagnostic integration seam. Off by default: only an instrumentation build that\n    // explicitly defines the hook can consume the exact key plus post-lookup result.\n#ifdef SHADPS4_BB_GRAPHICS_PIPELINE_OBSERVE\n    SHADPS4_BB_GRAPHICS_PIPELINE_OBSERVE(graphics_key, is_new);\n#endif\n\n    if (is_new) {\n"""


class PatchPreparationError(ValueError):
    pass


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def verify_source_identity(
    data: bytes,
    source_commit: str,
    expected_blob_sha: str = PINNED_SOURCE_BLOB_SHA,
) -> None:
    if source_commit != PINNED_SOURCE_COMMIT:
        raise PatchPreparationError(
            f"unsupported source commit: expected {PINNED_SOURCE_COMMIT}, got {source_commit}"
        )
    actual_blob_sha = git_blob_sha(data)
    if actual_blob_sha != expected_blob_sha:
        raise PatchPreparationError(
            f"source blob mismatch: expected {expected_blob_sha}, got {actual_blob_sha}"
        )


def prepare_source(source: str) -> str:
    if "SHADPS4_BB_GRAPHICS_PIPELINE_OBSERVE" in source:
        raise PatchPreparationError("diagnostic seam already present")
    count = source.count(_NEEDLE)
    if count != 1:
        raise PatchPreparationError(
            f"expected exactly one pinned GetGraphicsPipeline seam, found {count}"
        )
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

    data = args.source.read_bytes()
    verify_source_identity(data, args.source_commit)
    source = data.decode("utf-8")
    patched = prepare_source(source)
    patch = make_patch(source, patched)
    if not patch:
        raise PatchPreparationError("prepared patch is unexpectedly empty")
    args.output.write_text(patch, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

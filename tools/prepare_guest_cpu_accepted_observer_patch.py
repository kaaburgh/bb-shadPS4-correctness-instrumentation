#!/usr/bin/env python3
"""Prepare a bounded BB-INS2 patch at accepted GPU-mapped guest-CPU access seams."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

SOURCE_COMMIT = "28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64"
SOURCE_GIT_BLOB = "e2b9ec75f88b632998e3cd15ddd6ca0a9cfd396c"
HOOK = "SHADPS4_BB_GUEST_CPU_ACCEPTED_OBSERVE"

WRITE_ANCHOR = """bool Rasterizer::InvalidateMemory(VAddr addr, u64 size) {\n    if (!IsMapped(addr, size)) {\n        // Not GPU mapped memory, can skip invalidation logic entirely.\n        return false;\n    }\n    buffer_cache.InvalidateMemory(addr, size);\n"""
WRITE_REPLACEMENT = """bool Rasterizer::InvalidateMemory(VAddr addr, u64 size) {\n    if (!IsMapped(addr, size)) {\n        // Not GPU mapped memory, can skip invalidation logic entirely.\n        return false;\n    }\n#ifdef SHADPS4_BB_GUEST_CPU_ACCEPTED_OBSERVE\n    SHADPS4_BB_GUEST_CPU_ACCEPTED_OBSERVE(addr, size, true);\n#endif\n    buffer_cache.InvalidateMemory(addr, size);\n"""

READ_ANCHOR = """bool Rasterizer::ReadMemory(VAddr addr, u64 size) {\n    if (!IsMapped(addr, size)) {\n        // Not GPU mapped memory, can skip invalidation logic entirely.\n        return false;\n    }\n    buffer_cache.ReadMemory(addr, size);\n"""
READ_REPLACEMENT = """bool Rasterizer::ReadMemory(VAddr addr, u64 size) {\n    if (!IsMapped(addr, size)) {\n        // Not GPU mapped memory, can skip invalidation logic entirely.\n        return false;\n    }\n#ifdef SHADPS4_BB_GUEST_CPU_ACCEPTED_OBSERVE\n    SHADPS4_BB_GUEST_CPU_ACCEPTED_OBSERVE(addr, size, false);\n#endif\n    buffer_cache.ReadMemory(addr, size);\n"""


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def prepare(source: bytes, source_commit: str) -> str:
    if source_commit != SOURCE_COMMIT:
        raise ValueError("source commit does not match pinned BB-BL1 commit")
    if git_blob_sha(source) != SOURCE_GIT_BLOB:
        raise ValueError("source Git blob does not match pinned vk_rasterizer.cpp")
    text = source.decode("utf-8")
    if HOOK in text:
        raise ValueError("observer hook already present")
    for anchor, replacement, label in (
        (WRITE_ANCHOR, WRITE_REPLACEMENT, "write"),
        (READ_ANCHOR, READ_REPLACEMENT, "read"),
    ):
        count = text.count(anchor)
        if count != 1:
            raise ValueError(f"expected exactly one {label} acceptance seam, found {count}")
        text = text.replace(anchor, replacement, 1)
    return text


def unified_patch(original: str, updated: str, path: str) -> str:
    import difflib
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.read_bytes()
    updated = prepare(source, args.source_commit)
    original = source.decode("utf-8")
    patch = unified_patch(original, updated, "src/video_core/renderer_vulkan/vk_rasterizer.cpp")
    if patch.count("@@") != 4:  # two hunks, each has opening/closing @@ tokens
        raise ValueError("expected exactly two patch hunks")
    args.output.write_text(patch, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

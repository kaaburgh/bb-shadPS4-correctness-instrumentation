#!/usr/bin/env python3
"""Prepare a bounded BB-INS2 patch at BufferCache live-range lifecycle seams."""

from __future__ import annotations

import argparse
import difflib
import hashlib
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.shadps4_source_baseline import COMMIT as _PINNED_COMMIT

SOURCE_COMMIT = _PINNED_COMMIT
SOURCE_GIT_BLOB = "68b85116029b6f05c45e9cc32be3ccf7de335bae"
SOURCE_PATH = "src/video_core/buffer_cache/buffer_cache.cpp"
HOOK = "SHADPS4_BB_BUFFER_LIVE_RANGE_OBSERVE"

REGISTER_ANCHOR = """        buffer_ranges.Add(buffer.CpuAddr(), buffer.SizeBytes(), buffer_id);\n"""
REGISTER_REPLACEMENT = """        buffer_ranges.Add(buffer.CpuAddr(), buffer.SizeBytes(), buffer_id);\n#ifdef SHADPS4_BB_BUFFER_LIVE_RANGE_OBSERVE\n        SHADPS4_BB_BUFFER_LIVE_RANGE_OBSERVE(buffer_id, buffer.CpuAddr(), buffer.SizeBytes(), true);\n#endif\n"""

UNREGISTER_ANCHOR = """        buffer_ranges.Subtract(buffer.CpuAddr(), buffer.SizeBytes());\n"""
UNREGISTER_REPLACEMENT = """        buffer_ranges.Subtract(buffer.CpuAddr(), buffer.SizeBytes());\n#ifdef SHADPS4_BB_BUFFER_LIVE_RANGE_OBSERVE\n        SHADPS4_BB_BUFFER_LIVE_RANGE_OBSERVE(buffer_id, buffer.CpuAddr(), buffer.SizeBytes(), false);\n#endif\n"""


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def prepare(source: bytes, source_commit: str) -> str:
    if source_commit != SOURCE_COMMIT:
        raise ValueError("source commit does not match pinned BB-BL1 commit")
    if git_blob_sha(source) != SOURCE_GIT_BLOB:
        raise ValueError("source Git blob does not match pinned buffer_cache.cpp")

    text = source.decode("utf-8")
    if HOOK in text:
        raise ValueError("buffer live-range observer hook already present")

    for anchor, replacement, label in (
        (REGISTER_ANCHOR, REGISTER_REPLACEMENT, "register"),
        (UNREGISTER_ANCHOR, UNREGISTER_REPLACEMENT, "unregister"),
    ):
        count = text.count(anchor)
        if count != 1:
            raise ValueError(f"expected exactly one {label} live-range seam, found {count}")
        text = text.replace(anchor, replacement, 1)
    return text


def unified_patch(original: str, updated: str) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{SOURCE_PATH}",
            tofile=f"b/{SOURCE_PATH}",
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
    patch = unified_patch(source.decode("utf-8"), updated)
    # Register/unregister statements are close enough that difflib deliberately
    # emits one bounded hunk containing both lifecycle transitions.
    if patch.count("@@") != 2:
        raise ValueError("expected exactly one patch hunk")
    args.output.write_text(patch, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

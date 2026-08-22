#!/usr/bin/env python3
"""Prepare a deterministic source patch for the pinned guest-CPU access-violation seam."""

from __future__ import annotations

import argparse
import difflib
import hashlib
from pathlib import Path

PINNED_SOURCE_COMMIT = "28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64"
PINNED_SOURCE_PATH = "src/video_core/page_manager.cpp"
PINNED_SOURCE_BLOB_SHA = "6a4bcbd7dfd2031f93f069968304dd835443a342"

_HOOK_MARKER = "SHADPS4_BB_GUEST_CPU_OBSERVE"
_NEEDLE = """    static bool GuestFaultSignalHandler(void* context, void* fault_address) {
        const auto addr = reinterpret_cast<VAddr>(fault_address);
        if (Common::IsWriteError(context)) {
"""

_INSERT = """    static bool GuestFaultSignalHandler(void* context, void* fault_address) {
        const auto addr = reinterpret_cast<VAddr>(fault_address);

        // BB diagnostic integration seam. Off by default: only an instrumentation build
        // that explicitly defines the hook observes access-violation faults here.
#ifdef SHADPS4_BB_GUEST_CPU_OBSERVE
        SHADPS4_BB_GUEST_CPU_OBSERVE(addr, Common::IsWriteError(context));
#endif

        if (Common::IsWriteError(context)) {
"""


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
    if _HOOK_MARKER in source:
        raise PatchPreparationError("diagnostic seam already present")
    count = source.count(_NEEDLE)
    if count != 1:
        raise PatchPreparationError(
            f"expected exactly one pinned GuestFaultSignalHandler seam, found {count}"
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
    source = data.decode("utf-8")
    if _HOOK_MARKER in source:
        raise PatchPreparationError("diagnostic seam already present")
    verify_source_identity(data, args.source_commit)
    patched = prepare_source(source)
    patch = make_patch(source, patched)
    if not patch:
        raise PatchPreparationError("prepared patch is unexpectedly empty")
    args.output.write_text(patch, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

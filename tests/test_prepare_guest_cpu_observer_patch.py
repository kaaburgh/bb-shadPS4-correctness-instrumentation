from __future__ import annotations

import unittest

from tools import prepare_guest_cpu_observer_patch as patcher


PINNED_SNIPPET = """    static bool GuestFaultSignalHandler(void* context, void* fault_address) {
        const auto addr = reinterpret_cast<VAddr>(fault_address);
        if (Common::IsWriteError(context)) {
            return rasterizer->InvalidateMemory(addr, 8);
        } else {
            return rasterizer->ReadMemory(addr, 8);
        }
        return false;
    }
"""


class GuestCpuObserverPatchTests(unittest.TestCase):
    def test_prepares_guarded_access_violation_hook(self) -> None:
        patched = patcher.prepare_source(PINNED_SNIPPET)

        self.assertIn("#ifdef SHADPS4_BB_GUEST_CPU_OBSERVE", patched)
        self.assertIn(
            "SHADPS4_BB_GUEST_CPU_OBSERVE(addr, Common::IsWriteError(context));",
            patched,
        )
        self.assertIn("if (Common::IsWriteError(context)) {", patched)

    def test_rejects_repeated_application(self) -> None:
        patched = patcher.prepare_source(PINNED_SNIPPET)
        with self.assertRaisesRegex(patcher.PatchPreparationError, "already present"):
            patcher.prepare_source(patched)

    def test_rejects_missing_or_ambiguous_seam(self) -> None:
        with self.assertRaisesRegex(patcher.PatchPreparationError, "found 0"):
            patcher.prepare_source("no handler here\n")

        with self.assertRaisesRegex(patcher.PatchPreparationError, "found 2"):
            patcher.prepare_source(PINNED_SNIPPET + PINNED_SNIPPET)

    def test_rejects_wrong_source_commit(self) -> None:
        data = PINNED_SNIPPET.encode("utf-8")
        expected_blob = patcher.git_blob_sha(data)
        with self.assertRaisesRegex(patcher.PatchPreparationError, "unsupported source commit"):
            patcher.verify_source_identity(data, "0" * 40, expected_blob)

    def test_rejects_wrong_source_blob(self) -> None:
        data = PINNED_SNIPPET.encode("utf-8")
        with self.assertRaisesRegex(patcher.PatchPreparationError, "source blob mismatch"):
            patcher.verify_source_identity(
                data,
                patcher.PINNED_SOURCE_COMMIT,
                "0" * 40,
            )

    def test_accepts_exact_blob_when_identity_matches(self) -> None:
        data = PINNED_SNIPPET.encode("utf-8")
        expected_blob = patcher.git_blob_sha(data)
        patcher.verify_source_identity(data, patcher.PINNED_SOURCE_COMMIT, expected_blob)

    def test_patch_is_single_file_and_contains_one_hunk(self) -> None:
        patched = patcher.prepare_source(PINNED_SNIPPET)
        diff = patcher.make_patch(PINNED_SNIPPET, patched)

        self.assertIn(f"--- a/{patcher.PINNED_SOURCE_PATH}", diff)
        self.assertIn(f"+++ b/{patcher.PINNED_SOURCE_PATH}", diff)
        self.assertEqual(diff.count("@@"), 2)
        self.assertEqual(diff.count("SHADPS4_BB_GUEST_CPU_OBSERVE(addr"), 1)


if __name__ == "__main__":
    unittest.main()

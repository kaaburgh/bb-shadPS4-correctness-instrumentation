import unittest

from tools.prepare_guest_cpu_accepted_observer_patch import (
    HOOK,
    READ_ANCHOR,
    SOURCE_COMMIT,
    WRITE_ANCHOR,
    prepare,
)


class GuestCpuAcceptedObserverPatchTests(unittest.TestCase):
    def _source(self) -> bytes:
        # Unit tests exercise seam/cardinality semantics without pretending this fixture
        # is the pinned upstream blob; the exact blob path is exercised in CI.
        return (WRITE_ANCHOR + "    texture_cache.InvalidateMemory(addr, size);\n    return true;\n}\n\n" + READ_ANCHOR + "    return true;\n}\n").encode()

    def _prepare_unpinned_fixture(self, source: bytes) -> str:
        # Preserve the production transformation semantics while bypassing only the
        # exact-upstream blob assertion in this isolated synthetic fixture.
        import tools.prepare_guest_cpu_accepted_observer_patch as mod
        original = mod.SOURCE_GIT_BLOB
        try:
            mod.SOURCE_GIT_BLOB = mod.git_blob_sha(source)
            return prepare(source, SOURCE_COMMIT)
        finally:
            mod.SOURCE_GIT_BLOB = original

    def test_inserts_write_and_read_hooks_after_gpu_mapping_acceptance(self):
        updated = self._prepare_unpinned_fixture(self._source())
        self.assertIn(f"{HOOK}(addr, size, true);", updated)
        self.assertIn(f"{HOOK}(addr, size, false);", updated)
        self.assertEqual(updated.count("#ifdef SHADPS4_BB_GUEST_CPU_ACCEPTED_OBSERVE"), 2)

    def test_wrong_commit_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "source commit"):
            self._prepare_unpinned_fixture.__wrapped__  # type: ignore[attr-defined]

    def test_missing_write_seam_fails_closed(self):
        source = self._source().replace(WRITE_ANCHOR.encode(), b"")
        with self.assertRaisesRegex(ValueError, "write acceptance seam"):
            self._prepare_unpinned_fixture(source)

    def test_ambiguous_read_seam_fails_closed(self):
        source = self._source() + READ_ANCHOR.encode()
        with self.assertRaisesRegex(ValueError, "read acceptance seam"):
            self._prepare_unpinned_fixture(source)

    def test_repeated_application_fails_closed(self):
        first = self._prepare_unpinned_fixture(self._source()).encode()
        import tools.prepare_guest_cpu_accepted_observer_patch as mod
        original = mod.SOURCE_GIT_BLOB
        try:
            mod.SOURCE_GIT_BLOB = mod.git_blob_sha(first)
            with self.assertRaisesRegex(ValueError, "already present"):
                prepare(first, SOURCE_COMMIT)
        finally:
            mod.SOURCE_GIT_BLOB = original


if __name__ == "__main__":
    unittest.main()

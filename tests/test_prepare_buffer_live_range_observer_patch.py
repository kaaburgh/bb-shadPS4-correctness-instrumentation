import unittest

from tools.prepare_buffer_live_range_observer_patch import (
    HOOK,
    REGISTER_ANCHOR,
    SOURCE_COMMIT,
    UNREGISTER_ANCHOR,
    prepare,
)


class BufferLiveRangeObserverPatchTests(unittest.TestCase):
    def _source(self) -> bytes:
        return (
            "void BufferCache::Register(BufferId buffer_id) {\n"
            + REGISTER_ANCHOR
            + "}\n\nvoid BufferCache::Unregister(BufferId buffer_id) {\n"
            + UNREGISTER_ANCHOR
            + "}\n"
        ).encode()

    def _prepare_unpinned_fixture(self, source: bytes, commit: str = SOURCE_COMMIT) -> str:
        import tools.prepare_buffer_live_range_observer_patch as mod

        original = mod.SOURCE_GIT_BLOB
        try:
            mod.SOURCE_GIT_BLOB = mod.git_blob_sha(source)
            return prepare(source, commit)
        finally:
            mod.SOURCE_GIT_BLOB = original

    def test_inserts_live_and_dead_hooks_after_range_state_change(self):
        updated = self._prepare_unpinned_fixture(self._source())
        self.assertIn(
            f"{HOOK}(buffer_id, buffer.CpuAddr(), buffer.SizeBytes(), true);", updated
        )
        self.assertIn(
            f"{HOOK}(buffer_id, buffer.CpuAddr(), buffer.SizeBytes(), false);", updated
        )
        self.assertEqual(updated.count("#ifdef SHADPS4_BB_BUFFER_LIVE_RANGE_OBSERVE"), 2)
        self.assertLess(updated.index(REGISTER_ANCHOR), updated.index(f"{HOOK}(buffer_id"))

    def test_wrong_commit_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "source commit"):
            self._prepare_unpinned_fixture(self._source(), "0" * 40)

    def test_missing_register_seam_fails_closed(self):
        source = self._source().replace(REGISTER_ANCHOR.encode(), b"")
        with self.assertRaisesRegex(ValueError, "register live-range seam"):
            self._prepare_unpinned_fixture(source)

    def test_ambiguous_unregister_seam_fails_closed(self):
        source = self._source() + UNREGISTER_ANCHOR.encode()
        with self.assertRaisesRegex(ValueError, "unregister live-range seam"):
            self._prepare_unpinned_fixture(source)

    def test_repeated_application_fails_closed(self):
        first = self._prepare_unpinned_fixture(self._source()).encode()
        import tools.prepare_buffer_live_range_observer_patch as mod

        original = mod.SOURCE_GIT_BLOB
        try:
            mod.SOURCE_GIT_BLOB = mod.git_blob_sha(first)
            with self.assertRaisesRegex(ValueError, "already present"):
                prepare(first, SOURCE_COMMIT)
        finally:
            mod.SOURCE_GIT_BLOB = original


if __name__ == "__main__":
    unittest.main()

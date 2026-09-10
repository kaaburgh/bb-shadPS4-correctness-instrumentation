"""Disposable-copy guard controls using only synthetic local files."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from tools import prepare_env1_target_copy as copy_tool


class TargetCopyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "original"
        self.source.mkdir()
        (self.source / "eboot.bin").write_bytes(b"synthetic")
        self.destination = self.root / "disposable"
        self.expected = copy_tool.identity(self.source)

    def prepare(self):
        return copy_tool.prepare(self.source, self.destination, self.expected)

    def test_receipt_after_verified_copy_allows_reuse_without_hashing(self):
        self.prepare()
        (self.destination / "app/eboot.bin").write_bytes(b"working drift")
        with mock.patch.object(copy_tool, "identity", side_effect=AssertionError("expensive hash")):
            copy_tool.require_copy_receipt(self.destination)
        self.assertEqual((self.source / "eboot.bin").read_bytes(), b"synthetic")
        self.assertFalse((self.source / copy_tool.RECEIPT_NAME).exists())

    def test_original_and_copied_receipt_rejected(self):
        self.prepare()
        with self.assertRaises(OSError):
            copy_tool.require_copy_receipt(self.source)
        shutil.copyfile(self.destination / copy_tool.RECEIPT_NAME, self.source / copy_tool.RECEIPT_NAME)
        with self.assertRaises(ValueError):
            copy_tool.require_copy_receipt(self.source)

    def test_replaced_app_and_malformed_receipts_rejected(self):
        self.prepare()
        (self.destination / "app").rename(self.destination / "previous-app")
        shutil.copytree(self.source, self.destination / "app")
        with self.assertRaises(ValueError):
            copy_tool.require_copy_receipt(self.destination)
        path = self.destination / copy_tool.RECEIPT_NAME
        for value in ([], {}, {"copy_verified": False}):
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                copy_tool.require_copy_receipt(self.destination)

    def test_failed_verification_leaves_no_receipt(self):
        with mock.patch.object(copy_tool, "identity", side_effect=[self.expected, {}]):
            with self.assertRaises(ValueError):
                self.prepare()
        self.assertFalse((self.destination / copy_tool.RECEIPT_NAME).exists())

    def test_migrate_existing_copy_without_recopying(self):
        shutil.copytree(self.source, self.destination / "app")
        with mock.patch.object(copy_tool.shutil, "copytree", side_effect=AssertionError("recopy")):
            copy_tool.prepare(self.source, self.destination, self.expected, verify_existing=True)
        copy_tool.require_copy_receipt(self.destination)

    def test_migration_rejects_hardlinks_to_original(self):
        import os
        (self.destination / "app").mkdir(parents=True)
        os.link(self.source / "eboot.bin", self.destination / "app/eboot.bin")
        with self.assertRaisesRegex(ValueError, "hardlinks"):
            copy_tool.prepare(self.source, self.destination, self.expected, verify_existing=True)
        self.assertFalse((self.destination / copy_tool.RECEIPT_NAME).exists())

    def test_link_receipt_rejected(self):
        self.prepare()
        path = self.destination / copy_tool.RECEIPT_NAME
        saved = self.root / "receipt"
        path.rename(saved)
        try:
            path.symlink_to(saved)
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaises(ValueError):
            copy_tool.require_copy_receipt(self.destination)

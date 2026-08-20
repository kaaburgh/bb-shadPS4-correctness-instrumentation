import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import run_target_experiment as runner


class ExecutableStagingRegressionTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX executable staging regression")
    def test_staged_binary_fails_closed_when_filesystem_is_not_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source-binary"
            source.write_bytes(b"stand-in executable bytes")
            os.chmod(source, 0o700)
            destination = root / "staged-binary"
            source_info = source.stat()

            with mock.patch.object(runner.os, "access", return_value=False) as access:
                with self.assertRaisesRegex(
                    runner.TargetRunError,
                    "working_directory filesystem may be mounted noexec",
                ):
                    runner._stage_emulator_binary(source, destination, source_info)

            access.assert_called_once_with(destination, os.X_OK)
            self.assertTrue(destination.is_file())
            self.assertTrue(stat.S_IMODE(destination.stat().st_mode) & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools" / "graphics_pipeline_cpp_identity_conformance.cpp"
VECTOR = ROOT / "docs" / "instrumentation" / "examples" / "graphics-pipeline-cpp-identity-vector.synthetic.json"


class GraphicsPipelineCppIdentityConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.binary = Path(cls._tmp.name) / "graphics-pipeline-cpp-identity-conformance"
        subprocess.run(
            [
                "c++",
                "-std=c++20",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pedantic",
                str(SOURCE),
                "-o",
                str(cls.binary),
            ],
            cwd=ROOT,
            check=True,
        )
        completed = subprocess.run(
            [str(cls.binary)],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        cls.lines = completed.stdout.splitlines()
        cls.vector = json.loads(VECTOR.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_emits_exact_frozen_canonical_payload_bytes(self) -> None:
        self.assertEqual(len(self.lines), 2)
        self.assertEqual(self.lines[0], self.vector["canonical_pipeline_payload_utf8"])

    def test_computes_expected_pipeline_identity_in_cpp(self) -> None:
        self.assertEqual(self.lines[1], self.vector["expected_pipeline_identity"])


if __name__ == "__main__":
    unittest.main()

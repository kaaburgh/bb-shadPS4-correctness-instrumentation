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
        cls.source_text = SOURCE.read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_emits_exact_frozen_canonical_payload_bytes(self) -> None:
        self.assertEqual(len(self.lines), 2)
        self.assertEqual(self.lines[0], self.vector["canonical_pipeline_payload_utf8"])

    def test_computes_expected_pipeline_identity_in_cpp(self) -> None:
        self.assertEqual(self.lines[1], self.vector["expected_pipeline_identity"])

    def test_canonical_key_values_are_typed_not_pre_serialized_fragments(self) -> None:
        self.assertIn("struct CanonicalPipelineKey", self.source_text)
        self.assertIn("std::array<std::uint64_t, 6> stage_hashes", self.source_text)
        self.assertIn("std::array<ColorBuffer, 8> color_buffers", self.source_text)
        self.assertIn("append_number_array(out, key.stage_hashes)", self.source_text)
        self.assertNotIn('\\"stage_hashes\\":[1229782938247303441', self.source_text)
        self.assertNotIn('\\"color_samples\\":[1,0,0,0,0,0,0,0]', self.source_text)
        self.assertNotIn('\\"write_masks\\":[15,0,0,0,0,0,0,0]', self.source_text)


if __name__ == "__main__":
    unittest.main()

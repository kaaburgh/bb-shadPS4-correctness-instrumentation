import copy
import json
import unittest
from pathlib import Path

from tools import graphics_pipeline_cpp_identity_vector as vector

VECTOR = Path("docs/instrumentation/examples/graphics-pipeline-cpp-identity-vector.synthetic.json")


class GraphicsPipelineCppIdentityVectorTest(unittest.TestCase):
    def load(self):
        return json.loads(VECTOR.read_text(encoding="utf-8"))

    def test_committed_vector_matches_model(self):
        summary = vector.validate(self.load())
        self.assertEqual(summary["schema_version"], vector.VECTOR_VERSION)
        self.assertTrue(summary["pipeline_identity"].startswith("pipeline:sha256:"))
        self.assertGreater(summary["payload_bytes"], 1000)

    def test_rejects_stale_expected_identity(self):
        document = self.load()
        document["expected_pipeline_identity"] = "pipeline:sha256:" + "0" * 64
        with self.assertRaisesRegex(vector.PipelineIdentityVectorError, "expected_pipeline_identity"):
            vector.validate(document)

    def test_rejects_payload_drift(self):
        document = self.load()
        document["canonical_pipeline_payload_utf8"] += " "
        with self.assertRaisesRegex(vector.PipelineIdentityVectorError, "canonical_pipeline_payload_utf8"):
            vector.validate(document)

    def test_rejects_surface_provenance_drift(self):
        document = self.load()
        document["key_surface_sha256"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(vector.PipelineIdentityVectorError, "key_surface_sha256"):
            vector.validate(document)

    def test_rejects_unknown_fields(self):
        document = self.load()
        document["note"] = "not part of the contract"
        with self.assertRaisesRegex(vector.PipelineIdentityVectorError, "unexpected keys"):
            vector.validate(document)


if __name__ == "__main__":
    unittest.main()

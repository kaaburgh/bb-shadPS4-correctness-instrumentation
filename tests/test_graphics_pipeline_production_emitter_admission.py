import copy
import json
import unittest
from pathlib import Path

from tools.graphics_pipeline_production_emitter_admission import validate


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/instrumentation/graphics-pipeline-production-emitter-admission.json"


class ProductionEmitterAdmissionTests(unittest.TestCase):
    def load(self):
        return json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_committed_contract_is_ready(self):
        self.assertTrue(validate(self.load(), ROOT))

    def test_rejects_wrong_runtime_key_input(self):
        doc = self.load()
        doc["integration"]["key_input"] = "pipeline_hash"
        with self.assertRaisesRegex(ValueError, "runtime key input drift"):
            validate(doc, ROOT)

    def test_rejects_std_hash_as_admitted_identity(self):
        doc = self.load()
        doc["integration"]["forbidden_identity_sources"] = ["object_bytes", "memcmp_bytes"]
        with self.assertRaisesRegex(ValueError, "forbidden identity-source policy drift"):
            validate(doc, ROOT)

    def test_rejects_created_cache_hit_inversion(self):
        doc = self.load()
        doc["integration"]["classification"] = {
            "created_when": "is_new == false",
            "cache_hit_when": "is_new == true",
        }
        with self.assertRaisesRegex(ValueError, "created/cache_hit classification drift"):
            validate(doc, ROOT)

    def test_rejects_runtime_claim_promotion(self):
        doc = self.load()
        doc["evidence_boundary"]["runtime_emission_established"] = True
        with self.assertRaisesRegex(ValueError, "unsupported runtime claim"):
            validate(doc, ROOT)

    def test_rejects_hidden_bundle_path(self):
        doc = self.load()
        doc["integration"]["required_bundle_paths"].append("src/hidden_fallback.cpp")
        with self.assertRaisesRegex(ValueError, "patch bundle path drift"):
            validate(doc, ROOT)


if __name__ == "__main__":
    unittest.main()

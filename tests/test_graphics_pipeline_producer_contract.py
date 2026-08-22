from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools import graphics_pipeline_producer_contract as contract

FIXTURE = Path("docs/instrumentation/examples/graphics-pipeline-producer.synthetic.json")


class GraphicsPipelineProducerContractTest(unittest.TestCase):
    def fixture(self) -> dict:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_synthetic_fixture_validates(self):
        summary = contract.validate(self.fixture())
        self.assertEqual(summary["observation_count"], 3)
        self.assertEqual(summary["created"], 2)
        self.assertEqual(summary["cache_hits"], 1)
        self.assertEqual(summary["distinct_pipeline_identities"], 2)

    def test_rejects_wrong_source_commit(self):
        document = self.fixture()
        document["source"]["commit"] = "0" * 40
        with self.assertRaisesRegex(contract.PipelineProducerContractError, "pinned BB-BL1"):
            contract.validate(document)

    def test_rejects_wrong_observation_seam(self):
        document = self.fixture()
        document["seam"]["observation_point"] = "pre_lookup"
        with self.assertRaisesRegex(contract.PipelineProducerContractError, "GetGraphicsPipeline"):
            contract.validate(document)

    def test_rejects_stale_identity_contract(self):
        document = self.fixture()
        document["identity_contract"]["model_version"] = "bb-graphics-identity/v1"
        with self.assertRaisesRegex(contract.PipelineProducerContractError, "stale or incompatible"):
            contract.validate(document)

    def test_rejects_capture_local_pipeline_id(self):
        document = self.fixture()
        document["observations"][0]["pipeline_identity"] = "pipe:00000001"
        with self.assertRaisesRegex(contract.PipelineProducerContractError, "invalid format"):
            contract.validate(document)

    def test_rejects_duplicate_sequence_numbers(self):
        document = self.fixture()
        document["observations"][1]["seq"] = document["observations"][0]["seq"]
        with self.assertRaisesRegex(contract.PipelineProducerContractError, "must be unique"):
            contract.validate(document)

    def test_rejects_unknown_result(self):
        document = self.fixture()
        document["observations"][0]["result"] = "unknown"
        with self.assertRaisesRegex(contract.PipelineProducerContractError, "created or cache_hit"):
            contract.validate(document)

    def test_rejects_unbounded_observation_extension(self):
        document = self.fixture()
        document["observations"][0]["extra"] = "payload"
        with self.assertRaisesRegex(contract.PipelineProducerContractError, "unexpected keys"):
            contract.validate(document)


if __name__ == "__main__":
    unittest.main()

import copy
import unittest
from pathlib import Path

from tools import resource_sync_trace, trace_event_model


ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "docs" / "instrumentation" / "examples" / "resource-sync.synthetic.json"


def _observer(*, write_state: str):
    capability = {"state": write_state}
    if write_state != "unknown":
        capability["evidence_sha256"] = "5" * 64
    if write_state == "negative_validated":
        capability["coverage_oracle_sha256"] = "6" * 64
    return {
        "schema_version": trace_event_model.OBSERVER_SCHEMA_VERSION,
        "fault_mechanism": "access_violation",
        "build_path": "non_userfaultfd",
        "capabilities": {
            "read": {"state": "observable", "evidence_sha256": "5" * 64},
            "write": capability,
        },
    }


class ResourceSyncTraceTests(unittest.TestCase):
    def setUp(self):
        self.document = trace_event_model.load_strict(EXAMPLE)

    def _runtime_document(self, *, write_state: str):
        document = copy.deepcopy(self.document)
        material = document["provenance"]["material"]
        material["evidence_class"] = "runtime"
        material["producer"]["producer_id"] = "shadps4-bb-instrumentation"
        material["producer"]["producer_sha256"] = "7" * 64
        material["observer"] = _observer(write_state=write_state)
        document["provenance"]["baseline_id"] = trace_event_model.baseline_id_for(material)
        return document

    def test_reconstructs_closed_lifetime_and_accesses(self):
        result = resource_sync_trace.reconstruct(self.document)
        resource = result["resources"][0]
        self.assertEqual(resource["resource_id"], "res:00000001")
        self.assertEqual(resource["lifetime_state"], "closed")
        self.assertEqual(
            [event["kind"] for event in resource["accesses"]],
            ["guest_cpu", "host_gpu", "guest_cpu"],
        )
        self.assertEqual(resource["guest_cpu_coverage_states"], ["observed", "ambiguous"])

    def test_reconstruction_preserves_correlation_ids(self):
        result = resource_sync_trace.reconstruct(self.document)
        resource = result["resources"][0]
        self.assertEqual(
            resource["sync"][0]["correlation"],
            {
                "resource_id": "res:00000001",
                "queue_id": "queue:00000000",
            },
        )

    def test_expected_baseline_mismatch_is_rejected(self):
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "expected baseline"):
            resource_sync_trace.reconstruct(
                self.document, expected_baseline_id="0" * 64
            )

    def test_invalid_category_kind_pair_is_rejected_before_reconstruction(self):
        document = copy.deepcopy(self.document)
        document["events"][1]["kind"] = "barrier"
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "invalid for category"):
            resource_sync_trace.reconstruct(document)

    def test_missing_guest_cpu_events_remain_unknown(self):
        document = copy.deepcopy(self.document)
        document["events"] = [
            event for event in document["events"] if event["kind"] != "guest_cpu"
        ]
        for seq, event in enumerate(document["events"]):
            event["seq"] = seq
        document["summary"]["recorded_events"] = len(document["events"])
        result = resource_sync_trace.reconstruct(document)
        self.assertEqual(result["resources"][0]["guest_cpu_coverage_states"], ["unknown"])

    def test_runtime_negative_coverage_rejects_observable_only_capability(self):
        document = self._runtime_document(write_state="observable")
        document["events"][1]["coverage"] = "unobserved"
        with self.assertRaisesRegex(
            trace_event_model.TraceContractError, "negative_validated write"
        ):
            resource_sync_trace.reconstruct(document)

    def test_runtime_negative_coverage_accepts_independent_oracle_binding(self):
        document = self._runtime_document(write_state="negative_validated")
        document["events"][1]["coverage"] = "unobserved"
        result = resource_sync_trace.reconstruct(document)
        self.assertIn(
            "unobserved", result["resources"][0]["guest_cpu_coverage_states"]
        )

    def test_access_before_create_is_rejected(self):
        document = copy.deepcopy(self.document)
        document["events"][0], document["events"][1] = document["events"][1], document["events"][0]
        for seq, event in enumerate(document["events"]):
            event["seq"] = seq
            event["timestamp_ns"] = 100 + seq * 10
        with self.assertRaisesRegex(resource_sync_trace.ResourceTraceError, "outside active lifetime"):
            resource_sync_trace.reconstruct(document)

    def test_access_after_destroy_is_rejected(self):
        document = copy.deepcopy(self.document)
        destroy = document["events"].pop()
        document["events"].insert(2, destroy)
        for seq, event in enumerate(document["events"]):
            event["seq"] = seq
            event["timestamp_ns"] = 100 + seq * 10
        with self.assertRaisesRegex(resource_sync_trace.ResourceTraceError, "outside active lifetime"):
            resource_sync_trace.reconstruct(document)


if __name__ == "__main__":
    unittest.main()

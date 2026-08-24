import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from tools.buffer_guest_cpu_diagnostic import DiagnosticError, produce


ROOT = Path(__file__).resolve().parents[1]
TRACE_SCHEMA_PATH = ROOT / "schemas" / "trace-event.schema.json"


def base_document():
    return {
        "schema_version": "bb-buffer-guest-cpu-diagnostic/v1",
        "document_kind": "input",
        "complete_lifecycle": True,
        "first_resource_ordinal": 1,
        "lifecycle_events": [
            {"seq": 1, "buffer_id": 7, "guest_address": 1000, "size_bytes": 100, "live": True},
            {"seq": 2, "buffer_id": 8, "guest_address": 1050, "size_bytes": 100, "live": True},
            {"seq": 6, "buffer_id": 7, "guest_address": 1000, "size_bytes": 100, "live": False},
            {"seq": 7, "buffer_id": 8, "guest_address": 1050, "size_bytes": 100, "live": False},
        ],
        "accepted_accesses": [
            {"seq": 3, "timestamp_ns": 30, "guest_address": 1005, "size_bytes": 10, "access": "read"},
            {"seq": 4, "timestamp_ns": 40, "guest_address": 1060, "size_bytes": 10, "access": "write"},
            {"seq": 5, "timestamp_ns": 50, "guest_address": 2000, "size_bytes": 10, "access": "read"},
        ],
    }


class BufferGuestCpuDiagnosticTests(unittest.TestCase):
    def test_unique_emits_trace_event_and_preserves_nonunique_diagnostics(self):
        result = produce(base_document())

        self.assertEqual(result["schema_version"], "bb-buffer-guest-cpu-diagnostic/v1")
        self.assertEqual(result["document_kind"], "output")
        self.assertEqual(result["next_resource_ordinal"], 3)
        self.assertEqual(result["summary"], {
            "accepted_accesses": 3,
            "emitted_events": 1,
            "unmapped": 1,
            "ambiguous": 1,
        })
        self.assertEqual(result["events"], [{
            "seq": 0,
            "timestamp_ns": 30,
            "category": "access",
            "kind": "guest_cpu",
            "correlation": {"resource_id": "res:00000001"},
            "access": "read",
            "coverage": "observed",
        }])
        self.assertEqual(result["event_sources"], [{"trace_seq": 0, "source_seq": 3}])
        self.assertEqual(result["diagnostics"][0]["status"], "ambiguous")
        self.assertEqual(
            result["diagnostics"][0]["candidate_resource_ids"],
            ["res:00000001", "res:00000002"],
        )
        self.assertEqual(result["diagnostics"][1]["status"], "unmapped")
        self.assertEqual(result["diagnostics"][1]["candidate_resource_ids"], [])

    def test_emitted_event_is_compatible_with_canonical_trace_event_schema(self):
        event = produce(base_document())["events"][0]
        trace = json.loads(TRACE_SCHEMA_PATH.read_text(encoding="utf-8"))
        event_schema = {
            "$schema": trace["$schema"],
            "$defs": trace["$defs"],
            "$ref": "#/$defs/event",
        }
        Draft202012Validator(event_schema).validate(event)

    def test_emitted_trace_seq_is_contiguous_and_source_mapping_is_preserved(self):
        document = base_document()
        document["lifecycle_events"] = [
            {"seq": 1, "buffer_id": 7, "guest_address": 1000, "size_bytes": 100, "live": True},
            {"seq": 5, "buffer_id": 7, "guest_address": 1000, "size_bytes": 100, "live": False},
        ]
        document["accepted_accesses"] = [
            {"seq": 2, "timestamp_ns": 20, "guest_address": 1000, "size_bytes": 1, "access": "read"},
            {"seq": 4, "timestamp_ns": 40, "guest_address": 1001, "size_bytes": 1, "access": "write"},
        ]
        result = produce(document)
        self.assertEqual([event["seq"] for event in result["events"]], [0, 1])
        self.assertEqual(result["event_sources"], [
            {"trace_seq": 0, "source_seq": 2},
            {"trace_seq": 1, "source_seq": 4},
        ])

    def test_reused_buffer_id_gets_fresh_resource_identity(self):
        document = base_document()
        document["lifecycle_events"] = [
            {"seq": 1, "buffer_id": 7, "guest_address": 1000, "size_bytes": 100, "live": True},
            {"seq": 3, "buffer_id": 7, "guest_address": 1000, "size_bytes": 100, "live": False},
            {"seq": 5, "buffer_id": 7, "guest_address": 1000, "size_bytes": 100, "live": True},
            {"seq": 7, "buffer_id": 7, "guest_address": 1000, "size_bytes": 100, "live": False},
        ]
        document["accepted_accesses"] = [
            {"seq": 2, "timestamp_ns": 20, "guest_address": 1000, "size_bytes": 1, "access": "write"},
            {"seq": 6, "timestamp_ns": 60, "guest_address": 1000, "size_bytes": 1, "access": "write"},
        ]

        result = produce(document)
        self.assertEqual(
            [event["correlation"]["resource_id"] for event in result["events"]],
            ["res:00000001", "res:00000002"],
        )

    def test_shared_sequence_collision_is_rejected(self):
        document = base_document()
        document["accepted_accesses"][0]["seq"] = 2
        with self.assertRaisesRegex(DiagnosticError, "shared sequence domain collision"):
            produce(document)

    def test_accepted_access_sequence_must_increase(self):
        document = base_document()
        document["accepted_accesses"][1]["seq"] = 2
        with self.assertRaisesRegex(DiagnosticError, "accepted-access seq must be strictly increasing"):
            produce(document)

    def test_accepted_access_timestamps_must_be_monotonic(self):
        document = base_document()
        document["accepted_accesses"][1]["timestamp_ns"] = 29
        with self.assertRaisesRegex(DiagnosticError, "accepted-access timestamps must be monotonic"):
            produce(document)

    def test_lifecycle_misuse_fails_closed(self):
        document = base_document()
        document["lifecycle_events"][1] = {
            "seq": 2,
            "buffer_id": 7,
            "guest_address": 1000,
            "size_bytes": 100,
            "live": True,
        }
        with self.assertRaisesRegex(DiagnosticError, "registered while already live"):
            produce(document)

    def test_access_range_overflow_fails_closed(self):
        document = base_document()
        document["accepted_accesses"][0]["guest_address"] = (1 << 64) - 2
        document["accepted_accesses"][0]["size_bytes"] = 4
        with self.assertRaisesRegex(DiagnosticError, "range exceeds unsigned 64-bit"):
            produce(document)

    def test_partial_overlap_is_unmapped_not_heuristically_owned(self):
        document = base_document()
        document["lifecycle_events"] = [
            {"seq": 1, "buffer_id": 7, "guest_address": 1000, "size_bytes": 100, "live": True},
            {"seq": 3, "buffer_id": 7, "guest_address": 1000, "size_bytes": 100, "live": False},
        ]
        document["accepted_accesses"] = [
            {"seq": 2, "timestamp_ns": 20, "guest_address": 1095, "size_bytes": 10, "access": "read"},
        ]
        result = produce(document)
        self.assertEqual(result["events"], [])
        self.assertEqual(result["event_sources"], [])
        self.assertEqual(result["diagnostics"][0]["status"], "unmapped")

    def test_unknown_input_fields_fail_schema_validation(self):
        document = deepcopy(base_document())
        document["unexpected"] = True
        with self.assertRaisesRegex(DiagnosticError, "schema validation failed"):
            produce(document)


if __name__ == "__main__":
    unittest.main()

import copy
import unittest
from pathlib import Path

from tools import trace_event_model


ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "docs" / "instrumentation" / "examples" / "trace-events.synthetic.json"


class TraceEventContractTests(unittest.TestCase):
    def setUp(self):
        self.document = trace_event_model.load_strict(EXAMPLE)

    def test_synthetic_fixture_validates(self):
        trace_event_model.validate_semantics(self.document)

    def test_duplicate_json_member_is_rejected(self):
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "duplicate JSON member"):
            trace_event_model.loads_strict('{"schema_version":"a","schema_version":"b"}')

    def test_event_count_is_bounded(self):
        document = copy.deepcopy(self.document)
        document["capture"]["limits"]["max_events"] = 4
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "exceeds max_events"):
            trace_event_model.validate_semantics(document)

    def test_sequence_gaps_are_rejected(self):
        document = copy.deepcopy(self.document)
        document["events"][2]["seq"] = 9
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "contiguous"):
            trace_event_model.validate_semantics(document)

    def test_timestamp_regression_is_rejected(self):
        document = copy.deepcopy(self.document)
        document["events"][3]["timestamp_ns"] = 1
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "monotonic"):
            trace_event_model.validate_semantics(document)

    def test_filter_is_enforced(self):
        document = copy.deepcopy(self.document)
        document["capture"]["filter"].remove("graphics")
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "not enabled"):
            trace_event_model.validate_semantics(document)

    def test_drop_accounting_is_explicit(self):
        document = copy.deepcopy(self.document)
        document["summary"]["dropped_events"] = 17
        trace_event_model.validate_semantics(document)
        self.assertEqual(document["summary"]["dropped_events"], 17)

    def test_buffer_high_water_cannot_exceed_bound(self):
        document = copy.deepcopy(self.document)
        document["summary"]["buffer_high_water_bytes"] = 70000
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "high-water"):
            trace_event_model.validate_semantics(document)

    def test_all_sampling_requires_every_event(self):
        document = copy.deepcopy(self.document)
        document["capture"]["sampling"]["every_n"] = 2
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "every_n=1"):
            trace_event_model.validate_semantics(document)


if __name__ == "__main__":
    unittest.main()

import copy
import unittest
from pathlib import Path

from tools import graphics_timing_trace, trace_event_model


ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "docs" / "instrumentation" / "examples" / "graphics-timing.synthetic.json"


class GraphicsTimingTraceTests(unittest.TestCase):
    def setUp(self):
        self.document = trace_event_model.load_strict(EXAMPLE)

    def test_synthetic_fixture_reconstructs_pipeline_and_timing(self):
        result = graphics_timing_trace.reconstruct(self.document)
        self.assertEqual(len(result["pipelines"]), 1)
        pipeline = result["pipelines"][0]
        self.assertEqual(pipeline["pipeline_id"], "pipe:00000007")
        self.assertEqual(pipeline["graphics_events"][0]["kind"], "draw")
        self.assertEqual(
            pipeline["graphics_events"][0]["correlation"]["resource_id"],
            "res:00000011",
        )
        self.assertEqual(pipeline["timing_ns"], {"cpu_span": 40, "gpu_span": 55})
        self.assertEqual(
            pipeline["timing_spans"][1]["correlation"]["queue_id"],
            "queue:00000000",
        )
        self.assertEqual(result["unscoped_timing"], [])

    def test_expected_baseline_mismatch_is_rejected(self):
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "expected baseline"):
            graphics_timing_trace.reconstruct(
                self.document, expected_baseline_id="0" * 64
            )

    def test_invalid_category_kind_pair_is_rejected_before_reconstruction(self):
        document = copy.deepcopy(self.document)
        document["events"][1]["kind"] = "cpu_span"
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "invalid for category"):
            graphics_timing_trace.reconstruct(document)

    def test_draw_without_pipeline_id_is_rejected(self):
        document = copy.deepcopy(self.document)
        del document["events"][1]["correlation"]["pipeline_id"]
        with self.assertRaisesRegex(graphics_timing_trace.GraphicsTimingError, "requires pipeline_id"):
            graphics_timing_trace.reconstruct(document)

    def test_timing_without_duration_is_rejected(self):
        document = copy.deepcopy(self.document)
        del document["events"][2]["duration_ns"]
        with self.assertRaisesRegex(trace_event_model.TraceContractError, "timing events require duration_ns"):
            graphics_timing_trace.reconstruct(document)

    def test_pipeline_timing_without_graphics_anchor_is_rejected(self):
        document = copy.deepcopy(self.document)
        document["events"][2]["correlation"]["span_id"] = "span:00000022"
        with self.assertRaisesRegex(graphics_timing_trace.GraphicsTimingError, "no graphics anchor"):
            graphics_timing_trace.reconstruct(document)

    def test_timing_pipeline_must_match_anchor(self):
        document = copy.deepcopy(self.document)
        document["events"][2]["correlation"]["pipeline_id"] = "pipe:00000008"
        with self.assertRaisesRegex(graphics_timing_trace.GraphicsTimingError, "disagrees"):
            graphics_timing_trace.reconstruct(document)

    def test_unscoped_timing_is_preserved_not_assigned(self):
        document = copy.deepcopy(self.document)
        del document["events"][2]["correlation"]["pipeline_id"]
        result = graphics_timing_trace.reconstruct(document)
        self.assertEqual(len(result["unscoped_timing"]), 1)
        self.assertEqual(result["unscoped_timing"][0]["kind"], "cpu_span")
        self.assertEqual(result["pipelines"][0]["timing_ns"]["cpu_span"], 0)


if __name__ == "__main__":
    unittest.main()

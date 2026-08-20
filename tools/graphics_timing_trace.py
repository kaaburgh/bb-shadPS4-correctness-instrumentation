from __future__ import annotations

import json
from pathlib import Path

try:
    from tools import trace_event_model
except ModuleNotFoundError:
    import trace_event_model


class GraphicsTimingError(ValueError):
    pass


def reconstruct(document, *, expected_baseline_id: str | None = None):
    trace_event_model.validate_schema(document)
    trace_event_model.validate_semantics(
        document, expected_baseline_id=expected_baseline_id
    )

    pipelines = {}
    span_anchors = {}
    unscoped_timing = []

    for event in document["events"]:
        category = event["category"]
        kind = event["kind"]
        correlation = dict(event["correlation"])
        pipeline_id = correlation.get("pipeline_id")
        span_id = correlation.get("span_id")

        if category == "graphics":
            if kind in {"draw", "dispatch"} and pipeline_id is None:
                raise GraphicsTimingError(f"{kind} event requires pipeline_id")
            if pipeline_id is None:
                continue

            pipeline = pipelines.setdefault(
                pipeline_id,
                {"pipeline_id": pipeline_id, "graphics_events": [], "timing_spans": []},
            )
            pipeline["graphics_events"].append(
                {
                    "seq": event["seq"],
                    "timestamp_ns": event["timestamp_ns"],
                    "kind": kind,
                    "correlation": correlation,
                }
            )
            if span_id is not None:
                previous = span_anchors.setdefault(span_id, pipeline_id)
                if previous != pipeline_id:
                    raise GraphicsTimingError("span_id is anchored to multiple pipelines")

        elif category == "timing":
            if kind not in {"cpu_span", "gpu_span"}:
                raise GraphicsTimingError(f"unsupported timing kind: {kind}")
            if "duration_ns" not in event:
                raise GraphicsTimingError("timing event requires duration_ns")
            if span_id is None:
                raise GraphicsTimingError("timing event requires span_id")

            record = {
                "seq": event["seq"],
                "timestamp_ns": event["timestamp_ns"],
                "kind": kind,
                "duration_ns": event["duration_ns"],
                "correlation": correlation,
            }

            if pipeline_id is None:
                unscoped_timing.append(record)
                continue

            anchored_pipeline = span_anchors.get(span_id)
            if anchored_pipeline is None:
                raise GraphicsTimingError("pipeline-scoped timing span has no graphics anchor")
            if anchored_pipeline != pipeline_id:
                raise GraphicsTimingError("timing span pipeline_id disagrees with graphics anchor")

            pipeline = pipelines.setdefault(
                pipeline_id,
                {"pipeline_id": pipeline_id, "graphics_events": [], "timing_spans": []},
            )
            pipeline["timing_spans"].append(record)

    result_pipelines = []
    for pipeline_id in sorted(pipelines):
        pipeline = pipelines[pipeline_id]
        pipeline["timing_ns"] = {
            "cpu_span": sum(
                record["duration_ns"]
                for record in pipeline["timing_spans"]
                if record["kind"] == "cpu_span"
            ),
            "gpu_span": sum(
                record["duration_ns"]
                for record in pipeline["timing_spans"]
                if record["kind"] == "gpu_span"
            ),
        }
        result_pipelines.append(pipeline)

    return {
        "baseline_id": document["provenance"]["baseline_id"],
        "pipelines": result_pipelines,
        "unscoped_timing": unscoped_timing,
    }


def reconstruct_path(path: Path, *, expected_baseline_id: str | None = None):
    return reconstruct(
        trace_event_model.load_strict(path),
        expected_baseline_id=expected_baseline_id,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Reconstruct bounded graphics/pipeline/timing correlation from a BB trace"
    )
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--expected-baseline-id",
        help="fail closed unless trace provenance matches this exact baseline id",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            reconstruct_path(
                args.path, expected_baseline_id=args.expected_baseline_id
            ),
            sort_keys=True,
            indent=2,
        )
    )

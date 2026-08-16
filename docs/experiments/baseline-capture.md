# BB-BL5 baseline metrics capture

Issue: #21

## Result of the first telemetry inventory

The pinned repository contract already gives BB-BL5 one trustworthy benchmark-adjacent measurement: the bounded target runner records `termination.elapsed_seconds` in `run-manifest.json`. The safe target-run v3 artifact does **not** export FPS, per-frame frametime, RAM residency, VRAM residency, or shader-compilation counters. This slice therefore does not infer those values from logs, compatibility metadata, filenames, or other indirect signals.

The distinction is deliberate: “not exposed by the current capture contract” is evidence about availability, not evidence that shadPS4 lacks an internal implementation detail or UI counter. A later slice may add a metric only after its producer, units, sampling semantics, overhead, and exact source/build provenance are established.

## One-command packer

After a bounded run has already been produced through the BB-ENV1 route:

```bash
python3 tools/collect_benchmark_metrics.py \
  --run-artifact /path/to/target-run.zip \
  --output /path/to/benchmark-metrics.json
```

The collector is stdlib-only. It does not launch shadPS4, attach to a process, read private target files, capture raw process output, or automate gameplay/input. It only reads the already-redacted `run-manifest.json` from the supplied target-run ZIP.

The output uses `schemas/benchmark-metrics.schema.json` and binds itself to the exact input ZIP with SHA-256 and byte size. `run_wall_time_seconds` is copied from `run-manifest.json#/termination/elapsed_seconds`. The requested FPS, frametime, RAM, VRAM, and shader-compilation metrics are emitted with `status: unavailable`, null value/source/unit, and reason `not-exposed-by-bb-target-run-v3`.

## Overhead semantics

`capture.collector_overhead_ms` measures only the post-run packer's wall-clock processing time. It is **not** target-runtime instrumentation overhead, because this slice deliberately performs no target observation. Consequently this number can quantify the cost of producing the derived metrics artifact but must not be subtracted from run timing or used as evidence about emulator overhead.

## Provenance and privacy boundary

The metrics artifact contains no operator path, username, hostname, target bytes, stdout/stderr, shaders, save data, or private content identifiers. Its durable input identity is the target-run ZIP digest/size plus the published target-run contract kind/version. Any future metric producer that needs target-process observation must preserve the repository's local-only/advisory-only boundary and must not create a second execution path around `tools/run_target_experiment.py`.

## Validation contract

The repository test suite covers strict JSON parsing, duplicate/non-finite rejection, exact input digest binding, explicit unavailable states, available wall-time provenance, and CLI artifact production:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The normal repository build checks remain applicable as declared by `docs/agent-playbook.md`.

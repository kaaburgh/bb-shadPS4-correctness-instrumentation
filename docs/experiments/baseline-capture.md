# BB-BL5 baseline capture — safe packer slice

## Scope

This slice establishes a one-command, payload-free packaging contract around the safe ZIP emitted by `tools/run_target_experiment.py`. It deliberately does **not** claim that the pinned shadPS4 baseline exposes machine-readable FPS, frametime, RAM, VRAM, or shader-compilation telemetry.

The existing gated target-run artifact already contains exact target/host/source/scenario provenance and execution elapsed time. Raw process output is excluded by that contract. Consequently this packer treats all five BB-BL5 metric families as unavailable unless an operator supplies a separate strict numeric sidecar produced by a measurement mechanism whose provenance can be documented independently.

## Command

```bash
python tools/baseline_capture.py \
  --target-run /safe/path/target-run.zip \
  --measurements /safe/path/measurements.json \
  --output /safe/path/baseline-capture.zip
```

`--measurements` is optional. Omitting it is valid and produces an explicit missing-data record rather than guessed values.

The sidecar may contain only these keys:

```json
{
  "fps": [30.0, 30.1],
  "frametime_ms": [33.3, 33.2],
  "ram_bytes": [123456789],
  "vram_bytes": [987654321],
  "shader_compilations": [12]
}
```

Every value is a non-empty array of finite non-negative numeric samples; byte/count metrics require integers. Unknown keys, duplicate JSON members, negative values, non-finite values, and oversized inputs fail closed.

## Safe artifact

The output ZIP contains only:

- `baseline-capture.json` — normalized metrics, missing-data states, copied provenance keys, and packer overhead;
- `run-manifest.json`;
- `target-manifest.json`;
- `host-environment.json`;
- `scenario.json`.

Extra entries in the input target-run ZIP are never propagated. Raw stdout/stderr, target paths, command files, executable bytes, saves, shaders, dumps, and other proprietary payload are not admitted by this packer.

## Telemetry inventory at this slice

| BB-BL5 signal | Current safe route | State in this slice |
| --- | --- | --- |
| source/target/host/scenario provenance | target-run safe ZIP | available |
| execution elapsed time | `run-manifest.json` | available |
| FPS | no attested machine-readable producer in current route | unavailable unless numeric sidecar supplied |
| frametime | no attested machine-readable producer in current route | unavailable unless numeric sidecar supplied |
| RAM | no attested machine-readable producer in current route | unavailable unless numeric sidecar supplied |
| VRAM | no attested machine-readable producer in current route | unavailable unless numeric sidecar supplied |
| shader compilation count/timing | no attested machine-readable producer in current route | unavailable unless numeric sidecar supplied |

“Unavailable” here is deliberately scoped to the **current safe capture route**, not a claim that no shadPS4 UI/log/internal signal exists. A later BB-BL5 slice may promote a family to directly collected only after identifying and attesting a stable producer at the exact pinned source baseline.

## Overhead semantics

`baseline-capture.json` records packer wall-clock and process-CPU seconds. This makes the cost of validation/normalization/ZIP packaging measurable.

It does **not** measure emulator/runtime instrumentation overhead. That field is therefore emitted as `unknown`. Numeric runtime measurements are not suitable for performance attribution until their producer and instrumentation overhead are separately established.

## Evidence boundary

The tests for this slice are synthetic contract tests. They verify strict metric normalization, explicit missing data, allowlisted ZIP propagation, provenance projection, and overhead fields. They do not execute Bloodborne or shadPS4 and establish no runtime/performance claim.

This is a bounded BB-BL5 vertical slice, not completion of BB-BL5: direct capture producers for the five requested metric families and runtime instrumentation-overhead measurement remain open.
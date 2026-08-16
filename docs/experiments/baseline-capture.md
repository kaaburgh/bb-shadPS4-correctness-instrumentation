# BB-BL5 baseline capture workflow

## Result

This CLOUD RESEARCH slice provides a one-command, privacy-bounded packer for comparable baseline provenance. It does **not** execute Bloodborne and does not convert synthetic/contract checks into runtime evidence.

The source identity is fixed to `shadps4-emu/shadPS4@28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64` from BB-BL1. The command validates a BB-BL2 target manifest, projects it through the same transfer-safe allowlist used by the gated target runner, collects the allowlisted BB-BL3 host environment, and writes one ZIP containing canonical `capture-manifest.json`, `target-manifest.json`, and `host-environment.json`.

## One command

From the repository root:

```text
python tools/capture_baseline.py \
  --target-manifest <bb-bl2-manifest.json> \
  --backend vulkan \
  --output <safe-output-directory>/baseline-capture.zip
```

`--emulator-config <path>` is optional and uses the BB-BL3 collector's hash-only contract: the path and file contents are not serialized.

## Telemetry inventory at the pinned baseline

This packer has no producer-bound target runtime input. Therefore it deliberately records `fps`, `frametime`, `ram`, `vram`, and `shader-compilation` as `unavailable` rather than deriving, scraping, or inventing values. The repository's current safe target-run contract also does not attest these metric producers. A future GATED target run must introduce a versioned, producer-bound telemetry contract before any of these fields can become runtime evidence.

This is a negative result about the **currently supported evidence path**, not a claim that shadPS4 internally has no counters, UI displays, logging, or profiler-related state. Internal signals are not accepted here until their producer/semantics can be bound to the exact source and run.

## Provenance and privacy boundary

The capture manifest always carries all three baseline identities required by repository policy:

- exact shadPS4 repository and commit;
- the SHA-256 of the validated operator BB-BL2 source manifest plus the SHA-256 of its embedded transfer-safe projection;
- a digest plus embedded safe BB-BL3 host-environment manifest.

The ZIP never copies the operator target manifest verbatim. `target-manifest.json` is the existing fail-closed transfer projection from the gated target-runner contract: unrestricted target strings are nulled, normalized, allowlisted, or rejected before packaging. A schema-valid but non-allowlisted configuration value is therefore a packaging error, not evidence that the value is safe to transfer.

The ZIP contains no emulator executable, target assets, opaque captures, command output, arbitrary environment variables, host/user names, paths, or emulator configuration contents. The operator target manifest is bounded to 4 MiB before parsing and validated before projection.

## Measurable overhead

`collection_overhead.packer_elapsed_ns` measures monotonic wall-clock time spent validating and safely projecting the target manifest, collecting the host manifest, and canonicalizing the records before packaging. It explicitly excludes target runtime because this CLOUD RESEARCH workflow does not run the target. This gives later target instrumentation a stable place to separate collection overhead from gameplay/runtime measurements.

## Validation boundary

The checked-in synthetic target manifest is suitable only for CI/contract validation. CI verifies the one-shot command, ZIP member allowlist, exact source SHA, explicit unavailable telemetry, transfer-safe target projection, rejection of unsafe schema-valid target strings, and the no-runtime-claim flag. Passing those checks establishes packer behavior, not Bloodborne or shadPS4 runtime performance/correctness.

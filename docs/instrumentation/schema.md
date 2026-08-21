# Trace event schema and overhead contract

BB-INS1 defines a contract for future diagnostic instrumentation. It does **not** instrument shadPS4 and does not establish Bloodborne runtime behavior.

## Event model

`schemas/trace-event.schema.json` defines `bb-trace-events/v1`. Every event has a contiguous sequence number, monotonic timestamp, category, kind, and bounded correlation identifiers. The five categories are `resource`, `access`, `sync`, `graphics`, and `timing`.

`kind` is a closed enum, not a producer-supplied label. The semantic contract binds every kind to exactly one category: `resource` → `create`/`destroy`; `access` → `guest_cpu`/`host_gpu`; `sync` → `barrier`/`fence`/`submit`; `graphics` → `draw`/`dispatch`/`present`; and `timing` → `cpu_span`/`gpu_span`. A cross-category pair is invalid even when both strings independently belong to their closed enums, so in-repository consumers fail closed before dispatch instead of reclassifying or silently dropping the event.

Kind-specific payload fields are bounded by the same semantic contract. Access events require both `access` and `coverage`, and those fields are invalid on non-access events. Timing events require `duration_ns`, which is invalid on non-timing events. `size_bytes` is required only for resource `create` and is invalid on other event kinds. Future widening of any category/kind or payload-field relationship requires an explicit contract revision rather than consumer-specific interpretation.

Correlation identifiers are typed generated ordinals with fixed forms such as `res:00000001`, `queue:00000000`, `pipe:00000007`, and `span:00000002`; free-form usernames, hostnames, paths, tokens, shader text, or other operator strings do not validate. Future identifier or event-kind semantics require an explicit schema revision instead of widening these fields into arbitrary text.

The stream is deliberately reconstructable rather than verbose: lifecycle/access/synchronization/graphics/timing consumers share stable IDs and timestamps. Missing observation coverage is represented explicitly with `observed`, `unobserved`, `unknown`, or `ambiguous`; absence of an event is not by itself a negative semantic claim.

For `guest_cpu` events, `bb-trace-events/v1` does not encode the observer/fault mechanism or independently established read/write capability coverage. Consequently a **runtime** `guest_cpu` event with `coverage=unobserved` is semantically inadmissible under v1 and the validator fails closed on it. Synthetic fixtures may still use `unobserved` to exercise consumer behavior, but runtime negative direct-access evidence requires a versioned observer-provenance boundary first. Runtime `unknown`/`ambiguous` remain the truthful representations when observer completeness is not established.

## Provenance and stale-evidence rejection

Every detached stream carries `provenance.material` for all material baseline inputs: the exact shadPS4 repository/commit and patch-set digest, Bloodborne target-manifest digest, host-manifest digest, scenario digest, emulator-config digest, producer identity/digest, and schema digest. `evidence_class` distinguishes `synthetic` from `runtime`.

`provenance.baseline_id` is SHA-256 of canonical JSON for `provenance.material` (`sort_keys=true`, separators `,`/`:`, ASCII encoding). The validator recomputes it and fails closed if any material identity changes without a corresponding baseline id. Consumers comparing or joining detached traces should additionally supply the expected baseline id and reject a mismatch rather than mixing stale or cross-baseline evidence.

The committed fixture uses synthetic placeholder manifest/config digests and therefore remains only contract evidence even though it references the pinned BB-BL1 shadPS4 commit. It is not a record of a Bloodborne run.

## Bounds and backpressure

A capture declares `max_events` and `max_buffer_bytes` before collection. Producers must buffer in memory and flush outside the per-event hot path; per-draw/per-event filesystem I/O is outside this contract. Once either bound would be exceeded, producers drop additional events and increment `summary.dropped_events` instead of growing memory without bound. `buffer_high_water_bytes` must remain within the declared limit.

Filtering is category-based and explicit. Sampling is either `all` (`every_n = 1`) or deterministic `every_n`. Future producers may add implementation-specific filtering only by versioning the contract when it changes observable semantics.

## Overhead accounting

The trace summary records `instrumentation_cpu_ns` and `serialization_cpu_ns` separately. These values describe collector/serialization work only; they are not target frame time or GPU time. Target validation in BB-INS4 must compare tracing-off and tracing-on runs on the exact same source/target/host/scenario baseline and report distributions, dropped-event counts, buffer high-water marks, and any missing observer coverage. A synthetic fixture can validate accounting structure but cannot establish runtime overhead.

## Validation

The synthetic example is `docs/instrumentation/examples/trace-events.synthetic.json`. Validate it with:

```bash
python -m pip install --disable-pip-version-check jsonschema==4.25.1
python -m unittest tests.test_trace_event_model -v
python tools/trace_event_model.py docs/instrumentation/examples/trace-events.synthetic.json
```

To fail closed when consuming a trace for an already selected baseline, add `--expected-baseline-id <64-hex-id>`.

Validation checks schema shape plus semantic invariants that JSON Schema alone does not express: provenance digest binding, optional exact-baseline matching, category↔kind and kind-specific payload coupling, contiguous sequence numbers, monotonic timestamps, filter enforcement, configured event/buffer bounds, sampling consistency, exact recorded-event accounting, and rejection of runtime `guest_cpu coverage=unobserved` until observer provenance is versioned. Regression tests also reject representative private/token-like identifier values and verify that resource-sync and graphics-timing consumers reject invalid category/kind pairs before reconstruction.

## Evidence boundary

Evidence for BB-INS1 is `synthetic`/contract-only. No proprietary target bytes are inputs, no runtime is launched, and no claim is made that current shadPS4 source already exposes these events. BB-INS2/BB-INS3 must identify and implement actual source seams; BB-INS4 must independently establish target coverage and overhead.

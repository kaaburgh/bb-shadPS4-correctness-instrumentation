# Trace event schema and overhead contract

BB-INS1 defines a contract for future diagnostic instrumentation. It does **not** instrument shadPS4 and does not establish Bloodborne runtime behavior.

## Event model

`schemas/trace-event.schema.json` defines `bb-trace-events/v1`. Every event has a contiguous sequence number, monotonic timestamp, category, kind, and bounded correlation identifiers. The five categories are `resource`, `access`, `sync`, `graphics`, and `timing`.

`kind` is a closed enum, not a producer-supplied label. The semantic contract binds every kind to exactly one category: `resource` → `create`/`destroy`; `access` → `guest_cpu`/`host_gpu`; `sync` → `barrier`/`fence`/`submit`; `graphics` → `draw`/`dispatch`/`present`; and `timing` → `cpu_span`/`gpu_span`. A cross-category pair is invalid even when both strings independently belong to their closed enums, so in-repository consumers fail closed before dispatch instead of reclassifying or silently dropping the event.

Kind-specific payload fields are bounded by the same semantic contract. Access events require both `access` and `coverage`, and those fields are invalid on non-access events. Timing events require `duration_ns`, which is invalid on non-timing events. `size_bytes` is required only for resource `create` and is invalid on other event kinds. Future widening of any category/kind or payload-field relationship requires an explicit contract revision rather than consumer-specific interpretation.

Correlation identifiers are typed generated ordinals with fixed forms such as `res:00000001`, `queue:00000000`, `pipe:00000007`, and `span:00000002`; free-form usernames, hostnames, paths, tokens, shader text, or other operator strings do not validate. Future identifier or event-kind semantics require an explicit schema revision instead of widening these fields into arbitrary text.

The stream is deliberately reconstructable rather than verbose: lifecycle/access/synchronization/graphics/timing consumers share stable IDs and timestamps. Missing observation coverage is represented explicitly with `observed`, `unobserved`, `unknown`, or `ambiguous`; absence of an event is not by itself a negative semantic claim.

For runtime `guest_cpu` events, `provenance.material.observer` provides a separately versioned `bb-guest-cpu-observer/v1` compatibility boundary. It binds the active fault mechanism/build path and independent read/write capability records. `observed` or `ambiguous` requires the relevant direction to be `observable` or `negative_validated`; `unobserved` additionally requires `negative_validated` and a separately bound `coverage_oracle_sha256`. A non-unknown capability is also bound to its own `evidence_sha256`. Runtime `guest_cpu` events without compatible observer provenance fail closed.

Observer v1 recognizes the pinned static distinction between `access_violation`/`non_userfaultfd` and `userfaultfd_write_protect`/`enable_userfaultfd`. The userfaultfd mechanism cannot claim direct-read capability under v1; its read state must remain `unknown`. Synthetic fixtures may omit observer provenance and may still use `unobserved` to exercise contract/consumer behavior without promoting runtime evidence.

## Provenance and stale-evidence rejection

Every detached stream carries `provenance.material` for all material baseline inputs: the exact shadPS4 repository/commit and patch-set digest, Bloodborne target-manifest digest, host-manifest digest, scenario digest, emulator-config digest, producer identity/digest, and schema digest. `evidence_class` distinguishes `synthetic` from `runtime`. When runtime guest-CPU observations are present, the versioned observer record is part of the same material and therefore also contributes to baseline identity.

`provenance.baseline_id` is SHA-256 of canonical JSON for `provenance.material` (`sort_keys=true`, separators `,`/`:`, ASCII encoding). The validator recomputes it and fails closed if any material identity changes without a corresponding baseline id. Consumers comparing or joining detached traces should additionally supply the expected baseline id and reject a mismatch rather than mixing stale or cross-baseline evidence.

The committed fixtures use synthetic placeholder manifest/config digests and therefore remain only contract evidence even though they reference the pinned BB-BL1 shadPS4 commit. They are not records of a Bloodborne run.

The observer capability digests bind claims to evidence outside the event stream transformation. Presence of a digest does not by itself prove that the referenced artifact is an independent coverage oracle; that relationship must be established when a runtime producer/capture is admitted. This contract only ensures that a consumer cannot accept a negative runtime coverage claim without a separately identified oracle artifact.

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

Validation checks schema shape plus semantic invariants that JSON Schema alone does not express: provenance digest binding, optional exact-baseline matching, category↔kind and kind-specific payload coupling, contiguous sequence numbers, monotonic timestamps, filter enforcement, configured event/buffer bounds, sampling consistency, exact recorded-event accounting, observer mechanism/build-path compatibility, direction-specific capability evidence, and independent-oracle binding for runtime negative `guest_cpu` coverage. Regression tests also preserve the userfaultfd direct-read `unknown` boundary and verify that resource-sync fails closed on unsupported runtime negative coverage before reconstruction.

## Evidence boundary

Evidence for BB-INS1/BB-INS2 contract behavior remains `synthetic` plus the separately documented BB-INS2 static source seams. No proprietary target bytes are inputs, no runtime is launched, and no claim is made that current shadPS4 source already emits these events. BB-INS2 must still implement and independently exercise the actual producer; BB-INS4 must independently establish target coverage and overhead.

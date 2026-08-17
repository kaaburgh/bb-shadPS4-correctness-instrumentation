# Trace event schema and overhead contract

BB-INS1 defines a contract for future diagnostic instrumentation. It does **not** instrument shadPS4 and does not establish Bloodborne runtime behavior.

## Event model

`schemas/trace-event.schema.json` defines `bb-trace-events/v1`. Every event has a contiguous sequence number, monotonic timestamp, category, kind, and bounded correlation identifiers. The five categories are `resource`, `access`, `sync`, `graphics`, and `timing`. Optional correlation fields connect resource, queue, pipeline, and span identities without storing payload bytes, file paths, usernames, shader contents, or arbitrary operator strings.

The stream is deliberately reconstructable rather than verbose: lifecycle/access/synchronization/graphics/timing consumers share stable IDs and timestamps. Missing observation coverage is represented explicitly with `observed`, `unobserved`, `unknown`, or `ambiguous`; absence of an event is not by itself a negative semantic claim.

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

Validation checks schema shape plus semantic invariants that JSON Schema alone does not express: contiguous sequence numbers, monotonic timestamps, filter enforcement, configured event/buffer bounds, sampling consistency, and exact recorded-event accounting.

## Evidence boundary

Evidence for BB-INS1 is `synthetic`/contract-only. No proprietary target bytes are inputs, no runtime is launched, and no claim is made that current shadPS4 source already exposes these events. BB-INS2/BB-INS3 must identify and implement actual source seams; BB-INS4 must independently establish target coverage and overhead.

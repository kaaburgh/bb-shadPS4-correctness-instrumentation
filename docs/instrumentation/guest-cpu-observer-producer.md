# Guest-CPU observer producer boundary

This document records a bounded BB-INS2 CLOUD RESEARCH design slice at the exact BB-BL1 shadPS4 baseline `shadps4-emu/shadPS4@28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64`.

It specifies where a future diagnostic producer may observe direct guest-CPU accesses and what evidence must exist before those observations can support resource classification. It does **not** implement a shadPS4 producer, execute Bloodborne, establish observer completeness, or justify a negative `GPU-only` claim.

## Established source seams

The source-seam evidence in `docs/instrumentation/resources-sync.md` establishes two host/build paths:

- **non-userfaultfd access-violation path** — `PageManager::GuestFaultSignalHandler` distinguishes direct guest-CPU write and read faults. Writes dispatch to `Rasterizer::InvalidateMemory(addr, 8)`; reads dispatch to `Rasterizer::ReadMemory(addr, 8)`.
- **`ENABLE_USERFAULTFD` path** — registered GPU mappings use write-protect fault handling and dispatch observed write-protect faults to `Rasterizer::InvalidateMemory`. Static inspection does not establish an equivalent direct-read fault path.

The rasterizer methods reject ranges that are not GPU-mapped before forwarding to the buffer/texture cache paths. A producer must therefore count an access as an observed tracked-GPU-memory access only after the GPU-mapped predicate has accepted the range; emitting at the raw fault entry alone would over-report unrelated guest faults.

## Proposed diagnostic emission points

A future diagnostic implementation should keep fault detection and evidence emission separate:

1. The page-fault mechanism identifies access direction and fault address.
2. The rasterizer boundary establishes that the range is GPU-mapped.
3. Only then may the producer enqueue a bounded `category=access`, `kind=guest_cpu` observation.
4. Serialization and file output happen outside the fault/hot path through the BB-INS1 bounded in-memory buffering contract.

For the non-userfaultfd path, an accepted write maps to `access=write`, and an accepted read maps to `access=read`.

For the userfaultfd path, an accepted write-protect fault maps to `access=write`. This design does not map absence of a userfaultfd read event to `unobserved`; direct-read coverage for that mechanism remains `unknown` until a separate read observer or independent coverage evidence exists.

## Correlation requirement

A `guest_cpu` event is useful for BB-INS2 only when it can be correlated to the tracked resource lifetime whose guest-memory range contains the accepted fault address. The future producer therefore needs a deterministic, bounded address-range-to-capture-`resource_id` lookup at the observation boundary.

If the lookup produces zero or multiple live resource candidates, the producer must not choose by ordering, nearest address, or another heuristic. The observation remains uncorrelated/ambiguous evidence until the event contract provides a representation that preserves that state safely.

## Provenance requirement and current v1 gap

`bb-trace-events/v1` binds the whole stream to exact source, target-manifest, host-manifest, scenario, emulator-config, producer, and schema digests. That is necessary but not sufficient for the BB-INS2 negative-access claim.

The current event schema has no explicit observer/fault-mechanism field and its `guest_cpu` event shape does not require an observer identity. Consequently a consumer cannot determine from a v1 event alone whether it came from:

- the non-userfaultfd read/write access-violation observer;
- the userfaultfd write-protect observer; or
- a future different observer with different coverage semantics.

This is a compatibility boundary, not a reason to smuggle the mechanism into a free-form ID. Before a runtime producer is admitted as evidence for observer coverage, the trace contract must gain a versioned, bounded way to bind observer mechanism/capability semantics to the stream or event. The representation must distinguish at least the exact build/configuration path and whether direct read and direct write observation are independently covered.

Until that versioned provenance exists, a prototype may be used only as diagnostic development output; it must not be consumed as evidence that a missing direct access was observed absent.

## Coverage semantics

The future producer/consumer contract must preserve these distinctions:

- `observed` — an accepted observer path emitted the concrete access and resource correlation is established;
- `unknown` — the active build/fault mechanism has no independently established observer for that access direction, or observer provenance is missing/incompatible;
- `ambiguous` — an access was observed but exact live resource correlation is not unique;
- `unobserved` — admissible only after an independently exercised coverage oracle establishes that the exact observer path was active and capable of seeing the relevant access class, and the bounded capture actually observed none.

A successful process run, green synthetic CI, or absence of an event is not such an oracle.

## Independent coverage oracle

Every observer path used for a negative claim needs a control that can fail independently of the event reconstruction. Acceptable future directions include a bounded known-access control that deliberately triggers the exact read/write path or a structural seam-coverage probe that proves the installed observer was reached for the relevant tracked range.

The oracle result and its provenance must be separable from the event stream transformation it validates. Replaying producer-derived addresses back through the same mapping code is only internal consistency and cannot establish observer completeness.

## Hot-path and privacy constraints

The producer must remain diagnostic-only and disabled by default. Fault/hot-path work is bounded to direction detection, GPU-mapped acceptance, deterministic resource correlation, timestamp/counter work, and bounded in-memory enqueue/drop accounting. No per-event filesystem I/O, unbounded allocation/logging, proprietary payload capture, private path, username, or arbitrary operator string belongs in the event.

BB-INS4 remains responsible for target tracing-off/on overhead measurement and runtime coverage validation.

## Result of this slice

The direct page-fault seams are sufficient to specify where producer events belong, but `bb-trace-events/v1` is **not yet sufficient to represent the exact observer-mechanism provenance required for negative direct-access evidence**. The next implementation step is therefore to version the trace/producer provenance boundary first, including fail-closed read/write capability semantics, and then implement the bounded producer against that contract. This avoids producing runtime traces whose missing events are semantically indistinguishable across host/build fault mechanisms.

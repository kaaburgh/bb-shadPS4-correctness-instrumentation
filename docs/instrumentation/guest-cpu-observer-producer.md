# Guest-CPU observer producer boundary

This document records the BB-INS2 CLOUD RESEARCH observer-provenance boundary at the exact BB-BL1 shadPS4 baseline `shadps4-emu/shadPS4@28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64`.

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

For the userfaultfd path, an accepted write-protect fault maps to `access=write`. Absence of a userfaultfd read event remains `unknown`; direct-read coverage for that mechanism is not admitted by observer provenance v1.

## Correlation requirement

A `guest_cpu` event is useful for BB-INS2 only when it can be correlated to the tracked resource lifetime whose guest-memory range contains the accepted fault address. The future producer therefore needs a deterministic, bounded address-range-to-capture-`resource_id` lookup at the observation boundary.

If the lookup produces zero or multiple live resource candidates, the producer must not choose by ordering, nearest address, or another heuristic. The observation remains uncorrelated/ambiguous evidence until the event contract provides a representation that preserves that state safely.

## Versioned observer provenance

`bb-trace-events/v1` now permits an optional `provenance.material.observer` record with its own compatibility version, currently `bb-guest-cpu-observer/v1`. The field is optional for synthetic/non-observer traces, but every **runtime** `guest_cpu` event requires a compatible observer record.

The v1 observer record binds:

- `fault_mechanism`: `access_violation` or `userfaultfd_write_protect`;
- `build_path`: respectively `non_userfaultfd` or `enable_userfaultfd`;
- independent `read` and `write` capability records.

Mechanism and build path must match. Observer v1 additionally fails closed if `userfaultfd_write_protect` claims any direct-read capability other than `unknown`, preserving the pinned static result rather than generalizing the non-userfaultfd read seam across builds.

Each direction has one of three capability states:

- `unknown` — the run does not establish that this direction can be observed;
- `observable` — a separate evidence artifact, bound by `evidence_sha256`, establishes the observation seam strongly enough to admit concrete `observed`/`ambiguous` events, but not absence as negative evidence;
- `negative_validated` — the observation seam has `evidence_sha256` **and** a separate independent coverage-oracle artifact bound by `coverage_oracle_sha256`; only this state can admit runtime `coverage=unobserved` for that direction.

A non-`unknown` capability without `evidence_sha256` fails closed. A `negative_validated` capability without `coverage_oracle_sha256` fails closed. Conversely, attaching a coverage-oracle digest to `unknown` or merely `observable` capability is rejected rather than silently upgrading its semantics.

For `access=read_write`, both direction capabilities must satisfy the event's coverage requirement.

These digests bind the trace to evidence outside the event reconstruction. The contract does not prove that an arbitrary artifact is a valid independent oracle merely because its digest is present; review/producer admission must establish that relationship. This prevents the consumer from turning a self-asserted capability bit or absence of events into observer completeness.

## Runtime coverage semantics

The validator applies the observer record only to runtime `guest_cpu` events:

- `observed` / `ambiguous` require `observable` or `negative_validated` capability for every relevant access direction;
- `unknown` remains admissible with compatible versioned observer provenance because it makes no coverage claim;
- `unobserved` requires `negative_validated` capability and its separate coverage-oracle digest for every relevant access direction.

Synthetic fixtures may still use all coverage labels to test contract/consumer behavior without claiming target observation.

The public resource-sync consumer validates this contract before reconstruction, so an unsupported runtime negative claim fails before it can become `guest_cpu_coverage_states` evidence.

## Independent coverage oracle

Every observer path used for a negative claim needs a control that can fail independently of the event reconstruction. Acceptable future directions include a bounded known-access control that deliberately triggers the exact read/write path or a structural seam-coverage probe that proves the installed observer was reached for the relevant tracked range.

The oracle result and its provenance must be separable from the event stream transformation it validates. Replaying producer-derived addresses back through the same mapping code is only internal consistency and cannot establish observer completeness.

No current repository artifact upgrades either direct-access path to `negative_validated`. In particular, userfaultfd direct-read coverage remains `unknown` until a separate read observer is established and independently exercised.

## Hot-path and privacy constraints

The producer must remain diagnostic-only and disabled by default. Fault/hot-path work is bounded to direction detection, GPU-mapped acceptance, deterministic resource correlation, timestamp/counter work, and bounded in-memory enqueue/drop accounting. No per-event filesystem I/O, unbounded allocation/logging, proprietary payload capture, private path, username, or arbitrary operator string belongs in the event.

BB-INS4 remains responsible for target tracing-off/on overhead measurement and runtime coverage validation.

## Result of this slice

The compatibility gap identified by the earlier design slice is now represented fail-closed: runtime `guest_cpu` traces must identify their observer mechanism/build path, concrete observations must be backed by direction capability evidence, and negative coverage additionally requires a separately bound coverage oracle. The contract deliberately leaves userfaultfd read capability `unknown` and does not itself establish a real producer or any negative target evidence.

The next BB-INS2 implementation step is the bounded diagnostic producer at the accepted page-fault/rasterizer seam, together with independent exercise of every capability it wants to promote. A producer must emit truthful `unknown` rather than claiming completeness for an unvalidated direction.

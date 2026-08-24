# Buffer-backed guest-CPU diagnostic producer

`bb-buffer-guest-cpu-diagnostic/v1` is a bounded static/synthetic compatibility contract for the first buffer-backed guest-CPU diagnostic producer in BB-INS2.

It composes three already established contracts without claiming that shadPS4 emits this artifact at runtime:

- `bb-buffer-resource-id-binding/v1` turns cache-local `BufferId` lifetimes into fresh capture-local `res:[0-9]{8}` identities;
- `bb-guest-cpu-resource-correlation/v1` correlates one GPU-mapped accepted access against resources live at that sequence point using full containment only;
- emitted `unique` accesses use the canonical `bb-trace-events/v1` `access` / `guest_cpu` event shape with `coverage=observed`.

## Shared sequence domain

The input contains buffer lifecycle observations and GPU-mapped accepted guest-CPU accesses. Both streams use one caller-owned unsigned-64 sequence domain. Lifecycle order must satisfy the binding contract, accepted accesses must be strictly increasing, and a sequence value may not occur in both streams.

A registered lifetime is live for accesses whose sequence is strictly after its register observation and strictly before its unregister observation. This makes the temporal rule explicit without choosing an owner by input-list order.

## Correlation and diagnostics

For each accepted access, the producer derives the live buffer ranges at that sequence and delegates candidate selection to `bb-guest-cpu-resource-correlation/v1`.

- exactly one fully containing live range: emit one trace-compatible `guest_cpu` event;
- zero candidates: emit no trace event and preserve an `unmapped` diagnostic;
- multiple candidates: emit no trace event and preserve an `ambiguous` diagnostic with all candidate resource IDs.

Partial overlap is not ownership. Ambiguity is not broken by nearest address, insertion order, `BufferId`, or another heuristic.

## Boundedness and fail-closed behavior

The contract caps lifecycle observations, accepted accesses, output events, diagnostics, and bindings at one million entries. The underlying live-resource correlation contract independently caps the live candidate set at 4096 resources. Unsupported versions, duplicate JSON members, unknown fields, malformed ranges, 64-bit overflow, lifecycle misuse, sequence collisions, incompatible resource IDs, and trace-event schema incompatibility fail closed.

The producer returns `next_resource_ordinal`; namespace ownership remains with the eventual multi-class producer rather than this buffer-only slice.

## Evidence boundary

This contract is `static` + `synthetic` evidence only. It does not implement the C++ runtime producer, prove that the prepared raw-fault and GPU-mapped-acceptance hooks are paired correctly at runtime, establish a real image/texture/other-class resource source, promote any observer capability, establish `userfaultfd_write_protect` direct-read coverage, run Bloodborne, support a negative `GPU-only` conclusion, or measure target instrumentation overhead.

The next runtime implementation must source the shared sequence domain from the bounded diagnostic producer itself, ingest actual buffer lifecycle observations, emit accepted accesses only after the established GPU-mapped acceptance seam, and retain `unmapped` / `ambiguous` diagnostics rather than silently dropping or assigning them.

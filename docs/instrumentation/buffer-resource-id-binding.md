# Buffer cache lifetime → trace resource identity binding

`bb-buffer-resource-id-binding/v1` is a static/synthetic BB-INS2 compatibility contract for converting the prepared buffer-cache lifecycle stream into capture-local durable trace resource IDs.

## Why this exists

The pinned `BufferCache::buffer_ranges` seam exposes a cache-local `BufferId`, guest address, size, and register/unregister state. `BufferId` is an implementation-local slot identity and may be reused after a lifetime ends; it is therefore not the durable `res:[0-9]{8}` identifier expected by `bb-trace-events/v1`.

This contract assigns a fresh durable resource ID for every registered lifetime, in registration order. Reuse of the same `BufferId` after an exact unregister receives a new resource ID. Ordering is based on the bounded lifecycle stream's strictly increasing `seq`, never on numeric `BufferId` ordering.

## Fail-closed lifecycle rules

- each register (`live=true`) requires that the cache-local `buffer_id` is not already live;
- each unregister (`live=false`) requires an active lifetime with the exact same guest address and size;
- lifecycle sequence is strictly increasing;
- guest ranges use unsigned 64-bit half-open address semantics and must not overflow;
- a document marked `complete=true` must end with no live buffers;
- unknown or extra fields are rejected rather than ignored.

The output uses `res:00000001`, `res:00000002`, ... in registration order. These IDs are capture-local durable correlation IDs, not cross-run resource identity.

## Evidence boundary

This slice does not implement a runtime producer and does not claim that the synthetic order is already wired to the shadPS4 tracing producer. It only defines deterministic binding semantics for the already prepared **buffer** lifecycle seam.

Image/texture and other GPU-mapped resource classes remain unresolved. The contract cannot by itself establish observer completeness, negative `GPU-only` evidence, Bloodborne runtime behavior, target coverage, or instrumentation overhead.

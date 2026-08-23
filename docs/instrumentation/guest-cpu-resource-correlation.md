# Guest-CPU accepted-access live-resource correlation

This document defines the BB-INS2 static/synthetic compatibility rule for correlating one GPU-mapped accepted guest-CPU access range to the resource lifetime that owns the corresponding guest-memory range.

It does **not** implement the shadPS4 runtime producer, establish Bloodborne coverage, prove observer completeness, or justify a negative `GPU-only` claim.

## Contract

`bb-guest-cpu-resource-correlation/v1` takes the currently live resource ranges plus one already accepted guest-CPU access range. Addresses and sizes are unsigned 64-bit values. Ranges use half-open semantics `[guest_address, guest_address + size_bytes)`, and every size must be positive.

A resource is a candidate only when its live range **fully contains** the complete accepted access range. Partial overlap is not correlation evidence.

The result is deterministic and has exactly one of three states:

- `unique` — exactly one live range contains the access; only this state yields a `resource_id` suitable for a correlated `guest_cpu` trace event;
- `unmapped` — no live range contains the complete access;
- `ambiguous` — more than one live range contains the access, including legal alias/overlap cases.

For `ambiguous`, candidate IDs are preserved in lexical order for diagnostics. The producer must not choose by insertion order, nearest address, smallest range, or another heuristic.

## Fail-closed boundary

The validator rejects malformed input before correlation, including unsupported schema versions, unknown fields, duplicate live `resource_id` values, zero sizes, and any range whose last addressed byte would exceed the unsigned 64-bit address space.

Boundary-touching half-open ranges are non-overlapping. An access beginning exactly at a resource's exclusive end does not match that resource.

The contract intentionally does not reject overlapping live resource ranges. Aliasing can be meaningful; rejecting it would discard evidence, while silently choosing one owner would invent identity. Instead, an access fully contained by multiple live ranges becomes explicit `ambiguous` evidence.

## Runtime producer use

The future diagnostic producer described by `docs/instrumentation/guest-cpu-observer-producer.md` should invoke equivalent semantics only **after** the rasterizer has accepted the access range as GPU-mapped. The live-range set supplied to the correlator must come from actual resource lifetime state, not from a post-hoc heuristic reconstruction.

Only `unique` may populate `correlation.resource_id` on a runtime `guest_cpu` event. `unmapped` and `ambiguous` cannot be silently converted into a correlated access. A later trace-contract extension may preserve those states directly if runtime diagnostics need them; until then they remain bounded producer diagnostics rather than fabricated resource events.

## Evidence boundary

The committed tool, fixture, tests and CI establish deterministic range semantics and fail-closed contract behavior using synthetic inputs. They do not establish where every shadPS4 resource lifetime range is obtained, whether all relevant aliases are represented, or whether the future runtime producer observes every direct guest-CPU access path. Those remain BB-INS2/BB-INS4 work.

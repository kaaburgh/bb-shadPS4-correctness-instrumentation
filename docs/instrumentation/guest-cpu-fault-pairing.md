# Guest-CPU raw-fault to GPU-mapped acceptance pairing

`bb-guest-cpu-fault-pairing/v1` is a static/synthetic compatibility contract for the bounded BB-INS2 runtime producer.

At the pinned non-userfaultfd BB-BL1 source, `GuestFaultSignalHandler` observes the raw fault address and then forwards that same address to `Rasterizer::InvalidateMemory(addr, 8)` for a write or `Rasterizer::ReadMemory(addr, 8)` for a read. The separately prepared rasterizer hooks observe the access only after `Rasterizer::IsMapped(addr, size)` accepts the range as GPU-mapped. A runtime producer therefore needs a deterministic pairing boundary between those two observation classes before accepted accesses are fed to the buffer-backed diagnostic contract.

## Pairing rule

Each source observation carries a capture-local `thread:[0-9]{8}` identifier. It is an instrumentation ordinal, not a raw host thread identifier and must not encode private host information.

For one accepted access, candidates are currently pending raw faults with the same capture-local thread, exact guest fault address, and read/write class:

- exactly one candidate -> `paired`; that raw fault is consumed;
- zero candidates -> `unmatched`;
- multiple candidates -> `ambiguous`; every candidate source sequence is preserved and no candidate is consumed.

The contract intentionally does not pick the newest, nearest, or first candidate. At a complete stream boundary, remaining raw faults are preserved as `unpaired_raw_seqs`. Source `seq` is strictly increasing and `timestamp_ns` is monotonic. Accepted ranges must fit within unsigned 64-bit guest address space.

`paired_accesses` intentionally uses the exact field shape consumed by `bb-buffer-guest-cpu-diagnostic/v1`: `seq`, `timestamp_ns`, `guest_address`, `size_bytes`, and `access`. The dedicated workflow checks this cross-contract compatibility against the committed diagnostic schema.

## Evidence boundary

This contract establishes deterministic synthetic pairing semantics only. It does not establish that either prepared hook executed in Bloodborne, that a shadPS4 producer correctly assigns capture-local thread ordinals, or that every relevant fault path is observed. The `ENABLE_USERFAULTFD` path is outside this v1 pairing contract; direct-read capability there remains `unknown`. Missing/ambiguous pairings are diagnostics, never negative `GPU-only` evidence.

Runtime producer implementation, known-access controls/coverage oracles, non-buffer resource sourcing, and target overhead remain separate work.

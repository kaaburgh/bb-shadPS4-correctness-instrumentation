# Bloodborne death/reload performance conclusion

Date: 2026-09-12

This note records the current performance conclusion for the automated Bloodborne 1.09 death/reload workload. It is intentionally separate from the local, not-yet-pushed detailed profiling/vblank evidence.

## Established

The measured post-death reload interval is approximately 12.4 s:

- `load_start -> load_end`: ~12.399 s median in the vblank A/B;
- `death -> next_gameplay_ready`: ~13.2 s in the longer profiling run.

Host file I/O is not a material bottleneck in this workload:

- ~4,791-4,792 `read()` calls per reload;
- ~247.7-247.9 MB read per reload;
- AIO: 0 calls / 0 requests;
- measured host read + invalidation + staging-copy + wrapper timing is only about 45 ms total, roughly 0.36% of the 12.4 s wall interval.

Reload is CPU-heavy and deterministic:

- ~29.3 CPU-s per reload;
- ~2.34 effective host cores on average;
- one `Game:Main` thread is essentially runnable for the whole reload;
- one separate hot `NexusRevolution` TID consumes approximately one core-equivalent during the reload;
- load duration forms ~33.3 ms timing buckets.

The emulated-vblank A/B decisively did **not** accelerate reload:

| Arm | Load median (ms) | CPU s/reload | Effective cores | Flip / GNM events |
| --- | ---: | ---: | ---: | ---: |
| 60A | 12,399.594 | 29.360 | 2.368 | 372.7 / 372.0 |
| 120 | 12,398.574 | 29.280 | 2.362 | 372.3 / 372.7 |
| 240 | 12,398.985 | 29.480 | 2.376 | 373.0 / 372.3 |
| 60B | 12,399.831 | 29.340 | 2.364 | 373.0 / 372.3 |

All four arms completed 3/3 cycles (12/12 total).

Relative to pooled 60 Hz:

- 120 Hz speedup: `1.000087`, about 0.009% wall-time reduction;
- 240 Hz speedup: `1.000053`, about 0.005% wall-time reduction.

Flip/GNM rates remained approximately 30 events/s in all arms. They did not scale with configured emulated vblank frequency (`60 -> 120 -> 240 Hz`). The total progression count per reload also stayed essentially constant at ~372-373 events.

Therefore the 12.4 s reload is **not paced by shadPS4's configurable emulated vblank frequency**, and a fast-vblank/loading-only vblank mode is not worth implementing for this workload.

## Strong inference

The best current model is:

> The ~12.4 s post-death load is dominated by deterministic guest/emulator CPU and resource-processing work, with completion observed on a ~30 Hz game/progression boundary. The ~30 Hz progression behavior is not driven by the tested shadPS4 `GPU.vblank_frequency` setting.

The available evidence does not support storage, page-cache, AIO, staging-copy, invalidation, or configurable vblank pacing as meaningful optimization targets.

The ~33.3 ms timing buckets remain real, but changing the emulator vblank source from 60 to 120 or 240 Hz neither changes their practical wall-clock cost nor increases the observed flip/GNM progression rate. Thus the bucket quantization should not be interpreted as evidence that a faster host/emulated display clock can accelerate the load.

## Closed performance directions for this workload

Unless future measurements contradict the existing evidence, do not spend further time on:

- asynchronous AIO for Bloodborne death reload;
- host storage / SSD tuning;
- Linux page-cache tuning;
- read-path staging-copy/invalidation micro-optimization;
- increasing `GPU.vblank_frequency`;
- a loading-only fast-vblank mode.

These directions have either been directly disproven or are too small to materially affect a ~12.4 s reload.

## Remaining possible speedup directions

This is **not** proof that 12.4 s is an unavoidable fundamental limit of Bloodborne game logic.

A material further speedup would now require a narrower, more invasive class of work:

1. identify the exact guest/emulator functions/subsystem responsible for the two nearly saturated host cores during reload and optimize a real emulator bottleneck if one exists;
2. identify a Bloodborne-specific resource-loading/recreation path that can be cached, reused, or otherwise accelerated without changing the research result;
3. as a benchmark-only option, investigate a Bloodborne-specific guest/research shortcut only if correctness can be demonstrated.

Do not start another broad profiling pass merely to repeat aggregate CPU measurements. If performance work resumes, the most useful missing information is function/stack-level attribution for `Game:Main` and the single hot `NexusRevolution` TID during `load_start -> load_end`, preferably compared with an equal-duration neutral-gameplay control.

The ongoing death/reload memory-retention investigation should take priority because it may localize the same resource subsystem that is repeatedly reconstructed during loading. If it identifies a concrete resource/allocator/cache owner, use that result to decide whether a targeted performance experiment is justified.

## Current roadmap decision

For automated research cycles of the form:

```text
spawn -> fast death -> reload -> repeat
```

there is currently **no demonstrated low-hanging emulator configuration/timing optimization** that materially shortens the reload.

Status:

```text
Fast-vblank: CLOSED / disproven for this workload.
Host I/O / AIO: CLOSED as material bottleneck.
Current best model: deterministic guest CPU/resource-processing work.
Next performance work: only after a concrete subsystem/hotspot is localized.
Current priority: death/reload memory-retention localization.
```

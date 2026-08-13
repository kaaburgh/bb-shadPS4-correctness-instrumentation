# Bloodborne on shadPS4 correctness + instrumentation

## Goal

Довести Bloodborne на актуальном shadPS4 до состояния, в котором:

* основные известные проблемы корректности воспроизведения либо исправлены, либо хорошо локализованы;
* поведение CPU/GPU/memory paths достаточно инструментировано;
* можно надёжно измерять, где именно shadPS4 теряет производительность на Bloodborne;
* собран набор данных и инвариантов, достаточный для следующего этапа — Bloodborne-specific optimizations / runtime;
* по возможности общие исправления и инструменты остаются пригодными для upstream в shadPS4.

На этом этапе **не делать отдельный Bloodborne runtime и не оптимизировать игру за счёт предположений, специфичных только для Bloodborne**, кроме минимальных экспериментов для проверки гипотез.

---

## Milestone 0 — Reproducible baseline

Получить стабильное и воспроизводимое окружение Bloodborne + shadPS4, на котором можно сравнивать изменения.

Результат:

* зафиксирован baseline shadPS4;
* выбран небольшой набор воспроизводимых игровых сцен;
* известны baseline FPS / frametime / VRAM / RAM / shader compilation behaviour;
* есть простой способ повторять проверки после изменений.

---

## Milestone 1 — Bloodborne correctness inventory

Собрать и воспроизвести известные проблемы Bloodborne на текущем shadPS4.

Основные направления:

* shadows / depth-related artifacts;
* VRAM overusage / resource lifetime;
* synchronization / readback-related проблемы;
* shader / rendering corner cases;
* crashes или hardware-specific failures, если они ещё актуальны.

Результат:

* каждая заметная проблема имеет минимально воспроизводимый сценарий;
* проблемы разделены на понятные категории;
* понятно, какие из них являются generic shadPS4 correctness bugs, а какие могут оказаться Bloodborne-specific behaviour.

---

## Milestone 2 — Correctness fixes upstream-first

Разобраться с наиболее важными correctness problems и, где возможно, исправить их на уровне общей PS4 semantics в shadPS4.

Приоритет:

1. resource lifetime / VRAM;
2. synchronization и CPU↔GPU readbacks;
3. shadows / depth / render-target semantics;
4. остальные Bloodborne-visible rendering issues.

Результат:

* Bloodborne работает достаточно корректно, чтобы performance profiling не маскировался эмуляционными ошибками;
* generic fixes по возможности подготовлены в форме, пригодной для upstream;
* для оставшихся проблем понятно, почему generic решение затруднительно.

---

## Milestone 3 — GPU and memory instrumentation

Добавить observability вокруг наиболее интересных для будущей оптимизации областей.

Собирать как минимум:

* guest memory ↔ host resource mappings;
* resource creation/destruction/lifetime;
* CPU reads/writes и GPU reads/writes;
* readbacks;
* synchronization/barriers;
* render targets / depth resources;
* shader и pipeline identifiers;
* pipeline creation/cache behaviour;
* GPU/CPU timing для крупных операций.

Результат:

* можно восстановить lifetime и access pattern значимых ресурсов;
* можно видеть, где возникают expensive synchronization и readbacks;
* можно связать performance spikes с конкретными GPU/resource/shader событиями.

---

## Milestone 4 — Shader and pipeline corpus

Понять фактический shader/pipeline workload Bloodborne.

Результат:

* собран corpus используемых Bloodborne GCN shaders;
* известны соответствующие SPIR-V variants;
* понятно, сколько shader/pipeline work происходит во время игры;
* измерен эффект shader/pipeline cache;
* можно оценить feasibility полного pretranslation / prewarming перед запуском.

---

## Milestone 5 — Resource behaviour corpus

На основе instrumentation собрать фактические memory/resource patterns Bloodborne.

Искать повторяющиеся классы ресурсов:

* CPU upload → GPU-only;
* GPU-only transient;
* GPU write → CPU readback;
* render-target ↔ texture aliasing;
* predictable short-lived resources;
* persistent resources;
* suspicious synchronization-heavy paths.

Результат:

* появляется набор наблюдаемых Bloodborne resource invariants;
* для важных ресурсов известно, какие assumptions можно потенциально сделать безопаснее и агрессивнее generic shadPS4.

---

## Milestone 6 — Performance bottleneck map

Построить достаточно грубую, но доказательную картину того, где Bloodborne теряет время относительно потенциально более специализированного runtime.

Разделить стоимость примерно на:

* guest CPU execution;
* HLE/system calls;
* command processing;
* shader translation;
* Vulkan pipeline creation;
* synchronization/barriers;
* CPU↔GPU transfers/readbacks;
* resource management;
* actual GPU rendering workload.

Результат:

* понятны 3–5 наиболее перспективных направлений оптимизации;
* для каждого есть оценка потенциального выигрыша и сложности;
* становится понятно, есть ли вообще значимый запас производительности сверх текущего shadPS4.

---

## Milestone 7 — Specialization boundary

На основании накопленных данных определить границу следующего проекта.

Для каждого кандидата решить:

* улучшать generic shadPS4;
* добавить generic fast path;
* добавить Bloodborne-specific guarded optimization;
* вынести в будущий Bloodborne-specific runtime.

Возможные направления следующего этапа:

* заранее подготовленный shader corpus;
* pipeline prewarming;
* specialized resource lifetime rules;
* сокращение unnecessary readbacks/synchronization;
* распознавание повторяющихся Bloodborne GPU patterns;
* standalone launcher/runtime.

Результат:

**обоснованный план Bloodborne-specific performance layer**, основанный на измерениях и reverse engineering, а не на предположении, что generic emulator обязательно создаёт большой overhead.

---

## Exit criteria

Этап **Bloodborne on shadPS4 correctness + instrumentation** можно считать завершённым, когда:

* Bloodborne имеет достаточно хороший correctness baseline;
* ключевые оставшиеся rendering/memory проблемы понятны;
* существуют воспроизводимые benchmarks;
* instrumentation позволяет проследить основные GPU/memory/resource paths;
* собраны shader/pipeline и resource-behaviour corpora;
* известны реальные главные bottlenecks;
* есть конкретный список specialization opportunities для следующего этапа.

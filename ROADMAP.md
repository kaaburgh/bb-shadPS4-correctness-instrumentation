# Bloodborne on shadPS4 correctness + instrumentation

## Goal

Довести Bloodborne на shadPS4 до состояния, в котором correctness достаточно надёжен для profiling, CPU/GPU/memory paths наблюдаемы, baseline/corpora воспроизводимы, реальные bottlenecks измерены, а граница между generic shadPS4 work и Bloodborne-specific specialization определяется evidence.

На этом этапе **не делать отдельный Bloodborne runtime и не оптимизировать игру за счёт неподтверждённых title-specific assumptions**. Минимальные title-specific эксперименты допустимы только для проверки гипотез.

## Execution contract

- Один PR — один primary roadmap item; PR reconciles status/evidence/dependencies/acceptance.
- Investigation заканчивается знанием, decision или negative result; patch не обязателен.
- Implementation не открывается до established semantic seam/compatibility boundary.
- Title-visible symptom ≠ title-specific cause. Build/synthetic checks ≠ Bloodborne target validation.
- Если evidence устанавливает generic PS4/shadPS4 semantic correctness defect, default path — minimal generic, upstreamable shadPS4 correction; фактический merge в upstream не является обязательным acceptance criterion, потому что он зависит от решения upstream maintainers.
- Title/resource/shader-ID hardcoding не считается заменой generic correctness fix только потому, что такой workaround проще реализовать.
- Bloodborne-specific correctness workaround допустим только если evidence показывает, что generic solution impractical/disproportionate или поведение действительно title-specific; такой tradeoff нужно явно зафиксировать и направить к последующей specialization boundary, а не считать generic correctness completion.
- Evidence classes: `static`, `runtime`, `synthetic`, `reported`, `assumed`.
- Execution: **CLOUD**, **CLOUD RESEARCH**, **GATED**, **LOCAL ONLY**. `LOCAL ONLY` допустим только после documented feasibility result.
- Каждый **GATED** target-run item должен прямо зависеть от **BB-ENV1**. Он не стартует, пока feasibility item не зафиксировал конкретный execution route и handoff.
- Gated run должен быть one-shot и выдавать safe self-contained artifact; proprietary executables/assets/private dumps не коммитить.
- Runtime claims фиксируют shadPS4 repo+exact commit+patches, Bloodborne build/content/update/config, host OS/CPU/GPU/driver/backend/config, scenario и tool version.
- Correctness evidence precedes optimization profiling/specialization. До completed **BB-COR7** разрешены reproducibility baseline и bounded diagnostic measurements, необходимые для correctness/instrumentation (например **BB-BL6** и **BB-INS4**); optimization-ranking datasets и post-correctness corpora (**BB-SHD2**, **BB-RES2**, **BB-PERF2**) до gate не собираются.
- Изменение shadPS4 source/target/config baseline correctness-fix'ом инвалидирует затронутые downstream baseline/corpus/performance evidence. Такой PR обязан явно reopen/reconcile нужные capture items вместо сравнения stale datasets; shared provenance не делает unaffected artifact classes stale автоматически.
- Опровергнутые hypotheses и superseded directions сохраняются.

## Post-correctness capture and analysis contract

После hard gates **BB-COR7** и **BB-INS4** items **BB-SHD2**, **BB-RES2** и **BB-PERF2** являются независимыми data-collection items, а не последовательными стадиями одного pipeline. Один bounded target run/workflow **может** выпустить любой набор safe artifacts — shader/pipeline corpus, resource trace и performance timings — если у них совпадают exact source/target/host baselines, scenario/config identity, instrumentation build/configuration и run provenance. Это optional co-capture: roadmap не требует объединять runs, но и не должен структурно требовать отдельный run для каждого artifact class.

- Каждый artifact class валидируется и сохраняется независимо; отсутствие, неполнота или invalidation одного output не блокирует collection/analysis другого.
- **BB-SHD3**, **BB-RES3** и **BB-PERF3** остаются независимыми evidence-driven consumers своих соответствующих datasets. В частности, **BB-PERF2** не ждёт shader/resource analysis, а **BB-PERF3** не получает разрешение на ranking из одного только факта co-capture.
- Co-capture запрещён для performance attribution, если instrumentation materially меняет overhead или semantics относительно attribution-safe режима. В таком случае timing artifact не принимается как **BB-PERF2** evidence и должен быть recaptured отдельно; shader/resource artifacts можно сохранить только если их собственные provenance и validity criteria выполнены.
- Любое изменение correctness/source/target/config baseline или instrumentation, затрагивающее shared provenance, reopen'ит соответствующие datasets. Нельзя повторно использовать stale timing/corpus только потому, что они были получены в одном run; unaffected artifact classes остаются действительными при сохранении их provenance и acceptance evidence.

The **CLOUD**, **CLOUD RESEARCH**, **GATED** and **LOCAL ONLY** distinctions, together with the feasibility and one-shot handoff machinery, are agent-execution scaffolding. They separate autonomous work from target-machine work and preserve safe, reproducible handoffs; they are not architectural assumptions about shadPS4, Bloodborne, or the eventual specialization design. Technical milestone ordering must not be inferred solely from execution location. If execution capabilities change, this machinery may be simplified without changing the research goals.

## Ready now

Items со статусом `Open` или `Partially implemented` готовы к независимой bounded работе, если все их `Depends on` completed и для item нет активного PR. `Implemented, validation incomplete` не считается completed: зависимые **GATED** items остаются blocked, пока named validation gate явно не закрыт. После completed **BB-ENV1** GATED item использует зафиксированный target-machine route и operator handoff; его нельзя подменять cloud-only runtime claim. Остальные items остаются blocked до выполнения своих явных dependencies.

---

# Milestone 0 — Reproducible baseline

Outcome: source/target/host identities, target-execution feasibility, minimal scenarios и baseline captures сравнимы между runs.

### BB-BL1 — Pin shadPS4 source baseline and integration model
- **Status / priority / execution:** Completed / Critical / CLOUD RESEARCH
- **Depends on:** None
- **Question:** Какой exact upstream repo/commit является baseline и как future shadPS4 changes представлены reviewable способом без drift?
- **Result / evidence:** Static upstream inspection pinned the emulator core at `shadps4-emu/shadPS4@28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64`; source changes use exact-base fork/topic commits while this repository records immutable source/build provenance.
- **Acceptance / artifacts:** Completed in `docs/baseline/shadps4.md`: exact baseline, fail-closed fetch verification, update policy, build provenance and source-change workflow; no runtime claims.
- **Scope:** Medium

### BB-BL2 — Define Bloodborne target identity manifest
- **Status / priority / execution:** Completed / Critical / CLOUD
- **Depends on:** None
- **Question:** Какие safe identifiers различают materially different Bloodborne baselines?
- **Evidence / decision:** Schema v1 разделяет descriptive labels от field-level evidenced exact identity, сохраняет explicit partial identity и задаёт fail-closed three-way comparison (`same` / `different` / `indeterminate`) с учётом unknown pointers. Evidence: `synthetic`; реальный Bloodborne target не использовался.
- **Acceptance / artifacts:** [`docs/baseline/bloodborne.md`](./docs/baseline/bloodborne.md) + [JSON Schema](./schemas/bloodborne-target-manifest.schema.json) + [synthetic example](./docs/baseline/examples/bloodborne-target-manifest.synthetic.json) + [validator/comparator](./tools/bloodborne_target_manifest.py) + [tests](./tests/test_bloodborne_target_manifest.py) покрывают build/content/update/config state, hashing/comparison semantics и licensing/privacy boundary без proprietary payload.
- **Validation:** Draft 2020-12 schema, executable semantic checks и positive/negative synthetic cases валидируют format/internal consistency; это не реальная target identity или runtime verification.
- **Scope:** Small

### BB-BL3 — Define host/run environment manifest and collector
- **Status / priority / execution:** Completed and verified / High / CLOUD
- **Depends on:** None
- **Question:** Как автоматически фиксировать host factors, влияющие на correctness/performance?
- **Evidence / result:** `bb-host-environment/v1` schema и stdlib-only collector фиксируют allowlisted host/run fields, explicit unknown pointers и config fingerprint без путей/содержимого. Synthetic tests проверяют normalization, hardware-backed Windows CPU identity, bounded GPU inventory, published-schema constraint enforcement и privacy boundary; GitHub Actions run `31831060935` подтвердил 34-test suite, real collector smoke, producer validation и published-schema validation на Ubuntu, Windows и macOS для exact validation commit `9935b18c8b3c053572a94c9ed113f283f1e359a2`.
- **Acceptance / artifacts:** `docs/baseline/host-environment.md`, `schemas/host-environment.schema.json`, `tools/collect_host_environment.py` и tests выдают stable manifest с explicit unknown fields и без sensitive user data.
- **Scope:** Medium

### BB-ENV1 — Resolve target execution feasibility and handoff
- **Status / priority / execution:** Implemented, validation incomplete / Critical / GATED
- **Depends on:** BB-BL1, BB-BL2, BB-BL3
- **Question:** Может ли required Bloodborne target execution быть воспроизводимо выполнен в доступной cloud infrastructure; если нет, какой минимальный target-machine handoff объективно необходим?
- **Evidence / result:** Static repository review established that the cloud checkout contains only a synthetic target identity and cannot safely execute the proprietary target. The selected concrete route is a `GATED` target-machine run; this is not a claim that the target is `LOCAL ONLY` or that runtime behavior was observed. The route implementation and contract have synthetic/non-synthetic-classified stand-in coverage, but no target-owning machine has yet produced a bounded run record through it.
- **Handoff / next experiment:** Execute one bounded `process-exit` scenario on a target-owning machine through `tools/run_target_experiment.py` only and retain the resulting safe ZIP/run record as the validation evidence for this item. Non-synthetic execution is limited to the exact independently observed unpatched BB-BL1 CI artifact for the host; the runner copies the selected regular non-link executable into private per-run staging, verifies staged digest/size against the pinned artifact and caller-supplied digest, rewrites the snapshotted `argv[0]` to that staged path, then delegates to the normal bounded compatibility-engine executor. Direct execution of `tools/run_target_experiment_v3.py` fails closed. The handoff rejects explicit `--emulator-config`, non-empty `--patch-commit`, non-synthetic file oracles, and non-synthetic declared artifacts until those provenance relationships can be independently attested. Analyze only the resulting safe ZIP.
- **Acceptance / artifacts:** `docs/experiments/target-execution-feasibility.md` records the route, exact upstream build artifact identities, immutable input snapshots, supported entrypoint, private staged executable provenance checks, oracle/artifact restrictions, isolation rules, unsupported claims, and operator procedure. `schemas/target-run.schema.json` v3, `tools/run_target_experiment.py`, the internal compatibility engine, the v3 synthetic scenario, and tests define and validate the bounded run record while preventing the internal engine from being used as an ungated CLI. `Completed and verified` is reserved for a successful bounded target-machine run record produced through the supported entrypoint with the required source/target/host provenance and termination result.
- **Validation:** Exact-head CI for #62 exercised strict finite JSON parsing; exact BB-BL2 target-tree and direct-emulator argv binding; fail-closed unpatched-source/config provenance; exact official CI-produced executable identity; single-snapshot target/scenario/command inputs; private executable staging with pre-delegation digest/size verification and Linux non-synthetic-classified stand-in execution; fail-closed direct compatibility-engine invocation; non-synthetic oracle/artifact producer gating; safe target/scenario/DLC projections and packaged digests; stale-output rejection; process-tree containment and exception-safe teardown. `bb-target-runner/1.11.0` identifies this mechanism. This is contract/synthetic capability evidence only: no Bloodborne target-machine run record exists yet, so BB-ENV1 validation remains incomplete.
- **Scope:** Medium

### BB-BL4 — Select minimal reproducible scenario catalogue
- **Status / priority / execution:** Blocked on target evidence / Critical / GATED
- **Depends on:** BB-ENV1, BB-BL1, BB-BL2, BB-BL3
- **Question:** Какие 3–6 коротких scenarios покрывают startup, representative gameplay и correctness/performance-sensitive behavior?
- **Result / evidence:** `docs/scenarios/README.md` now defines the durable scenario-entry template, baseline/evidence fields, bounded actions/end conditions, oracle-strength boundary, and candidate→selected gate. Static inspection of the existing BB-ENV1 route established that non-synthetic runs currently accept only the `process-exit` oracle and no declared artifacts: this can bind exact provenance and bounded termination, but it cannot independently attest a title-visible gameplay/correctness/performance checkpoint. Evidence is `static`; no Bloodborne target was executed and no scenario is selected by this slice. The documentation slice is implemented, but target candidate exercise is blocked until BB-ENV1 has its first successful bounded target-machine run record.
- **Next experiment / information gain:** After BB-ENV1 is validated by a successful bounded target-machine run record, exercise bounded candidates on a target-owning machine through that route and retain only safe evidence. Keep operator checkpoint observations as `reported`; promote a candidate to `selected` only when the expected observable has an independent evidence path appropriate to the claim. If the current runner cannot produce that semantic evidence, add a producer-bound oracle/artifact path in its own bounded work before relying on it for selection.
- **Acceptance / artifacts:** `docs/scenarios/README.md` is the current template/evidence boundary. Completion still requires 3–6 selected scenarios with minimal overlap, including startup and representative gameplay plus correctness/performance-sensitive coverage, each recording reproducible start/actions/end conditions, expected observable, exact source/target/host baseline identity, oracle strength, and safe run-evidence references; non-redistributable saves/assets are never committed.
- **Validation:** Repository/CI checks for this partial slice validate documentation and roadmap consistency only; they do not establish target scenario reproducibility or semantic checkpoint evidence.
- **Scope:** Medium

### BB-BL5 — Build one-shot baseline capture workflow
- **Status / priority / execution:** Completed / Critical / CLOUD RESEARCH
- **Depends on:** BB-BL1, BB-BL2, BB-BL3
- **Question:** Как одним запуском собирать comparable FPS/frametime/RAM/VRAM/shader-compilation metadata и provenance?
- **Result / evidence:** Static inventory of the pinned baseline and available cloud route found no producer-bound target runtime telemetry for FPS, frametime, RAM, VRAM or shader-compilation measurements. `tools/capture_baseline.py` therefore emits a privacy-bounded one-shot ZIP with exact BB-BL1 source identity, a fail-closed transfer-safe BB-BL2 target projection, BB-BL3 host provenance, explicit `unavailable` states for all five runtime metrics, and measured collector/packer overhead. Evidence is `static` + `synthetic`; no Bloodborne target runtime was executed or inferred.
- **Acceptance / artifacts:** `tools/capture_baseline.py`, `tests/test_capture_baseline.py`, `.github/workflows/baseline-capture.yml`, and `docs/experiments/baseline-capture.md` define and exercise the one-command safe artifact contract. The artifact records separate source/packaged target digests, excludes unrestricted operator strings, and reports `packer_elapsed_ns` separately from target runtime. A future producer-bound GATED telemetry contract may replace individual `unavailable` states without changing this negative result.
- **Validation:** Synthetic/unit and CI smoke checks validate the packer contract and privacy boundary only; they do not establish Bloodborne runtime behavior, real performance values, or target telemetry availability outside the inventoried route.
- **Scope:** Medium

### BB-BL6 — Capture reproducible baseline dataset
- **Status / priority / execution:** Blocked / Critical / GATED
- **Depends on:** BB-ENV1, BB-BL4, BB-BL5
- **Question:** Каковы baseline distributions и run-to-run variance по selected scenarios?
- **Next experiment / information gain:** Несколько bounded repetitions prepared workflow с exact manifests по route из BB-ENV1.
- **Acceptance / artifacts:** `docs/experiments/baseline/` содержит safe derived metrics, provenance, summary statistics, missing-data/overhead notes.
- **Scope:** Medium

---

# Milestone 1 — Correctness inventory

Outcome: каждый актуальный symptom class воспроизводим либо закрыт как stale и имеет evidence-driven generic-vs-specific classification.

### BB-COR1 — Define correctness inventory and triage contract
- **Status / priority / execution:** Completed / High / CLOUD
- **Depends on:** BB-BL1, BB-BL2, BB-BL3
- **Question:** Как хранить symptom, provenance, evidence class, subsystem hypothesis, reproduction quality и next experiment?
- **Result / evidence:** `bb-correctness-case/v1` separates reported observations from target runtime outcomes, binds every observation to its own source/target/host baseline references, preserves provisional subsystem hypotheses, and fails closed when evidence is insufficient for ownership classification. Evidence: synthetic contract fixtures only; no Bloodborne runtime observation.
- **Acceptance / artifacts:** `docs/correctness/README.md`, `schemas/correctness-case.schema.json`, `tools/correctness_inventory.py`, the synthetic reported-only example, tests, and the dedicated correctness-inventory workflow define the triage contract without chat context. Runtime evidence requires exact target/host manifest references; `reported_only` cannot carry reproduction claims; `reproduced`, `not_reproduced`, and `stale` require bounded/repeatable runtime evidence plus a scenario; ownership classifications require an established semantic seam and static/runtime evidence, with backend/driver-specific claims additionally requiring explicit host-baseline contrast.
- **Validation:** Exact-head GitHub Actions for the final PR head must pass `Correctness inventory contract` plus the repository contract workflows. These are schema/semantic synthetic contract checks only, so BB-COR1 is completed as a contract definition but is not marked verified by target evidence.
- **Scope:** Small

### BB-COR2 — Reproduce graphics/shader/depth/render-target symptoms
- **Status / priority / execution:** Blocked / High / GATED
- **Depends on:** BB-ENV1, BB-BL6, BB-COR1
- **Question:** Какие rendering/shadow/depth/shader/pipeline symptoms актуальны и при каких resource/state conditions?
- **Next experiment / information gain:** Bounded descriptors/state/events/ID capture, различающий guest semantics, backend translation, sync и stale reports.
- **Acceptance / artifacts:** `docs/experiments/correctness-graphics/` фиксирует reproduced/not-reproduced status, evidence, negative results и next semantic question; proprietary shader payload не коммитится.
- **Scope:** Medium

### BB-COR3 — Reproduce VRAM/resource-lifetime symptoms
- **Status / priority / execution:** Blocked / Critical / GATED
- **Depends on:** BB-ENV1, BB-BL6, BB-COR1
- **Question:** Есть ли anomalous lifetime/VRAM growth и какие resources/allocations его объясняют?
- **Next experiment / information gain:** Bounded lifetime/allocation capture, различающий leak, delayed destruction, cache/residency, aliasing/reuse и expected workload.
- **Acceptance / artifacts:** `docs/experiments/correctness-resource-lifetime/` содержит timeline/summary и classification confirmed/not reproduced/expected/unknown.
- **Scope:** Medium

### BB-COR4 — Reproduce synchronization/readback symptoms
- **Status / priority / execution:** Blocked / Critical / GATED
- **Depends on:** BB-ENV1, BB-BL6, BB-COR1
- **Question:** Какие CPU↔GPU waits/readbacks/barriers коррелируют с correctness symptoms или stalls?
- **Next experiment / information gain:** Capture bounded event sequence с resource IDs/timestamps, separating required guest ordering from host over-sync/missing hazards.
- **Acceptance / artifacts:** `docs/experiments/correctness-sync-readback/` документирует sequence, affected resources, waits и competing hypotheses.
- **Scope:** Medium

### BB-COR5 — Reproduce crash/backend/hardware-specific failures
- **Status / priority / execution:** Blocked / Medium / GATED
- **Depends on:** BB-ENV1, BB-BL6, BB-COR1
- **Question:** Какие reported crashes/backend/hardware failures ещё актуальны и какие environment dimensions меняют result?
- **Next experiment / information gain:** Minimal matrix только для concrete reproduced symptom; classify generic/backend/driver/resource-pressure/stale.
- **Acceptance / artifacts:** `docs/experiments/correctness-compatibility/` фиксирует confirmed/not reproduced/stale/environment-specific cases без broad hardware claims.
- **Scope:** Small

### BB-COR6 — Cross-case correctness inventory and prioritization
- **Status / priority / execution:** Blocked / High / CLOUD
- **Depends on:** BB-COR2, BB-COR3, BB-COR4, BB-COR5
- **Question:** Какие reproduced issues остаются после per-class investigations, как они соотносятся по severity/confidence и какие additional distinct classes нужны?
- **Next experiment / information gain:** Cross-case analysis; объединять issues только при общем подтверждённом seam и не блокировать independent per-class FIX investigations ожиданием этого rollup.
- **Acceptance / artifacts:** `docs/correctness/README.md` содержит ranked inventory, confidence/evidence class и rationale; новые distinct classes получают отдельные roadmap IDs.
- **Scope:** Small

---

# Milestone 2 — Correctness fixes upstream-first

Outcome: priority defects исправляются только после установленного semantic seam, при этом generic PS4/shadPS4 defects получают предпочтительно generic upstreamable correction; false premises сохраняются как negative results; profiling открывается отдельным correctness gate.

**Shared acceptance policy:** Для каждого correction path evidence сначала определяет ownership boundary. Установленный generic defect должен вести к generic, reviewable и upstreamable shadPS4 fix; upstream merge не требуется для completion этого roadmap, поскольку решение находится у maintainers. Hardcoded title/resource/shader IDs не закрывают generic correctness requirement. Title-specific workaround остаётся допустимым только при documented evidence о genuine title-specific behavior либо impractical/disproportionate generic solution; в этом случае PR фиксирует evidence и tradeoff, применяет explicit guard/validated scope и передаёт решение к `BB-SPEC1`, а не выдаёт его за generic correctness fix.

### BB-FIX1 — Establish resource-lifetime semantic seam
- **Status / priority / execution:** Blocked / Critical / CLOUD RESEARCH
- **Depends on:** BB-COR3
- **Question:** Какой guest/emulator lifetime contract нарушен и где minimal source seam?
- **Next experiment / information gain:** Source tracing + smallest synthetic lifetime fixture; не предполагать architecture заранее.
- **Acceptance / artifacts:** `docs/re/resource-lifetime.md` фиксирует call/resource sequence, expected semantics, source seam и regression plan либо explicit rejected premise. Negative seam result reconciles BB-FIX2 as superseded/not-applicable rather than inventing a patch.
- **Scope:** Medium

### BB-FIX2 — Resolve resource-lifetime correction and target validation
- **Status / priority / execution:** Blocked / Critical / GATED
- **Depends on:** BB-ENV1, BB-FIX1
- **Question:** Если BB-FIX1 установил generic defect — реализовать minimal generic correction и проверить target behavior; если evidence показывает genuine title-specific behavior или impractical/disproportionate generic solution — проверить guarded workaround с documented tradeoff; если premise rejected — закрыть correction path без speculative patch.
- **Next experiment / information gain:** Synthetic regression first; target validation only for established behavior change, using BB-ENV1 route.
- **Acceptance / artifacts:** Valid outcomes: (a) tests + objective target evidence подтверждают generic correction без new lifetime/VRAM regression и upstreamability documented; (b) tests + objective target evidence подтверждают guarded title-specific workaround, а item фиксирует evidence genuine title-specific behavior либо why generic solution impractical/disproportionate, explicit guard/validated scope, tradeoff и handoff к `BB-SPEC1`; либо (c) item marked Superseded/Not applicable с ссылкой на negative seam evidence. Любое изменение source/config baseline явно invalidates/reopens affected BB-BL6/BB-INS4/BB-SHD2/BB-RES2/BB-PERF2 evidence.
- **Scope:** Medium

### BB-FIX3 — Establish synchronization/readback semantic seam
- **Status / priority / execution:** Blocked / Critical / CLOUD RESEARCH
- **Depends on:** BB-COR4
- **Question:** Какой ordering/readback contract требует observed behavior и где implementation diverges/over-synchronizes?
- **Next experiment / information gain:** Source trace + synthetic ordering/hazard fixture.
- **Acceptance / artifacts:** `docs/re/synchronization-readback.md` фиксирует semantic requirement, source seam и regression strategy; expensive sync не считается removable без proof. Negative seam result reconciles BB-FIX4.
- **Scope:** Medium

### BB-FIX4 — Resolve synchronization/readback correction and target validation
- **Status / priority / execution:** Blocked / Critical / GATED
- **Depends on:** BB-ENV1, BB-FIX3
- **Question:** Если established generic correction существует — реализовать и проверить ordering/data visibility; если evidence показывает genuine title-specific behavior или impractical/disproportionate generic solution — проверить guarded workaround с documented tradeoff; иначе закрыть path evidence-backed negative result.
- **Next experiment / information gain:** Synthetic regression + target event/correctness capture only after seam established.
- **Acceptance / artifacts:** Valid outcomes: (a) generic correction implemented and validated без unexplained hazards/waits/correctness-for-performance trade; (b) synthetic regression + target event/correctness evidence validates a guarded title-specific workaround with documented rationale, tradeoff, explicit guard/validated scope и handoff к `BB-SPEC1`; либо (c) Superseded/Not applicable по evidence. Baseline-changing correction reopens affected downstream capture items.
- **Scope:** Medium

### BB-FIX5 — Establish graphics/shader semantic seam
- **Status / priority / execution:** Blocked / High / CLOUD RESEARCH
- **Depends on:** BB-COR2
- **Question:** Какой render/depth/shader/pipeline semantic contract объясняет confirmed artifact и где minimal translation/state seam?
- **Next experiment / information gain:** Source tracing + smallest synthetic state/translation fixture.
- **Acceptance / artifacts:** `docs/re/graphics-correctness.md` фиксирует root-cause confidence, source seam, expected behavior и validation plan; no title/resource/shader-ID hardcode. Negative seam result reconciles BB-FIX6.
- **Scope:** Medium

### BB-FIX6 — Resolve graphics/shader correction and target validation
- **Status / priority / execution:** Blocked / High / GATED
- **Depends on:** BB-ENV1, BB-FIX5
- **Question:** Если established generic graphics/shader defect существует — исправить его и объективно проверить; если evidence показывает genuine title-specific behavior или impractical/disproportionate generic solution — объективно проверить guarded title-specific workaround; иначе закрыть correction path evidence-backed negative result.
- **Next experiment / information gain:** Synthetic state/translation regression + objective target capture only after seam established.
- **Acceptance / artifacts:** Valid outcomes: (a) tests + target pixel/state/event evidence prove generic correction with relevant formats/layouts/barriers/variants considered and upstreamability documented; (b) tests + target pixel/state/event evidence validate a guarded title-specific workaround, with evidence-backed rationale, explicit guard/validated scope, tradeoff, no title/resource/shader-ID hardcoding и handoff к `BB-SPEC1`; либо (c) Superseded/Not applicable по negative evidence. Baseline-changing correction reopens affected downstream capture items.
- **Scope:** Medium

### BB-COR7 — Decide whether correctness is sufficient for profiling
- **Status / priority / execution:** Blocked / Critical / CLOUD
- **Depends on:** BB-COR6, BB-FIX2, BB-FIX4, BB-FIX6
- **Question:** Достаточно ли текущего correctness состояния, чтобы performance measurements не ранжировали стоимость известных emulator defects как optimization opportunities?
- **Next experiment / information gain:** Review per-class reproduction, seam/fix outcomes и remaining compatibility blockers. Для каждого unresolved issue определить: materially distorts profiling, bounded/non-distorting, stale/not reproduced, или blocked on named evidence.
- **Acceptance / artifacts:** `docs/correctness/profiling-gate.md` фиксирует decision и exact baseline. `Completed` допустим только если key issues fixed/verified либо локализованы так, что их влияние на profiling bounded/explicit. Если issue всё ещё может materially distort measurements, item остаётся Blocked и добавляет конкретную dependency. Любые correctness changes, invalidating prior baseline/corpora, reopen/reconcile соответствующие capture items до target performance collection.
- **Scope:** Small

---

# Milestone 3 — GPU and memory instrumentation

Outcome: bounded tracing восстанавливает resource/access/sync/graphics events and timing, а tracing overhead измерим.

### BB-INS1 — Define trace event model and overhead contract
- **Status / priority / execution:** Completed / High / CLOUD
- **Depends on:** BB-BL1, BB-BL2, BB-BL3
- **Question:** Какой minimal schema/correlation model покрывает resource, access, sync, graphics and timing без ad-hoc unbounded logs?
- **Result / evidence:** `bb-trace-events/v1` defines provenance-bound resource/access/sync/graphics/timing events with typed generated correlation IDs, explicit observer coverage, category filters, deterministic sampling, bounded event/buffer limits and dropped-event accounting. Material source/target/host/scenario/config identities are digest-bound into `baseline_id`. The contract additionally verifies the recorded trace-schema digest against the canonical repository schema, verifies `bb-trace-event-model` producer identity against the canonical repository producer text, rejects `runtime` evidence attributed to the contract producer instead of `shadps4-bb-instrumentation`, and lets the resource-sync and graphics-timing consumers require an exact expected `baseline_id`. Evidence: `synthetic`; no Bloodborne runtime or shadPS4 source-seam observation was performed.
- **Acceptance / artifacts:** `schemas/trace-event.schema.json`, `tools/trace_event_model.py`, `tools/resource_sync_trace.py`, `tools/graphics_timing_trace.py`, their focused tests and synthetic examples, and the dedicated trace/resource-sync/graphics-timing workflows define and validate the bounded provenance/consumer contract. Instrumentation and serialization CPU overhead are recorded separately by the contract; actual target overhead remains a BB-INS4 tracing-off/on measurement and is not established by this item.
- **Validation:** Synthetic/unit CI coverage verifies repository schema/producer identity gates, runtime-producer mismatch rejection, caller-specified expected-baseline mismatch rejection in both reconstruction consumers, and cross-platform canonical-text provenance hashing. These checks establish schema/semantic/synthetic contract behavior only; they do not establish runtime observer coverage, a real instrumentation producer, target correctness, or target performance overhead.
- **Scope:** Medium

### BB-INS2 — Instrument resource mapping/lifetime/access and sync/readbacks
- **Status / priority / execution:** Partially implemented / High / CLOUD RESEARCH
- **Depends on:** BB-INS1
- **Question:** Где minimal source seams для guest-memory↔host-resource lifetime/access, CPU↔GPU transfers, waits/barriers/readbacks, включая прямые чтения/записи guest CPU в tracked GPU-backed guest-memory ranges, которые не проходят через explicit HLE transfer/readback API?
- **Result / evidence:** Static inspection at exact BB-BL1 baseline identifies the resource/sync/readback seams and establishes the direct guest-CPU page-fault observer chain: on the non-userfaultfd access-violation path, protected GPU-mapped writes dispatch to `Rasterizer::InvalidateMemory` and reads to `Rasterizer::ReadMemory`; under `ENABLE_USERFAULTFD`, static source establishes write-protect fault observation but not an equivalent direct-read fault path. The bounded producer-design slice places observation after the rasterizer GPU-mapped acceptance boundary, requires deterministic live-resource correlation, and preserves host/build/fault-mechanism coverage as an explicit evidence concern. The versioned `bb-guest-cpu-observer/v1` compatibility slice now binds the exact fault mechanism/build path and separate read/write capability states into trace material; runtime `guest_cpu` events require compatible observer provenance, and runtime `coverage=unobserved` additionally requires `negative_validated` capability evidence plus a distinct coverage-oracle digest. The source-integration preparation slice pins `src/video_core/page_manager.cpp` at BB-BL1 commit `28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64` and Git blob `6a4bcbd7dfd2031f93f069968304dd835443a342`, then prepares an off-by-default `SHADPS4_BB_GUEST_CPU_OBSERVE(addr, Common::IsWriteError(context))` hook at the non-userfaultfd `GuestFaultSignalHandler` seam without changing normal builds. The accepted-range source-integration slice additionally pins `src/video_core/renderer_vulkan/vk_rasterizer.cpp` at the same BB-BL1 commit and Git blob `e2b9ec75f88b632998e3cd15ddd6ca0a9cfd396c`, then prepares off-by-default `SHADPS4_BB_GUEST_CPU_ACCEPTED_OBSERVE(addr, size, true)` / `SHADPS4_BB_GUEST_CPU_ACCEPTED_OBSERVE(addr, size, false)` hooks immediately after `Rasterizer::InvalidateMemory` / `ReadMemory` accept the range as GPU-mapped, without changing normal builds. `bb-guest-cpu-resource-correlation/v1` now defines deterministic static/synthetic correlation from one accepted access range to currently live guest-memory resource ranges using unsigned 64-bit half-open ranges and full containment only: exactly one containing resource is `unique`, zero is `unmapped`, and multiple—including legal alias/overlap cases—remain explicit `ambiguous` evidence rather than a heuristic owner choice. Correlation resource IDs are kept exactly compatible with `bb-trace-events/v1` (`^res:[0-9]{8}$`). The buffer-live-range source-integration slice additionally pins `src/video_core/buffer_cache/buffer_cache.cpp` at BB-BL1 commit `28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64` and Git blob `68b85116029b6f05c45e9cc32be3ccf7de335bae`, then prepares off-by-default `SHADPS4_BB_BUFFER_LIVE_RANGE_OBSERVE(buffer_id, buffer.CpuAddr(), buffer.SizeBytes(), live)` hooks immediately after `buffer_ranges.Add` / `buffer_ranges.Subtract` in `BufferCache::ChangeRegister`. This exposes cache-local `BufferId` plus guest-range lifecycle without treating `BufferId` as durable trace resource identity, and establishes only the buffer-cache range source; image/texture and other GPU-mapped resource-class live-range sources remain unresolved. `bb-buffer-resource-id-binding/v1` now defines the static/synthetic buffer-lifetime→trace-ID compatibility boundary: it consumes the prepared bounded `BufferId` lifecycle stream, requires strictly increasing lifecycle sequence and exact register/unregister range pairing, assigns a fresh durable capture-local `res:[0-9]{8}` identity to every registered lifetime (including `BufferId` reuse after unregister), and uses a caller-owned `first_resource_ordinal`/`next_resource_ordinal` cursor so a future multi-class producer can own one shared trace namespace without buffer-private collisions. `bb-buffer-guest-cpu-diagnostic/v1` now defines the bounded static/synthetic buffer-backed diagnostic producer contract: it consumes one shared source-observation sequence domain for buffer lifecycles and GPU-mapped accepted accesses, composes the established buffer lifetime→trace-ID binding and accepted-access→live-resource correlation contracts, emits canonical trace-shaped `access` / `guest_cpu` events only for `unique` correlations, preserves `unmapped` and `ambiguous` outcomes as explicit diagnostics, assigns emitted trace events a trace-local contiguous `seq=0..N-1`, and preserves the audit mapping from each emitted `trace_seq` back to its source-observation `source_seq`. The output also returns the caller-owned `next_resource_ordinal` so a future multi-class runtime producer can own one shared namespace rather than this buffer-only slice. `bb-guest-cpu-fault-pairing/v1` now defines the bounded static/synthetic raw-fault→GPU-mapped-acceptance pairing boundary for the pinned non-userfaultfd path: one strictly ordered source-observation stream uses privacy-safe capture-local `thread:[0-9]{8}` identities; a uniquely matching raw fault with the same thread, exact guest address and read/write class is consumed and yields a paired accepted access in the exact shape consumed by `bb-buffer-guest-cpu-diagnostic/v1`; zero candidates remain `unmatched`; multiple same-key candidates remain explicit `ambiguous` evidence with all raw sequence IDs preserved and none consumed; terminal pending raw faults are retained for audit. No newest/nearest/first-candidate heuristic is permitted. `userfaultfd_write_protect` direct-read capability remains fail-closed as `unknown`. Evidence is `static` + `synthetic`; no Bloodborne runtime execution, shadPS4 runtime diagnostic producer, runtime hook execution/pairing, complete actual live-range source binding, observer completeness, or negative `GPU-only` claim is established.
- **Next experiment / information gain:** Implement the bounded shadPS4 runtime diagnostic producer for buffer-backed ranges using the provenance-bound raw access-violation, GPU-mapped-acceptance, and buffer-lifecycle seams plus `bb-guest-cpu-fault-pairing/v1`; assign capture-local thread ordinals without persisting raw host thread identifiers, feed uniquely paired accepted accesses and actual live buffer lifetimes through the established buffer resource-ID/correlation/diagnostic contracts, and preserve unmatched/ambiguous pairing diagnostics without promoting non-buffer coverage. Preserve image/texture and other non-buffer classes as explicitly unresolved until equivalent live-range sources and durable identity mappings are established. Then independently exercise every claimed observer path with a known-access control or structural seam-coverage oracle before promoting capability states. Keep userfaultfd direct-read coverage `unknown` unless a separate read observer is established; do not admit negative `GPU-only` evidence from missing events alone.
- **Acceptance / artifacts:** `schemas/trace-event.schema.json`, `tools/trace_event_model.py`, `tests/test_trace_event_model.py`, `tools/resource_sync_trace.py`, `tests/test_resource_sync_trace.py`, `docs/instrumentation/schema.md`, `docs/instrumentation/resources-sync.md`, `docs/instrumentation/guest-cpu-observer-producer.md`, `tools/prepare_guest_cpu_observer_patch.py`, `tests/test_prepare_guest_cpu_observer_patch.py`, `docs/instrumentation/guest-cpu-observer-source-patch.md`, `.github/workflows/guest-cpu-observer-patch.yml`, `tools/prepare_guest_cpu_accepted_observer_patch.py`, `tests/test_prepare_guest_cpu_accepted_observer_patch.py`, `docs/instrumentation/guest-cpu-accepted-observer-source-patch.md`, `.github/workflows/guest-cpu-accepted-observer-patch.yml`, `schemas/guest-cpu-resource-correlation.schema.json`, `tools/guest_cpu_resource_correlation.py`, `tests/test_guest_cpu_resource_correlation.py`, `docs/instrumentation/guest-cpu-resource-correlation.md`, `docs/instrumentation/examples/guest-cpu-resource-correlation.synthetic.json`, `.github/workflows/guest-cpu-resource-correlation.yml`, `tools/prepare_buffer_live_range_observer_patch.py`, `tests/test_prepare_buffer_live_range_observer_patch.py`, `docs/instrumentation/buffer-live-range-source-patch.md`, `.github/workflows/buffer-live-range-observer-patch.yml`, `schemas/buffer-resource-id-binding.schema.json`, `tools/buffer_resource_id_binding.py`, `tests/test_buffer_resource_id_binding.py`, `docs/instrumentation/buffer-resource-id-binding.md`, `docs/instrumentation/examples/buffer-resource-id-binding.synthetic.json`, `.github/workflows/buffer-resource-id-binding.yml`, `schemas/buffer-guest-cpu-diagnostic.schema.json`, `tools/buffer_guest_cpu_diagnostic.py`, `tests/test_buffer_guest_cpu_diagnostic.py`, `docs/instrumentation/buffer-guest-cpu-diagnostic.md`, `docs/instrumentation/examples/buffer-guest-cpu-diagnostic.synthetic.json`, `.github/workflows/buffer-guest-cpu-diagnostic.yml`, `schemas/guest-cpu-fault-pairing.schema.json`, `tools/guest_cpu_fault_pairing.py`, `tests/test_guest_cpu_fault_pairing.py`, `docs/instrumentation/guest-cpu-fault-pairing.md`, `docs/instrumentation/examples/guest-cpu-fault-pairing.synthetic.json`, `.github/workflows/guest-cpu-fault-pairing.yml`, the existing synthetic trace examples, and the dedicated trace/resource-sync workflows define the current reconstruction/static-seam/versioned observer-compatibility/source-integration/correlation/resource-ID-binding/buffer-backed diagnostic/raw-fault pairing slices. Completion still requires an evidence-backed shadPS4 runtime producer of direct guest CPU read/write observations for tracked GPU-backed ranges, runtime execution of the pairing/correlation chain from actual live-resource sources with durable resource identity/lifetime/GPU activity, image/texture and other relevant live-range sourcing, and independent coverage validation for every path supporting a negative claim. Diagnostic mode remains disabled by default.
- **Validation:** Exact-head CI for #112 exercises the published raw-fault pairing schema/CLI, strict source-observation ordering and monotonic timestamps, privacy-safe thread ordinal format, exact thread/address/access matching, explicit `paired`/`unmatched`/`ambiguous` outcomes without heuristic selection, preservation of terminal unpaired raw observations, overflow/extra-field rejection, and cross-contract compatibility by validating produced `paired_accesses` inside a complete `bb-buffer-guest-cpu-diagnostic/v1` input document. Exact-head CI for #110 exercises the published buffer-backed diagnostic schema/CLI, composition with the buffer resource-ID binding and live-resource correlation contracts, shared source-observation ordering, canonical trace-local contiguous event sequencing with explicit `trace_seq`→`source_seq` provenance, monotonic accepted-access timestamps, `unique` emission plus explicit `unmapped`/`ambiguous` accounting, schema-bound generated output, malformed/overflow/extra-field rejection, and the synthetic fixture's expected 3-access/1-event/1-unmapped/1-ambiguous result. Exact-head CI for #108 exercises the published buffer resource-ID binding schema/CLI, strict lifecycle sequence/register/unregister semantics, fresh IDs across `BufferId` reuse, caller-owned resource-ordinal namespace cursor, overflow/duplicate/extra-field/incomplete-stream rejection, trace-compatible decimal `resource_id` format, and regression coverage that the emitted artifact uses the documented singular `bb-buffer-resource-id-binding/v1` schema version. Exact-head CI for #106 exercises fail-closed BB-BL1 commit/Git-blob binding, exact `buffer_ranges.Add` / `buffer_ranges.Subtract` seam matching after the live-range state mutation, repeated-application rejection, bounded single-hunk patch shape and exact upstream-source preparation for the off-by-default buffer lifecycle hooks. Exact-head CI for #104 exercises the published correlation schema/CLI, deterministic half-open-range full-containment semantics, explicit `unique`/`unmapped`/`ambiguous` outcomes, overflow/duplicate/extra-field rejection, trace-compatible decimal `resource_id` rejection of incompatible hex IDs, and a cross-contract regression that keeps the correlation and trace `resource_id` definitions identical. Exact-head CI for #102 exercises fail-closed BB-BL1 commit/Git-blob binding, exact write/read accepted-seam matching after GPU-mapped range admission, repeated-application rejection, two-hunk patch shape and exact upstream-source preparation for the off-by-default accepted-range hooks; exact-head CI for #100 exercises the raw access-violation hook's corresponding provenance/single-seam/single-hunk contract; the existing #92 contract CI covers versioned observer compatibility, distinct observation-evidence/coverage-oracle digests, resource-sync consumer rejection and provenance-bound synthetic fixtures. These checks establish static/synthetic integration, raw-fault pairing, correlation, resource-ID binding, bounded diagnostic composition, and compatibility behavior only; they do not establish Bloodborne runtime coverage, shadPS4 runtime producer behavior, runtime hook execution/pairing, complete live-range sourcing, userfaultfd read coverage, observer completeness, negative `GPU-only` evidence, or target overhead.
- **Scope:** Medium

### BB-INS3 — Instrument render/depth/shader/pipeline identity and timing
- **Status / priority / execution:** Partially implemented / High / CLOUD RESEARCH
- **Depends on:** BB-INS1
- **Question:** Как correlate render/depth resources with safe shader/pipeline IDs, creation/cache events and coarse CPU/GPU timings?
- **Result / evidence:** Static inspection at exact BB-BL1 baseline identified `PipelineCache::RefreshGraphicsKey`/`GetGraphicsPipeline` and `Scheduler::BeginRendering`/`SubmitExecution` as candidate graphics/pipeline/render-lifecycle seams. The earlier synthetic `bb-trace-events/v1` reconstruction correlates capture-local graphics events with pipeline IDs and separate CPU/GPU timing spans while preserving resource/queue/pipeline/span correlation. Deterministic source-bound shader identities, a bounded `pipeline_family_identity`, and render identities with explicit color/depth/stencil attachment roles are established synthetically from pinned source semantics. The complete pinned 21-field top-level/flattened `GraphicsPipelineKey` equality surface is inventoried in `docs/instrumentation/graphics-pipeline-key-surface.json`; exact canonicalization covers all 21/21 fields and the checker reports `pipeline_identity_ready=true`. `bb-graphics-identity/v2` defines an exact `pipeline_identity` from the complete canonical key, validates every canonical value against the committed surface rules, binds identity provenance to the pinned source baseline and SHA-256 of the validated surface document, and retains `pipeline_family_identity` as a separate coarser descriptor. `bb-graphics-pipeline-producer/v1` now defines a versioned static/synthetic admission contract for the future bounded `GetGraphicsPipeline` producer: it pins the exact BB-BL1 source seam plus identity/key-surface compatibility, requires exact `pipeline:sha256:...` identities, distinguishes `created` from `cache_hit`, enforces a strictly increasing capture-local sequence with bounded record count, and fails closed on stale or incompatible provenance. The source-integration preparation slice pins `src/video_core/renderer_vulkan/vk_pipeline_cache.cpp` at BB-BL1 commit `28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64` and Git blob `b39f1c30bfb00d1f21a082da48369ba95ce31368`, then prepares an off-by-default `SHADPS4_BB_GRAPHICS_PIPELINE_OBSERVE(graphics_key, is_new)` hook immediately after the unique `graphics_pipelines.try_emplace(graphics_key)` lookup result without changing normal builds. `bb-graphics-pipeline-cpp-identity-vector/v1` now freezes the exact canonical UTF-8 JSON payload and expected `pipeline:sha256:c46cf5568ebdb232b52bc092f2fc445bf1fa9aee1b7663717b087fae5cce1c38` digest that an independent C++ implementation of `bb-graphics-identity/v2` must reproduce; the vector is bound to the pinned source baseline, the committed `bb-graphics-pipeline-key-surface/v12` version/digest, and the existing graphics-identity synthetic fixture. This is internal static/synthetic conformance evidence only, not an independent validation of the Python identity model. Evidence is `static` + `synthetic`; no Bloodborne runtime execution, emitted exact cross-run pipeline identity, enabled runtime producer, independently observed creation/cache semantics, GPU timestamp semantics, target coverage, or measured instrumentation overhead is established.
- **Next experiment / information gain:** Implement the bounded C++ exact-identity emitter at the provenance-bound prepared `GetGraphicsPipeline` hook and require it to independently reproduce the committed conformance vector bytes and digest before emitting records satisfying `bb-graphics-pipeline-producer/v1`; then independently exercise `created`/`cache_hit` classification before promoting runtime evidence. Separately establish a bounded runtime timing producer with independently justified CPU/GPU timing semantics; do not treat optional Tracy GPU scopes as the BB timing source without independent evidence.
- **Acceptance / artifacts:** `tools/graphics_timing_trace.py`, `tests/test_graphics_timing_trace.py`, `docs/instrumentation/examples/graphics-timing.synthetic.json`, `.github/workflows/graphics-timing-trace.yml`, and `docs/instrumentation/graphics-timing.md` provide the capture-local reconstruction slice. `tools/graphics_identity_model.py`, `tests/test_graphics_identity_model.py`, `docs/instrumentation/examples/graphics-identity.synthetic.json`, and `.github/workflows/graphics-identity-model.yml` provide safe shader/render/pipeline-family identities plus the static/synthetic exact canonical pipeline-identity contract. `docs/instrumentation/graphics-pipeline-key-surface.json`, `tools/graphics_pipeline_key_surface.py`, `tests/test_graphics_pipeline_key_surface.py`, and `.github/workflows/graphics-pipeline-key-surface.yml` provide the complete exact pinned equality-surface canonicalization contract. `schemas/graphics-pipeline-producer.schema.json`, `tools/graphics_pipeline_producer_contract.py`, `tests/test_graphics_pipeline_producer_contract.py`, `docs/instrumentation/graphics-pipeline-producer.md`, `docs/instrumentation/examples/graphics-pipeline-producer.synthetic.json`, and `.github/workflows/graphics-pipeline-producer.yml` provide the versioned producer-admission compatibility slice. `tools/prepare_graphics_pipeline_producer_patch.py`, `tests/test_prepare_graphics_pipeline_producer_patch.py`, `docs/instrumentation/graphics-pipeline-producer-source-patch.md`, and `.github/workflows/graphics-pipeline-producer-patch.yml` provide the exact provenance-bound source-seam preparation slice. `tools/graphics_pipeline_cpp_identity_vector.py`, `tests/test_graphics_pipeline_cpp_identity_vector.py`, `docs/instrumentation/graphics-pipeline-cpp-identity-vector.md`, `docs/instrumentation/examples/graphics-pipeline-cpp-identity-vector.synthetic.json`, and `.github/workflows/graphics-pipeline-cpp-identity-vector.yml` provide the byte-exact C++ conformance-vector slice. Completion still requires an evidence-backed runtime producer emitting exact safe cross-run pipeline identity, independently supported creation/cache observations, a runtime timing producer with established CPU/GPU semantics, target coverage and measured tracing overhead; no proprietary shader payload may be committed.
- **Validation:** Exact-head CI for #114 exercises regeneration of the frozen canonical payload from the committed Python model/fixture, byte-for-byte canonical UTF-8 JSON matching, expected SHA-256 identity matching, stale source/model/key-surface provenance rejection, unknown/non-canonical vector rejection, and dedicated workflow triggering across all material identity/surface inputs. This establishes internal static/synthetic cross-language conformance evidence only; independent evidence begins when a separate C++ implementation reproduces the committed bytes and digest. Exact-head CI for #98 exercises fail-closed BB-BL1 commit/Git-blob binding, unique exact source-seam matching, repeated-application rejection, single-hunk patch shape and exact upstream-source preparation for the off-by-default pipeline observer hook; exact-head CI for #96 exercises the producer-admission JSON Schema/semantic validator, strict increasing-sequence and bounded-volume rules, exact identity/source/seam compatibility, stale/incompatible provenance rejection, capture-local-ID rejection and synthetic fixture CLI validation. Together with the existing graphics-identity/key-surface checks, this establishes static/synthetic producer compatibility, source integration and C++ conformance target only; it does not establish runtime emission, creation/cache runtime semantics, target coverage, GPU timestamp semantics, or target overhead.
- **Scope:** Medium

### BB-INS4 — Validate instrumentation coverage and overhead on target
- **Status / priority / execution:** Blocked / Critical / GATED
- **Depends on:** BB-ENV1, BB-BL4, BB-INS2, BB-INS3
- **Question:** Достаточны ли events для reconstruction, независимо подтверждена ли полнота direct guest CPU coverage, и каков measured overhead on representative scenarios?
- **Next experiment / information gain:** Tracing off/on one-shot captures with bounded event volume using BB-ENV1 route, plus a bounded known-access control or structural seam-coverage oracle for every claimed direct-access path so missed probes are distinguishishable from true no-access.
- **Acceptance / artifacts:** `docs/experiments/instrumentation-validation/` records correlation completeness, overhead distribution, missing probes, and the independent coverage-oracle result/provenance; any uncovered observer path remains explicit and blocks negative `GPU-only` classification. Large raw captures are externalized.
- **Scope:** Medium

---

# Milestone 4 — Shader and pipeline corpus

Outcome: actual shader/pipeline workload, variants, cache behavior и prewarming opportunity основаны на captures made only after correctness profiling gate.

### BB-SHD1 — Define shader/pipeline corpus identity and storage
- **Status / priority / execution:** Blocked / Medium / CLOUD
- **Depends on:** BB-INS3
- **Question:** Какие safe IDs/metadata позволяют deduplicate guest shader identity, translated variants and pipelines across runs?
- **Next experiment / information gain:** Versioned corpus schema + synthetic merge/dedup fixtures.
- **Acceptance / artifacts:** `docs/corpus/shaders.md` + schema/tools preserve variant/baseline boundaries без proprietary payload redistribution.
- **Scope:** Small

### BB-SHD2 — Capture representative shader/pipeline corpus
- **Status / priority / execution:** Blocked / Medium / GATED
- **Depends on:** BB-ENV1, BB-COR7, BB-INS4, BB-SHD1
- **Question:** Какой shader/pipeline set реально используется selected scenarios и насколько он стабилен between runs?
- **Next experiment / information gain:** Repeated bounded corpus captures across scenario catalogue after correctness gate; capture workflow may emit shader, resource and timing artifacts together when the shared provenance contract is satisfied.
- **Acceptance / artifacts:** `docs/experiments/shader-corpus/` + safe deduplicated index, run coverage and stability summary tied to exact post-gate baseline. Shader evidence remains independently consumable when a co-captured resource or timing output is missing or invalid.
- **Scope:** Medium

### BB-SHD3 — Analyze variants/cache and prewarming feasibility
- **Status / priority / execution:** Blocked / Medium / CLOUD RESEARCH
- **Depends on:** BB-SHD2
- **Question:** Сколько translation/pipeline work происходит, каков cache behavior и есть ли evidence для pretranslation/prewarming?
- **Next experiment / information gain:** Offline counts/correlation; если benefit hypothesis survives, подготовить controlled A/B target experiment as a new bounded item.
- **Acceptance / artifacts:** `docs/analysis/shader-pipeline-workload.md` documents distributions, cache effects, uncertainty and go/no-go for separate feasibility/optimization item.
- **Scope:** Medium

---

# Milestone 5 — Resource behaviour corpus

Outcome: actual resource lifetime/access classes превращены в conditional evidence-backed invariants after correctness profiling gate.

### BB-RES1 — Define resource classification and invariant extraction
- **Status / priority / execution:** Blocked / Medium / CLOUD
- **Depends on:** BB-INS2
- **Question:** Как classify upload→GPU-only, transient, readback, aliasing, persistent and sync-heavy resources reproducibly while retaining direct guest CPU access evidence for tracked GPU-backed ranges?
- **Next experiment / information gain:** Rule-based schema/classifier + synthetic traces including direct guest CPU reads/writes, explicit transfer/readback calls, GPU activity, and unknown/unobserved/ambiguous coverage cases.
- **Acceptance / artifacts:** `docs/corpus/resources.md` + parser/tests classify fixtures and preserve event timing/order, resource/lifetime/GPU correlation, and unknown/ambiguous coverage. A `GPU-only` classification requires adequate direct guest CPU read/write coverage for the tracked range, an independent known-access or structural seam-coverage check for the relevant observer paths, and an evidence-backed observed absence/condition; it is not inferred solely from missing explicit transfer/readback calls. Classification не объявляется semantic fact.
- **Scope:** Small

### BB-RES2 — Capture representative resource traces
- **Status / priority / execution:** Blocked / Medium / GATED
- **Depends on:** BB-ENV1, BB-COR7, BB-INS4, BB-RES1
- **Question:** Какие lifetime/access patterns реально встречаются и насколько repeatable их classes?
- **Next experiment / information gain:** Repeated bounded traces over scenario catalogue after correctness gate; the same bounded workflow may also emit shader/pipeline and timing artifacts without making their downstream analyses dependencies, with the independent known-access or structural seam-coverage oracle checked before accepting negative classifications.
- **Acceptance / artifacts:** `docs/experiments/resource-corpus/` records completeness/correlation, direct guest CPU read/write observations (or explicit unknown/unobserved/ambiguous coverage) for tracked GPU-backed ranges, and the independent coverage-oracle result/provenance for relevant observer paths. Safe summaries remain tied to the exact post-gate baseline, and resource evidence remains independently consumable when a co-captured shader or timing output is missing or invalid. If any relevant path is not independently covered, the range stays unknown/unobserved and no `GPU-only` label is accepted; no resource contents unless separately justified.
- **Scope:** Medium

### BB-RES3 — Derive and validate candidate resource invariants
- **Status / priority / execution:** Blocked / Medium / CLOUD RESEARCH
- **Depends on:** BB-RES2, BB-BL4
- **Question:** Какие patterns repeat enough to be conditional invariants, какие are outliers, и какой scope survives scenario/config changes?
- **Next experiment / information gain:** Offline clustering/counterexamples; any required target discriminating matrix becomes a separate GATED item depending on BB-ENV1.
- **Acceptance / artifacts:** `docs/analysis/resource-invariants.md` stores support, conditions, counterexamples/rejections and go/no-go for any guarded fast-path item.
- **Scope:** Medium

---

# Milestone 6 — Performance bottleneck map

Outcome: cost attribution rank-ит 3–5 real opportunities с explicit uncertainty, unattributed time и instrumentation overhead, без смешивания cloud model design и target collection.

### BB-PERF1 — Define non-overlapping performance attribution model
- **Status / priority / execution:** Blocked / High / CLOUD RESEARCH
- **Depends on:** BB-INS2, BB-INS3
- **Question:** Как разделить guest CPU, HLE/syscalls, command processing, translation, pipeline creation, sync, transfers, resource management and actual GPU workload без double counting?
- **Next experiment / information gain:** Synthetic accounting model with explicit unattributed bucket, overhead accounting and fixture cases. Target execution в этом item не выполняется.
- **Acceptance / artifacts:** `docs/performance/attribution-model.md` defines non-overlapping accounting, required inputs, uncertainty/unattributed handling and instrumentation-overhead treatment; synthetic fixtures reconcile totals.
- **Scope:** Medium

### BB-PERF2 — Collect representative performance timing dataset
- **Status / priority / execution:** Blocked / High / GATED
- **Depends on:** BB-ENV1, BB-COR7, BB-PERF1, BB-INS4
- **Question:** Каковы repeated timing distributions across selected scenarios/warm-cold states на correctness-approved exact baseline?
- **Next experiment / information gain:** Prepared repeated target captures using BB-PERF1 accounting inputs and BB-ENV1 execution route; timing may be co-captured with BB-SHD2/BB-RES2, but does not wait for BB-SHD3/BB-RES3.
- **Acceptance / artifacts:** `docs/experiments/performance-datasets/` contains safe derived datasets with exact post-BB-COR7 provenance, variance, instrumentation overhead and missing/unattributed data. Co-captured timings are accepted only when instrumentation remains attribution-safe; otherwise they are recaptured separately. If baseline or relevant instrumentation changed after COR7/corpus capture, stale dependencies are recaptured before completion.
- **Scope:** Medium

### BB-PERF3 — Build ranked bottleneck map
- **Status / priority / execution:** Blocked / High / CLOUD
- **Depends on:** BB-PERF2
- **Question:** Какие 3–5 cost classes имеют largest measured optimization potential и sufficient confidence?
- **Next experiment / information gain:** Cross-scenario ranking with uncertainty/overhead sensitivity; “no meaningful headroom” is valid result.
- **Acceptance / artifacts:** `docs/performance/bottleneck-map.md` gives contribution/range, confidence, constraints and creates bounded feasibility items only для evidence-backed candidates.
- **Scope:** Medium

---

# Milestone 7 — Specialization boundary

Outcome: next-stage scope выбирается evidence, а не предположением о необходимости specialized runtime.

### BB-SPEC1 — Decide specialization boundary and next-stage plan
- **Status / priority / execution:** Blocked / Medium / CLOUD
- **Depends on:** BB-PERF3
- **Question:** Для ranked candidates: generic correctness, generic fast path, guarded Bloodborne optimization, future runtime или reject; выполнены ли exit criteria?
- **Next experiment / information gain:** Decision matrix using measured benefit, semantic assumptions, guardability, maintenance cost and upstream fit; reconcile remaining correctness/corpus gaps.
- **Compatibility / safety:** Title-specific assumption requires explicit guard and validated scope; unresolved correctness blocks aggressive specialization.
- **Acceptance / artifacts:** `docs/architecture/specialization-boundary.md` + `docs/architecture/next-stage-plan.md` record decisions, evidence, risks/rejected alternatives and explicit go/no-go, включая valid “no separate runtime” outcome.
- **Scope:** Medium

---

# Exit criteria

Этап завершён только когда:

- source/target/host baselines, target-execution route и scenarios воспроизводимы;
- key correctness issues fixed/verified либо локализованы с documented blocker, а BB-COR7 разрешает profiling на exact baseline;
- instrumentation traces main GPU/memory/resource/sync/shader paths и имеет measured overhead;
- shader/pipeline и resource-behaviour corpora имеют exact post-correctness provenance;
- bottleneck map основан на repeated measurements с uncertainty/unattributed cost;
- specialization boundary имеет explicit decisions для ranked candidates;
- следующий этап не предполагает benefit отдельного runtime без измерений.

Невыполненный criterion остаётся видимым blocker или отдельным roadmap item.

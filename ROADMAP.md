# Bloodborne on shadPS4 correctness + instrumentation

## Goal

Довести Bloodborne на shadPS4 до состояния, в котором correctness достаточно надёжен для profiling, CPU/GPU/memory paths наблюдаемы, baseline/corpora воспроизводимы, реальные bottlenecks измерены, а граница между generic shadPS4 work и Bloodborne-specific specialization определяется evidence.

На этом этапе **не делать отдельный Bloodborne runtime и не оптимизировать игру за счёт неподтверждённых title-specific assumptions**. Минимальные title-specific эксперименты допустимы только для проверки гипотез.

## Execution contract

- Один PR — один primary roadmap item; PR reconciles status/evidence/dependencies/acceptance.
- Investigation заканчивается знанием, decision или negative result; patch не обязателен.
- Implementation не открывается до established semantic seam/compatibility boundary.
- Title-visible symptom ≠ title-specific cause. Build/synthetic checks ≠ Bloodborne target validation.
- Evidence classes: `static`, `runtime`, `synthetic`, `reported`, `assumed`.
- Execution: **CLOUD**, **CLOUD RESEARCH**, **GATED**, **LOCAL ONLY**. `LOCAL ONLY` допустим только после documented feasibility result.
- Gated run должен быть one-shot и выдавать safe self-contained artifact; proprietary executables/assets/private dumps не коммитить.
- Runtime claims фиксируют shadPS4 repo+exact commit+patches, Bloodborne build/content/update/config, host OS/CPU/GPU/driver/backend/config, scenario и tool version.
- Опровергнутые hypotheses и superseded directions сохраняются.

## Ready now

Независимо можно брать: **BB-BL1**, **BB-BL2**, **BB-BL3**. Остальные items имеют явные dependencies.

---

# Milestone 0 — Reproducible baseline

Outcome: source/target/host identities, minimal scenarios и baseline captures сравнимы между runs.

### BB-BL1 — Pin shadPS4 source baseline and integration model
- **Status / priority / execution:** Open / Critical / CLOUD RESEARCH
- **Depends on:** None
- **Question:** Какой exact upstream repo/commit является baseline и как future shadPS4 changes представлены reviewable способом без drift?
- **Next experiment / information gain:** Исследовать upstream workflow; зафиксировать repo+commit, fetch/build provenance и patch/fork/reference model.
- **Acceptance / artifacts:** `docs/baseline/shadps4.md` фиксирует exact baseline, update policy, build provenance и source-change workflow; никаких runtime claims.
- **Scope:** Medium

### BB-BL2 — Define Bloodborne target identity manifest
- **Status / priority / execution:** Open / Critical / CLOUD
- **Depends on:** None
- **Question:** Какие safe identifiers различают materially different Bloodborne baselines?
- **Next experiment / information gain:** Спроектировать minimal machine-readable manifest с synthetic example и licensing/privacy boundary.
- **Acceptance / artifacts:** `docs/baseline/bloodborne.md` + schema/format покрывают build/content/update/config state без proprietary payload.
- **Scope:** Small

### BB-BL3 — Define host/run environment manifest and collector
- **Status / priority / execution:** Open / High / CLOUD
- **Depends on:** None
- **Question:** Как автоматически фиксировать host factors, влияющие на correctness/performance?
- **Next experiment / information gain:** Определить bounded OS/CPU/GPU/driver/backend/emulator-config fields и redaction rules; сделать synthetic-testable collector.
- **Acceptance / artifacts:** `docs/baseline/host-environment.md` + tool/tests выдают stable manifest с explicit unknown fields и без sensitive user data.
- **Scope:** Medium

### BB-BL4 — Select minimal reproducible scenario catalogue
- **Status / priority / execution:** Blocked / Critical / GATED
- **Depends on:** BB-BL1, BB-BL2, BB-BL3
- **Question:** Какие 3–6 коротких scenarios покрывают startup, representative gameplay и correctness/performance-sensitive behavior?
- **Next experiment / information gain:** Подготовить scenario template и выполнить bounded target selection run.
- **Acceptance / artifacts:** `docs/scenarios/` хранит start condition, actions, duration/end condition, expected observable и baseline identity; non-redistributable saves/assets не коммитятся.
- **Scope:** Medium

### BB-BL5 — Build one-shot baseline capture workflow
- **Status / priority / execution:** Blocked / Critical / CLOUD RESEARCH
- **Depends on:** BB-BL1, BB-BL2, BB-BL3
- **Question:** Как одним запуском собирать comparable FPS/frametime/RAM/VRAM/shader-compilation metadata и provenance?
- **Next experiment / information gain:** Инвентаризировать telemetry/signals pinned baseline; сделать bounded collector/packer и явно отмечать unavailable metrics.
- **Acceptance / artifacts:** `tools/` + `docs/experiments/baseline-capture.md`; one command emits safe artifact; overhead measurable.
- **Scope:** Medium

### BB-BL6 — Capture reproducible baseline dataset
- **Status / priority / execution:** Blocked / Critical / GATED
- **Depends on:** BB-BL4, BB-BL5
- **Question:** Каковы baseline distributions и run-to-run variance по selected scenarios?
- **Next experiment / information gain:** Несколько bounded repetitions prepared workflow с exact manifests.
- **Acceptance / artifacts:** `docs/experiments/baseline/` содержит safe derived metrics, provenance, summary statistics, missing-data/overhead notes.
- **Scope:** Medium

---

# Milestone 1 — Correctness inventory

Outcome: каждый актуальный symptom class воспроизводим либо закрыт как stale и имеет evidence-driven generic-vs-specific classification.

### BB-COR1 — Define correctness inventory and triage contract
- **Status / priority / execution:** Blocked / High / CLOUD
- **Depends on:** BB-BL1, BB-BL2, BB-BL3
- **Question:** Как хранить symptom, provenance, evidence class, subsystem hypothesis, reproduction quality и next experiment?
- **Next experiment / information gain:** Schema/template с synthetic examples; `reported` явно отделён от reproduced `runtime`.
- **Acceptance / artifacts:** `docs/correctness/README.md` позволяет добавлять cases без chat context; “generic bug” требует evidence.
- **Scope:** Small

### BB-COR2 — Reproduce graphics/shader/depth/render-target symptoms
- **Status / priority / execution:** Blocked / High / GATED
- **Depends on:** BB-BL6, BB-COR1
- **Question:** Какие rendering/shadow/depth/shader/pipeline symptoms актуальны и при каких resource/state conditions?
- **Next experiment / information gain:** Bounded descriptors/state/events/ID capture, различающий guest semantics, backend translation, sync и stale reports.
- **Acceptance / artifacts:** `docs/experiments/correctness-graphics/` фиксирует reproduced/not-reproduced status, evidence, negative results и next semantic question; proprietary shader payload не коммитится.
- **Scope:** Medium

### BB-COR3 — Reproduce VRAM/resource-lifetime symptoms
- **Status / priority / execution:** Blocked / Critical / GATED
- **Depends on:** BB-BL6, BB-COR1
- **Question:** Есть ли anomalous lifetime/VRAM growth и какие resources/allocations его объясняют?
- **Next experiment / information gain:** Bounded lifetime/allocation capture, различающий leak, delayed destruction, cache/residency, aliasing/reuse и expected workload.
- **Acceptance / artifacts:** `docs/experiments/correctness-resource-lifetime/` содержит timeline/summary и classification confirmed/not reproduced/expected/unknown.
- **Scope:** Medium

### BB-COR4 — Reproduce synchronization/readback symptoms
- **Status / priority / execution:** Blocked / Critical / GATED
- **Depends on:** BB-BL6, BB-COR1
- **Question:** Какие CPU↔GPU waits/readbacks/barriers коррелируют с correctness symptoms или stalls?
- **Next experiment / information gain:** Capture bounded event sequence с resource IDs/timestamps, separating required guest ordering from host over-sync/missing hazards.
- **Acceptance / artifacts:** `docs/experiments/correctness-sync-readback/` документирует sequence, affected resources, waits и competing hypotheses.
- **Scope:** Medium

### BB-COR5 — Reproduce crash/backend/hardware-specific failures
- **Status / priority / execution:** Blocked / Medium / GATED
- **Depends on:** BB-BL6, BB-COR1
- **Question:** Какие reported crashes/backend/hardware failures ещё актуальны и какие environment dimensions меняют result?
- **Next experiment / information gain:** Minimal matrix только для concrete reproduced symptom; classify generic/backend/driver/resource-pressure/stale.
- **Acceptance / artifacts:** `docs/experiments/correctness-compatibility/` фиксирует confirmed/not reproduced/stale/environment-specific cases без broad hardware claims.
- **Scope:** Small

### BB-COR6 — Classify and prioritize confirmed correctness issues
- **Status / priority / execution:** Blocked / Critical / CLOUD
- **Depends on:** BB-COR2, BB-COR3, BB-COR4, BB-COR5
- **Question:** Какие reproduced issues являются generic semantic defects, host/backend defects, title-specific behavior или unresolved?
- **Next experiment / information gain:** Cross-case analysis; объединять issues только при общем подтверждённом seam.
- **Acceptance / artifacts:** `docs/correctness/README.md` содержит ranked set, confidence/evidence class и rationale; FIX items reconciled, новые distinct classes получают отдельные roadmap IDs.
- **Scope:** Small

---

# Milestone 2 — Correctness fixes upstream-first

Outcome: priority defects исправляются только после установленного semantic seam; false premises сохраняются как negative results.

### BB-FIX1 — Establish resource-lifetime semantic seam
- **Status / priority / execution:** Blocked / Critical / CLOUD RESEARCH
- **Depends on:** BB-COR3, BB-COR6
- **Question:** Какой guest/emulator lifetime contract нарушен и где minimal source seam?
- **Next experiment / information gain:** Source tracing + smallest synthetic lifetime fixture; не предполагать architecture заранее.
- **Acceptance / artifacts:** `docs/re/resource-lifetime.md` фиксирует call/resource sequence, expected semantics, source seam и regression plan либо explicit rejected premise.
- **Scope:** Medium

### BB-FIX2 — Implement validated resource-lifetime correction
- **Status / priority / execution:** Blocked / Critical / GATED
- **Depends on:** BB-FIX1
- **Question:** Реализовать established minimal lifetime fix без title-specific semantic weakening.
- **Next experiment / information gain:** Implementation + synthetic regression + exact target scenario validation.
- **Acceptance / artifacts:** Tests + objective target evidence show intended correction без new lifetime/VRAM regression; upstreamability documented.
- **Scope:** Medium

### BB-FIX3 — Establish synchronization/readback semantic seam
- **Status / priority / execution:** Blocked / Critical / CLOUD RESEARCH
- **Depends on:** BB-COR4, BB-COR6
- **Question:** Какой ordering/readback contract требует observed behavior и где implementation diverges/over-synchronizes?
- **Next experiment / information gain:** Source trace + synthetic ordering/hazard fixture.
- **Acceptance / artifacts:** `docs/re/synchronization-readback.md` фиксирует semantic requirement, source seam и regression strategy; expensive sync не считается removable без proof.
- **Scope:** Medium

### BB-FIX4 — Implement validated synchronization/readback correction
- **Status / priority / execution:** Blocked / Critical / GATED
- **Depends on:** BB-FIX3
- **Question:** Реализовать established generic correction и проверить ordering/data visibility.
- **Next experiment / information gain:** Synthetic regression + target event/correctness capture.
- **Acceptance / artifacts:** Tests + target evidence подтверждают correction без unexplained hazards/waits или correctness-for-performance trade.
- **Scope:** Medium

### BB-FIX5 — Establish graphics/shader semantic seam
- **Status / priority / execution:** Blocked / High / CLOUD RESEARCH
- **Depends on:** BB-COR2, BB-COR6
- **Question:** Какой render/depth/shader/pipeline semantic contract объясняет confirmed artifact и где minimal translation/state seam?
- **Next experiment / information gain:** Source tracing + smallest synthetic state/translation fixture.
- **Acceptance / artifacts:** `docs/re/graphics-correctness.md` фиксирует root-cause confidence, source seam, expected behavior и validation plan; no title/resource/shader-ID hardcode.
- **Scope:** Medium

### BB-FIX6 — Implement validated graphics/shader correction
- **Status / priority / execution:** Blocked / High / GATED
- **Depends on:** BB-FIX5
- **Question:** Исправить established generic graphics/shader semantic defect.
- **Next experiment / information gain:** Synthetic state/translation regression + objective target capture.
- **Acceptance / artifacts:** Tests + target pixel/state/event evidence prove correction; formats/layouts/barriers/variants and unaffected paths considered.
- **Scope:** Medium

---

# Milestone 3 — GPU and memory instrumentation

Outcome: bounded tracing восстанавливает resource/access/sync/graphics events and timing, а tracing overhead измерим.

### BB-INS1 — Define trace event model and overhead contract
- **Status / priority / execution:** Blocked / High / CLOUD
- **Depends on:** BB-BL1, BB-BL2, BB-BL3
- **Question:** Какой minimal schema/correlation model покрывает resource, access, sync, graphics and timing без ad-hoc unbounded logs?
- **Next experiment / information gain:** Versioned schema + filtering/sampling controls + synthetic parser fixtures.
- **Acceptance / artifacts:** `docs/instrumentation/schema.md` + tests; no per-draw filesystem I/O/unbounded buffers/private data; overhead plan explicit.
- **Scope:** Medium

### BB-INS2 — Instrument resource mapping/lifetime/access and sync/readbacks
- **Status / priority / execution:** Blocked / High / CLOUD RESEARCH
- **Depends on:** BB-INS1
- **Question:** Где minimal source seams для guest-memory↔host-resource lifetime/access, CPU↔GPU transfers, waits/barriers/readbacks?
- **Next experiment / information gain:** Source tracing + synthetic/unit event prototypes with stable resource correlation.
- **Acceptance / artifacts:** Synthetic fixtures reconstruct create→access→destroy and sync/readback sequences; disabled-by-default diagnostic mode; `docs/instrumentation/resources-sync.md`.
- **Scope:** Medium

### BB-INS3 — Instrument render/depth/shader/pipeline identity and timing
- **Status / priority / execution:** Blocked / High / CLOUD RESEARCH
- **Depends on:** BB-INS1
- **Question:** Как correlate render/depth resources with safe shader/pipeline IDs, creation/cache events and coarse CPU/GPU timings?
- **Next experiment / information gain:** Source lifecycle tracing + stable ID/timing prototype + synthetic variant fixtures.
- **Acceptance / artifacts:** Deterministic synthetic correlation, bounded descriptors, no proprietary shader payload; `docs/instrumentation/graphics-timing.md`.
- **Scope:** Medium

### BB-INS4 — Validate instrumentation coverage and overhead on target
- **Status / priority / execution:** Blocked / Critical / GATED
- **Depends on:** BB-BL4, BB-INS2, BB-INS3
- **Question:** Достаточны ли events для reconstruction и каков measured overhead on representative scenarios?
- **Next experiment / information gain:** Tracing off/on one-shot captures with bounded event volume.
- **Acceptance / artifacts:** `docs/experiments/instrumentation-validation/` records correlation completeness, overhead distribution and missing probes; large raw captures externalized.
- **Scope:** Medium

---

# Milestone 4 — Shader and pipeline corpus

Outcome: actual shader/pipeline workload, variants, cache behavior и prewarming opportunity основаны на captures.

### BB-SHD1 — Define shader/pipeline corpus identity and storage
- **Status / priority / execution:** Blocked / Medium / CLOUD
- **Depends on:** BB-INS3
- **Question:** Какие safe IDs/metadata позволяют deduplicate guest shader identity, translated variants and pipelines across runs?
- **Next experiment / information gain:** Versioned corpus schema + synthetic merge/dedup fixtures.
- **Acceptance / artifacts:** `docs/corpus/shaders.md` + schema/tools preserve variant/baseline boundaries без proprietary payload redistribution.
- **Scope:** Small

### BB-SHD2 — Capture representative shader/pipeline corpus
- **Status / priority / execution:** Blocked / Medium / GATED
- **Depends on:** BB-INS4, BB-SHD1
- **Question:** Какой shader/pipeline set реально используется selected scenarios и насколько он стабилен between runs?
- **Next experiment / information gain:** Repeated bounded corpus captures across scenario catalogue.
- **Acceptance / artifacts:** `docs/experiments/shader-corpus/` + safe deduplicated index, run coverage and stability summary tied to exact baseline.
- **Scope:** Medium

### BB-SHD3 — Analyze variants/cache and prewarming feasibility
- **Status / priority / execution:** Blocked / Medium / CLOUD RESEARCH
- **Depends on:** BB-SHD2
- **Question:** Сколько translation/pipeline work происходит, каков cache behavior и есть ли evidence для pretranslation/prewarming?
- **Next experiment / information gain:** Offline counts/correlation; если benefit hypothesis survives, подготовить controlled A/B target experiment.
- **Acceptance / artifacts:** `docs/analysis/shader-pipeline-workload.md` documents distributions, cache effects, uncertainty and go/no-go for separate feasibility/optimization item.
- **Scope:** Medium

---

# Milestone 5 — Resource behaviour corpus

Outcome: actual resource lifetime/access classes превращены в conditional evidence-backed invariants.

### BB-RES1 — Define resource classification and invariant extraction
- **Status / priority / execution:** Blocked / Medium / CLOUD
- **Depends on:** BB-INS2
- **Question:** Как classify upload→GPU-only, transient, readback, aliasing, persistent and sync-heavy resources reproducibly?
- **Next experiment / information gain:** Rule-based schema/classifier + synthetic traces including ambiguous cases.
- **Acceptance / artifacts:** `docs/corpus/resources.md` + parser/tests classify fixtures and preserve unknown/ambiguous state; classification не объявляется semantic fact.
- **Scope:** Medium

### BB-RES2 — Capture representative resource traces
- **Status / priority / execution:** Blocked / Medium / GATED
- **Depends on:** BB-INS4, BB-RES1
- **Question:** Какие lifetime/access patterns реально встречаются и насколько repeatable их classes?
- **Next experiment / information gain:** Repeated bounded traces over scenario catalogue.
- **Acceptance / artifacts:** `docs/experiments/resource-corpus/` records completeness/correlation and safe summaries; no resource contents unless separately justified.
- **Scope:** Medium

### BB-RES3 — Derive and validate candidate resource invariants
- **Status / priority / execution:** Blocked / Medium / CLOUD RESEARCH
- **Depends on:** BB-RES2, BB-BL4
- **Question:** Какие patterns repeat enough to be conditional invariants, какие are outliers, и какой scope survives scenario/config changes?
- **Next experiment / information gain:** Offline clustering/counterexamples; prepare minimal discriminating target matrix for high-value candidates.
- **Acceptance / artifacts:** `docs/analysis/resource-invariants.md` stores support, conditions, counterexamples/rejections and go/no-go for any guarded fast-path item.
- **Scope:** Medium

---

# Milestone 6 — Performance bottleneck map

Outcome: cost attribution rank-ит 3–5 real opportunities с explicit uncertainty, unattributed time и instrumentation overhead.

### BB-PERF1 — Define attribution model and collect representative timing data
- **Status / priority / execution:** Blocked / High / CLOUD RESEARCH
- **Depends on:** BB-INS4, BB-SHD3, BB-RES3
- **Question:** Как разделить guest CPU, HLE/syscalls, command processing, translation, pipeline creation, sync, transfers, resource management and actual GPU workload без double counting?
- **Next experiment / information gain:** Synthetic accounting with explicit unattributed bucket, затем prepared repeated target captures across scenarios/warm-cold states.
- **Acceptance / artifacts:** `docs/performance/attribution-model.md` + `docs/experiments/performance-datasets/` define non-overlapping accounting, variance, overhead and provenance.
- **Scope:** Medium

### BB-PERF2 — Build ranked bottleneck map
- **Status / priority / execution:** Blocked / High / CLOUD
- **Depends on:** BB-PERF1
- **Question:** Какие 3–5 cost classes имеют largest measured optimization potential и sufficient confidence?
- **Next experiment / information gain:** Cross-scenario ranking with uncertainty/overhead sensitivity; “no meaningful headroom” is valid result.
- **Acceptance / artifacts:** `docs/performance/bottleneck-map.md` gives contribution/range, confidence, constraints and creates bounded feasibility items only for evidence-backed candidates.
- **Scope:** Medium

---

# Milestone 7 — Specialization boundary

Outcome: next-stage scope выбирается evidence, а не предположением о необходимости specialized runtime.

### BB-SPEC1 — Decide specialization boundary and next-stage plan
- **Status / priority / execution:** Blocked / Medium / CLOUD
- **Depends on:** BB-PERF2
- **Question:** Для ranked candidates: generic correctness, generic fast path, guarded Bloodborne optimization, future runtime или reject; выполнены ли exit criteria?
- **Next experiment / information gain:** Decision matrix using measured benefit, semantic assumptions, guardability, maintenance cost and upstream fit; reconcile remaining correctness/corpus gaps.
- **Compatibility / safety:** Title-specific assumption requires explicit guard and validated scope; unresolved correctness blocks aggressive specialization.
- **Acceptance / artifacts:** `docs/architecture/specialization-boundary.md` + `docs/architecture/next-stage-plan.md` record decisions, evidence, risks/rejected alternatives and explicit go/no-go, включая valid “no separate runtime” outcome.
- **Scope:** Medium

---

# Exit criteria

Этап завершён только когда:

- source/target/host baselines и scenarios воспроизводимы;
- key correctness issues fixed/verified либо локализованы с documented blocker;
- instrumentation traces main GPU/memory/resource/sync/shader paths и имеет measured overhead;
- shader/pipeline и resource-behaviour corpora имеют exact provenance;
- bottleneck map основан на repeated measurements с uncertainty/unattributed cost;
- specialization boundary имеет explicit decisions для ranked candidates;
- следующий этап не предполагает benefit отдельного runtime без измерений.

Невыполненный criterion остаётся видимым blocker или отдельным roadmap item.

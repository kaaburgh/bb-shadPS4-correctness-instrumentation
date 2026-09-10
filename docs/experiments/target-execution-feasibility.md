# Target execution: exploration and opt-in verification

## Current decision and evidence

Exploration is the default. BB-ENV1 is a capability/verification item, not
permission to launch Bloodborne, try candidate gameplay scenarios, instrument,
test hypotheses or run dirty local patches. It remains **Implemented, validation
incomplete**: the supported source-built attempt on 2026-09-09 passed strict
admission and target pre/post verification but timed out after 30 seconds, with
oracle `unknown`. Preserve that negative result and the exact provenance in
[the source-first experiment](env1-source-first-2026-09-09.md). A successful
verification run and resolution of material host/config unknowns are still needed
for ENV1 completion; no gameplay/menu checkpoint is required for this item.

The original synthetic-only repository observation did not establish the absence
of target-owning machines. PR #128 found an Ubuntu route and HTTP 410 for the old
Linux CI artifact. The historical `28c84fb` workflow `31742892228`, Windows
artifact `9198403207` and Linux artifact `9198177755` are no longer execution
dependencies. Neither arbitrary binary hashes nor unchecked patch declarations
are a replacement for strict source-build verification.

## Default exploratory procedure

Use [`tools/run_target_experiment.py`](../../tools/run_target_experiment.py).
The v3-named internal engine remains unsupported as a direct CLI. Reuse the
existing durable checkout, out-of-tree build, dependency/compiler caches and
binary; dirty/uncommitted instrumentation is allowed. See the
[persistent incremental build default](../baseline/source-builds.md).

The active node target is the EU `CUSA03173` view recorded in
[`bloodborne-target-1.09.json`](../baseline/bloodborne-target-1.09.json): retain
the existing base component at `01.00` together with the sibling
`CUSA03173-UPDATE` component at effective `01.09`. Launch the base path so the
pinned shadPS4 overlay mechanism supplies the update; do not launch the update
directory as a separate game or copy its files into the base. This view is
reusable between exploratory runs and does not require another full target copy.

Original operator-owned game/package inputs stay immutable. Once, prepare a
separate verified disposable target working copy with no links to originals.
[`prepare_env1_target_copy.py`](../../tools/prepare_env1_target_copy.py) accepts
an explicit base app tree and, when the target manifest says an update is
installed, an explicit update tree as well. Supply independent
digest/count/size values for both components. The helper copies the base to
`app` and the update to its shadPS4-native `app-UPDATE` sibling; it never merges
update files into the base. It reads original and copy trees independently,
then writes the private `.bb-env1-disposable-copy.json` receipt inside the
destination. The v2 receipt binds `root`, `app`, and `app-UPDATE` directory
identity and records the one-time resolved app-tree identity.

Exploration requires the receipt and, for an installed update, requires that
v2 sibling binding and compares its recorded resolved tree with the target
manifest before execution; it does not rehash the target on every run. For a
pre-receipt copy, run the helper once with the same base flags plus
`--update-source`, `--update-expected-sha256`, `--update-expected-file-count`,
`--update-expected-total-bytes`, and `--verify-existing`. This can add the
update sibling to an unchanged existing disposable base without recopying its
30+ GB `app` tree. A changed app or mismatching update cannot acquire a receipt
through this migration; retain it and prepare a separate verified copy instead.
Moving/replacing a receipted directory invalidates its receipt. Never manually
mint or copy a receipt onto original inputs.

Reuse that copy, profile/cache state
and a separate writable working directory between exploratory runs. Do not make
a full new copy or hash the complete tree before and after every experiment
unless the hypothesis requires it. The runner does not sandbox writes: never
point `--target-root` or writable command inputs at original evidence.

Prepare a private command JSON with `argv[0]` naming the existing regular non-link
binary and a target argument pointing to the disposable copy's `app` or
`app/eboot.bin`, using the existing command schema. The `app-UPDATE` sibling
must remain beside that `app` for every run. Run a bounded scenario:

```text
python3 tools/run_target_experiment.py run \
  --target-manifest <existing-BB-BL2-manifest.json> \
  --scenario <bounded-scenario.json> \
  --command-file <private-command.json> \
  --emulator-binary <existing-binary> \
  --target-root <reusable-disposable-target-tree> \
  --working-directory <existing-separate-working-directory> \
  --backend vulkan \
  --output <safe-output-directory>/run-<unique-id>.zip
```

No `--build-manifest`, clean live `--source-checkout`, declared source commit/tree
or precomputed binary hash is required. Optional `--source-*` and `--patch-commit`
fields are unverified declarations only, stored as `emulator.source_observation`;
missing identity is `null`. `--source-checkout` alone is permitted, including dirty
state, but is not inspected or used to infer a source-to-binary relationship.
The runner observes actual binary SHA-256/size immediately before launch. An
optional `--emulator-binary-sha256` is a byte-integrity assertion and must match;
it does not confer verified provenance. The binary runs in place so relative
runtime libraries/assets from existing builds remain available. Full target
pre/post hashing is skipped and explicitly recorded as `not_checked`; the prior
manifest is a reference, with current target identity `unverified`.

Non-synthetic exploratory records are always `exploratory-unverified`, even when
the process/file oracle passes and packaging is complete. Fully synthetic
controls retain their identity-checking regression path and are separately
classified `synthetic-control`; they never prove proprietary-target behavior.

Reuse previous captures, logs and generated artifacts for investigation. Give
newly declared oracle/artifact outputs fresh names: those paths still must not
pre-exist, so stale bytes cannot masquerade as current-run production. Existing
unrelated outputs and working state are allowed. Exploratory file hashes and
allowlisted artifacts are observations without producer/semantic attestation.

`--emulator-config` remains unsupported because the actual pinned emulator CLI
has no explicit config-file path binding. Reusing its existing profile or using
real supported argv flags is allowed in exploration; do not assert consumed
configuration identity from a backend label or a file hash alone.

## Opt-in strict verification/promotion candidate

Supply both `--build-manifest <private-build-manifest.json>` and
`--source-checkout <exact-clean-checkout>`, plus the exact manifest source base
repository/commit/tree, ordered `--patch-commit` list and binary digest. A supplied
manifest never falls back to exploration on error. Strict #130 semantics remain:

- `shadps4_build_manifest.py build` requires a fresh out-of-tree build directory,
  clean exact source/submodules, observed configure/build and pre/post checks;
- exact commit **and** tree, public patch repository, complete single-parent
  linear chain and effective HEAD/tree are independently checked against Git;
- shallow top-level history, replacements, grafts, hidden index flags, dirty
  source (including ignored/untracked inputs), omitted/reordered/duplicate/merge
  patch commits and submodule drift fail closed;
- the runner snapshots inputs, privately stages the regular executable and
  verifies its digest/size against the manifest and caller digest; the engine
  repeats byte verification before launch. Staging must permit execution;
- full target identity is verified pre-run and rechecked post-run. A changed or
  unverifiable target preserves the record with partial packaging and a warning;
- non-synthetic strict candidates accept only `process-exit` and no declared
  artifacts until independent current-run producer attestation is implemented.

The strict tool, schema and tests remain the promotion mechanism; there is no
retrospective “bless this binary” command. Fresh strict builds are for promotion,
explicit reproducibility verification or concrete stale/corrupt-build suspicion,
not every failed/intermediate experiment. Existing valid strict build manifests
and unchanged verified binaries can also be reused without another fresh build.

## Records and promotion boundary

The runner emits [`bb-target-run` schema v4](../../schemas/target-run.schema.json)
with producer `bb-target-runner/1.13.1`. The schema requires matching run
classification, target evidence classes and emulator admission. Synthetic leaf
or top-level target evidence remains `synthetic-control` with a strict build.
Exploratory records cannot contain
`source` or `build_provenance`; strict records require source/build agreement.
The v4 compatibility boundary makes old consumers fail closed. Historical v3
records remain historical evidence with their original limitations; do not relabel
them or fabricate v4 fields to pass a gate. Pre-review v4 records from 1.13.0
lack the required target evidence-class projection and also fail closed; do not
backfill their summaries to obtain promotion admission.

```text
python3 tools/run_target_experiment.py validate <run-manifest.json>
python3 tools/run_target_experiment.py validate <run-manifest.json> --require-promotion
```

The first command checks format and internal agreement only. The second also
rejects exploratory/synthetic records, incomplete target identity, unchecked
or changed trees, failed/unknown termination or oracle, and partial packaging.
Aggregate host unknown/warning counts are retained, but are not a generic gate:
non-material or unavailable optional fields do not invalidate bounded evidence.
Its success is necessary, not sufficient: a reviewer must resolve material host
unknowns and establish consumed
configuration and an independent semantic oracle appropriate to the promoted
claim. A `verification-candidate` or passed process-exit oracle proves neither
menu/gameplay nor graphics correctness nor performance. Missing promotion-grade
provenance blocks promotion of a claim, never ordinary exploration.

The reusable disposable-route exploratory launch recorded in
[`bloodborne-1.09-exploratory-launch.md`](./bloodborne-1.09-exploratory-launch.md)
was admitted through the v2 receipt with its `app-UPDATE` sibling and matching
resolved-tree identity. The existing AppImage then reported `Game id:
CUSA03173` and `App Version: 01.09` after Vulkan and Bloodborne
resource/pipeline initialization. The safe runner record was complete but timed
out as exploratory evidence. This is launch/liveness evidence only; it is not a
semantic checkpoint, correctness evidence, or ENV1 completion record.

Full manifests are maintainer-owned local build observations, not signed
third-party attestations or protection against deliberate forgery. Detached
validation cannot independently re-prove Git ancestry without its checkout.

## Bounds, privacy and isolation in both paths

Commands run with `shell=False`, closed stdin, bounded output drains and timeout.
Windows uses a kill-on-close Job Object; Linux uses a process group and subreaper
with exception-safe descendant teardown. Other POSIX hosts currently fail closed
because that containment capability is not implemented. Target and working trees
are separate; output ZIPs must be outside both. This separation does not require
fresh directories. The runner snapshots target/scenario/command inputs and binds
the final command digest to the original command bytes, not temporary paths.

Safe ZIPs contain the run record, safe target and scenario projections, host
manifest and explicitly allowlisted redacted artifacts. Raw process output,
commands, config contents, emulator/target bytes and opaque captures are excluded.
DLC keys remain hashed; free-form versions are redacted. There is no same-user
adversary or sealed-executable claim. Preserve safe negative records without
representing reused or changed state as a verified current baseline.

The structured recorded-experiment runner still requires command/scenario JSON, a
target manifest and a fresh declared output path. PR #131 review identified a
possible thinner exploratory invocation as a nonblocking follow-up: measure
actual operator friction before adding another interface.

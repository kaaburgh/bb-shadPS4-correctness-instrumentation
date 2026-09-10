# Bloodborne 1.09 exploratory launch

## Evidence boundary

This note records one bounded runtime launch against the active target manifest
[`bloodborne-target-1.09.json`](../baseline/bloodborne-target-1.09.json). It is
an exploratory launch check, not a semantic gameplay or correctness result and
not a BB-ENV1 one-shot runner record.

## Inputs

- Target: EU `CUSA03173`, base component `01.00` plus sibling `-UPDATE` component
  `01.09`; no DLC or target modifications. The reusable disposable root has
  independent `app` and `app-UPDATE` directories with a v2 copy receipt.
- Emulator: existing SDL AppImage labeled `v0.18.0`, SHA-256
  `70693665d2aed2281bd86b0b727eb1174328d09b5e0e9b7d1c9212f8fc598d0f`,
  35,326,456 bytes.
- Source identity reported by the emulator: upstream
  `shadps4-emu/shadPS4`, commit
  `e3ce810f3a653f43ac64ebab63023de281a4103a`, patches `none`.
- Configuration: existing node configuration, `Game-specific config used:
  false`, Vulkan backend, automatic game-patch loading enabled.
- Bound: 55 seconds, launched with the reusable disposable `app` path and no
  memory patch argument.

## Result

The emulator reported `v0.18.0`, revision `e3ce810f3a653f43ac64ebab63023de281a4103a`,
`Game id: CUSA03173`, and `App Version: 01.09`. It initialized the Vulkan
instance/device and reached Bloodborne file loads and graphics-pipeline
compilation. The process ended with the intentional timeout after the bounded
observation window; no launch failure was observed before timeout.

The base/update directories and both operator-owned PKG inputs retained their
pre-launch identities. That original direct probe created no copy. Ordinary
exploratory runs should use the reusable disposable `app`/`app-UPDATE` root
described below, together with the existing shadPS4 AppImage, user
configuration, and generated mutable user data.

## Reusable disposable-route follow-up

After review, the existing node did not contain a receipted disposable target,
so one reusable copy was prepared once from the immutable base and update
directories. Its private receipt records these payload-free identities:

- base: `sha256-tree-v1`, `212a0643e0506f1d863f33ae761d41710fe0a746a26a15a95ff0fe0777b719c3`, 28,831 files;
- update sibling: `76db55ecdbe29257a7dd30eace70834cafb634d3d311d8c3d3101801f7c45648`, 440 files;
- resolved app view: `743bd38658fcb96fbf9418386e2eb2dcc63fd1c7408c59afd30e5aef726b55b8`, 28,849 files.

The supported `tools/run_target_experiment.py` entrypoint then launched the
existing pinned AppImage through that reusable root. The safe run artifact was
complete and classified `exploratory-unverified`; the bounded 55-second run
timed out with `oracle=unknown`, preserving the prior liveness limitation. A
runtime probe using the same disposable `app` path reported `Game id:
CUSA03173` and `App Version: 01.09`. No semantic gameplay or correctness claim
is made.

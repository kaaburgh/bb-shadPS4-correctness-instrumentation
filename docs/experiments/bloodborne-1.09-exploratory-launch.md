# Bloodborne 1.09 exploratory launch

## Evidence boundary

This note records one bounded runtime launch against the active target manifest
[`bloodborne-target-1.09.json`](../baseline/bloodborne-target-1.09.json). It is
an exploratory launch check, not a semantic gameplay or correctness result and
not a BB-ENV1 one-shot runner record.

## Inputs

- Target: EU `CUSA03173`, base component `01.00` plus sibling `-UPDATE` component
  `01.09`; no DLC or target modifications.
- Emulator: existing SDL AppImage labeled `v0.18.0`, SHA-256
  `70693665d2aed2281bd86b0b727eb1174328d09b5e0e9b7d1c9212f8fc598d0f`,
  35,326,456 bytes.
- Source identity reported by the emulator: upstream
  `shadps4-emu/shadPS4`, commit
  `e3ce810f3a653f43ac64ebab63023de281a4103a`, patches `none`.
- Configuration: existing node configuration, `Game-specific config used:
  false`, Vulkan backend, automatic game-patch loading enabled.
- Bound: 55 seconds, launched with the existing base game path and no memory
  patch argument.

## Result

The emulator reported `v0.18.0`, revision `e3ce810f3a653f43ac64ebab63023de281a4103a`,
`Game id: CUSA03173`, and `App Version: 01.09`. It initialized the Vulkan
instance/device and reached Bloodborne file loads and graphics-pipeline
compilation. The process ended with the intentional timeout after the bounded
observation window; no launch failure was observed before timeout.

The base/update directories and both operator-owned PKG inputs retained their
pre-launch identities. No new full game copy was created. Ordinary exploratory
runs can reuse the same base directory, `CUSA03173-UPDATE` overlay, existing
shadPS4 AppImage, user configuration, and generated mutable user data.

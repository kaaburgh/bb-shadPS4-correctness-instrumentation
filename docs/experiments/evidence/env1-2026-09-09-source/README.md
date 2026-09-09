# BB-ENV1 source-build attempt — 2026-09-09

These four JSON entries are byte-for-byte extractions from the supported runner's
metadata-only ZIP: `run-manifest.json`, `target-manifest.json`,
`host-environment.json`, `scenario.json`. The ZIP itself is retained privately.
All four schemas and the entry hashes/sizes in the run record were checked.
The transfer projection was also scanned for private host paths.

- Original ZIP SHA-256: `e0f0f0b3eb03957fd92971f710b73f5fb7db6d0eede8908ca4009b0fad68ff0e`; size 8,114 bytes.
- Source/build producer: repository commit `17bbe02`; the manifest projection
  contains its exact file hash and the private manifest's digest and size.
- Execution: 30-second deadline; `timed_out`, exit `-15`, elapsed 34.064 seconds
  including teardown; process-exit oracle `unknown`; packaging `complete`.
- Target tree was verified before and after execution. A post-run process check
  found no remaining shadPS4 process.
- `target-copy.json` independently records original pre/post and disposable-copy
  hashing, with its producer hash. It is preparation evidence outside the ZIP.
- `gpu-observation.json` is an adjacent independent host inventory observation,
  with exact query, executable/output hashes and timestamp. It supplies the GPU
  name/driver version that the existing run collector leaves explicitly unknown;
  the original host record was not rewritten. OS build and emulator-config hash
  also remain unknown in that record; clean-profile CLI settings are documented
  in the linked experiment, and explicit config admission remains gated.

This is real source-build admission and bounded-execution failure evidence,
not a successful ENV1 termination oracle, guest checkpoint or correctness result.
No target payload, executable, raw process log, command, save or config is included.
See [the experiment](../../env1-source-first-2026-09-09.md) for preparation,
baselines, toolchain settings and remaining gates.

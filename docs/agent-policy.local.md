## Project-specific baseline identity

Any correctness, profiling, or performance claim must identify the relevant baseline precisely enough to reproduce and compare it:

1. **shadPS4 source baseline** — upstream repository, exact commit SHA, and relevant local patches;
2. **Bloodborne target baseline** — game version/build, content/update identity, and relevant configuration or mod state;
3. **host execution environment** — OS, CPU, GPU, GPU driver, graphics backend, and relevant emulator configuration.

Do not compare captures, benchmarks, or correctness observations across materially different baselines without recording the difference explicitly.

## agentic-repo-kit artifact and check procedure

Use the `tool_version` in `.agentic-repo.lock.json` as the source of truth for normal contract checks; do not silently substitute `latest`. Follow `docs/agentic-repo-kit.md` to obtain the matching versioned GitHub Release artifact, verify it, and run `agentic-repo check`.

If the current environment cannot read the private `kaaburgh/agentic-repo-kit` release, request the matching versioned archive plus `SHA256SUMS` from the operator and continue independent work. Lack of direct release access in one sandbox is an environment acquisition constraint, not evidence that repository validation is impossible.

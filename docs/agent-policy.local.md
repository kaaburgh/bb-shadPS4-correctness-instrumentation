## Project-specific baseline identity

Any correctness, profiling, or performance claim must identify the relevant baseline precisely enough to reproduce and compare it:

1. **shadPS4 source baseline** — upstream repository, exact commit SHA, and relevant local patches;
2. **Bloodborne target baseline** — game version/build, content/update identity, and relevant configuration or mod state;
3. **host execution environment** — OS, CPU, GPU, GPU driver, graphics backend, and relevant emulator configuration.

Do not compare captures, benchmarks, or correctness observations across materially different baselines without recording the difference explicitly.

## agentic-repo-kit artifact and check procedure

Use `tool_version` and `distribution` in `.agentic-repo.lock.json` as the source of truth for normal contract checks; do not silently substitute `latest`. Follow `docs/agentic-repo-kit.md` to obtain the exact public `.pyz` named by the lock, verify its SHA-256 against `distribution.sha256`, and run `check`.

If the current environment cannot download the public release because of network/egress or platform constraints, request the exact `.pyz` artifact named in the lock from the operator. Verify the supplied bytes against the digest already committed in the lock before execution. A separately supplied checksum is not required for trust because the expected digest is already part of repository state. Lack of direct artifact access in one sandbox is an environment acquisition constraint, not evidence that repository validation is impossible.

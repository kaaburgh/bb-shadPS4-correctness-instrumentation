from pathlib import Path

Path('docs/agent-policy.local.md').write_text('''## Project-specific baseline identity

Any correctness, profiling, or performance claim must identify the relevant baseline precisely enough to reproduce and compare it:

1. **shadPS4 source baseline** — upstream repository, exact commit SHA, and relevant local patches;
2. **Bloodborne target baseline** — game version/build, content/update identity, and relevant configuration or mod state;
3. **host execution environment** — OS, CPU, GPU, GPU driver, graphics backend, and relevant emulator configuration.

Do not compare captures, benchmarks, or correctness observations across materially different baselines without recording the difference explicitly.

## agentic-repo-kit artifact and check procedure

Use `tool_version` and `distribution` in `.agentic-repo.lock.json` as the source of truth for normal contract checks; do not silently substitute `latest`. Follow `docs/agentic-repo-kit.md` to obtain the exact public `.pyz` named by the lock, verify its SHA-256 against `distribution.sha256`, and run `check`.

If the current environment cannot download the public release because of network/egress or platform constraints, request the exact `.pyz` artifact named in the lock from the operator. Verify the supplied bytes against the digest already committed in the lock before execution. A separately supplied checksum is not required for trust because the expected digest is already part of repository state. Lack of direct artifact access in one sandbox is an environment acquisition constraint, not evidence that repository validation is impossible.
''', encoding='utf-8')

Path('docs/agentic-repo-kit.md').write_text('''# agentic-repo-kit artifact and contract checks

This repository uses `agentic-repo-kit` generated policy plus a versioned executable checker. Normal validation is pinned entirely by `.agentic-repo.lock.json`.

## Source of truth

Lock format 2 records both the tool version and the exact executable distribution:

- `distribution.repository` — public GitHub repository;
- `distribution.release` — exact release tag;
- `distribution.artifact` — exact `.pyz` file name;
- `distribution.sha256` — expected artifact digest.

Do not substitute `latest`, another tag, another artifact, or a checksum obtained only alongside an untrusted artifact.

## Obtain and verify the pinned artifact

The canonical artifact is published in the public `kaaburgh/agentic-repo-kit` GitHub Release named by the lock. A normal shell flow is:

```bash
readarray -t KIT < <(python - <<'PY'
import json
from pathlib import Path
lock = json.loads(Path('.agentic-repo.lock.json').read_text(encoding='utf-8'))
d = lock['distribution']
print(d['repository'])
print(d['release'])
print(d['artifact'])
print(d['sha256'])
PY
)

KIT_REPOSITORY="${KIT[0]}"
KIT_RELEASE="${KIT[1]}"
KIT_ARTIFACT="${KIT[2]}"
KIT_SHA256="${KIT[3]}"
KIT_PATH="${RUNNER_TEMP:-/tmp}/$KIT_ARTIFACT"
KIT_URL="https://github.com/$KIT_REPOSITORY/releases/download/$KIT_RELEASE/$KIT_ARTIFACT"

curl --fail --location --proto '=https' --tlsv1.2 \
  --output "$KIT_PATH" "$KIT_URL"

actual="$(sha256sum "$KIT_PATH" | awk '{print $1}')"
test "$actual" = "$KIT_SHA256"
```

For the current lock this resolves to `agentic-repo-kit-0.1.9.pyz`. The repository does not need a cross-repository secret because the kit repository and releases are public.

If the environment cannot reach GitHub, an operator may provide only the exact `.pyz` named in the lock. Compute its SHA-256 locally and compare it with `distribution.sha256`; the committed lock is the trust anchor. `SHA256SUMS` published with the kit release is useful as an independent release-level cross-check, but it is not required for the consumer check path.

## Run `check`

After verification:

```bash
python "$KIT_PATH" check .
```

Success prints:

```text
agentic repository contract is consistent
```

The command re-renders managed outputs from `.agentic-repo.toml` plus local inputs, compares generated files byte-for-byte, validates the normalized roadmap's mechanical dependency graph, and checks relative Markdown links.

The managed `.github/workflows/agentic-repo-check.yml` performs this same acquisition, digest verification, and check automatically on pull requests and pushes.

## Upgrade to a newer kit version

An intentional upgrade starts with a selected newer public release, before the consumer lock can contain that newer digest. Verify the chosen release artifact using its release provenance (for example the release `SHA256SUMS`), then run the newer executable:

```bash
python /path/to/verified/agentic-repo-kit-NEW.pyz upgrade .
python /path/to/verified/agentic-repo-kit-NEW.pyz check .
```

`upgrade` atomically writes the new `tool_version`, distribution coordinates/digest, and managed output hashes into the lock. Review and commit that managed diff. Future normal checks then trust the newly committed lock digest.

Do not hand-edit generated files to imitate an upgrade. Project-specific policy belongs in configured local inputs such as `docs/agent-policy.local.md`.
''', encoding='utf-8')

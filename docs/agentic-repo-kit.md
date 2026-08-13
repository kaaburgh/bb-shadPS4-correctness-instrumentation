# agentic-repo-kit artifact and contract checks

This repository uses `agentic-repo-kit` generated files. The generated policy is self-contained for agents to read, but `check` and `upgrade` execute the kit's Python code.

## Version source of truth

For a normal drift/consistency check, read `tool_version` from `.agentic-repo.lock.json` and use exactly that tool version. Do not use `latest` implicitly.

The current pinned version after this upgrade is `0.1.7`.

## Obtain the pinned artifact

Versioned source artifacts are published in the private `kaaburgh/agentic-repo-kit` repository under GitHub Releases:

`https://github.com/kaaburgh/agentic-repo-kit/releases/tag/v<VERSION>`

Each release contains:

- `agentic-repo-kit-<VERSION>.tar.gz`
- `agentic-repo-kit-<VERSION>.zip`
- `SHA256SUMS`

An authenticated operator/environment with read access can fetch the pinned release with GitHub CLI:

```bash
KIT_VERSION="$(python - <<'PY'
import json
from pathlib import Path
print(json.loads(Path(".agentic-repo.lock.json").read_text())["tool_version"])
PY
)"

KIT_DL="${RUNNER_TEMP:-/tmp}/agentic-repo-kit-$KIT_VERSION"
mkdir -p "$KIT_DL"

gh release download "v$KIT_VERSION" \
  --repo kaaburgh/agentic-repo-kit \
  --pattern "agentic-repo-kit-$KIT_VERSION.tar.gz" \
  --pattern "agentic-repo-kit-$KIT_VERSION.zip" \
  --pattern SHA256SUMS \
  --dir "$KIT_DL"

(
  cd "$KIT_DL"
  sha256sum -c SHA256SUMS
)
```

For GitHub Actions in this public repository, the repository's ordinary `GITHUB_TOKEN` does not grant read access to the separate private kit repository. Set `GH_TOKEN` to a narrowly scoped credential that can read `kaaburgh/agentic-repo-kit`, or have an operator/cache provide the three release assets to the job.

If the agent environment has restricted egress or cannot authenticate to the private kit repository, the operator may supply the matching release archive and `SHA256SUMS` directly. Verify the supplied artifact before executing it.

For reference, release `v0.1.7` publishes:

- `agentic-repo-kit-0.1.7.tar.gz` — SHA-256 `e9c1d65ea2ee656de422951451da71d1606b5b32534c5042308ff6c360ab4e37`
- `agentic-repo-kit-0.1.7.zip` — SHA-256 `57278017939c694cd86f18fc03091ed450dc814b7374cffd8b5ac25c2a9b88ab`

The release-provided `SHA256SUMS` remains the primary verification input; the values above are a pinned cross-check for the current repository version.

## Run `check` without installing from a package registry

The release archives have a top-level directory `agentic-repo-kit-<VERSION>/`. Extract one archive and point `PYTHONPATH` at that directory:

```bash
tar -xzf "$KIT_DL/agentic-repo-kit-$KIT_VERSION.tar.gz" -C "$KIT_DL"
KIT_ROOT="$KIT_DL/agentic-repo-kit-$KIT_VERSION"

PYTHONPATH="$KIT_ROOT" python -m agentic_repo_kit check .
```

A successful check prints:

```text
agentic repository contract is consistent
```

The command re-renders the managed contract from `.agentic-repo.toml` plus local inputs, compares generated files byte-for-byte, checks the normalized roadmap's mechanical dependency graph, and validates relative Markdown links.

## Upgrade to a newer kit release

An upgrade intentionally uses the selected new release rather than the old `tool_version` from the lock:

1. choose and obtain the exact target release;
2. verify its `SHA256SUMS`;
3. extract it;
4. run `upgrade`;
5. review the managed diff;
6. run `check` with the same extracted kit version;
7. commit the updated managed files and lock.

Example:

```bash
NEW_VERSION="0.1.7"
KIT_ROOT="/path/to/verified/agentic-repo-kit-$NEW_VERSION"

PYTHONPATH="$KIT_ROOT" python -m agentic_repo_kit upgrade .
PYTHONPATH="$KIT_ROOT" python -m agentic_repo_kit check .
```

Do not hand-edit generated files to imitate an upgrade. Project-specific policy belongs in the configured local inputs such as `docs/agent-policy.local.md`.

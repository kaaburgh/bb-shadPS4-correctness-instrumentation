# Bloodborne target identity manifest

BB-BL2 defines a versioned, payload-free identity for the Bloodborne side of a reproducible run. The manifest records enough information to distinguish materially different game builds, installed content/update states, and target-visible configuration or modifications without committing game data.

The machine-readable contract is [JSON Schema draft 2020-12](../../schemas/bloodborne-target-manifest.schema.json). A fully synthetic, non-target example is [included here](./examples/bloodborne-target-manifest.synthetic.json).

## Identity boundary

The manifest describes the guest/title inputs only. The shadPS4 repository, commit, and patches belong to BB-BL1. Host OS, CPU, GPU, driver, graphics backend, and emulator configuration belong to BB-BL3. A reproducible runtime record will reference all three manifests rather than copying their fields into this one.

Schema version 1 separates four concerns:

- `target` identifies Bloodborne and the title/distribution identity;
- `build` records reported version labels plus exact SHA-256 identities for resolved `eboot.bin` and `sce_sys/param.sfo`;
- `content` records base/update/DLC labels and a digest of the resolved guest-visible content tree;
- `configuration` records the complete set of target-visible settings and active mods, patches, or configuration overlays not already represented by the resolved tree.

Version strings and content IDs are useful human-readable corroboration, but they are not exact identities. The `eboot`, `param_sfo`, resolved-tree, and active-modification digests are the exact identifiers.

Use JSON `null` when an optional descriptive label is unavailable; do not serialize placeholders such as `unknown`, `n/a`, or a guessed version. `provenance.evidence_classes` lists every evidence class used to populate the manifest. A `complete` identity must include direct `static`, `runtime`, or `synthetic` evidence for its exact identity values; reported-only or assumed identity remains `partial`.

`source_package` is optional acquisition provenance. It is `null` when the original package was not retained or was not hashed. Its absence does not make the runtime-material identity incomplete because `resolved_tree` records the content actually exposed to the guest. A repacked package can therefore have different package provenance while producing the same resolved target baseline.

## Hashing rules

All artifact SHA-256 values are lowercase hexadecimal digests of the exact raw file bytes. `size_bytes` is recorded independently so an accidental empty or truncated input is visible before comparison.

`sha256-tree-v1` identifies the resolved, read-only content view presented to the title after base, update, DLC, and file-replacement overlays have been applied, but before the title is launched. User saves, shader caches, emulator logs, captures, and other host-generated mutable data are outside this tree.

To compute it:

1. Enumerate every regular file in every resolved guest-visible content namespace. Prefix each relative path with its guest namespace so two mounts cannot collide.
2. Normalize separators to `/` and path text to UTF-8 NFC. Reject absolute paths, `.` or `..` components, duplicate normalized paths, symlinks, and unsupported entry types rather than guessing how to hash them.
3. For each file, form the byte record `path + NUL + decimal size + NUL + lowercase file SHA-256 + LF`.
4. Sort records by the UTF-8 bytes of the normalized path, concatenate them, and SHA-256 the result.
5. Record the aggregate digest, number of files, and total raw byte count.

This algorithm commits to file names and contents without placing either in the manifest. A later collector must preserve this exact algorithm name or introduce a new one; consumers must not reinterpret a new tree algorithm as version 1.

## Configuration rules

`settings` contains only target-visible inputs that can change the observed game behavior and are not already captured by the resolved tree. Keys use stable project-owned names such as `game.language`; values are bounded scalar JSON values.

`active_modifications` is keyed by stable modification ID and lists only enabled modifications. Each value has a kind, optional human-readable version, and an exact digest/size of the rule, patch, or configuration artifact that affects the run. Disabled mods are omitted because they do not affect the baseline. If the enabled set cannot be established completely, the manifest is `partial` and names the uncertain JSON Pointer paths in `identity_completeness.unknown_fields`.

Duplicate JSON object member names are invalid input even if a permissive parser would keep the last value. Collectors and consumers must reject them before schema validation so duplicate settings or modification IDs cannot be resolved by parser ordering.

Emulator implementation settings such as renderer/backend selection do not belong here merely because they influence the run. They remain host/run-environment state unless they also select a target modification represented by this manifest.

## Comparison semantics

A consumer must first validate the document against the exact supported schema version. Unknown schema versions and invalid documents fail closed.

For material target comparison, use this projection:

- `target.title_id`;
- `build.eboot` and `build.param_sfo`;
- `content.resolved_tree`;
- the complete `configuration.settings` and `configuration.active_modifications` objects, compared by member name rather than serialization order.

The result is:

- **different** if any projected field differs;
- **same** only if both manifests are valid, use the same supported schema/algorithm versions, assert `identity_completeness.state: complete` with direct evidence, and every projected field is equal;
- **indeterminate** otherwise.

Reported version labels, distribution region, component IDs, update state, DLC labels, source-package hashes, collection time, producer, and evidence classes remain in the audit record. They can reveal a collection error or explain a difference, but they do not override exact material digests.

Synthetic schema validation proves only the shape and fail-closed format. It does not establish any real Bloodborne build, content, update, configuration, or runtime fact.

## Licensing and privacy boundary

Safe to store:

- public title/content/version identifiers;
- SHA-256 digests, byte counts, aggregate counts, schema/tool versions, timestamps, and evidence classes;
- stable project-owned setting/modification IDs and bounded non-sensitive scalar values.

Never store:

- executables, packages, assets, extracted file contents, keys, licenses, tickets, credentials, or DRM material;
- user names, account IDs, machine IDs, private host paths, original download URLs, or unrelated environment data;
- a file listing or free-form notes copied from the proprietary target when a digest is sufficient.

Collection must read operator-supplied target material without modifying it. If a future collector needs a writable overlay to resolve content, it must operate on a verified copy or isolated view and emit only this safe metadata.

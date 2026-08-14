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

Version strings and content IDs are useful human-readable corroboration, but they are not exact identities. `target.title_id`, the `eboot`, `param_sfo`, resolved-tree, target-visible setting values, active-modification digests, and modification application order form the exact identity projection.

Use JSON `null` only when an optional descriptive label is unavailable; do not serialize placeholders such as `unknown`, `n/a`, or a guessed version. Every exact projected value carries its own `evidence_class`, limited to `static`, `runtime`, or `synthetic`. `provenance.evidence_classes` is an audit summary and cannot upgrade a reported or assumed projected value into direct evidence. A `complete` identity asserts both that every projected value is directly evidenced and that the setting/modification sets were enumerated completely.

`source_package` is optional acquisition provenance. It is `null` when the original package was not retained or was not hashed. Its absence does not make the runtime-material identity incomplete because `resolved_tree` records the content actually exposed to the guest. A repacked package can therefore have different package provenance while producing the same resolved target baseline.

## Hashing rules

All artifact SHA-256 values are lowercase hexadecimal digests of the exact raw file bytes. `size_bytes` is recorded independently so an accidental empty or truncated input is visible before comparison.

`sha256-tree-v1` identifies the resolved, read-only content view presented to the title after base, update, DLC, and file-replacement overlays have been applied, but before the title is launched. User saves, shader caches, emulator logs, captures, and other host-generated mutable data are outside this tree.

Schema v1 has exactly these content namespaces:

- `app/` is the final resolved application view after base, update, and file-replacement overlays;
- `dlc/<content-id>/` is one installed DLC view for each key in `content.dlc`.

Namespace names are lowercase ASCII exactly as shown, have no leading slash, and use one `/` between components. DLC content IDs are copied byte-for-byte from their manifest object key; the schema restricts those keys to ASCII letters, digits, `.`, `_`, and `-`. A content view requiring any other namespace is not representable by `sha256-tree-v1` and must remain partial or use a future algorithm version.

To compute the digest:

1. Enumerate every regular file in `app/` and each declared `dlc/<content-id>/` view.
2. Normalize the path relative to that namespace to UTF-8 NFC with `/` separators, then prefix it with the canonical namespace above. Reject empty/absolute relative paths, `.` or `..` components, duplicate normalized full paths, symlinks, and unsupported entry types rather than guessing how to hash them.
3. For each file, form the byte record `canonical full path + NUL + decimal size + NUL + lowercase file SHA-256 + LF`. `NUL` is one `0x00` byte and `LF` is one `0x0a` byte; the decimal size has no sign or leading zeroes except the value `0`.
4. Sort records by the UTF-8 bytes of the normalized path, concatenate them, and SHA-256 the result.
5. Record the aggregate digest, number of files, and total raw byte count.

This algorithm commits to file names and contents without placing either in the manifest. A later collector must preserve this exact algorithm name or introduce a new one; consumers must not reinterpret a new tree algorithm as version 1.

## Configuration rules

`settings` contains only target-visible inputs that can change the observed game behavior and are not already captured by the resolved tree. Keys use stable project-owned names such as `game.language`; each member carries a bounded scalar JSON `value` plus field-level direct evidence. Boolean, numeric (including fractional), and string values are supported. The comparator preserves the JSON scalar kind, so `true` and `1` are different values even though Python would otherwise consider them equal. Non-finite numeric values are invalid. `null` is forbidden: an unreadable setting makes the manifest `partial` and is named in `identity_completeness.unknown_fields`.

`active_modifications` is keyed by stable modification ID and lists only enabled modifications. Each value has a kind, optional human-readable version, and an exact digest/size plus field-level direct evidence for the rule, patch, or configuration artifact that affects the run. Disabled mods are omitted because they do not affect the baseline.

`modification_order.value` lists every `active_modifications` key exactly once, from lowest to highest precedence (first applied to last applied). Its field-level evidence identifies how that effective order was established. A consumer rejects a missing, duplicate, or extra key. If the enabled set cannot be established completely, the manifest is `partial` and marks both `/configuration/active_modifications` and `/configuration/modification_order` unknown; narrower uncertainty names the narrowest affected pointer.

Duplicate JSON object member names are invalid input even if a permissive parser would keep the last value. Collectors and consumers must reject them before schema validation so duplicate settings or modification IDs cannot be resolved by parser ordering. Use the committed [validator/comparator](../../tools/bloodborne_target_manifest.py)'s `validate_document` entry point for untrusted JSON text; `validate_manifest` intentionally accepts only a mapping that has already been strictly parsed. The tool enforces this rule and the cross-field modification-order invariant; [regression tests](../../tests/test_bloodborne_target_manifest.py) preserve the positive and negative cases.

Emulator implementation settings such as renderer/backend selection do not belong here merely because they influence the run. They remain host/run-environment state unless they also select a target modification represented by this manifest.

## Comparison semantics

A consumer must first validate the document against the exact supported schema version. Unknown schema versions and invalid documents fail closed.

For material target comparison, use this projection:

- `target.title_id.value`;
- `build.eboot` and `build.param_sfo`;
- `content.resolved_tree`;
- each target-visible `configuration.settings` value;
- each active modification's kind and artifact identity;
- `configuration.modification_order.value`.

Evidence-class members and descriptive labels are excluded from the material value comparison, but the schema requires field-level direct evidence for every projected value. Object members are compared by name rather than serialization order.

The result is:

- **different** if at least one differing projected field is known in both manifests;
- **same** only if both manifests are valid, use the same supported schema/algorithm versions, assert `identity_completeness.state: complete` with direct evidence, and every projected field is equal;
- **indeterminate** otherwise, including when the only mismatches overlap a JSON Pointer listed in either manifest's `unknown_fields`.

Pointer overlap includes ancestors and descendants. For example, `/configuration/active_modifications` makes a missing or extra modification inconclusive, while an independently known `target.title_id.value` mismatch can still establish **different**. A partial manifest never establishes **same**, even when all currently known projected values match.

Reported version labels, distribution region, component IDs, update state, DLC labels, source-package hashes, collection time, producer, and provenance summary remain in the audit record. They can reveal a collection error or explain a difference, but they do not override exact material values. `content.update.state: unknown` may appear in a complete material identity because the exact resolved tree already commits to the content actually presented to the title; the unknown label is descriptive rather than a hole in the comparison projection.

The reproducible validation procedure and negative cases are recorded in [`docs/experiments/BB-BL2-target-manifest-validation.md`](../experiments/BB-BL2-target-manifest-validation.md). Synthetic schema/semantic validation proves only the shape and fail-closed format. It does not establish any real Bloodborne build, content, update, configuration, or runtime fact.

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

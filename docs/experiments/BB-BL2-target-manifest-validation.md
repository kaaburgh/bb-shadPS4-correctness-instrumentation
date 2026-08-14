# BB-BL2 target-manifest validation

## Purpose and evidence boundary

This is the reproducible synthetic validation for the Bloodborne target identity format. It checks schema compatibility, fail-closed parsing, cross-field invariants, and three-way comparison behavior. Evidence class is `synthetic`; no Bloodborne file, package, identifier, configuration, or runtime behavior is used or established.

## Inputs

- `schemas/bloodborne-target-manifest.schema.json`
- `docs/baseline/examples/bloodborne-target-manifest.synthetic.json`
- `tools/bloodborne_target_manifest.py`
- `tests/test_bloodborne_target_manifest.py`
- `jsonschema==4.25.1`

The dedicated GitHub workflow installs the pinned validator and runs the real entry point. The tests retain a dependency-free subset for strict JSON parsing, semantic closure, and comparison; schema-specific cases are skipped when `jsonschema` is unavailable rather than making unrelated standard-library test jobs fail.

## Commands

```bash
python -m pip install jsonschema==4.25.1
python -m unittest tests.test_bloodborne_target_manifest -v
python tools/bloodborne_target_manifest.py validate \
  docs/baseline/examples/bloodborne-target-manifest.synthetic.json
```

## Preserved oracles

Positive cases establish internal format capability only:

- the Draft 2020-12 schema is valid and accepts the committed synthetic example;
- fractional target-visible settings are representable with direct field evidence;
- a descriptive unknown update label remains compatible with complete material identity because `resolved_tree` is exact;
- provenance may summarize reported/assumed labels without replacing direct evidence on projected values;
- an exact matching complete pair compares `same`.

Negative and ambiguity cases fail closed:

- duplicate JSON members are rejected before schema validation;
- unknown top-level payload fields, uppercase digests, unknown tree algorithms, invalid modification IDs, empty partial-identity pointers, and non-direct evidence on exact fields are rejected;
- `null` cannot represent an unreadable target-visible setting;
- modification order must contain every active modification ID exactly once;
- an unknown active-modification set also marks application order unknown;
- mismatches confined to unknown projected paths compare `indeterminate`, not `different`;
- a partial manifest never compares `same`;
- boolean and numeric settings with the same Python truthiness compare `different` when their JSON scalar kinds differ;
- non-finite JSON constants and overflowed numeric values are rejected before comparison;
- a separately known projected mismatch still compares `different` even when another path is uncertain;
- reversing modification order changes material identity.

## Non-claims

These checks do not validate a real Bloodborne target, shadPS4's actual content-mount implementation, or runtime behavior. A future collector must independently demonstrate that it produces the specified canonical `app/` and `dlc/<content-id>/` resolved views from the exact target baseline.

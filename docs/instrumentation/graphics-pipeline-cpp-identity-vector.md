# C++ exact pipeline identity conformance vector

`bb-graphics-pipeline-cpp-identity-vector/v1` freezes one byte-exact synthetic target for a future shadPS4 C++ implementation of the repository's `bb-graphics-identity/v2` exact `pipeline_identity`.

The vector is deliberately not a new identity model. It binds the existing committed graphics-identity fixture, BB-BL1 source baseline, `bb-graphics-pipeline-key-surface/v12` version and canonical surface digest to the exact canonical UTF-8 JSON payload hashed by the Python model and to the resulting `pipeline:sha256:...` identity.

## Why this is needed

The prepared `GetGraphicsPipeline` source seam exposes `graphics_key` and `is_new`, while `bb-graphics-pipeline-producer/v1` requires an exact cross-run `pipeline:sha256:...` identity. A runtime implementation must not substitute `std::hash<GraphicsPipelineKey>`, compiler object bytes, a capture-local identifier, or a different serialization.

The committed vector therefore gives an independent C++ implementation a byte-for-byte target:

1. canonicalize the full 21-field key according to the committed surface rules;
2. construct the exact semantic payload recorded in `canonical_pipeline_payload_utf8`;
3. hash those exact ASCII/UTF-8 bytes with SHA-256;
4. reproduce `expected_pipeline_identity` exactly.

The JSON canonicalization used by `bb-graphics-identity/v2` is `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=True)` semantics: recursively sorted object keys, no insignificant whitespace, ASCII escapes when needed, JSON decimal integers and ordinary array order.

## Evidence boundary

This is static + synthetic conformance evidence only. The repository validator intentionally regenerates the vector target from the existing Python identity model and committed fixture, so this check is not independent proof of the Python model itself. Its purpose is to freeze the exact cross-language target that a separately implemented C++ emitter must match.

This slice does not implement C++, does not enable the prepared runtime hook, and does not establish emitted pipeline identities, `created`/`cache_hit` behavior, Bloodborne coverage, GPU timing semantics or instrumentation overhead.

## Validation

Run:

```text
python -m unittest tests.test_graphics_pipeline_cpp_identity_vector -v
python tools/graphics_pipeline_cpp_identity_vector.py docs/instrumentation/examples/graphics-pipeline-cpp-identity-vector.synthetic.json
```

A future C++ implementation should add an independent test that feeds the same canonical key through the C++ serializer/hasher and compares both the serialized payload bytes and final identity to this committed vector.

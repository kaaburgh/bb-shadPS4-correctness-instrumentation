# C++ exact pipeline identity conformance implementation

This slice provides a standalone C++20 implementation that independently reproduces the committed `bb-graphics-pipeline-cpp-identity-vector/v1` synthetic vector.

The implementation represents all 21 canonical `GraphicsPipelineKey` fields as typed C++ scalars, arrays, or records, constructs the canonical pipeline JSON payload through a dedicated serializer, computes SHA-256 in C++, and emits exactly two lines: the canonical payload bytes and the resulting `pipeline:sha256:...` identity. It does not use the frozen payload string or pre-serialized JSON value fragments as implementation input. The dedicated regression compiles that implementation with strict warnings, compares both output lines against the committed vector, and guards the typed mapping for representative scalar/array/record fields.

This is **static/synthetic conformance evidence only**. It establishes that a separately written C++ implementation can reproduce the current frozen cross-language target. It is not the production shadPS4 emitter, does not modify or execute the prepared `GetGraphicsPipeline` hook, and does not establish runtime `created` / `cache_hit` semantics, Bloodborne coverage, GPU timing semantics, or instrumentation overhead.

The C++ source intentionally carries a compact self-contained SHA-256 implementation so digest computation does not delegate back to the Python identity model or depend on a host crypto library. It remains vector-scoped: production source integration must still map the real `GraphicsPipelineKey` into the same typed canonical representation and satisfy `bb-graphics-pipeline-producer/v1`.

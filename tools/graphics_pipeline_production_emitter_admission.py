#!/usr/bin/env python3
import json
import sys
from pathlib import Path

SCHEMA_VERSION = "bb-graphics-pipeline-production-emitter-admission/v1"
EXPECTED_SOURCE = {
    "repository": "https://github.com/shadps4-emu/shadPS4",
    "commit": "28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64",
    "path": "src/video_core/renderer_vulkan/vk_pipeline_cache.cpp",
    "git_blob": "b39f1c30bfb00d1f21a082da48369ba95ce31368",
    "function": "Vulkan::PipelineCache::GetGraphicsPipeline",
    "lookup_expression": "graphics_pipelines.try_emplace(graphics_key)",
    "classification_source": "is_new",
}
EXPECTED_DEP_VERSIONS = {
    "producer_contract": "bb-graphics-pipeline-producer/v1",
    "source_mapping": "bb-graphics-pipeline-cpp-source-mapping/v1",
    "canonical_surface": "bb-graphics-pipeline-key-surface/v12",
}
EXPECTED_BUNDLE = [
    "src/video_core/renderer_vulkan/bb_graphics_pipeline_exact_producer.h",
    "src/video_core/renderer_vulkan/vk_pipeline_cache.cpp",
]
EXPECTED_SYMBOLS = [
    "BbCanonicalPipelineKeyFromGraphicsPipelineKey",
    "BbExactPipelineIdentity",
    "BbObserveGraphicsPipeline",
]
EXPECTED_FORBIDDEN = ["std::hash<GraphicsPipelineKey>", "object_bytes", "memcmp_bytes"]


def _expect(condition, message):
    if not condition:
        raise ValueError(message)


def validate(doc, repo_root: Path):
    _expect(set(doc) == {"schema_version", "source", "dependencies", "integration", "evidence_boundary"}, "unexpected top-level fields")
    _expect(doc["schema_version"] == SCHEMA_VERSION, "unsupported schema_version")
    _expect(doc["source"] == EXPECTED_SOURCE, "source provenance/seam drift")

    deps = doc["dependencies"]
    _expect(set(deps) == {"producer_contract", "source_mapping", "cpp_identity_conformance", "canonical_surface"}, "dependency set drift")
    for name, version in EXPECTED_DEP_VERSIONS.items():
        _expect(deps[name]["schema_version"] == version, f"{name} version drift")
        _expect((repo_root / deps[name]["path" if name != "producer_contract" else "schema_path"]).is_file(), f"missing {name} material input")
    _expect(deps["source_mapping"]["required_canonical_fields"] == 21, "canonical field count drift")
    cpp_path = repo_root / deps["cpp_identity_conformance"]["path"]
    _expect(cpp_path.is_file(), "missing C++ identity conformance input")
    cpp_text = cpp_path.read_text(encoding="utf-8")
    _expect(deps["cpp_identity_conformance"]["required_identity_prefix"] == "pipeline:sha256:", "identity prefix drift")
    _expect('"pipeline:sha256:"' in cpp_text, "C++ conformance no longer constructs exact pipeline identity")

    mapping = json.loads((repo_root / deps["source_mapping"]["path"]).read_text(encoding="utf-8"))
    _expect(mapping.get("schema_version") == EXPECTED_DEP_VERSIONS["source_mapping"], "mapping document version mismatch")
    _expect(len(mapping.get("fields", [])) == 21, "mapping no longer covers 21 canonical fields")

    producer_schema = json.loads((repo_root / deps["producer_contract"]["schema_path"]).read_text(encoding="utf-8"))
    _expect(producer_schema.get("$id", "").endswith("graphics-pipeline-producer.schema.json") or producer_schema.get("title"), "producer schema is not recognizable")

    integration = doc["integration"]
    _expect(integration["gate_macro"] == "SHADPS4_BB_GRAPHICS_PIPELINE_EXACT_PRODUCER", "diagnostic gate macro drift")
    _expect(integration["normal_build_behavior"] == "no_runtime_work", "normal builds must remain unchanged")
    _expect(integration["key_input"] == "graphics_key", "runtime key input drift")
    _expect(integration["classification"] == {"created_when": "is_new == true", "cache_hit_when": "is_new == false"}, "created/cache_hit classification drift")
    _expect(integration["required_bundle_paths"] == EXPECTED_BUNDLE, "patch bundle path drift")
    _expect(integration["required_symbols"] == EXPECTED_SYMBOLS, "required symbol drift")
    _expect(integration["forbidden_identity_sources"] == EXPECTED_FORBIDDEN, "forbidden identity-source policy drift")

    boundary = doc["evidence_boundary"]
    _expect(boundary["class"] == ["static", "synthetic"], "evidence class drift")
    for key, value in boundary.items():
        if key != "class":
            _expect(value is False, f"unsupported runtime claim: {key}")
    return True


def main(argv):
    if len(argv) != 2:
        raise SystemExit(f"usage: {argv[0]} CONTRACT.json")
    path = Path(argv[1]).resolve()
    repo_root = Path(__file__).resolve().parents[1]
    doc = json.loads(path.read_text(encoding="utf-8"))
    validate(doc, repo_root)
    print("production_emitter_admission_ready=true")


if __name__ == "__main__":
    main(sys.argv)

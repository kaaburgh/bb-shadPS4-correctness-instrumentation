from __future__ import annotations

import json
import sys
from pathlib import Path

SCHEMA_VERSION = "bb-graphics-pipeline-producer/v1"
PINNED_SOURCE = {
    "repository": "https://github.com/shadps4-emu/shadPS4",
    "commit": "28c84fb5a7b19c7fb86156a1d6bb3e7e5a6cef64",
}
PINNED_SEAM = {
    "path": "src/video_core/renderer_vulkan/vk_pipeline_cache.cpp",
    "symbol": "VideoCore::PipelineCache::GetGraphicsPipeline",
    "observation_point": "post_lookup_result",
}
IDENTITY_CONTRACT = {
    "model_version": "bb-graphics-identity/v2",
    "key_surface_version": "bb-graphics-pipeline-key-surface/v12",
}
PRODUCER_ID = "shadps4-bb-pipeline-observer"
MAX_OBSERVATIONS = 1_000_000


class PipelineProducerContractError(ValueError):
    pass


def _require_exact_keys(value: dict, expected: set[str], field: str) -> None:
    if not isinstance(value, dict):
        raise PipelineProducerContractError(f"{field} must be an object")
    missing = expected - value.keys()
    extra = value.keys() - expected
    if missing:
        raise PipelineProducerContractError(f"{field} missing keys: {sorted(missing)}")
    if extra:
        raise PipelineProducerContractError(f"{field} unexpected keys: {sorted(extra)}")


def _require_sha256(value: object, field: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise PipelineProducerContractError(f"{field} must be 64 lowercase hexadecimal characters")
    try:
        int(value, 16)
    except ValueError as exc:
        raise PipelineProducerContractError(f"{field} must be hexadecimal") from exc
    if value.lower() != value:
        raise PipelineProducerContractError(f"{field} must be lowercase")


def validate(document: dict) -> dict:
    _require_exact_keys(
        document,
        {"schema_version", "source", "seam", "identity_contract", "producer", "observations"},
        "document",
    )
    if document["schema_version"] != SCHEMA_VERSION:
        raise PipelineProducerContractError("unsupported schema_version")
    if document["source"] != PINNED_SOURCE:
        raise PipelineProducerContractError("source must match the pinned BB-BL1 baseline exactly")
    if document["seam"] != PINNED_SEAM:
        raise PipelineProducerContractError("seam must match the reviewed GetGraphicsPipeline observation point exactly")
    if document["identity_contract"] != IDENTITY_CONTRACT:
        raise PipelineProducerContractError("identity contract is stale or incompatible")

    producer = document["producer"]
    _require_exact_keys(producer, {"producer_id", "producer_sha256"}, "producer")
    if producer["producer_id"] != PRODUCER_ID:
        raise PipelineProducerContractError("unsupported producer_id")
    _require_sha256(producer["producer_sha256"], "producer.producer_sha256")

    observations = document["observations"]
    if not isinstance(observations, list) or not observations or len(observations) > MAX_OBSERVATIONS:
        raise PipelineProducerContractError("observations must contain between 1 and 1000000 entries")

    previous_seq: int | None = None
    created = 0
    cache_hits = 0
    for index, observation in enumerate(observations):
        _require_exact_keys(observation, {"seq", "pipeline_identity", "result"}, f"observations[{index}]")
        seq = observation["seq"]
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
            raise PipelineProducerContractError(f"observations[{index}].seq must be a non-negative integer")
        if previous_seq is not None and seq <= previous_seq:
            raise PipelineProducerContractError("observation seq values must be strictly increasing")
        previous_seq = seq

        identity = observation["pipeline_identity"]
        prefix = "pipeline:sha256:"
        if not isinstance(identity, str) or not identity.startswith(prefix):
            raise PipelineProducerContractError(f"observations[{index}].pipeline_identity has invalid format")
        _require_sha256(identity[len(prefix):], f"observations[{index}].pipeline_identity")

        result = observation["result"]
        if result == "created":
            created += 1
        elif result == "cache_hit":
            cache_hits += 1
        else:
            raise PipelineProducerContractError(f"observations[{index}].result must be created or cache_hit")

    return {
        "schema_version": SCHEMA_VERSION,
        "observation_count": len(observations),
        "created": created,
        "cache_hits": cache_hits,
        "distinct_pipeline_identities": len({item["pipeline_identity"] for item in observations}),
    }


def validate_path(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineProducerContractError(f"unable to load producer record: {exc}") from exc
    return validate(document)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate BB graphics pipeline producer admission record")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(validate_path(args.path), sort_keys=True, indent=2))
    except PipelineProducerContractError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)

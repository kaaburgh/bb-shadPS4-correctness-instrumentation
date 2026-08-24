from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import graphics_identity_model

VECTOR_VERSION = "bb-graphics-pipeline-cpp-identity-vector/v1"
FIXTURE_PATH = Path("docs/instrumentation/examples/graphics-identity.synthetic.json")


class PipelineIdentityVectorError(ValueError):
    pass


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _require_exact_keys(value: dict, required: set[str]) -> None:
    if not isinstance(value, dict):
        raise PipelineIdentityVectorError("vector must be an object")
    missing = required - value.keys()
    extra = value.keys() - required
    if missing:
        raise PipelineIdentityVectorError(f"missing keys: {sorted(missing)}")
    if extra:
        raise PipelineIdentityVectorError(f"unexpected keys: {sorted(extra)}")


def expected_from_model() -> dict:
    derived = graphics_identity_model.derive_path(FIXTURE_PATH)
    semantic = {
        "source": derived["source"],
        "key_surface_version": derived["pipeline_key_surface_version"],
        "key_surface_sha256": derived["pipeline_key_surface_sha256"],
        "canonical_key": derived["pipeline_key"],
    }
    payload = _canonical({"kind": "pipeline", "value": semantic})
    identity = f"pipeline:sha256:{hashlib.sha256(payload).hexdigest()}"
    if identity != derived["pipeline_identity"]:
        raise PipelineIdentityVectorError("reconstructed canonical payload disagrees with graphics identity model")
    return {
        "model_version": derived["model_version"],
        "source": derived["source"],
        "key_surface_version": derived["pipeline_key_surface_version"],
        "key_surface_sha256": derived["pipeline_key_surface_sha256"],
        "canonical_pipeline_payload_utf8": payload.decode("ascii"),
        "expected_pipeline_identity": identity,
    }


def validate(document: dict) -> dict:
    required = {
        "schema_version",
        "model_version",
        "source",
        "key_surface_version",
        "key_surface_sha256",
        "fixture_path",
        "canonical_pipeline_payload_utf8",
        "expected_pipeline_identity",
    }
    _require_exact_keys(document, required)
    if document["schema_version"] != VECTOR_VERSION:
        raise PipelineIdentityVectorError("unsupported schema_version")
    if document["fixture_path"] != FIXTURE_PATH.as_posix():
        raise PipelineIdentityVectorError("fixture_path must bind the committed graphics identity fixture")

    expected = expected_from_model()
    for field in (
        "model_version",
        "source",
        "key_surface_version",
        "key_surface_sha256",
        "canonical_pipeline_payload_utf8",
        "expected_pipeline_identity",
    ):
        if document[field] != expected[field]:
            raise PipelineIdentityVectorError(f"{field} does not match the committed identity model")

    payload = document["canonical_pipeline_payload_utf8"]
    if not isinstance(payload, str) or not payload.isascii():
        raise PipelineIdentityVectorError("canonical payload must be ASCII UTF-8 text")
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PipelineIdentityVectorError("canonical payload is not valid JSON") from exc
    if _canonical(parsed).decode("ascii") != payload:
        raise PipelineIdentityVectorError("canonical payload is not canonical JSON")

    digest = hashlib.sha256(payload.encode("ascii")).hexdigest()
    if document["expected_pipeline_identity"] != f"pipeline:sha256:{digest}":
        raise PipelineIdentityVectorError("expected_pipeline_identity does not hash the committed payload")

    return {
        "schema_version": VECTOR_VERSION,
        "payload_bytes": len(payload.encode("ascii")),
        "pipeline_identity": document["expected_pipeline_identity"],
        "key_surface_sha256": document["key_surface_sha256"],
    }


def validate_path(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return validate(json.load(stream))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate BB C++ exact pipeline identity conformance vector")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_path(args.path), sort_keys=True, indent=2))

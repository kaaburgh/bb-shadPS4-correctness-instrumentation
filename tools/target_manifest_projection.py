"""Shared transfer-safe Bloodborne target-manifest projection.

This module owns the supported projection used by target-run packaging and
baseline capture.  It deliberately builds on the compatibility engine's
fail-closed base allowlist without mutating that module at import time.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from tools import run_target_experiment_v3 as _legacy


TargetRunError = _legacy.TargetRunError


def package_target_manifest(manifest: Mapping[str, Any]) -> bytes:
    """Return the supported transfer-safe target projection.

    The compatibility engine owns the conservative base allowlist.  The shared
    supported projection additionally preserves DLC identity as deterministic
    hashes without copying unrestricted identifiers or version strings.
    """
    packaged = _legacy.loads_strict(
        _legacy._package_target_manifest(manifest).decode("utf-8")
    )
    packaged_dlc: dict[str, Any] = {}
    for identifier, component in sorted(manifest["content"]["dlc"].items()):
        safe_identifier = "dlc-sha256-" + hashlib.sha256(
            identifier.encode("utf-8")
        ).hexdigest()
        source_package = component["source_package"]
        packaged_dlc[safe_identifier] = {
            "version": None,
            "source_package": (
                None
                if source_package is None
                else _legacy._copy_exact_artifact(source_package)
            ),
        }
    packaged["content"]["dlc"] = packaged_dlc
    try:
        _legacy.bloodborne_target_manifest.validate_manifest(packaged)
    except Exception as error:
        raise TargetRunError(
            f"safe target-manifest projection is invalid: {error}"
        ) from error
    return _legacy._json_bytes(packaged)

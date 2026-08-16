"""Repository host-environment collection tools."""

from __future__ import annotations

import sys
from pathlib import Path


def _direct_legacy_target_runner_invocation() -> bool:
    """Detect unsupported direct execution of the compatibility engine."""
    original = tuple(getattr(sys, "orig_argv", ()))
    if len(original) >= 3 and original[1:3] == ("-m", "tools.run_target_experiment_v3"):
        return True
    return Path(sys.argv[0]).name == "run_target_experiment_v3.py"


if _direct_legacy_target_runner_invocation():
    print(
        "error: tools.run_target_experiment_v3 is an internal compatibility engine; "
        "use tools/run_target_experiment.py or python -m tools.run_target_experiment",
        file=sys.stderr,
    )
    raise SystemExit(2)

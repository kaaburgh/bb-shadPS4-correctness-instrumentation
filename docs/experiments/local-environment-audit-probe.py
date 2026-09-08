#!/usr/bin/env python3
"""Bounded observational probe; NOT the BB-ENV1 supported runner.

Use only with an independently verified disposable target copy and extracted
emulator. This does not admit a source baseline or attest a semantic checkpoint.
Raw output stays private. See local-environment-audit-2026-09-08.md.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time


def limits():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024,) * 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-run", type=Path, required=True)
    parser.add_argument("--target-copy", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    app = args.app_run.resolve(strict=True)
    target = args.target_copy.resolve(strict=True)
    if not (target / "eboot.bin").is_file():
        parser.error("target copy must contain eboot.bin")
    work = args.work.absolute()
    work.mkdir(exist_ok=False)
    for name in ("user", "data", "cache", "config"):
        (work / name).mkdir()
    env = os.environ.copy()
    env.update(DISPLAY=":1", XDG_DATA_HOME=str(work / "data"),
               XDG_CACHE_HOME=str(work / "cache"),
               XDG_CONFIG_HOME=str(work / "config"),
               __GL_SHADER_DISK_CACHE_PATH=str(work / "cache"))
    argv = [str(app), "--game", str(target / "eboot.bin"),
            "--override-root", str(target), "--config-clean",
            "--ignore-game-patch", "--fullscreen", "false"]
    start = time.monotonic()
    timed_out = False
    with (work / "stdout.private.log").open("wb") as output:
        process = subprocess.Popen(argv, cwd=work, env=env,
                                   stdin=subprocess.DEVNULL, stdout=output,
                                   stderr=subprocess.STDOUT,
                                   start_new_session=True, preexec_fn=limits)
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=3)
    result = {
        "schema": "bb-local-audit-process/v1",
        "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "elapsed_seconds": round(time.monotonic() - start, 3),
        "timeout_seconds": 60,
        "timed_out": timed_out,
        "returncode": process.returncode,
        "semantic_checkpoint": "unassessed",
        "bb_env1_validation": False,
    }
    (work / "process.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()

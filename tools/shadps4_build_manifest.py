#!/usr/bin/env python3
"""Build a clean exact source state, or verify its durable build manifest.

The producer executes CMake/Ninja in a NEW out-of-tree directory. There is no
command to retrospectively bless an arbitrary existing executable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import shadps4_source_baseline as baseline

VERSION = "bb-shadps4-build/1.0.0"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas/shadps4-build.schema.json"


class BuildManifestError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def file_identity(path):
    if path.is_symlink() or not path.is_file():
        raise BuildManifestError("binary must be a regular non-link file")
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
            size += len(block)
    return {"sha256": "sha256:" + h.hexdigest(), "size_bytes": size}


def strict_load(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise BuildManifestError("duplicate build manifest member")
            result[key] = value
        return result

    def reject(value):
        raise BuildManifestError("non-finite build manifest value")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)
    except (ValueError, UnicodeError) as error:
        raise BuildManifestError("invalid build manifest JSON") from error


def git(source, *args):
    # Replacement objects/grafts must not change the meaning of pinned SHAs.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", "--no-replace-objects", "-C", str(source), *args],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=60, check=True,
        )
        return result.stdout.decode("utf-8").rstrip("\n")
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise BuildManifestError("unable to verify source Git identity: " + args[0]) from error


def repository_url(value):
    if not isinstance(value, str):
        raise BuildManifestError("repository identity must be an HTTPS URL")
    url = urlsplit(value)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.port
            or not re.fullmatch(r"/[A-Za-z0-9_./-]+", url.path)
            or any(part in {".", ".."} for part in url.path.split("/"))):
        raise BuildManifestError("repository identity must be a public HTTPS URL without credentials")
    return value.removesuffix(".git").rstrip("/")


def _clean(source, expected_head, *, require_history=True):
    if Path(git(source, "rev-parse", "--show-toplevel")).resolve() != source.resolve():
        raise BuildManifestError("source must identify a repository root")
    if require_history and git(source, "rev-parse", "--is-shallow-repository") != "false":
        raise BuildManifestError("shallow source history is ambiguous")
    if git(source, "for-each-ref", "refs/replace"):
        raise BuildManifestError("replacement source history is ambiguous")
    graft = Path(git(source, "rev-parse", "--git-path", "info/grafts"))
    if not graft.is_absolute():
        graft = source / graft
    if graft.exists():
        raise BuildManifestError("grafted source history is ambiguous")
    if git(source, "rev-parse", "HEAD") != expected_head:
        raise BuildManifestError("source commit/effective HEAD mismatch")
    flags = git(source, "ls-files", "-v").splitlines()
    if any(line and (line[0].islower() or line[0] == "S") for line in flags):
        raise BuildManifestError("hidden index state (skip-worktree/assume-unchanged)")
    if git(source, "status", "--porcelain=v1", "--untracked-files=all",
           "--ignored=matching", "--ignore-submodules=none"):
        raise BuildManifestError("dirty source state (including untracked/ignored files)")


def _submodules(source, prefix="", depth=0):
    if depth > 16:
        raise BuildManifestError("recursive submodule depth exceeds bound")
    result = []
    for entry in git(source, "ls-tree", "-rz", "HEAD").split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        mode, kind, commit = meta.split()
        if mode != "160000":
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", path):
            raise BuildManifestError("unsafe submodule path")
        child = source / path
        if child.is_symlink() or not child.resolve().is_relative_to(source.resolve()):
            raise BuildManifestError("submodule escapes source")
        _clean(child, commit, require_history=False)
        # Read URL from committed .gitmodules, never mutable local URL overrides.
        definitions = git(source, "config", "--blob", "HEAD:.gitmodules",
                          "--get-regexp", r"^submodule\..*\.path$").splitlines()
        matches = [line.split(" ", 1)[0][:-5] for line in definitions
                   if line.split(" ", 1)[1] == path]
        if len(matches) != 1:
            raise BuildManifestError("ambiguous submodule identity")
        url = repository_url(git(source, "config", "--blob", "HEAD:.gitmodules",
                                 "--get", matches[0] + ".url"))
        result.append({"path": prefix + path, "repository": url, "commit": commit,
                       "tree": git(child, "rev-parse", "HEAD^{tree}"), "dirty": False})
        result.extend(_submodules(child, prefix + path + "/", depth + 1))
        if len(result) > 512:
            raise BuildManifestError("too many submodules")
    return sorted(result, key=lambda item: item["path"])


def observe_source(source, patch_repository=None, patch_commits=()):
    """Prove a complete linear patch chain rooted in the active exact baseline."""
    source = source.resolve(strict=True)
    patches = list(patch_commits)
    if len(patches) > 64 or len(set(patches)) != len(patches) or any(
            not re.fullmatch(r"[0-9a-f]{40}", sha) for sha in patches):
        raise BuildManifestError("invalid or duplicate ordered patch commits")
    if bool(patches) != bool(patch_repository):
        raise BuildManifestError("patch identity requires repository and complete ordered commits together")
    patch_repository = repository_url(patch_repository) if patches else None
    remotes = [repository_url(git(source, "remote", "get-url", name))
               for name in git(source, "remote").splitlines()]
    if baseline.REPOSITORY not in remotes or (patches and patch_repository not in remotes):
        raise BuildManifestError("source/patch repository is not identified by checkout remotes")
    if git(source, "rev-parse", baseline.COMMIT + "^{tree}") != baseline.TREE:
        raise BuildManifestError("base source tree mismatch")
    previous = baseline.COMMIT
    for commit in patches:
        parents = git(source, "show", "-s", "--format=%P", commit).split()
        if parents != [previous]:
            raise BuildManifestError("patch commits must be in complete linear parent order (no merges)")
        previous = commit
    _clean(source, previous)
    return {"repository": baseline.REPOSITORY, "commit": baseline.COMMIT,
            "tree": baseline.TREE, "dirty": False, "patch_repository": patch_repository,
            "patch_commits": patches, "effective_head": previous,
            "effective_tree": git(source, "rev-parse", "HEAD^{tree}"),
            "submodules": _submodules(source)}


def validate(document):
    from jsonschema import Draft202012Validator
    schema = json.loads(SCHEMA_PATH.read_text())
    errors = list(Draft202012Validator(schema).iter_errors(document))
    if errors:
        raise BuildManifestError("build manifest schema violation at " +
                                 "/".join(map(str, errors[0].absolute_path)))
    s = document["source"]
    if (s["repository"], s["commit"], s["tree"]) != (
            baseline.REPOSITORY, baseline.COMMIT, baseline.TREE):
        raise BuildManifestError("manifest source commit/tree does not match active baseline")
    if s["dirty"] or any(x["dirty"] for x in s["submodules"]):
        raise BuildManifestError("dirty source manifest")
    if bool(s["patch_commits"]) != bool(s["patch_repository"]):
        raise BuildManifestError("incomplete patch identity")
    if s["effective_head"] != (s["patch_commits"][-1] if s["patch_commits"] else s["commit"]):
        raise BuildManifestError("effective HEAD does not close patch chain")
    if not s["patch_commits"] and s["effective_tree"] != s["tree"]:
        raise BuildManifestError("unpatched effective tree mismatch")
    if s["patch_repository"]:
        repository_url(s["patch_repository"])
    paths = [x["path"] for x in s["submodules"]]
    if paths != sorted(set(paths)):
        raise BuildManifestError("ambiguous recursive submodule identities")
    return document


def verify(document, source, binary):
    validate(document)
    expected = document["source"]
    observed = observe_source(source, expected["patch_repository"], expected["patch_commits"])
    if observed != expected:
        raise BuildManifestError("source commit/tree/effective state/submodule identity mismatch")
    if file_identity(binary) != document["binary"]:
        raise BuildManifestError("binary digest or size mismatch against build manifest")
    return document


def load(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
        raise BuildManifestError("build manifest must be a bounded regular input")
    with path.open("rb") as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise BuildManifestError("build manifest exceeds size bound")
    return raw, validate(strict_load(raw))


def tool_version(executable):
    try:
        output = subprocess.check_output([executable, "--version"], timeout=15,
                                         stderr=subprocess.STDOUT).decode()
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise BuildManifestError("unable to establish build tool version") from error
    match = re.search(r"\d+(?:\.\d+){1,3}", output.splitlines()[0])
    if not match:
        raise BuildManifestError("unknown build tool version format")
    return {"version": match[0], "version_output_sha256": digest(output.encode()),
            "executable_sha256": file_identity(Path(executable).resolve())["sha256"]}


def build(*, source, build_directory, output, cc, cxx, options=(), patches=(), patch_repository=None,
          build_type="RelWithDebInfo", jobs=4, timeout=7200):
    source = source.resolve(strict=True)
    directory = build_directory.resolve()
    if directory.is_relative_to(source) or source.is_relative_to(directory) or directory.exists():
        raise BuildManifestError("build directory must be new and separate from source")
    if output.resolve().is_relative_to(source) or output.exists():
        raise BuildManifestError("manifest output must be new and outside source")
    producer_sha = digest(Path(__file__).read_bytes())
    state = observe_source(source, patch_repository, patches)
    tool_paths = {name: shutil.which(value) for name, value in
                  {"cc": cc, "cxx": cxx, "cmake": "cmake", "ninja": "ninja", "git": "git"}.items()}
    if not all(tool_paths.values()):
        raise BuildManifestError("required compiler/CMake/Ninja is unavailable")
    versions = {name: tool_version(path) for name, path in tool_paths.items()}
    material = {"CMAKE_BUILD_TYPE": build_type, "CMAKE_EXPORT_COMPILE_COMMANDS": "ON"}
    for value in options:
        key, sep, setting = value.partition("=")
        if not sep or not re.fullmatch(r"[A-Z][A-Za-z0-9_]*", key) or key.startswith("CMAKE_"):
            raise BuildManifestError("options must be unique project NAME=VALUE settings")
        if key in material or not setting or len(setting) > 256:
            raise BuildManifestError("ambiguous material build option")
        material[key] = setting
    configure = [tool_paths["cmake"], "-S", str(source), "-B", str(directory), "-G", "Ninja",
                 "-DCMAKE_MAKE_PROGRAM=" + tool_paths["ninja"],
                 "-DCMAKE_C_COMPILER=" + tool_paths["cc"],
                 "-DCMAKE_CXX_COMPILER=" + tool_paths["cxx"],
                 *["-D" + key + "=" + value for key, value in sorted(material.items())]]
    compile_command = [tool_paths["cmake"], "--build", str(directory), "--target", "shadps4",
                       "--parallel", str(jobs)]
    # Caller environment is part of the private build record by digest. It is
    # never embedded in a run ZIP. No source or target bytes enter the manifest.
    environment_sha = digest(canonical(dict(os.environ)))
    material_environment = {key: os.environ[key] for key in (
        "PATH", "CC", "CXX", "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS",
        "CMAKE_PREFIX_PATH", "PKG_CONFIG_PATH", "PKG_CONFIG_SYSROOT_DIR",
        "LIBRARY_PATH", "LD_LIBRARY_PATH", "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH"
    ) if key in os.environ}
    commands = [configure, compile_command]
    directory.mkdir(parents=True)
    try:
        for i, command in enumerate(commands):
            with (directory / f"build-step-{i}.log").open("wb") as log:
                subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT,
                               timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as error:
        raise BuildManifestError("build failed; private step log retained, no manifest emitted") from error
    if observe_source(source, patch_repository, patches) != state:
        raise BuildManifestError("source changed during build")
    if digest(Path(__file__).read_bytes()) != producer_sha:
        raise BuildManifestError("producer changed during build; no manifest emitted")
    resolved_cache = {}
    for line in (directory / "CMakeCache.txt").read_text().splitlines():
        if line.startswith(("#", "//")) or ":" not in line or "=" not in line:
            continue
        key, rest = line.split(":", 1)
        kind, value = rest.split("=", 1)
        if kind not in {"INTERNAL", "STATIC"}:
            resolved_cache[key] = {"type": kind, "value": value}
    binary = directory / ("shadps4.exe" if os.name == "nt" else "shadps4")
    document = {"schema_version": "bb-shadps4-build/v1",
                "producer": {"version": VERSION, "sha256": producer_sha},
                "source": state,
                "build": {"os": platform.system(), "architecture": platform.machine(),
                          "os_release_sha256": digest(platform.platform().encode()),
                          "tools": versions, "options": material, "commands": commands,
                          "environment_sha256": environment_sha,
                          "material_environment": material_environment, "resolved_cache": resolved_cache,
                          "cmake_cache_sha256": digest((directory / "CMakeCache.txt").read_bytes()),
                          "compile_commands_sha256": digest((directory / "compile_commands.json").read_bytes())},
                "binary": file_identity(binary)}
    validate(document)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(canonical(document) + b"\n")
    return document


def safe_projection(document, raw):
    """Only exact source identities, tool versions and hashes leave the host."""
    b = document["build"]
    return {"manifest_sha256": digest(raw), "manifest_size_bytes": len(raw),
            "schema_version": document["schema_version"], "producer": document["producer"],
            "source": document["source"], "binary": document["binary"],
            "build_os": b["os"], "build_architecture": b["architecture"],
            "tools": b["tools"], "options_sha256": digest(canonical(b["options"])),
            "commands_sha256": digest(canonical(b["commands"])),
            "environment_sha256": b["environment_sha256"],
            "cmake_cache_sha256": b["cmake_cache_sha256"],
            "compile_commands_sha256": b["compile_commands_sha256"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("build")
    create.add_argument("--source", type=Path, required=True)
    create.add_argument("--build-directory", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--cc", default="clang")
    create.add_argument("--cxx", default="clang++")
    create.add_argument("--option", action="append", default=[])
    create.add_argument("--patch-commit", action="append", default=[])
    create.add_argument("--patch-repository")
    create.add_argument("--build-type", choices=["Debug", "Release", "RelWithDebInfo"], default="RelWithDebInfo")
    create.add_argument("--jobs", type=int, choices=range(1, 65), default=4)
    check = sub.add_parser("verify")
    check.add_argument("manifest", type=Path)
    check.add_argument("--source", type=Path, required=True)
    check.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "verify":
            _, document = load(args.manifest)
            verify(document, args.source, args.binary)
        else:
            build(source=args.source, build_directory=args.build_directory, output=args.output,
                  cc=args.cc, cxx=args.cxx, options=args.option, patches=args.patch_commit,
                  patch_repository=args.patch_repository, build_type=args.build_type, jobs=args.jobs)
        print("verified source/build identity")
        return 0
    except (BuildManifestError, OSError) as error:
        print("error: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

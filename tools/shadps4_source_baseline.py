#!/usr/bin/env python3
"""Single source of truth for the pinned BB-BL1 shadPS4 source identity.

``docs/baseline/shadps4-source.json`` is the only place the pinned upstream
repository, commit and tree are declared.  Producers and CI import or resolve
them from here instead of repeating the literals, and :func:`check_repository`
fails closed when a literal reference elsewhere in the repository disagrees.

Provenance literals in fixtures, derived mappings and prose stay literal on
purpose: they record which baseline an artifact was produced against.  The
drift check exists so that those records must agree with this file while the
declared baseline is current, and so a partially applied baseline update fails
instead of silently validating against stale upstream sources.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPOSITORY_ROOT / "docs" / "baseline" / "shadps4-source.json"
SCHEMA_VERSION = "bb-shadps4-source-baseline/v1"

_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_ANY_GIT_SHA = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")

#: Text suffixes walked by the drift check.
_TEXT_SUFFIXES = frozenset(
    {".py", ".md", ".json", ".yml", ".yaml", ".toml", ".txt", ".cpp", ".h", ".hpp"}
)
_SKIP_DIRECTORIES = frozenset({".git", "__pycache__", ".pytest_cache", ".venv"})

#: How many lines after a line naming the upstream repository stay in scope.
#: Provenance records spell the repository and the commit as adjacent constants
#: -- a JSON object, a Python dict, a block of C++ ``constexpr`` values -- so a
#: short window catches them without inspecting unrelated hex elsewhere.
_UPSTREAM_CONTEXT_LINES = 3

#: Line shapes that unambiguously denote the pinned shadPS4 source baseline.
#: Unrelated 40-hex values elsewhere in the repository -- pinned GitHub Action
#: SHAs, per-patch expected digests, this repository's own commits -- do not
#: match any of these and are therefore never inspected.
_REFERENCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"shadps4-emu/shadPS4@(?P<sha>[0-9a-f]{40})"),
    re.compile(r"raw\.githubusercontent\.com/shadps4-emu/shadPS4/(?P<sha>[0-9a-f]{40})"),
    re.compile(r"github\.com/shadps4-emu/shadPS4/(?:blob|commit|tree)/(?P<sha>[0-9a-f]{40})"),
    re.compile(r"--source-commit[=\s]+(?P<sha>[0-9a-f]{40})"),
    re.compile(r"--source-tree[=\s]+(?P<sha>[0-9a-f]{40})"),
    re.compile(
        r"(?:PINNED_)?SOURCE_(?:COMMIT|TREE)\s*=\s*[\"'](?P<sha>[0-9a-f]{40})[\"']"
    ),
)

#: Paths that must not carry the literal at all, because they resolve it.
_DERIVED_PATHS: tuple[str, ...] = (".github/workflows",)


class SourceBaselineError(ValueError):
    """Raised when the pinned source identity cannot be interpreted safely."""


class BaselineDriftError(SourceBaselineError):
    """Raised when a literal baseline reference disagrees with this file."""


def _strict_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourceBaselineError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def loads_strict(text: str) -> Any:
    """Parse JSON while rejecting duplicate members, as the other tools do."""
    try:
        return json.loads(text, object_pairs_hook=_strict_object)
    except json.JSONDecodeError as error:
        raise SourceBaselineError(f"invalid JSON: {error}") from error


def validate_baseline(document: Any) -> dict[str, str]:
    """Validate the declared source identity and return it."""
    expected = {"schema_version", "repository", "repository_slug", "commit", "tree"}
    if not isinstance(document, Mapping) or set(document) != expected:
        raise SourceBaselineError(
            "source baseline must declare exactly "
            + ", ".join(sorted(expected))
        )
    if document["schema_version"] != SCHEMA_VERSION:
        raise SourceBaselineError("unsupported source-baseline schema_version")
    slug = document["repository_slug"]
    if not isinstance(slug, str) or slug != "shadps4-emu/shadPS4":
        raise SourceBaselineError("repository_slug must be shadps4-emu/shadPS4")
    repository = document["repository"]
    if not isinstance(repository, str) or repository != f"https://github.com/{slug}":
        raise SourceBaselineError("repository must be the https URL for repository_slug")
    for field in ("commit", "tree"):
        value = document[field]
        if not isinstance(value, str) or _GIT_SHA.fullmatch(value) is None:
            raise SourceBaselineError(f"{field} must be a 40-character lowercase git SHA")
    return dict(document)


def load(path: Path = BASELINE_PATH) -> dict[str, str]:
    """Read and validate the declared pinned source identity."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SourceBaselineError(f"unable to read {path}") from error
    return validate_baseline(loads_strict(text))


_BASELINE = load()

REPOSITORY: str = _BASELINE["repository"]
REPOSITORY_SLUG: str = _BASELINE["repository_slug"]
COMMIT: str = _BASELINE["commit"]
TREE: str = _BASELINE["tree"]

#: Values a literal shadPS4 baseline reference is allowed to carry.
_CANONICAL_SHAS = frozenset({COMMIT, TREE})


def raw_source_url(relative_path: str) -> str:
    """Build the raw upstream URL for one path at the pinned commit."""
    if relative_path.startswith("/"):
        raise SourceBaselineError("relative_path must not start with '/'")
    return (
        f"https://raw.githubusercontent.com/{REPOSITORY_SLUG}/{COMMIT}/{relative_path}"
    )


def _text_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in _TEXT_SUFFIXES:
            continue
        if any(part in _SKIP_DIRECTORIES for part in path.relative_to(root).parts):
            continue
        yield path


def _iter_json_objects(value: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _iter_json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_json_objects(child)


def _constant_value(value: Any) -> Any:
    """Unwrap ``{"const": x}`` so JSON Schema pins are inspected like values."""
    if isinstance(value, Mapping) and set(value) == {"const"}:
        return value["const"]
    return value


def _names_upstream(value: Any) -> bool:
    unwrapped = _constant_value(value)
    return isinstance(unwrapped, str) and REPOSITORY_SLUG.lower() in unwrapped.lower()


def _labels_source_revision(prefix: str) -> bool:
    """Does the text before a 40-hex value label it as the source commit or tree?

    Records that sit next to the upstream repository also carry values which are
    *not* the baseline -- most often a Git blob SHA-1 for the patched file -- so
    the label decides.  ``commit``/``tree`` qualifies; ``blob`` never does.
    """
    lowered = prefix.lower()
    if "blob" in lowered:
        return False
    return "commit" in lowered or "tree" in lowered


def _check_text(path: Path, relative: str, findings: list[str]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    derived = any(relative.startswith(prefix) for prefix in _DERIVED_PATHS)
    upstream_until = -1
    for number, line in enumerate(text.splitlines(), start=1):
        if derived:
            # A resolving location must carry no pinned literal at all, however
            # it is spelled -- URL, argument, or an inline assertion.
            for match in _ANY_GIT_SHA.finditer(line):
                if match.group(0) in _CANONICAL_SHAS:
                    findings.append(
                        f"{relative}:{number}: resolves the pinned baseline at runtime "
                        f"and must not embed the literal {match.group(0)}"
                    )
            continue
        for pattern in _REFERENCE_PATTERNS:
            for match in pattern.finditer(line):
                sha = match.group("sha")
                if sha not in _CANONICAL_SHAS:
                    findings.append(
                        f"{relative}:{number}: shadPS4 baseline reference {sha} "
                        f"disagrees with docs/baseline/shadps4-source.json ({COMMIT})"
                    )
        if REPOSITORY_SLUG.lower() in line.lower():
            upstream_until = number + _UPSTREAM_CONTEXT_LINES
        if number > upstream_until:
            continue
        for match in _ANY_GIT_SHA.finditer(line):
            sha = match.group(0)
            if sha in _CANONICAL_SHAS or not _labels_source_revision(line[: match.start()]):
                continue
            findings.append(
                f"{relative}:{number}: 40-hex value {sha} labelled as a shadPS4 "
                f"source revision disagrees with "
                f"docs/baseline/shadps4-source.json ({COMMIT})"
            )


def _check_json(path: Path, relative: str, findings: list[str]) -> None:
    try:
        document = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SourceBaselineError):
        return
    for node in _iter_json_objects(document):
        if not any(
            key in {"repository", "repository_slug", "source_repository"}
            and _names_upstream(value)
            for key, value in node.items()
        ):
            continue
        for key in ("commit", "tree", "source_commit", "source_tree"):
            if key not in node:
                continue
            value = _constant_value(node[key])
            if not isinstance(value, str) or _GIT_SHA.fullmatch(value) is None:
                continue
            if value not in _CANONICAL_SHAS:
                findings.append(
                    f"{relative}: shadPS4 object field {key!r}={value} disagrees "
                    f"with docs/baseline/shadps4-source.json ({COMMIT})"
                )


def collect_drift(root: Path = REPOSITORY_ROOT) -> list[str]:
    """Return every literal baseline reference that disagrees with this file."""
    findings: list[str] = []
    baseline_relative = BASELINE_PATH.relative_to(REPOSITORY_ROOT).as_posix()
    for path in _text_files(root):
        relative = path.relative_to(root).as_posix()
        if relative == baseline_relative:
            continue
        _check_text(path, relative, findings)
        if path.suffix == ".json":
            _check_json(path, relative, findings)
    return sorted(set(findings))


def check_repository(root: Path = REPOSITORY_ROOT) -> None:
    """Fail closed when any literal baseline reference has drifted."""
    findings = collect_drift(root)
    if findings:
        raise BaselineDriftError(
            "pinned shadPS4 baseline references disagree with "
            "docs/baseline/shadps4-source.json:\n  " + "\n  ".join(findings)
        )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    field = subparsers.add_parser("field", help="print one declared field")
    field.add_argument("name", choices=sorted(_BASELINE))
    url = subparsers.add_parser("raw-url", help="print the raw upstream URL for a path")
    url.add_argument("path")
    subparsers.add_parser("github-output", help="emit key=value lines for $GITHUB_OUTPUT")
    subparsers.add_parser("check", help="fail closed on drifted literal references")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.command == "field":
            print(_BASELINE[args.name])
        elif args.command == "raw-url":
            print(raw_source_url(args.path))
        elif args.command == "github-output":
            for key in sorted(_BASELINE):
                print(f"{key}={_BASELINE[key]}")
        else:
            check_repository()
            print("pinned shadPS4 source baseline is consistent")
    except SourceBaselineError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

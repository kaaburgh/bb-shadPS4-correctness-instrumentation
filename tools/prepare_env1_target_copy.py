#!/usr/bin/env python3
"""Prepare one disposable target tree and independently verify copied bytes.

The base app is copied to ``app``.  When an update is supplied, it is copied to
the shadPS4-native ``app-UPDATE`` sibling; update files are never merged into
the base app.  Expected identities must be supplied independently; this
command does not establish stock content.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

RECEIPT_NAME = ".bb-env1-disposable-copy.json"
UPDATE_DIR_NAME = "app-UPDATE"
RECEIPT_V1 = "bb-env1-disposable-copy/v1"
RECEIPT_V2 = "bb-env1-disposable-copy/v2"


def _binding(directory):
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("disposable copy component must be a real directory")
    return {"path": str(directory), "device": info.st_dev, "inode": info.st_ino}


def _tree_projection(identity_value):
    return {key: identity_value[key] for key in ("sha256", "file_count", "total_bytes")}


def require_copy_receipt(root, *, require_update=False, expected_resolved_tree=None):
    """Cheap accidental-original guard, not current content verification.

    The receipt is local/private and bound to the creation path and directory
    identity. Copying it to another tree or moving the tree invalidates it.
    This is not an attestation against deliberate forgery or later tree edits.
    """
    root = root.resolve(strict=True)
    path = root / RECEIPT_NAME
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 16384:
        raise ValueError("invalid disposable copy receipt file")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise ValueError("invalid disposable copy receipt")
    for name, directory in (("root", root), ("app", root / "app")):
        if receipt.get(name) != _binding(directory):
            raise ValueError("disposable copy receipt does not match directory")
    schema_version = receipt.get("schema_version")
    if schema_version not in {RECEIPT_V1, RECEIPT_V2} or receipt.get("copy_verified") is not True:
        raise ValueError("unverified disposable copy receipt")
    update_directory = root / UPDATE_DIR_NAME
    if schema_version == RECEIPT_V2:
        if receipt.get("update") != _binding(update_directory):
            raise ValueError("disposable copy receipt does not match app-UPDATE")
        if not isinstance(receipt.get("update_identity_at_creation"), dict):
            raise ValueError("disposable copy receipt lacks update identity")
        resolved = receipt.get("resolved_tree_at_creation")
        if not isinstance(resolved, dict) or set(resolved) != {"sha256", "file_count", "total_bytes"}:
            raise ValueError("disposable copy receipt lacks resolved-tree identity")
    elif update_directory.exists():
        raise ValueError("base-only disposable receipt has an unexpected app-UPDATE sibling")
    if require_update:
        if schema_version != RECEIPT_V2:
            raise ValueError("disposable copy receipt does not bind required app-UPDATE")
        if expected_resolved_tree is not None and receipt["resolved_tree_at_creation"] != _tree_projection(expected_resolved_tree):
            raise ValueError("disposable copy resolved tree does not match the target manifest")
    elif schema_version == RECEIPT_V2:
        raise ValueError("target manifest does not permit an app-UPDATE sibling")
    return receipt


def _identity_records(root, namespace="app"):
    records = []
    total = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError("target contains a link or nonregular entry")
        for name in names:
            path = Path(directory) / name
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            size = path.stat().st_size
            relative = (namespace + "/" + path.relative_to(root).as_posix()).encode("utf-8")
            if b"\n" in relative or b"\r" in relative:
                raise ValueError("ambiguous target namespace")
            records.append((relative, relative + b"\0" + str(size).encode() + b"\0" + digest.encode() + b"\n"))
            total += size
    records.sort()
    return records, total


def identity(root):
    records, total = _identity_records(root)
    return {"sha256": hashlib.sha256(b"".join(item[1] for item in records)).hexdigest(),
            "file_count": len(records), "total_bytes": total}


def resolved_identity(base, update):
    """Return the app namespace after the update overlay wins over base files."""
    base_records, _base_total = _identity_records(base)
    update_records, _update_total = _identity_records(update)
    by_path = {path: record for path, record in base_records}
    by_path.update({path: record for path, record in update_records})
    records = sorted(by_path.items())
    total = sum(int(record.split(b"\0", 2)[1]) for _path, record in records)
    return {"sha256": hashlib.sha256(b"".join(record for _path, record in records)).hexdigest(),
            "file_count": len(records), "total_bytes": total}


def prepare(source, destination, expected, *, update_source=None, update_expected=None,
            verify_existing=False):
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if (update_source is None) != (update_expected is None):
        raise ValueError("update source and expected update identity must be supplied together")
    if update_source is not None:
        update_source = update_source.resolve(strict=True)
        if update_source == source:
            raise ValueError("base and update sources must be separate directories")
    original_sources = [source] + ([update_source] if update_source is not None else [])
    if ((destination.exists() and not verify_existing)
            or any(destination == original or destination.is_relative_to(original)
                   or original.is_relative_to(destination) for original in original_sources)):
        raise ValueError("destination must be new and separate from source")
    if identity(source) != expected:
        raise ValueError("source target identity mismatch")
    if update_source is not None and identity(update_source) != update_expected:
        raise ValueError("update source identity mismatch")
    if verify_existing:
        # One-time migration of a pre-receipt working copy. Rehash both trees and
        # reject hardlinks as well as the symlinks rejected by identity().
        app = destination / "app"
        if not app.is_dir() or app.is_symlink() or (destination / RECEIPT_NAME).exists():
            raise ValueError("existing copy must have a real app directory and no receipt")
        update_destination = destination / UPDATE_DIR_NAME
        if update_source is None and update_destination.exists():
            raise ValueError("existing copy has an update but no independently supplied update source")
        for tree in (app, update_destination) if update_destination.exists() else (app,):
            for directory, _, names in os.walk(tree, followlinks=False):
                for name in names:
                    if (Path(directory) / name).lstat().st_nlink != 1:
                        raise ValueError("existing copy contains hardlinks")
        if update_source is not None and not update_destination.exists():
            shutil.copytree(update_source, update_destination, symlinks=True)
    else:
        destination.mkdir(parents=True, mode=0o700)
        shutil.copytree(source, destination / "app", symlinks=True)
        if update_source is not None:
            shutil.copytree(update_source, destination / UPDATE_DIR_NAME, symlinks=True)
    # Independent reads of destination and original after copying, not the
    # digest accumulated by the write operation being validated.
    if identity(destination / "app") != expected or identity(source) != expected:
        raise ValueError("target changed or copy verification failed")
    receipt = {"schema_version": RECEIPT_V1, "copy_verified": True,
               "identity_at_creation": expected}
    for name, directory in (("root", destination), ("app", destination / "app")):
        receipt[name] = _binding(directory)
    if update_source is not None:
        update_destination = destination / UPDATE_DIR_NAME
        if identity(update_destination) != update_expected or identity(update_source) != update_expected:
            raise ValueError("update changed or copy verification failed")
        receipt.update({
            "schema_version": RECEIPT_V2,
            "update": _binding(update_destination),
            "update_identity_at_creation": update_expected,
            "resolved_tree_at_creation": resolved_identity(destination / "app", update_destination),
        })
    with (destination / RECEIPT_NAME).open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, sort_keys=True)
    result = {"schema_version": "bb-env1-target-copy/v2" if update_source is not None else "bb-env1-target-copy/v1",
              "source_pre_verified": True, "source_post_verified": True, "copy_verified": True,
              "identity": expected, "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if update_source is not None:
        result.update({"update_identity": update_expected,
                       "resolved_tree": receipt["resolved_tree_at_creation"]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-file-count", type=int, required=True)
    parser.add_argument("--expected-total-bytes", type=int, required=True)
    parser.add_argument("--update-source", type=Path)
    parser.add_argument("--update-expected-sha256")
    parser.add_argument("--update-expected-file-count", type=int)
    parser.add_argument("--update-expected-total-bytes", type=int)
    parser.add_argument("--verify-existing", action="store_true",
                        help="verify a separate existing copy once and create its missing receipt")
    args = parser.parse_args()
    expected = {"sha256": args.expected_sha256, "file_count": args.expected_file_count,
                "total_bytes": args.expected_total_bytes}
    update_flags = (args.update_expected_sha256, args.update_expected_file_count,
                    args.update_expected_total_bytes)
    if args.update_source is None and any(value is not None for value in update_flags):
        parser.error("update expected identity requires --update-source")
    if args.update_source is not None and any(value is None for value in update_flags):
        parser.error("--update-source requires all update expected identity flags")
    update_expected = None
    if args.update_source is not None:
        update_expected = {"sha256": args.update_expected_sha256,
                           "file_count": args.update_expected_file_count,
                           "total_bytes": args.update_expected_total_bytes}
    print(json.dumps(prepare(args.source, args.destination, expected,
                             update_source=args.update_source,
                             update_expected=update_expected,
                             verify_existing=args.verify_existing), sort_keys=True))


if __name__ == "__main__":
    main()

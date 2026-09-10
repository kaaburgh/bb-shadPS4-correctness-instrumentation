#!/usr/bin/env python3
"""Copy one explicit base app tree and independently verify all copied bytes.

No adjacent update, save or profile is selected. The expected namespace digest
must be supplied independently; this command does not establish stock content.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

RECEIPT_NAME = ".bb-env1-disposable-copy.json"


def require_copy_receipt(root):
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
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or receipt.get(name) != {
            "path": str(directory), "device": info.st_dev, "inode": info.st_ino
        }:
            raise ValueError("disposable copy receipt does not match directory")
    if receipt.get("schema_version") != "bb-env1-disposable-copy/v1" or receipt.get("copy_verified") is not True:
        raise ValueError("unverified disposable copy receipt")


def identity(root):
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
            relative = ("app/" + path.relative_to(root).as_posix()).encode("utf-8")
            if b"\n" in relative or b"\r" in relative:
                raise ValueError("ambiguous target namespace")
            records.append((relative, relative + b"\0" + str(size).encode() + b"\0" + digest.encode() + b"\n"))
            total += size
    records.sort()
    return {"sha256": hashlib.sha256(b"".join(item[1] for item in records)).hexdigest(),
            "file_count": len(records), "total_bytes": total}


def prepare(source, destination, expected, *, verify_existing=False):
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if (destination.exists() and not verify_existing) or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("destination must be new and separate from source")
    if identity(source) != expected:
        raise ValueError("source target identity mismatch")
    if verify_existing:
        # One-time migration of a pre-receipt working copy. Rehash both trees and
        # reject hardlinks as well as the symlinks rejected by identity().
        app = destination / "app"
        if not app.is_dir() or app.is_symlink() or (destination / RECEIPT_NAME).exists():
            raise ValueError("existing copy must have a real app directory and no receipt")
        for directory, _, names in os.walk(app, followlinks=False):
            for name in names:
                if (Path(directory) / name).lstat().st_nlink != 1:
                    raise ValueError("existing copy contains hardlinks")
    else:
        destination.mkdir(parents=True, mode=0o700)
        shutil.copytree(source, destination / "app", symlinks=True)
    # Independent reads of destination and original after copying, not the
    # digest accumulated by the write operation being validated.
    if identity(destination / "app") != expected or identity(source) != expected:
        raise ValueError("target changed or copy verification failed")
    receipt = {"schema_version": "bb-env1-disposable-copy/v1", "copy_verified": True,
               "identity_at_creation": expected}
    for name, directory in (("root", destination), ("app", destination / "app")):
        info = directory.stat()
        receipt[name] = {"path": str(directory), "device": info.st_dev, "inode": info.st_ino}
    with (destination / RECEIPT_NAME).open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, sort_keys=True)
    return {"schema_version": "bb-env1-target-copy/v1", "source_pre_verified": True,
            "source_post_verified": True, "copy_verified": True, "identity": expected,
            "producer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-file-count", type=int, required=True)
    parser.add_argument("--expected-total-bytes", type=int, required=True)
    parser.add_argument("--verify-existing", action="store_true",
                        help="verify a separate existing copy once and create its missing receipt")
    args = parser.parse_args()
    expected = {"sha256": args.expected_sha256, "file_count": args.expected_file_count,
                "total_bytes": args.expected_total_bytes}
    print(json.dumps(prepare(args.source, args.destination, expected, verify_existing=args.verify_existing), sort_keys=True))


if __name__ == "__main__":
    main()

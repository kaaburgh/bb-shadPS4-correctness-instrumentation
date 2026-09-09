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


def prepare(source, destination, expected):
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("destination must be new and separate from source")
    if identity(source) != expected:
        raise ValueError("source target identity mismatch")
    destination.mkdir(parents=True, mode=0o700)
    shutil.copytree(source, destination / "app", symlinks=True)
    # Independent reads of destination and original after copying, not the
    # digest accumulated by the write operation being validated.
    if identity(destination / "app") != expected or identity(source) != expected:
        raise ValueError("target changed or copy verification failed")
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
    args = parser.parse_args()
    expected = {"sha256": args.expected_sha256, "file_count": args.expected_file_count,
                "total_bytes": args.expected_total_bytes}
    print(json.dumps(prepare(args.source, args.destination, expected), sort_keys=True))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate an artifact-hashed CI lock from an exact-version snapshot."""

from __future__ import annotations

import argparse
import hashlib
import platform
import subprocess
import sys
import tempfile
from pathlib import Path


def read_requirements(path: Path) -> list[str]:
    requirements = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line or " " in line:
            raise ValueError(f"Expected one exact requirement per line: {line!r}")
        requirements.append(line)
    return requirements


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_hash(requirement: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--disable-pip-version-check",
                "--no-deps",
                "--only-binary=:all:",
                "--dest",
                str(target),
                requirement,
            ],
            check=True,
        )
        artifacts = [path for path in target.iterdir() if path.is_file()]
        if len(artifacts) != 1:
            raise RuntimeError(f"Expected one wheel for {requirement}, found {artifacts}")
        return sha256(artifacts[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()

    rows = [(requirement, download_hash(requirement)) for requirement in read_requirements(args.source)]
    header = [
        "# Artifact-authenticated CI lock.",
        f"# Python {sys.version_info.major}.{sys.version_info.minor}; {platform.system()} {platform.machine()}.",
        f"# Generated from {args.source.as_posix()}; review hashes before merge.",
        "",
    ]
    body = [f"{requirement} --hash=sha256:{digest}" for requirement, digest in rows]
    args.target.write_text("\n".join([*header, *body, ""]), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

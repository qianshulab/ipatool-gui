#!/usr/bin/env python
"""Verify the pinned ipatool release inputs without using Apple credentials."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPOSITORY_ROOT / "third_party" / "ipatool" / "2.3.2" / "manifest.json"
PYTHON_MANIFEST_PATH = REPOSITORY_ROOT / "third_party" / "python" / "manifest.json"
LOCK_PATH = REPOSITORY_ROOT / "requirements-lock.txt"
EXPECTED_VERSION_OUTPUT = "ipatool version 2.3.2"
BOOTSTRAP_DISTRIBUTIONS = frozenset({"pip", "wheel"})


def normalize_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_locked_requirements(path: Path) -> dict[str, str]:
    """Parse the pinned top-level requirement lines from a hashed pip lock."""
    locked = {}
    pattern = re.compile(
        r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\]+)\s+\\$"
    )
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line or line.startswith((" ", "#")):
            continue
        match = pattern.fullmatch(line)
        if match is None:
            raise RuntimeError(
                f"invalid locked requirement at {path.name}:{line_number}"
            )
        name = normalize_distribution_name(match.group(1))
        if name in locked:
            raise RuntimeError(f"duplicate locked distribution: {name}")
        locked[name] = match.group(2)
    if not locked:
        raise RuntimeError("requirements lock is empty")
    return locked


def verify_python_build_environment(
    python_manifest: dict,
    locked: dict[str, str],
) -> None:
    expected_python = python_manifest["build_environment"]["python"]
    actual_python = platform.python_version()
    expected_minor = ".".join(expected_python.split(".")[:2])
    actual_minor = ".".join(actual_python.split(".")[:2])
    if actual_minor != expected_minor:
        raise RuntimeError(
            f"Python minor version mismatch: expected {expected_minor}, got {actual_python}"
        )
    if os.environ.get("PYTHONPATH"):
        raise RuntimeError("PYTHONPATH must be empty for a release build")

    installed = {}
    for distribution in metadata.distributions():
        raw_name = distribution.metadata.get("Name")
        if not raw_name:
            raise RuntimeError("installed distribution is missing Name metadata")
        name = normalize_distribution_name(raw_name)
        if name in installed:
            raise RuntimeError(f"duplicate installed distribution: {name}")
        installed[name] = distribution.version

    missing = sorted(set(locked) - set(installed))
    extra = sorted(set(installed) - set(locked) - BOOTSTRAP_DISTRIBUTIONS)
    mismatched = sorted(
        name
        for name in set(locked) & set(installed)
        if locked[name] != installed[name]
    )
    if missing or extra or mismatched:
        raise RuntimeError(
            "installed environment does not match lock; "
            f"missing={missing}, extra={extra}, mismatched={mismatched}"
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, expected_size: int, expected_sha256: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"missing required file: {path.relative_to(REPOSITORY_ROOT)}")
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        raise RuntimeError(
            f"size mismatch for {path.name}: expected {expected_size}, got {actual_size}"
        )
    actual_sha256 = sha256(path)
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"SHA-256 mismatch for {path.name}: expected {expected_sha256}, got {actual_sha256}"
        )


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    asset = manifest["artifacts"]["windows_amd64_executable"]
    bundled = REPOSITORY_ROOT / asset["path"]
    verify_file(bundled, asset["size_bytes"], asset["sha256"])

    license_metadata = manifest["license"]
    license_path = REPOSITORY_ROOT / license_metadata["path"]
    verify_file(
        license_path,
        license_metadata["size_bytes"],
        license_metadata["sha256"],
    )

    version = subprocess.run(
        [str(bundled), "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )
    if version.returncode != 0 or version.stdout.strip() != EXPECTED_VERSION_OUTPUT:
        raise RuntimeError(
            "unexpected ipatool --version result: "
            f"rc={version.returncode}, stdout={version.stdout.strip()!r}, "
            f"stderr={version.stderr.strip()!r}"
        )

    login_help = subprocess.run(
        [str(bundled), "auth", "login", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )
    if login_help.returncode != 0 or "--auth-code" not in login_help.stdout:
        raise RuntimeError("ipatool auth login --help does not expose --auth-code")

    python_manifest = json.loads(PYTHON_MANIFEST_PATH.read_text(encoding="utf-8"))
    locked = parse_locked_requirements(LOCK_PATH)
    verify_python_build_environment(python_manifest, locked)
    verified_packages = []
    for package in python_manifest["packages"]:
        installed_version = metadata.version(package["name"])
        if installed_version != package["version"]:
            raise RuntimeError(
                f"version mismatch for {package['name']}: "
                f"expected {package['version']}, got {installed_version}"
            )
        license_path = REPOSITORY_ROOT / package["license_path"]
        verify_file(
            license_path,
            package["license_size_bytes"],
            package["license_sha256"],
        )
        verified_packages.append(f"{package['name']}=={installed_version}")

    print(
        "verified ipatool 2.3.2: "
        f"size={bundled.stat().st_size}, sha256={sha256(bundled)}"
    )
    print("verified build packages: " + ", ".join(verified_packages))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        OSError,
        KeyError,
        ValueError,
        RuntimeError,
        metadata.PackageNotFoundError,
        subprocess.SubprocessError,
    ) as error:
        print(f"release input verification failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error

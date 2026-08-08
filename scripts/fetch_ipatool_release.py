#!/usr/bin/env python3
"""Fetch one pinned official ipatool release member for packaging."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import stat
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from core.ipatool_release import (
    IPATOOL_RELEASE_URLS,
    IPAToolRelease,
    get_ipatool_release,
)

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


def _matches_digest(actual: str, expected: str) -> bool:
    return hmac.compare_digest(actual.lower(), expected.strip().lower())


def download_verified_archive(release: IPAToolRelease, destination: Path) -> Path:
    parsed = urlparse(release.archive_url)
    if (
        release.archive_url not in IPATOOL_RELEASE_URLS
        or parsed.scheme != "https"
        or (parsed.hostname or "").casefold() != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        raise RuntimeError("release URL is not in the pinned GitHub contract")

    request = Request(release.archive_url, headers={"User-Agent": "ipatool-gui-release"})
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.part")
    digest = hashlib.sha256()
    downloaded = 0
    try:
        with urlopen(request, timeout=30) as response, temporary.open("xb") as stream:  # nosec B310
            content_length = int(response.headers.get("content-length", "0"))
            if content_length not in (0, release.archive_size_bytes):
                raise RuntimeError("release archive Content-Length mismatch")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > min(MAX_ARCHIVE_BYTES, release.archive_size_bytes):
                    raise RuntimeError("release archive exceeds its pinned size")
                stream.write(chunk)
                digest.update(chunk)

        if downloaded != release.archive_size_bytes:
            raise RuntimeError("release archive size mismatch")
        if not _matches_digest(digest.hexdigest(), release.archive_sha256):
            raise RuntimeError("release archive SHA-256 mismatch")
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def extract_verified_member(
    archive_path: Path,
    release: IPAToolRelease,
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / Path(release.member_path).name
    temporary = target.with_name(f".{target.name}.part")
    digest = hashlib.sha256()
    written = 0
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = archive.getmembers()
            if (
                len(members) != 1
                or members[0].name != release.member_path
                or not members[0].isfile()
                or members[0].issym()
                or members[0].islnk()
            ):
                raise RuntimeError("release archive member contract mismatch")
            source = archive.extractfile(members[0])
            if source is None:
                raise RuntimeError("release archive member cannot be read")
            with source, temporary.open("xb") as destination:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > release.member_size_bytes:
                        raise RuntimeError("release member exceeds its pinned size")
                    destination.write(chunk)
                    digest.update(chunk)

        if written != release.member_size_bytes:
            raise RuntimeError("release member size mismatch")
        if not _matches_digest(digest.hexdigest(), release.member_sha256):
            raise RuntimeError("release member SHA-256 mismatch")
        temporary.chmod(temporary.stat().st_mode | stat.S_IXUSR)
        os.replace(temporary, target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--system", required=True, choices=("Windows", "Darwin", "Linux"))
    parser.add_argument("--arch", required=True, choices=("amd64", "arm64"))
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()

    release = get_ipatool_release(args.system, args.arch)
    with tempfile.TemporaryDirectory(prefix="ipatool-release-") as temp_dir:
        archive_path = Path(temp_dir) / release.archive_name
        download_verified_archive(release, archive_path)
        output = extract_verified_member(archive_path, release, Path(args.output_dir))

    print(f"IPATOOL_PATH={output.resolve()}")
    print(f"IPATOOL_SIZE={output.stat().st_size}")
    print(f"IPATOOL_SHA256={release.member_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

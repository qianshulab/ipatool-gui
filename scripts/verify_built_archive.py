#!/usr/bin/env python3
"""Verify controlled resources embedded in a PyInstaller CArchive."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path, PurePosixPath
from typing import Callable

from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.ipatool_release import get_ipatool_release  # noqa: E402


class ArchiveVerificationError(RuntimeError):
    """Raised when a built executable violates the release archive contract."""


_WINDOWS_RESERVED_BASENAMES = frozenset(
    {"con", "prn", "aux", "nul", "clock$", "conin$", "conout$"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
    | {f"com{number}" for number in "¹²³"}
    | {f"lpt{number}" for number in "¹²³"}
)

CONTROLLED_THIRD_PARTY_FILES = (
    "third_party/ipatool/2.3.2/LICENSE",
    "third_party/ipatool/2.3.2/manifest.json",
    "third_party/python/PyInstaller/6.21.0/COPYING.txt",
    "third_party/python/PyQt6/6.11.0/LICENSE",
    "third_party/python/PyQt6-Qt6/6.11.1/LICENSE",
    "third_party/python/PyQt6-sip/13.12.0/LICENSE",
    "third_party/python/manifest.json",
)


def _normalized_archive_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    parts = normalized.split("/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or any(part in ("", ".", "..") for part in parts)
        or any(":" in part for part in parts)
        or any(part.endswith((".", " ")) for part in parts)
        or any(any(ord(character) < 32 for character in part) for part in parts)
        or any(
            part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_BASENAMES
            for part in parts
        )
    ):
        raise ArchiveVerificationError(f"unsafe CArchive member name: {name!r}")
    return path.as_posix()


class StrictCArchiveReader(CArchiveReader):
    """CArchive reader that rejects names lost by the upstream dict parser."""

    @classmethod
    def _parse_toc(cls, data):
        seen = {}
        cursor = 0
        while cursor < len(data):
            header_end = cursor + cls._TOC_ENTRY_LENGTH
            if header_end > len(data):
                raise ArchiveVerificationError("truncated CArchive TOC header")
            (
                entry_length,
                _entry_offset,
                _data_length,
                _uncompressed_length,
                _compression_flag,
                typecode,
            ) = struct.unpack(cls._TOC_ENTRY_FORMAT, data[cursor:header_end])
            if (
                entry_length <= cls._TOC_ENTRY_LENGTH
                or entry_length % 16 != 0
            ):
                raise ArchiveVerificationError("invalid CArchive TOC entry length")
            entry_end = cursor + entry_length
            if entry_end > len(data):
                raise ArchiveVerificationError("truncated CArchive TOC entry")
            name_field = data[header_end:entry_end]
            terminator = name_field.find(b"\0")
            if (
                terminator <= 0
                or any(name_field[terminator:])
            ):
                raise ArchiveVerificationError(
                    "CArchive TOC name is not canonically NUL-terminated"
                )
            try:
                name = name_field[:terminator].decode("utf-8")
                decoded_typecode = typecode.decode("ascii")
            except UnicodeDecodeError as error:
                raise ArchiveVerificationError(
                    "CArchive TOC contains invalid UTF-8 or typecode"
                ) from error
            if decoded_typecode != "o":
                normalized = _normalized_archive_name(name)
                collision_key = normalized.casefold()
                previous = seen.get(collision_key)
                if previous is not None:
                    raise ArchiveVerificationError(
                        f"duplicate or colliding CArchive members: {previous!r}, {name!r}"
                    )
                seen[collision_key] = name
            cursor = entry_end
        if cursor != len(data):
            raise ArchiveVerificationError("invalid CArchive TOC boundary")
        return super()._parse_toc(data)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def expected_controlled_files(root: Path) -> dict[str, bytes]:
    root = root.resolve()
    release = get_ipatool_release("Windows", "amd64")
    sources = {
        "LICENSE": root / "LICENSE",
        "THIRD_PARTY_NOTICES.md": root / "THIRD_PARTY_NOTICES.md",
        "assets/exe.png": root / "assets" / "exe.png",
        f"ipatool-{release.version}-windows-amd64.exe": (
            root / f"ipatool-{release.version}-windows-amd64.exe"
        ),
    }
    for relative in CONTROLLED_THIRD_PARTY_FILES:
        sources[relative] = root / relative

    missing = [
        str(path)
        for path in sources.values()
        if not path.is_file() or path.is_symlink()
    ]
    if missing:
        raise ArchiveVerificationError(
            "missing controlled release inputs: " + ", ".join(missing)
        )
    return {name: path.read_bytes() for name, path in sources.items()}


def _is_controlled(name: str) -> bool:
    folded = name.casefold()
    return (
        folded in {
            "license",
            "third_party_notices.md",
        }
        or (
            folded.startswith("ipatool-")
            and folded.endswith("-windows-amd64.exe")
        )
        or folded.startswith("assets/")
        or folded.startswith("third_party/")
    )


def verify_archive(
    executable: Path,
    root: Path,
    *,
    reader_factory: Callable[[str], object] = StrictCArchiveReader,
) -> dict[str, int | str]:
    expected = expected_controlled_files(root)
    reader = reader_factory(str(executable))

    archive_names = {}
    collision_names = {}
    for raw_name in reader.toc:
        normalized = _normalized_archive_name(raw_name)
        collision_key = normalized.casefold()
        previous = collision_names.get(collision_key)
        if previous is not None:
            raise ArchiveVerificationError(
                f"duplicate or colliding CArchive members: {previous!r}, {raw_name!r}"
            )
        collision_names[collision_key] = raw_name
        archive_names[normalized] = raw_name

    actual_controlled = {
        name for name in archive_names if _is_controlled(name)
    }
    expected_names = set(expected)
    if actual_controlled != expected_names:
        missing = sorted(expected_names - actual_controlled)
        extra = sorted(actual_controlled - expected_names)
        raise ArchiveVerificationError(
            f"controlled CArchive set mismatch; missing={missing}, extra={extra}"
        )

    for name, expected_bytes in expected.items():
        actual = reader.extract(archive_names[name])
        if not isinstance(actual, bytes):
            raise ArchiveVerificationError(f"CArchive member is not bytes: {name}")
        if len(actual) != len(expected_bytes) or _sha256(actual) != _sha256(expected_bytes):
            raise ArchiveVerificationError(
                f"CArchive member bytes differ from release input: {name}"
            )

    release = get_ipatool_release("Windows", "amd64")
    embedded_name = f"ipatool-{release.version}-windows-amd64.exe"
    embedded = expected[embedded_name]
    if (
        len(embedded) != release.member_size_bytes
        or _sha256(embedded) != release.member_sha256
    ):
        raise ArchiveVerificationError("embedded ipatool input violates immutable release tuple")

    return {
        "controlled_files": len(expected),
        "embedded_ipatool_size": len(embedded),
        "embedded_ipatool_sha256": _sha256(embedded),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
    )
    args = parser.parse_args()
    result = verify_archive(args.executable, args.root)
    print("BUILT_ARCHIVE_OK " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

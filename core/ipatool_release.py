# -*- coding: utf-8 -*-
"""Immutable provenance contract for the supported official ipatool release."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


IPATOOL_VERSION = "2.3.2"
IPATOOL_SOURCE_COMMIT = "ab79e429d5d5d3da6879711f6e04b8a240aabd94"


@dataclass(frozen=True, slots=True)
class IPAToolRelease:
    system: str
    arch: str
    version: str
    archive_name: str
    archive_url: str
    archive_size_bytes: int
    archive_sha256: str
    member_path: str
    member_size_bytes: int
    member_sha256: str

    def member_metadata(self) -> dict[str, str | int]:
        return {
            "path": self.member_path,
            "size_bytes": self.member_size_bytes,
            "sha256": self.member_sha256,
        }


def _release(
    system: str,
    arch: str,
    archive_size_bytes: int,
    archive_sha256: str,
    member_size_bytes: int,
    member_sha256: str,
) -> IPAToolRelease:
    platform_name = {
        "Windows": "windows",
        "Darwin": "macos",
        "Linux": "linux",
    }[system]
    archive_name = f"ipatool-{IPATOOL_VERSION}-{platform_name}-{arch}.tar.gz"
    member_suffix = ".exe" if system == "Windows" else ""
    return IPAToolRelease(
        system=system,
        arch=arch,
        version=IPATOOL_VERSION,
        archive_name=archive_name,
        archive_url=(
            "https://github.com/majd/ipatool/releases/download/"
            f"v{IPATOOL_VERSION}/{archive_name}"
        ),
        archive_size_bytes=archive_size_bytes,
        archive_sha256=archive_sha256,
        member_path=(
            f"bin/ipatool-{IPATOOL_VERSION}-{platform_name}-{arch}{member_suffix}"
        ),
        member_size_bytes=member_size_bytes,
        member_sha256=member_sha256,
    )


_RELEASES = {
    ("Windows", "amd64"): _release(
        "Windows",
        "amd64",
        15264571,
        "6352441f6f91df7947aaa203b19cb7d3c9d77920fc466dd784ff9cae88db5c92",
        33779712,
        "7da96104954d4a9625dcec5f18bf64df62107ada37822ca953e2fe503a69d079",
    ),
    ("Windows", "arm64"): _release(
        "Windows",
        "arm64",
        14200473,
        "9acb5ec15577ba84dffc14c428022fe70f5be44df33fcd6158bbb5fdf18ad668",
        32168960,
        "597bfe13762137eda37ec10e6efb2decb074c0f801e65474b5d0f6f1b8899de7",
    ),
    ("Darwin", "amd64"): _release(
        "Darwin",
        "amd64",
        16053466,
        "d1861a0e00ae78ca1982530b7732b3e105dc789eed99a767b4038b6b9473424e",
        34539872,
        "9d896b22fead634334164114c42ce3c86a31053601130689171c03411c4fed31",
    ),
    ("Darwin", "arm64"): _release(
        "Darwin",
        "arm64",
        15109893,
        "7c5a35a532de21240fcd0d5a4f3204c97dcb4b1e43df05b2487ad12378c0c044",
        33204738,
        "d7fe54d4fff9adbd4dbe10267c098ee22ae3e35b71b9af4536ee8fe8bd7173d4",
    ),
    ("Linux", "amd64"): _release(
        "Linux",
        "amd64",
        14943906,
        "7555b67612a196bad1961c3a6fbc2d1f115b5e7a4925e9b4a285ed2b99082077",
        33673600,
        "33a2838cc3eda6bf620f18873c58ff7a6c7224dbcf88cb726d094caa60ef11fb",
    ),
    ("Linux", "arm64"): _release(
        "Linux",
        "arm64",
        13896132,
        "2e7ed31d76eaa145a6147985fe5fbae1eaa4ad213648f74bc30a2b059cbd39c7",
        32230896,
        "b192160f94361783706be792bcca2a1e30d181c9b44f55c85296e3863c824753",
    ),
}

IPATOOL_RELEASES: Mapping[tuple[str, str], IPAToolRelease] = MappingProxyType(
    _RELEASES
)
IPATOOL_RELEASE_URLS = frozenset(
    release.archive_url for release in IPATOOL_RELEASES.values()
)


def get_ipatool_release(system: str, arch: str) -> IPAToolRelease:
    try:
        return IPATOOL_RELEASES[(system, arch)]
    except KeyError as error:
        raise ValueError(f"unsupported ipatool release target: {system}/{arch}") from error

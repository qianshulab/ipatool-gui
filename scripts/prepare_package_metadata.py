"""Prepare platform package metadata from the application's version source."""

from __future__ import annotations

import argparse
import os
import plistlib
from pathlib import Path

from app_metadata import (
    APP_BUNDLE_IDENTIFIER,
    APP_DEVELOPER,
    APP_NAME,
    APP_VERSION,
    COPYRIGHT_YEAR,
)


def _version_quad() -> tuple[int, int, int, int]:
    parts = APP_VERSION.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"APP_VERSION must use major.minor.patch: {APP_VERSION!r}")
    values = tuple(int(part) for part in parts)
    if any(value > 65535 for value in values):
        raise ValueError("APP_VERSION components must fit Windows version fields")
    return (*values, 0)


def write_windows_version_file(output: Path) -> None:
    """Write the PyInstaller version-resource definition used by Windows builds."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    version = _version_quad()
    output.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version!r},
    prodvers={version!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404B0',
        [
          StringStruct('CompanyName', 'qianshulab'),
          StringStruct('FileDescription', '{APP_NAME}'),
          StringStruct('FileVersion', '{APP_VERSION}'),
          StringStruct('InternalName', 'IPA-Download-Tool'),
          StringStruct('LegalCopyright', 'Copyright © {COPYRIGHT_YEAR} {APP_DEVELOPER}'),
          StringStruct('OriginalFilename', 'IPA-Download-Tool.exe'),
          StringStruct('ProductName', '{APP_NAME}'),
          StringStruct('ProductVersion', '{APP_VERSION}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""",
        encoding="utf-8",
        newline="\n",
    )


def stamp_macos_plist(plist_path: Path) -> None:
    """Apply the application version and bundle identifier to a built macOS app."""
    plist_path = Path(plist_path)
    with plist_path.open("rb") as handle:
        metadata = plistlib.load(handle)
    metadata["CFBundleShortVersionString"] = APP_VERSION
    metadata["CFBundleVersion"] = APP_VERSION
    metadata["CFBundleIdentifier"] = APP_BUNDLE_IDENTIFIER
    with plist_path.open("wb") as handle:
        plistlib.dump(metadata, handle, fmt=plistlib.FMT_XML, sort_keys=True)


def check_release_ref(ref_type: str, ref_name: str) -> None:
    """Reject a release tag that does not match the packaged application version."""
    if ref_type == "tag" and ref_name != f"v{APP_VERSION}":
        raise ValueError(
            f"release tag must be v{APP_VERSION}, received {ref_name or '<empty>'}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    operations = parser.add_mutually_exclusive_group(required=True)
    operations.add_argument("--check-release-ref", action="store_true")
    operations.add_argument("--windows-version-file", type=Path)
    operations.add_argument("--macos-plist", type=Path)
    args = parser.parse_args()

    if args.check_release_ref:
        ref_type = os.environ.get("GITHUB_REF_TYPE", "")
        ref_name = os.environ.get("GITHUB_REF_NAME", "")
        check_release_ref(ref_type, ref_name)
        if ref_type == "tag":
            print(f"RELEASE_VERSION={APP_VERSION} TAG={ref_name}")
        else:
            print(f"APPLICATION_VERSION={APP_VERSION}")
    elif args.windows_version_file is not None:
        write_windows_version_file(args.windows_version_file)
        print(f"WINDOWS_VERSION_FILE={args.windows_version_file} VERSION={APP_VERSION}")
    else:
        stamp_macos_plist(args.macos_plist)
        print(f"MACOS_PLIST={args.macos_plist} VERSION={APP_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

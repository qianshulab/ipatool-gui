import hashlib
import io
import os
import tarfile
import tempfile
import unittest
from pathlib import Path

from core.ipatool_release import IPAToolRelease
from scripts.fetch_ipatool_release import extract_verified_member


class FetchIPAToolReleaseTests(unittest.TestCase):
    @staticmethod
    def make_release(payload: bytes) -> IPAToolRelease:
        return IPAToolRelease(
            system="Darwin",
            arch="arm64",
            version="2.3.2",
            archive_name="synthetic.tar.gz",
            archive_url="https://github.com/example/synthetic.tar.gz",
            archive_size_bytes=0,
            archive_sha256="0" * 64,
            member_path="bin/ipatool-2.3.2-macos-arm64",
            member_size_bytes=len(payload),
            member_sha256=hashlib.sha256(payload).hexdigest(),
        )

    @staticmethod
    def write_archive(path: Path, members: dict[str, bytes]) -> None:
        with tarfile.open(path, "w:gz") as archive:
            for name, payload in members.items():
                info = tarfile.TarInfo(name=name)
                info.size = len(payload)
                info.mode = 0o755
                archive.addfile(info, io.BytesIO(payload))

    def test_extracts_only_the_pinned_member_and_marks_it_executable(self):
        payload = b"synthetic pinned ipatool"
        release = self.make_release(payload)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "release.tar.gz"
            self.write_archive(archive_path, {release.member_path: payload})

            output = extract_verified_member(archive_path, release, root / "output")

            self.assertEqual(output.name, "ipatool-2.3.2-macos-arm64")
            self.assertEqual(output.read_bytes(), payload)
            if os.name != "nt":
                self.assertTrue(output.stat().st_mode & 0o100)

    def test_rejects_an_archive_with_any_extra_member(self):
        payload = b"synthetic pinned ipatool"
        release = self.make_release(payload)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "release.tar.gz"
            self.write_archive(
                archive_path,
                {
                    release.member_path: payload,
                    "unexpected.txt": b"not allowed",
                },
            )

            with self.assertRaisesRegex(RuntimeError, "member"):
                extract_verified_member(archive_path, release, root / "output")


if __name__ == "__main__":
    unittest.main()

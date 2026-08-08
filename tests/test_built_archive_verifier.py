import struct
import tempfile
import unittest
from pathlib import Path

from scripts.verify_built_archive import (
    ArchiveVerificationError,
    StrictCArchiveReader,
    expected_controlled_files,
    verify_archive,
)


class _FakeArchive:
    def __init__(self, files):
        self._files = dict(files)
        self.toc = {
            name.replace("/", "\\"): (0, len(content), len(content), 0, "x")
            for name, content in self._files.items()
        }

    def extract(self, name):
        normalized = name.replace("\\", "/")
        return self._files[normalized]


class BuiltArchiveVerifierTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.expected = expected_controlled_files(self.root)

    def _reader_factory(self, files):
        return lambda _path: _FakeArchive(files)

    def test_accepts_exact_controlled_resources_with_identical_bytes(self):
        result = verify_archive(
            self.root / "synthetic.exe",
            self.root,
            reader_factory=self._reader_factory(self.expected),
        )

        self.assertEqual(result["controlled_files"], len(self.expected))
        self.assertEqual(result["embedded_ipatool_size"], 33779712)
        self.assertEqual(
            result["embedded_ipatool_sha256"],
            "7da96104954d4a9625dcec5f18bf64df62107ada37822ca953e2fe503a69d079",
        )

    def test_unreviewed_repository_file_cannot_self_authorize(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            isolated_root = Path(temp_dir)
            for name, contents in self.expected.items():
                path = isolated_root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
            unreviewed = isolated_root / "third_party" / "unreviewed" / "NOTICE"
            unreviewed.parent.mkdir(parents=True)
            unreviewed.write_bytes(b"not in immutable contract")

            isolated_expected = expected_controlled_files(isolated_root)

        self.assertEqual(set(isolated_expected), set(self.expected))
        self.assertNotIn("third_party/unreviewed/NOTICE", isolated_expected)

    def test_rejects_tampered_embedded_ipatool_bytes(self):
        files = dict(self.expected)
        files["ipatool-2.3.2-windows-amd64.exe"] = b"tampered"

        with self.assertRaises(ArchiveVerificationError):
            verify_archive(
                self.root / "synthetic.exe",
                self.root,
                reader_factory=self._reader_factory(files),
            )

    def test_rejects_unexpected_third_party_member(self):
        files = dict(self.expected)
        files["third_party/unreviewed/LICENSE.txt"] = b"unexpected"

        with self.assertRaises(ArchiveVerificationError):
            verify_archive(
                self.root / "synthetic.exe",
                self.root,
                reader_factory=self._reader_factory(files),
            )

    def test_rejects_unexpected_old_ipatool_member(self):
        files = dict(self.expected)
        files["ipatool-2.3.0-windows-amd64.exe"] = b"old"

        with self.assertRaises(ArchiveVerificationError):
            verify_archive(
                self.root / "synthetic.exe",
                self.root,
                reader_factory=self._reader_factory(files),
            )

    def test_rejects_case_variants_of_controlled_windows_namespaces(self):
        aliases = (
            "THIRD_PARTY/unreviewed/LICENSE.txt",
            "ASSETS/unreviewed.png",
            "IPATOOL-2.3.0-WINDOWS-AMD64.EXE",
        )
        for alias in aliases:
            with self.subTest(alias=alias):
                files = dict(self.expected)
                files[alias] = b"unexpected"

                with self.assertRaises(ArchiveVerificationError):
                    verify_archive(
                        self.root / "synthetic.exe",
                        self.root,
                        reader_factory=self._reader_factory(files),
                    )

    def test_rejects_windows_alias_and_ads_member_names(self):
        unsafe_names = (
            "LICENSE.",
            "LICENSE ",
            "uncontrolled/child:stream",
            "uncontrolled/NUL.txt",
            "uncontrolled/CONIN$.txt",
            "uncontrolled/CONOUT$.txt",
            "uncontrolled/COM¹.txt",
            "uncontrolled/COM².txt",
            "uncontrolled/COM³.txt",
            "uncontrolled/LPT¹.txt",
            "uncontrolled/LPT².txt",
            "uncontrolled/LPT³.txt",
        )
        for unsafe_name in unsafe_names:
            with self.subTest(name=unsafe_name):
                files = dict(self.expected)
                files[unsafe_name] = b"unexpected"

                with self.assertRaises(ArchiveVerificationError):
                    verify_archive(
                        self.root / "synthetic.exe",
                        self.root,
                        reader_factory=self._reader_factory(files),
                    )

    def test_raw_toc_rejects_duplicate_members_before_dict_collapse(self):
        def toc_entry(name):
            encoded = name.encode("utf-8") + b"\0"
            name_length = len(encoded)
            entry_length = StrictCArchiveReader._TOC_ENTRY_LENGTH + name_length
            if entry_length % 16:
                name_length += 16 - (entry_length % 16)
            encoded = encoded.ljust(name_length, b"\0")
            entry_length = StrictCArchiveReader._TOC_ENTRY_LENGTH + name_length
            return struct.pack(
                StrictCArchiveReader._TOC_ENTRY_FORMAT,
                entry_length,
                0,
                1,
                1,
                0,
                b"x",
            ) + encoded

        duplicate_toc = toc_entry("third_party/LICENSE") * 2
        with self.assertRaises(ArchiveVerificationError):
            StrictCArchiveReader._parse_toc(duplicate_toc)

    def test_raw_toc_requires_canonical_nul_termination_and_utf8(self):
        name_field_length = 32 - StrictCArchiveReader._TOC_ENTRY_LENGTH

        def toc_entry(name_field):
            self.assertEqual(len(name_field), name_field_length)
            return struct.pack(
                StrictCArchiveReader._TOC_ENTRY_FORMAT,
                32,
                0,
                1,
                1,
                0,
                b"x",
            ) + name_field

        malformed_fields = (
            b"A" * name_field_length,
            b"LICENSE\0suffix".ljust(name_field_length, b"\0"),
            b"LICENSE\0\0X".ljust(name_field_length, b"\0"),
            b"\xff\0".ljust(name_field_length, b"\0"),
            b"\0" * name_field_length,
        )
        for name_field in malformed_fields:
            with self.subTest(name_field=name_field):
                with self.assertRaises(ArchiveVerificationError):
                    StrictCArchiveReader._parse_toc(toc_entry(name_field))


if __name__ == "__main__":
    unittest.main()

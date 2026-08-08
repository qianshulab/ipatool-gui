import os
import tempfile
import unittest
from pathlib import Path

from core.atomic_file import UnsafePathError, replace_verified


@unittest.skipUnless(os.name == "nt", "Windows handle semantics only")
class WindowsVerifiedReplacementTests(unittest.TestCase):
    def test_parent_directory_swap_is_blocked_while_verifier_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            parent = root / "output"
            parent.mkdir()
            source = parent / ".app.part"
            target = parent / "app.ipa"
            moved = root / "moved"
            source.write_bytes(b"verified-new")
            target.write_bytes(b"old")
            swap_errors = []

            def verify(stream):
                self.assertEqual(stream.read(), b"verified-new")
                try:
                    os.replace(parent, moved)
                except OSError as exc:
                    swap_errors.append(exc)

            replace_verified(source, target, verify)

            self.assertTrue(swap_errors)
            self.assertTrue(parent.is_dir())
            self.assertFalse(moved.exists())
            self.assertFalse(source.exists())
            self.assertEqual(target.read_bytes(), b"verified-new")

    def test_source_path_replacement_is_blocked_while_verifier_holds_handle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            source = parent / ".app.part"
            replacement = parent / "malicious.tmp"
            target = parent / "app.ipa"
            source.write_bytes(b"verified-new")
            replacement.write_bytes(b"unverified-replacement")
            target.write_bytes(b"old")
            swap_errors = []

            def verify(stream):
                self.assertEqual(stream.read(), b"verified-new")
                try:
                    os.replace(replacement, source)
                except OSError as exc:
                    swap_errors.append(exc)

            replace_verified(source, target, verify)

            self.assertTrue(swap_errors)
            self.assertEqual(target.read_bytes(), b"verified-new")
            self.assertFalse(source.exists())
            self.assertEqual(replacement.read_bytes(), b"unverified-replacement")

    def test_post_commit_failure_restores_existing_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            source = parent / ".ipatool.tmp"
            target = parent / "ipatool.exe"
            source.write_bytes(b"verified-new")
            target.write_bytes(b"existing-install")

            def verify(stream):
                self.assertEqual(stream.read(), b"verified-new")

            def fail_config_write():
                raise RuntimeError("synthetic config write failure")

            with self.assertRaisesRegex(RuntimeError, "config write failure"):
                replace_verified(source, target, verify, after_commit=fail_config_write)

            self.assertEqual(target.read_bytes(), b"existing-install")
            self.assertEqual(source.read_bytes(), b"verified-new")

    def test_reparse_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            real_parent = root / "real"
            real_parent.mkdir()
            junction = root / "junction"
            result = os.system(
                f'cmd.exe /d /c mklink /J "{junction}" "{real_parent}" >nul'
            )
            if result != 0:
                self.skipTest("unable to create a junction in this environment")
            source = junction / ".app.part"
            target = junction / "app.ipa"
            source.write_bytes(b"verified-new")

            with self.assertRaises(UnsafePathError):
                replace_verified(source, target, lambda stream: stream.read())

            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()

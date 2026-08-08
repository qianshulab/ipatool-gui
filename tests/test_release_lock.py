import json
import unittest
from pathlib import Path

from core.ipatool_release import IPATOOL_RELEASES
from scripts.verify_release_inputs import parse_locked_requirements


class ReleaseDependencyLockTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]

    def test_windows_lock_pins_all_resolved_packages_with_hashes(self):
        lock_text = (self.root / "requirements-lock.txt").read_text(encoding="utf-8")
        package_lines = [
            line for line in lock_text.splitlines()
            if line and not line.startswith((" ", "#", "-"))
        ]

        self.assertGreaterEqual(len(package_lines), 10)
        for line in package_lines:
            with self.subTest(requirement=line):
                self.assertRegex(line, r"^[a-z0-9_-]+==[^ ]+ \\$")
        self.assertEqual(lock_text.count("--hash=sha256:"), 61)
        for direct_pin in (
            "pyinstaller==6.21.0",
            "pyqt6==6.11.0",
            "pyqt6-qt6==6.11.1",
            "pyqt6-sip==13.12.0",
        ):
            self.assertIn(direct_pin, lock_text.lower())

        locked = parse_locked_requirements(self.root / "requirements-lock.txt")
        self.assertEqual(len(locked), 10)
        self.assertEqual(locked["pyinstaller"], "6.21.0")
        self.assertEqual(locked["pyqt6"], "6.11.0")


    def test_ci_installs_the_hash_locked_windows_environment(self):
        workflow = (
            self.root / ".github" / "workflows" / "windows-ci.yml"
        ).read_text(encoding="utf-8")
        readme = (self.root / "README.md").read_text(encoding="utf-8")

        self.assertIn("requirements-lock.txt", workflow)
        self.assertIn(
            "python -m pip install --disable-pip-version-check --require-hashes --only-binary=:all: -r requirements-lock.txt",
            workflow,
        )
        self.assertIn('python-version: "3.11.9"', workflow)
        self.assertIn("requirements-lock.txt", readme)
        self.assertIn("--require-hashes", readme)
        self.assertIn("--only-binary=:all:", readme)
        self.assertIn("Python 3.11.15", readme)
        self.assertIn("uv pip compile requirements-dev.txt", readme)

    def test_ci_verifies_built_archive_bytes_and_bundles_project_license(self):
        workflow = (
            self.root / ".github" / "workflows" / "windows-ci.yml"
        ).read_text(encoding="utf-8")
        readme = (self.root / "README.md").read_text(encoding="utf-8")
        attribute_lines = set(
            (self.root / ".gitattributes").read_text(encoding="utf-8").splitlines()
        )

        self.assertIn('--add-data "LICENSE;."', workflow)
        self.assertIn('--add-data "LICENSE;."', readme)
        self.assertIn("scripts/verify_built_archive.py", workflow)
        self.assertNotIn("pyi-archive_viewer", workflow)
        self.assertIn("LICENSE text eol=lf", attribute_lines)
        self.assertIn("THIRD_PARTY_NOTICES.md text eol=lf", attribute_lines)
        self.assertLess(
            workflow.index("scripts/verify_release_inputs.py"),
            workflow.index("python -m PyInstaller"),
        )
        self.assertLess(
            workflow.index("python -m PyInstaller"),
            workflow.index("scripts/verify_built_archive.py"),
        )
        self.assertIn("python scripts/verify_release_inputs.py", readme)
        self.assertIn("python scripts/verify_built_archive.py", readme)
        self.assertLess(
            readme.index("python scripts/verify_release_inputs.py"),
            readme.index("python -m PyInstaller"),
        )
        self.assertLess(
            readme.index("python -m PyInstaller"),
            readme.index("python scripts/verify_built_archive.py"),
        )

    def test_tag_release_builds_windows_and_both_macos_architectures(self):
        workflow = (
            self.root / ".github" / "workflows" / "release.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("tags:", workflow)
        self.assertIn('"v*"', workflow)
        self.assertIn("macos-15-intel", workflow)
        self.assertIn("macos-15", workflow)
        self.assertIn("arch: amd64", workflow)
        self.assertIn("arch: arm64", workflow)
        self.assertIn("python -m scripts.fetch_ipatool_release", workflow)
        self.assertIn('--add-data "assets/exe.png;assets"', workflow)
        self.assertIn('--add-data "assets/exe.png:assets"', workflow)
        self.assertIn("--onedir", workflow)
        self.assertIn("ipatool version 2.3.2", workflow)
        self.assertIn("lipo", workflow)
        self.assertIn("ditto -c -k", workflow)
        self.assertIn("scripts/verify_built_archive.py", workflow)
        self.assertIn("gh release create", workflow)
        self.assertIn("gh release upload", workflow)
        self.assertIn("github.ref_type == 'tag'", workflow)
        self.assertIn("contents: write", workflow)
        self.assertIn("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02", workflow)
        self.assertIn("actions/download-artifact@634f93cb2916e3fdff6788551b99b062d0335ce0", workflow)

    def test_release_member_manifest_matches_runtime_pins(self):
        manifest = json.loads(
            (
                self.root
                / "third_party"
                / "ipatool"
                / "2.3.2"
                / "manifest.json"
            ).read_text(encoding="utf-8")
        )
        expected_archives = {}
        expected_members = {}
        for (system, arch), release in IPATOOL_RELEASES.items():
            expected_archives.setdefault(system, {})[arch] = {
                "url": release.archive_url,
                "size_bytes": release.archive_size_bytes,
                "sha256": release.archive_sha256,
            }
            expected_members.setdefault(system, {})[arch] = release.member_metadata()

        self.assertEqual(manifest["release_archives"], expected_archives)
        self.assertEqual(
            manifest["release_members"],
            expected_members,
        )
        self.assertEqual(
            sum(len(architectures) for architectures in manifest["release_members"].values()),
            6,
        )


if __name__ == "__main__":
    unittest.main()

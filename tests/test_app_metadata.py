import plistlib
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtGui import QImage

from app_metadata import (
    APP_BUNDLE_IDENTIFIER,
    APP_NAME,
    APP_ORGANIZATION,
    APP_VERSION,
)
from core.ipatool_release import IPATOOL_VERSION
from scripts.prepare_package_metadata import (
    check_release_ref,
    stamp_macos_plist,
    write_windows_version_file,
)


class AppMetadataTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]

    def test_application_version_has_one_release_source(self):
        self.assertEqual(APP_NAME, "IPA Download Tool")
        self.assertEqual(APP_VERSION, "1.0.0")
        self.assertEqual(APP_ORGANIZATION, "IPADownload")
        self.assertEqual(APP_BUNDLE_IDENTIFIER, "com.qianshulab.ipadownloadtool")

        main_source = (self.root / "main.py").read_text(encoding="utf-8")
        window_source = (self.root / "ui" / "main_window.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("app.setApplicationVersion(APP_VERSION)", main_source)
        self.assertIn("from app_metadata import", window_source)
        self.assertNotIn("APP_VERSION =", window_source)

    def test_windows_version_resource_uses_application_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "windows-version-info.txt"
            write_windows_version_file(output)
            text = output.read_text(encoding="utf-8")

        self.assertIn("filevers=(1, 0, 0, 0)", text)
        self.assertIn("prodvers=(1, 0, 0, 0)", text)
        self.assertIn("StringStruct('FileVersion', '1.0.0')", text)
        self.assertIn("StringStruct('ProductVersion', '1.0.0')", text)
        self.assertIn("StringStruct('ProductName', 'IPA Download Tool')", text)

    def test_macos_bundle_metadata_uses_application_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            plist_path = Path(temp_dir) / "Info.plist"
            with plist_path.open("wb") as handle:
                plistlib.dump({"CFBundleName": APP_NAME}, handle)

            stamp_macos_plist(plist_path)
            with plist_path.open("rb") as handle:
                metadata = plistlib.load(handle)

        self.assertEqual(metadata["CFBundleShortVersionString"], "1.0.0")
        self.assertEqual(metadata["CFBundleVersion"], "1.0.0")
        self.assertEqual(metadata["CFBundleIdentifier"], APP_BUNDLE_IDENTIFIER)

    def test_release_ref_rejects_version_drift(self):
        check_release_ref("branch", "main")
        check_release_ref("tag", "v1.0.0")
        with self.assertRaisesRegex(ValueError, "v1.0.0"):
            check_release_ref("tag", "v1.0.1")

    def test_workflows_stamp_windows_and_macos_metadata(self):
        release = (
            self.root / ".github" / "workflows" / "release.yml"
        ).read_text(encoding="utf-8")
        windows = (
            self.root / ".github" / "workflows" / "windows-ci.yml"
        ).read_text(encoding="utf-8")

        check_command = "python -m scripts.prepare_package_metadata --check-release-ref"
        windows_command = (
            "python -m scripts.prepare_package_metadata "
            "--windows-version-file build/windows-version-info.txt"
        )
        macos_command = (
            "python -m scripts.prepare_package_metadata "
            "--macos-plist dist/IPA-Download-Tool.app/Contents/Info.plist"
        )
        self.assertIn(check_command, release)
        self.assertIn(windows_command, release)
        self.assertIn(windows_command, windows)
        self.assertIn("--version-file build/windows-version-info.txt", release)
        self.assertIn("--version-file build/windows-version-info.txt", windows)
        self.assertIn(macos_command, release)

    def test_readme_targets_the_current_release(self):
        readme = (self.root / "README.md").read_text(encoding="utf-8")

        self.assertIn("下载最新版 v1.0.0", readme)
        self.assertIn("releases/download/v1.0.0/IPA-Download-Tool-1.0.0", readme)
        self.assertNotIn("v1." + "2.2", readme)

    def test_readme_screenshot_records_current_product_versions(self):
        screenshot = QImage(str(self.root / "assets" / "main-window.png"))

        self.assertFalse(screenshot.isNull())
        self.assertEqual(screenshot.text("ApplicationVersion"), APP_VERSION)
        self.assertEqual(screenshot.text("BundledIpatoolVersion"), IPATOOL_VERSION)


if __name__ == "__main__":
    unittest.main()

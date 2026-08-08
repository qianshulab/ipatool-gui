import io
import os
import ssl
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from core.ipatool_installer import (
    IPAToolInstaller,
    IPAToolInstallError,
    IPAToolIntegrityError,
)


OFFICIAL_WINDOWS_AMD64_URL = (
    "https://github.com/majd/ipatool/releases/download/v2.3.2/"
    "ipatool-2.3.2-windows-amd64.tar.gz"
)


class _ConfigStub:
    def __init__(self):
        self.ipatool_path = ""
        self.values = {
            "ipatool_version": "2.3.2",
            "ipatool_download_urls": {
                "Windows": (
                    "https://github.com/majd/ipatool/releases/download/"
                    "v{version}/ipatool-{version}-windows-{arch}.tar.gz"
                )
            },
            "ipatool_sha256": {
                "Windows": {
                    "amd64": (
                        "6352441f6f91df7947aaa203b19cb7d3c9d77920fc466dd784ff9cae88db5c92"
                    )
                }
            },
            "ipatool_release_members": {
                "Windows": {
                    "amd64": {
                        "path": "bin/ipatool-2.3.2-windows-amd64.exe",
                        "size_bytes": 33779712,
                        "sha256": (
                            "7da96104954d4a9625dcec5f18bf64df62107ada37822ca953e2fe503a69d079"
                        ),
                    }
                }
            },
        }

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FailingConfigStub(_ConfigStub):
    def __init__(self):
        self._allow_path_write = True
        self._ipatool_path = ""
        super().__init__()
        self._allow_path_write = False

    @property
    def ipatool_path(self):
        return self._ipatool_path

    @ipatool_path.setter
    def ipatool_path(self, value):
        if not self._allow_path_write:
            raise RuntimeError("synthetic config persistence failure")
        self._ipatool_path = value


class _Response(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"content-length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False


class IPAToolInstallerSecurityTests(unittest.TestCase):
    def test_business_success_signal_does_not_shadow_qthread_finished(self):
        installer = IPAToolInstaller(_ConfigStub())

        self.assertEqual(installer.finished.signal, "2finished()")
        self.assertEqual(installer.succeeded.signal, "2succeeded(QString)")

    def test_error_signal_redacts_nested_exception_payload(self):
        installer = IPAToolInstaller(_ConfigStub())
        secret = "SYNTHETIC_INSTALLER_SECRET"
        errors = []
        installer.error.connect(errors.append)
        installer._release_arch = lambda: (_ for _ in ()).throw(
            RuntimeError(
                "transport failed: "
                + repr({
                    "password": secret,
                    "nested": {"Authorization": f"Bearer {secret}"},
                })
            )
        )

        installer.run()

        self.assertEqual(len(errors), 1)
        self.assertNotIn(secret, errors[0])
        self.assertNotIn(f"Bearer {secret}", errors[0])

    def test_runtime_release_identity_ignores_user_config_metadata(self):
        config = _ConfigStub()
        config.values.update({
            "ipatool_version": "9.9.9",
            "ipatool_download_urls": {
                "Windows": "https://github.com/synthetic/release-{version}-{arch}.tar.gz"
            },
            "ipatool_sha256": {
                "Windows": {"amd64": "0" * 64}
            },
            "ipatool_release_members": {
                "Windows": {
                    "amd64": {
                        "path": "bin/synthetic.exe",
                        "size_bytes": 1,
                        "sha256": "1" * 64,
                    }
                }
            },
        })
        installer = IPAToolInstaller(config)
        requested_urls = []

        def fake_download(url, destination, *_args, **_kwargs):
            requested_urls.append(url)
            Path(destination).write_bytes(b"not an official archive")

        installer._download_file = fake_download
        with patch("core.ipatool_installer.platform.system", return_value="Windows"), patch(
            "core.ipatool_installer.platform.machine", return_value="AMD64"
        ):
            installer.run()

        self.assertEqual(
            requested_urls,
            [
                "https://github.com/majd/ipatool/releases/download/v2.3.2/"
                "ipatool-2.3.2-windows-amd64.tar.gz"
            ],
        )

    def test_download_keeps_tls_certificate_verification_enabled(self):
        installer = IPAToolInstaller(_ConfigStub())
        captured = {}

        def fake_urlopen(request, **kwargs):
            captured.update(kwargs)
            return _Response(b"archive")

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "ipatool.tar.gz"
            with patch("core.ipatool_installer.urlopen", fake_urlopen):
                installer._download_file(
                    OFFICIAL_WINDOWS_AMD64_URL,
                    destination,
                )

        context = captured.get("context")
        self.assertTrue(
            context is None or context.verify_mode == ssl.CERT_REQUIRED,
            "installer must never use an unverified TLS context",
        )
        self.assertGreater(captured.get("timeout", 0), 0, "download must use a finite timeout")

    def test_download_rejects_declared_size_that_differs_from_release(self):
        installer = IPAToolInstaller(_ConfigStub())
        response = _Response(b"short")

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "ipatool.tar.gz"
            with patch(
                "core.ipatool_installer.urlopen", return_value=response
            ), self.assertRaises(IPAToolIntegrityError):
                installer._download_file(
                    OFFICIAL_WINDOWS_AMD64_URL,
                    destination,
                    expected_size=6,
                )

            self.assertEqual(destination.read_bytes(), b"")

    def test_download_rejects_short_body_when_content_length_is_missing(self):
        installer = IPAToolInstaller(_ConfigStub())
        response = _Response(b"short")
        response.headers = {}

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "ipatool.tar.gz"
            with patch(
                "core.ipatool_installer.urlopen", return_value=response
            ), self.assertRaises(IPAToolIntegrityError):
                installer._download_file(
                    OFFICIAL_WINDOWS_AMD64_URL,
                    destination,
                    expected_size=6,
                )

    def test_download_rejects_non_https_github_url_before_opening(self):
        installer = IPAToolInstaller(_ConfigStub())
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "core.ipatool_installer.urlopen",
            side_effect=AssertionError("urlopen must not be called"),
        ):
            with self.assertRaises(IPAToolInstallError):
                installer._download_file(
                    "file:///synthetic/ipatool.tar.gz",
                    Path(temp_dir) / "download.tar.gz",
                )

    def test_download_rejects_oversized_content_length_before_writing(self):
        installer = IPAToolInstaller(_ConfigStub())
        response = _Response(b"archive")
        response.headers["content-length"] = str(1024 * 1024 * 1024)

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "ipatool.tar.gz"
            with patch(
                "core.ipatool_installer.urlopen", return_value=response
            ), self.assertRaises(IPAToolInstallError):
                installer._download_file(
                    OFFICIAL_WINDOWS_AMD64_URL,
                    destination,
                )

            self.assertEqual(destination.read_bytes(), b"")

    def test_download_enforces_size_limit_when_content_length_is_missing(self):
        installer = IPAToolInstaller(_ConfigStub())
        installer.MAX_DOWNLOAD_BYTES = 8
        response = _Response(b"123456789")
        response.headers = {}

        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "ipatool.tar.gz"
            with patch(
                "core.ipatool_installer.urlopen", return_value=response
            ), self.assertRaises(IPAToolInstallError):
                installer._download_file(
                    OFFICIAL_WINDOWS_AMD64_URL,
                    destination,
                )

            self.assertLessEqual(destination.stat().st_size, 8)

    def test_checksum_mismatch_stops_before_archive_extraction(self):
        installer = IPAToolInstaller(_ConfigStub())
        errors = []
        extract_calls = []
        installer.error.connect(errors.append)

        def fake_download(_url, destination, **_kwargs):
            Path(destination).write_bytes(b"tampered archive")

        def fake_extract(_archive, _system):
            extract_calls.append(True)
            raise AssertionError("archive extraction must not run after checksum mismatch")

        installer._download_file = fake_download
        installer._extract_archive = fake_extract

        with patch("core.ipatool_installer.platform.system", return_value="Windows"), patch(
            "core.ipatool_installer.platform.machine", return_value="AMD64"
        ):
            installer.run()

        self.assertEqual(extract_calls, [])
        self.assertTrue(errors)
        self.assertIn("SHA-256", errors[0])

    def test_missing_version_uses_2_3_2_compatible_default(self):
        config = _ConfigStub()
        config.values.pop("ipatool_version")
        installer = IPAToolInstaller(config)
        urls = []

        def fake_download(url, destination, **_kwargs):
            urls.append(url)
            Path(destination).write_bytes(b"not the official archive")

        installer._download_file = fake_download
        with patch("core.ipatool_installer.platform.system", return_value="Windows"), patch(
            "core.ipatool_installer.platform.machine", return_value="AMD64"
        ):
            installer.run()

        self.assertEqual(len(urls), 1)
        self.assertIn("/v2.3.2/ipatool-2.3.2-", urls[0])

    def test_zip_path_traversal_is_rejected_before_extraction(self):
        installer = IPAToolInstaller(_ConfigStub())
        with tempfile.TemporaryDirectory() as temp_dir:
            installer.temp_dir = Path(temp_dir)
            archive = installer.temp_dir / "ipatool.zip"
            escaped = installer.temp_dir / "escaped.exe"
            with zipfile.ZipFile(archive, "w") as zip_ref:
                zip_ref.writestr("../escaped.exe", b"payload")

            with self.assertRaises(IPAToolInstallError):
                installer._extract_archive(archive, "Windows")

            self.assertFalse(escaped.exists())

    def test_tar_link_is_rejected_before_extraction(self):
        installer = IPAToolInstaller(_ConfigStub())
        member = tarfile.TarInfo("bin/ipatool")
        member.type = tarfile.SYMTYPE
        member.linkname = "../../outside"

        class TarStub:
            extracted = False

            def getmembers(self):
                return [member]

            def extractall(self, _destination):
                self.extracted = True

        tar_ref = TarStub()
        with tempfile.TemporaryDirectory() as temp_dir, self.assertRaises(IPAToolInstallError):
            installer._safe_extract_tar(tar_ref, Path(temp_dir))

        self.assertFalse(tar_ref.extracted)

    def test_duplicate_archive_member_names_are_rejected(self):
        installer = IPAToolInstaller(_ConfigStub())
        member_name = "bin/ipatool-2.3.2-windows-amd64.exe"
        with tempfile.TemporaryDirectory() as temp_dir:
            installer.temp_dir = Path(temp_dir)
            archive = installer.temp_dir / "ipatool.tar.gz"
            with tarfile.open(archive, "w:gz") as tar_ref:
                for payload in (b"first", b"second"):
                    member = tarfile.TarInfo(member_name)
                    member.size = len(payload)
                    tar_ref.addfile(member, io.BytesIO(payload))

            with self.assertRaises(IPAToolInstallError):
                installer._extract_archive(archive, "Windows")

    def test_archive_with_unexpected_file_member_is_rejected(self):
        installer = IPAToolInstaller(_ConfigStub())
        with tempfile.TemporaryDirectory() as temp_dir:
            installer.temp_dir = Path(temp_dir)
            archive = installer.temp_dir / "ipatool.zip"
            with zipfile.ZipFile(archive, "w") as zip_ref:
                zip_ref.writestr(
                    "bin/ipatool-2.3.2-windows-amd64.exe",
                    b"expected",
                )
                zip_ref.writestr("bin/ipatool-helper.exe", b"unexpected")

            with self.assertRaises(IPAToolInstallError):
                installer._extract_archive(archive, "Windows")

    def test_archive_with_unexpected_directory_member_is_rejected(self):
        installer = IPAToolInstaller(_ConfigStub())
        with tempfile.TemporaryDirectory() as temp_dir:
            installer.temp_dir = Path(temp_dir)
            archive = installer.temp_dir / "ipatool.zip"
            with zipfile.ZipFile(archive, "w") as zip_ref:
                zip_ref.writestr(
                    "bin/ipatool-2.3.2-windows-amd64.exe",
                    b"expected",
                )
                zip_ref.writestr("unexpected/", b"")

            with self.assertRaises(IPAToolInstallError):
                installer._extract_archive(archive, "Windows")

    def test_extracted_binary_is_verified_before_install(self):
        installer = IPAToolInstaller(_ConfigStub())
        errors = []
        finished = []
        installer.error.connect(errors.append)
        installer.succeeded.connect(finished.append)

        def fake_download(_url, destination, **_kwargs):
            Path(destination).write_bytes(b"synthetic archive")

        def fake_extract(_archive, _system):
            extracted = installer.temp_dir / "tampered-ipatool.exe"
            extracted.write_bytes(b"tampered executable")
            return extracted

        installer._download_file = fake_download
        installer._verify_sha256 = lambda *_args: None
        installer._extract_archive = fake_extract
        installer._add_to_path = lambda *_args: None

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "managed" / "ipatool.exe"
            with patch(
                "core.ipatool_installer.platform.system", return_value="Windows"
            ), patch(
                "core.ipatool_installer.platform.machine", return_value="AMD64"
            ), patch(
                "core.ipatool_installer.Config._managed_ipatool_path",
                return_value=target,
            ):
                installer.run()

            self.assertTrue(errors)
            self.assertEqual(finished, [])
            self.assertFalse(target.exists())

    def test_failed_atomic_replace_preserves_existing_install(self):
        installer = IPAToolInstaller(_ConfigStub())
        errors = []
        finished = []
        installer.error.connect(errors.append)
        installer.succeeded.connect(finished.append)

        def fake_download(_url, destination, **_kwargs):
            Path(destination).write_bytes(b"synthetic archive")

        def fake_extract(_archive, _system):
            extracted = installer.temp_dir / "verified-ipatool.exe"
            extracted.write_bytes(b"new executable")
            return extracted

        installer._download_file = fake_download
        installer._verify_sha256 = lambda *_args: None
        installer._verify_release_member = lambda *_args: None
        installer._extract_archive = fake_extract
        installer._add_to_path = lambda *_args: None

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "managed" / "ipatool.exe"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"existing executable")
            with patch(
                "core.ipatool_installer.platform.system", return_value="Windows"
            ), patch(
                "core.ipatool_installer.platform.machine", return_value="AMD64"
            ), patch(
                "core.ipatool_installer.Config._managed_ipatool_path",
                return_value=target,
            ), patch(
                "core.ipatool_installer.replace_verified",
                side_effect=OSError("replace denied"),
            ):
                installer.run()

            self.assertTrue(errors)
            self.assertEqual(finished, [])
            self.assertEqual(target.read_bytes(), b"existing executable")

    def test_config_persistence_failure_restores_existing_install(self):
        installer = IPAToolInstaller(_FailingConfigStub())
        errors = []
        finished = []
        installer.error.connect(errors.append)
        installer.succeeded.connect(finished.append)

        def fake_download(_url, destination, **_kwargs):
            Path(destination).write_bytes(b"synthetic archive")

        def fake_extract(_archive, _system):
            extracted = installer.temp_dir / "verified-ipatool.exe"
            extracted.write_bytes(b"new executable")
            return extracted

        installer._download_file = fake_download
        installer._verify_sha256 = lambda *_args: None
        installer._verify_release_member = lambda *_args: None
        installer._extract_archive = fake_extract
        installer._add_to_path = lambda *_args: None

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "managed" / "ipatool.exe"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"existing executable")
            with patch(
                "core.ipatool_installer.platform.system", return_value="Windows"
            ), patch(
                "core.ipatool_installer.platform.machine", return_value="AMD64"
            ), patch(
                "core.ipatool_installer.Config._managed_ipatool_path",
                return_value=target,
            ):
                installer.run()

            self.assertTrue(errors)
            self.assertEqual(finished, [])
            self.assertEqual(target.read_bytes(), b"existing executable")

    @unittest.skipUnless(os.name == "nt", "Windows junction semantics only")
    def test_parent_swap_during_final_member_verification_is_blocked(self):
        installer = IPAToolInstaller(_ConfigStub())
        errors = []
        finished = []
        installer.error.connect(errors.append)
        installer.succeeded.connect(finished.append)

        def fake_download(_url, destination, **_kwargs):
            Path(destination).write_bytes(b"synthetic archive")

        def fake_extract(_archive, _system):
            extracted = installer.temp_dir / "verified-ipatool.exe"
            extracted.write_bytes(b"new executable")
            return extracted

        installer._download_file = fake_download
        installer._verify_sha256 = lambda *_args: None
        installer._extract_archive = fake_extract
        installer._add_to_path = lambda *_args: None

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            install_dir = root / "managed"
            install_dir.mkdir()
            moved_dir = root / "moved"
            target = install_dir / "ipatool.exe"
            target.write_bytes(b"existing executable")
            swap_errors = []

            def verify_and_attempt_swap(source, _metadata):
                if hasattr(source, "read"):
                    self.assertEqual(source.read(), b"new executable")
                    source.seek(0)
                    try:
                        os.replace(install_dir, moved_dir)
                    except OSError as exc:
                        swap_errors.append(exc)

            installer._verify_release_member = verify_and_attempt_swap
            with patch(
                "core.ipatool_installer.platform.system", return_value="Windows"
            ), patch(
                "core.ipatool_installer.platform.machine", return_value="AMD64"
            ), patch(
                "core.ipatool_installer.Config._managed_ipatool_path",
                return_value=target,
            ):
                installer.run()

            self.assertTrue(swap_errors)
            self.assertEqual(errors, [])
            self.assertEqual(finished, [str(target)])
            self.assertTrue(install_dir.is_dir())
            self.assertFalse(moved_dir.exists())
            self.assertEqual(target.read_bytes(), b"new executable")


if __name__ == "__main__":
    unittest.main()

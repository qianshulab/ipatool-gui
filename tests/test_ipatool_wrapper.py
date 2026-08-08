import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.config import Config
from core.ipatool import IPATool
from core.ipatool_release import get_ipatool_release


IPATOOL_2_3_2_FIXTURES = Path(__file__).parent / "fixtures" / "ipatool-2.3.2"


class IPAToolLoginParsingTests(unittest.TestCase):
    def setUp(self):
        self.tool = object.__new__(IPATool)
        self.tool.ipatool_path = "ipatool"

    def _login_from_upstream_fixture(self, fixture_name):
        completed = SimpleNamespace(
            stdout=(IPATOOL_2_3_2_FIXTURES / fixture_name).read_bytes(),
            stderr=b"",
            returncode=0,
        )
        with patch("core.ipatool.platform.system", return_value="Linux"), patch(
            "core.ipatool.subprocess.run", return_value=completed
        ):
            return self.tool.login("synthetic@example.invalid", "SYNTHETIC_PASSWORD")

    def test_login_reports_auth_code_required(self):
        result = self._login_from_upstream_fixture("auth-2fa-required.jsonl")

        self.assertFalse(result["success"])
        self.assertTrue(result["requires_auth_code"])

    def test_login_reports_invalid_auth_code_from_failure_type(self):
        self.tool._execute = lambda args: {
            "level": "error",
            "error": "failed to login: bad login",
            "metadata": {"Data": {"FailureType": "5005"}},
            "success": False,
            "returncode": 1,
        }

        result = self.tool.login("user@example.com", "password", "123456")

        self.assertFalse(result["success"])
        self.assertTrue(result["invalid_auth_code"])

    def test_login_reports_success_with_email(self):
        result = self._login_from_upstream_fixture("auth-login-success.jsonl")

        self.assertTrue(result["success"])
        self.assertEqual(result["email"], "synthetic@example.invalid")

    def test_login_does_not_enable_verbose_logging(self):
        calls = []
        self.tool._execute = lambda args: calls.append(args) or {
            "success": False,
            "error": "test failure",
            "returncode": 1,
        }

        self.tool.login("user@example.com", "password")

        self.assertNotIn("--verbose", calls[0])

    def test_login_requires_explicit_success_instead_of_email_only(self):
        self.tool._execute = lambda args: {
            "email": "user@example.com",
            "success": False,
            "error": "backend error",
            "returncode": 1,
        }

        result = self.tool.login("user@example.com", "password")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "backend error")

    def test_login_rejects_success_event_with_nonzero_exit_code(self):
        self.tool._execute = lambda args: {
            "email": "user@example.com",
            "success": True,
            "returncode": 1,
        }

        result = self.tool.login("user@example.com", "password")

        self.assertFalse(result["success"])

    def test_login_does_not_guess_2fa_from_generic_error_without_code(self):
        self.tool._execute = lambda args: {
            "level": "error",
            "error": "something went wrong",
            "success": False,
            "returncode": 1,
        }

        result = self.tool.login("user@example.com", "password")

        self.assertFalse(result["success"])
        self.assertNotIn("requires_auth_code", result)
        self.assertEqual(result["error"], "something went wrong")

    def test_login_reports_temporary_apple_auth_failure_without_2fa_prompt(self):
        self.tool._execute = lambda args: {
            "level": "error",
            "error": (
                "request failed: unexpected response from Apple "
                "(HTTP 503): Service Unavailable"
            ),
            "success": False,
            "returncode": 1,
        }

        result = self.tool.login("user@example.com", "password")

        self.assertFalse(result["success"])
        self.assertTrue(result["temporary_failure"])
        self.assertNotIn("requires_auth_code", result)

    def test_temporary_failure_wins_over_verification_code_context(self):
        self.tool._execute = lambda args: {
            "level": "error",
            "error": "verification code endpoint returned HTTP 503 service unavailable",
            "success": False,
            "returncode": 1,
        }

        result = self.tool.login("user@example.com", "password")

        self.assertTrue(result["temporary_failure"])
        self.assertNotIn("requires_auth_code", result)

    def test_login_rejects_malformed_auth_code_before_starting_ipatool(self):
        calls = []
        self.tool._execute = lambda args: calls.append(args) or {"success": True}

        result = self.tool.login("user@example.com", "password", "12a456")

        self.assertFalse(result["success"])
        self.assertTrue(result["invalid_auth_code_format"])
        self.assertEqual(calls, [])

    def test_login_normalizes_spaced_auth_code(self):
        calls = []

        def execute(args):
            calls.append(args)
            return {
                "name": "Test User",
                "email": "user@example.com",
                "success": True,
                "returncode": 0,
            }

        self.tool._execute = execute

        result = self.tool.login("user@example.com", "password", "123 456")

        self.assertTrue(result["success"])
        auth_code_index = calls[0].index("--auth-code")
        self.assertEqual(calls[0][auth_code_index + 1], "123456")

    def test_login_treats_generic_error_with_code_as_ambiguous_credentials_error(self):
        self.tool._execute = lambda args: {
            "level": "error",
            "error": "something went wrong",
            "success": False,
            "returncode": 1,
        }

        result = self.tool.login("user@example.com", "password", "123456")

        self.assertFalse(result["success"])
        self.assertTrue(result["credentials_or_auth_code_invalid"])

    def test_login_treats_bad_login_with_code_as_ambiguous_credentials_error(self):
        self.tool._execute = lambda args: {
            "level": "error",
            "error": "something went wrong",
            "metadata": {
                "Data": {
                    "FailureType": "",
                    "CustomerMessage": "MZFinance.BadLogin.Configurator_message",
                }
            },
            "success": False,
            "returncode": 1,
        }

        result = self.tool.login("user@example.com", "password", "123456")

        self.assertFalse(result["success"])
        self.assertTrue(result["credentials_or_auth_code_invalid"])


class IPAToolDiscoveryTests(unittest.TestCase):
    def test_bundled_versioned_binary_wins_over_ambiguous_ipatool_exe(self):
        tool = object.__new__(IPATool)
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            (directory / "ipatool.exe").write_bytes(b"old ambiguous binary")
            pinned = directory / "ipatool-2.3.2-windows-amd64.exe"
            pinned.write_bytes(b"pinned binary")

            with patch("core.ipatool.platform.system", return_value="Windows"), patch(
                "core.ipatool.sys._MEIPASS", str(directory), create=True
            ):
                found = tool._find_ipatool()

        self.assertEqual(found, str(pinned.absolute()))

    def test_bundled_macos_binary_is_loaded_from_pyinstaller_resources(self):
        tool = object.__new__(IPATool)
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            pinned = directory / "ipatool-2.3.2-macos-arm64"
            pinned.write_bytes(b"pinned macOS binary")

            with patch(
                "core.ipatool.platform.system", return_value="Darwin"
            ), patch(
                "core.ipatool.platform.machine", return_value="arm64"
            ), patch(
                "core.ipatool.sys._MEIPASS", str(directory), create=True
            ), patch("core.ipatool.subprocess.run") as which:
                found = tool._find_ipatool()

        self.assertEqual(found, str(pinned.absolute()))
        which.assert_not_called()


class IPAToolOutputParsingTests(unittest.TestCase):
    def setUp(self):
        self.tool = object.__new__(IPATool)
        self.tool.ipatool_path = "ipatool"

    def test_parse_uses_last_json_line_and_keeps_metadata(self):
        stdout = (
            '{"level":"debug","metadata":{"Data":{"FailureType":"5005"}}}\n'
            '{"level":"error","error":"failed to login","success":false}\n'
        )

        result = self.tool._parse_json_output(stdout, "")

        self.assertEqual(result["error"], "failed to login")
        self.assertEqual(result["metadata"]["Data"]["FailureType"], "5005")

    def test_parse_prefers_stdout_protocol_events_over_stderr_diagnostics(self):
        stdout = '{"level":"info","email":"user@example.com","success":true}\n'
        stderr = '{"level":"debug","message":"diagnostic only"}\n'

        result = self.tool._parse_json_output(stdout, stderr)

        self.assertTrue(result["success"])
        self.assertEqual(result["email"], "user@example.com")

    def test_execute_rejects_stderr_only_success_protocol_event(self):
        completed = SimpleNamespace(
            stdout=b"",
            stderr=(
                b'{"level":"info","email":"synthetic@example.invalid",'
                b'"success":true}\n'
            ),
            returncode=0,
        )

        with patch("core.ipatool.platform.system", return_value="Linux"), patch(
            "core.ipatool.subprocess.run", return_value=completed
        ):
            result = self.tool._execute(["auth", "info"])

        self.assertFalse(result["success"])
        self.assertTrue(result["protocol_error"])
        self.assertEqual(result["returncode"], 0)
        self.assertNotIn("email", result)

    def test_login_does_not_treat_nonzero_exit_text_as_auth_code_challenge(self):
        self.tool._execute = MagicMock(return_value={
            "success": False,
            "returncode": 1,
            "error": "2FA code is required",
        })

        result = self.tool.login(
            "synthetic@example.invalid",
            "SYNTHETIC_PASSWORD",
        )

        self.assertFalse(result["success"])
        self.assertNotEqual(result.get("requires_auth_code"), True)

    def test_parse_non_object_json_is_not_implicitly_successful(self):
        result = self.tool._parse_json_output('["unexpected"]\n', "")

        self.assertNotEqual(result.get("success"), True)

    def test_execute_redacts_non_json_error_before_logging_or_returning(self):
        password = "TEST_PASSWORD_VALUE"
        auth_code = "654321"
        email = "unit@example.invalid"
        completed = SimpleNamespace(
            stdout=b"",
            stderr=(
                f"request failed --password {password} "
                f"--auth-code {auth_code} --email {email}"
            ).encode(),
            returncode=1,
        )
        captured = io.StringIO()

        with patch("core.ipatool.subprocess.run", return_value=completed), redirect_stdout(captured):
            result = self.tool._execute(["auth", "info"])

        combined = captured.getvalue() + repr(result)
        self.assertNotIn(password, combined)
        self.assertNotIn(auth_code, combined)
        self.assertNotIn(email, combined)

    def test_mask_sensitive_text_redacts_standard_bearer_authorization(self):
        secret = "SYNTHETIC_BEARER_CREDENTIAL_VALUE"

        masked = self.tool._mask_sensitive_text(
            f"Authorization: Bearer {secret}"
        )

        self.assertNotIn(secret, masked)
        self.assertNotIn("Bearer", masked)

    def test_execute_does_not_log_auth_protocol_identity_fields(self):
        display_name = "SYNTHETIC_PRIVATE_DISPLAY_NAME"
        completed = SimpleNamespace(
            stdout=json.dumps({
                "success": True,
                "email": "synthetic@example.invalid",
                "name": display_name,
            }).encode(),
            stderr=b"",
            returncode=0,
        )
        captured = io.StringIO()

        with patch("core.ipatool.platform.system", return_value="Linux"), patch(
            "core.ipatool.subprocess.run", return_value=completed
        ), redirect_stdout(captured):
            result = self.tool._execute(["auth", "info"])

        self.assertTrue(result["success"])
        self.assertNotIn(display_name, captured.getvalue())

    def test_execute_uses_real_exit_code_instead_of_json_claim(self):
        completed = SimpleNamespace(
            stdout=b'{"success":true,"returncode":0,"email":"user@example.invalid"}\n',
            stderr=b"",
            returncode=1,
        )

        with patch("core.ipatool.platform.system", return_value="Linux"), patch(
            "core.ipatool.subprocess.run", return_value=completed
        ):
            result = self.tool._execute(["auth", "info"])

        self.assertEqual(result["returncode"], 1)
        self.assertFalse(result["success"])

    def test_execute_rejects_zero_exit_without_json_protocol_event(self):
        completed = SimpleNamespace(stdout=b"", stderr=b"", returncode=0)

        with patch("core.ipatool.platform.system", return_value="Linux"), patch(
            "core.ipatool.subprocess.run", return_value=completed
        ):
            result = self.tool._execute(["auth", "info"])

        self.assertFalse(result["success"])
        self.assertTrue(result["protocol_error"])
        self.assertEqual(result["returncode"], 0)

    def test_execute_redacts_exception_text_before_returning(self):
        password = "SYNTHETIC_PASSWORD_VALUE"
        auth_code = "654321"
        email = "synthetic@example.invalid"
        error = RuntimeError(
            f"spawn failed --password {password} --auth-code {auth_code} --email {email}"
        )

        with patch("core.ipatool.subprocess.run", side_effect=error):
            result = self.tool._execute(["auth", "info"])

        combined = repr(result)
        self.assertNotIn(password, combined)
        self.assertNotIn(auth_code, combined)
        self.assertNotIn(email, combined)

    def test_mask_sensitive_text_redacts_escaped_json_value(self):
        secret = 'SYNTHETIC_SECRET_\"_TAIL'
        payload = json.dumps({"password": secret, "message": "diagnostic"})

        masked = self.tool._mask_sensitive_text(payload)

        self.assertNotIn(secret, masked)
        self.assertEqual(json.loads(masked)["password"], "***")

    def test_mask_sensitive_text_redacts_prefixed_python_repr_recursively(self):
        secret = "SYNTHETIC_REPR_SECRET"
        payload = (
            "request failed: "
            + repr({
                "password": secret,
                "nested": {"Authorization": f"Bearer {secret}"},
                "items": [("token", secret)],
            })
        )

        masked = self.tool._mask_sensitive_text(payload)

        self.assertNotIn(secret, masked)
        self.assertNotIn(f"Bearer {secret}", masked)

    def test_mask_sensitive_jsonl_redacts_each_protocol_event(self):
        secret = "SYNTHETIC_SESSION_TOKEN"
        payload = "\n".join((
            json.dumps({"message": "diagnostic"}),
            json.dumps({"X-Apple-Session-Token": secret}),
        ))

        masked = self.tool._mask_sensitive_text(payload)

        self.assertNotIn(secret, masked)
        events = [json.loads(line) for line in masked.splitlines()]
        self.assertEqual(events[1]["X-Apple-Session-Token"], "***")

    def test_sanitize_result_redacts_composite_sensitive_keys(self):
        secret = "SYNTHETIC_SECRET_VALUE"
        result = {
            "PasswordToken": secret,
            "X-Apple-Session-Token": secret,
            "nested": {"authorizationToken": secret},
        }

        sanitized = self.tool._sanitize_result(result)

        self.assertNotIn(secret, repr(sanitized))

    def test_check_auth_requires_explicit_success_and_zero_exit_code(self):
        for response in (
            {"email": "user@example.com", "returncode": 0},
            {"email": "user@example.com", "success": True, "returncode": 1},
            {"email": "user@example.com", "success": False, "returncode": 0},
        ):
            with self.subTest(response=response):
                self.tool._execute = lambda args, value=response: value
                self.assertFalse(self.tool.check_auth())

        self.tool._execute = lambda args: {
            "email": "user@example.com",
            "success": True,
            "returncode": 0,
        }
        self.assertTrue(self.tool.check_auth())


class IPAToolCacheTests(unittest.TestCase):
    def test_clear_local_cache_fails_if_cache_directory_still_exists(self):
        tool = object.__new__(IPATool)
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            cache_dir = home / ".ipatool"
            cache_dir.mkdir()
            (cache_dir / "synthetic-cache").write_text("data", encoding="utf-8")

            with patch("core.ipatool.Path.home", return_value=home), patch(
                "core.ipatool.shutil.rmtree", return_value=None
            ):
                result = tool.clear_local_cache()

            self.assertFalse(result["success"])
            self.assertTrue(cache_dir.exists())
            self.assertNotIn(str(cache_dir), result["removed"])
            self.assertIn("仍然存在", result["error"])


class IPAToolSearchTests(unittest.TestCase):
    def setUp(self):
        self.tool = object.__new__(IPATool)

    def test_search_raises_for_authentication_failure_instead_of_returning_no_results(self):
        self.tool._execute = MagicMock(return_value={
            "success": False,
            "returncode": 1,
            "error": "authentication required for synthetic@example.invalid",
        })

        with self.assertRaisesRegex(RuntimeError, "authentication required") as raised:
            self.tool.search("synthetic-query", limit=5)

        self.assertNotIn("synthetic@example.invalid", str(raised.exception))

    def test_search_keeps_successful_result_formatting(self):
        self.tool._execute = MagicMock(return_value={
            "success": True,
            "returncode": 0,
            "results": [{
                "id": 123,
                "bundleID": "com.example.synthetic",
                "name": "Synthetic App",
                "price": 1.99,
            }],
        })

        results = self.tool.search("synthetic-query", limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["bundleId"], "com.example.synthetic")
        self.assertEqual(results[0]["formattedPrice"], "$1.99")


class ConfigMigrationTests(unittest.TestCase):
    def test_concurrent_writers_serialize_without_resurrecting_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config = Config(str(config_path))
            self.assertTrue(
                config.save_apple_credentials(
                    "synthetic@example.invalid",
                    "SYNTHETIC_OLD_PASSWORD",
                    True,
                    raise_on_error=True,
                )
            )

            original_replace = os.replace
            first_replace_entered = threading.Event()
            release_first_replace = threading.Event()
            second_replace_entered = threading.Event()
            replace_count_lock = threading.Lock()
            replace_count = 0
            errors = []

            def interleaved_replace(source, destination):
                nonlocal replace_count
                with replace_count_lock:
                    replace_count += 1
                    current_count = replace_count
                if current_count == 1:
                    first_replace_entered.set()
                    if not release_first_replace.wait(timeout=3):
                        raise TimeoutError("first config transaction was not released")
                else:
                    second_replace_entered.set()
                return original_replace(source, destination)

            def install_writer():
                try:
                    config.set("ipatool_path", "C:/synthetic/ipatool.exe")
                except Exception as exc:  # pragma: no cover - asserted below
                    errors.append(exc)

            def credential_clear_writer():
                try:
                    config.save_apple_credentials(
                        "",
                        "",
                        False,
                        raise_on_error=True,
                    )
                except Exception as exc:  # pragma: no cover - asserted below
                    errors.append(exc)

            with patch("core.config.os.replace", side_effect=interleaved_replace):
                first = threading.Thread(target=install_writer)
                second = threading.Thread(target=credential_clear_writer)
                first.start()
                self.assertTrue(first_replace_entered.wait(timeout=3))
                second.start()
                overlapped = second_replace_entered.wait(timeout=0.5)
                release_first_replace.set()
                first.join(timeout=3)
                second.join(timeout=3)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(errors, [])
            self.assertFalse(
                overlapped,
                "a second config writer entered os.replace before the first transaction ended",
            )

            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config.config_data, persisted)
            self.assertEqual(persisted["ipatool_path"], "C:/synthetic/ipatool.exe")
            self.assertFalse(persisted["remember_credentials"])
            self.assertEqual(persisted["apple_id"], {"email": "", "password": ""})

    def test_failed_general_set_rolls_back_memory_and_disk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config = Config(str(config_path))
            self.assertTrue(config.save())
            original_data = json.loads(json.dumps(config.config_data))
            original_bytes = config_path.read_bytes()

            with patch(
                "core.config.os.replace",
                side_effect=OSError("synthetic replace denied"),
            ):
                with self.assertRaises(OSError):
                    config.set("synthetic.nested.value", "changed")

            self.assertEqual(config.config_data, original_data)
            self.assertEqual(config_path.read_bytes(), original_bytes)
            self.assertEqual(
                list(config_path.parent.glob(f".{config_path.name}.*.tmp")),
                [],
            )

    def test_failed_credential_save_does_not_linger_or_leak_into_later_save(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config = Config(str(config_path))
            self.assertTrue(config.save())

            with patch("core.config.os.replace", side_effect=OSError("synthetic write denied")):
                with self.assertRaises(OSError):
                    config.save_apple_credentials(
                        "synthetic@example.invalid",
                        "SYNTHETIC_PASSWORD",
                        True,
                        raise_on_error=True,
                    )

            self.assertEqual(config.apple_email, "")
            self.assertEqual(config.apple_password, "")
            self.assertFalse(config.remember_credentials)

            config.set("theme", "dark")
            persisted = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["apple_id"]["email"], "")
            self.assertEqual(persisted["apple_id"]["password"], "")
            self.assertFalse(persisted["remember_credentials"])

    def test_failed_atomic_replace_preserves_existing_config_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config = Config(str(config_path))
            self.assertTrue(config.save())
            original_bytes = config_path.read_bytes()
            config.config_data["theme"] = "dark"

            with patch("core.config.os.replace", side_effect=OSError("synthetic replace denied")):
                with self.assertRaises(OSError):
                    config.save(raise_on_error=True)

            self.assertEqual(config_path.read_bytes(), original_bytes)
            temporary_files = list(config_path.parent.glob(f".{config_path.name}.*.tmp"))
            self.assertEqual(temporary_files, [])

    def test_migration_drops_user_controlled_release_trust_metadata(self):
        config = object.__new__(Config)
        old_data = {
            "ipatool_version": "9.9.9",
            "ipatool_download_urls": {
                "Windows": "https://github.com/synthetic/release.tar.gz"
            },
            "ipatool_sha256": {"Windows": {"amd64": "0" * 64}},
            "ipatool_release_members": {
                "Windows": {"amd64": {"path": "synthetic", "size_bytes": 1}}
            },
        }

        migrated = config._migrate_config(old_data)

        for key in (
            "ipatool_version",
            "ipatool_download_urls",
            "ipatool_sha256",
            "ipatool_release_members",
        ):
            self.assertNotIn(key, migrated)

    def test_migrates_broken_2_3_0_auth_release(self):
        config = object.__new__(Config)
        old_data = {
            "ipatool_version": "2.3.0",
            "ipatool_download_urls": {"Windows": "https://github.com/legacy"},
        }

        migrated = config._migrate_config(old_data)

        self.assertNotIn("ipatool_version", migrated)
        self.assertNotIn("ipatool_download_urls", migrated)

    def test_migration_drops_only_old_app_managed_ipatool_path(self):
        config = object.__new__(Config)
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir) / "LocalAppData"
            managed_path = local_app_data / "ipatool" / "ipatool.exe"
            old_data = {
                "ipatool_version": "2.3.0",
                "ipatool_path": str(managed_path),
            }
            with patch(
                "core.config.platform.system", return_value="Windows"
            ), patch.dict(
                os.environ,
                {"LOCALAPPDATA": str(local_app_data)},
                clear=False,
            ):
                migrated = config._migrate_config(old_data)

        self.assertEqual(migrated["ipatool_path"], "")

    def test_migration_drops_managed_installer_paths_on_all_platforms(self):
        config = object.__new__(Config)
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "home"
            local_app_data = Path(temp_dir) / "redirected-local-app-data"
            cases = (
                ("Windows", local_app_data / "ipatool" / "ipatool.exe"),
                ("Windows", home / "AppData" / "Local" / "ipatool" / "ipatool.exe"),
                ("Darwin", home / ".local" / "bin" / "ipatool"),
                ("Darwin", home / "Library" / "Application Support" / "ipatool" / "ipatool"),
                ("Linux", home / ".local" / "bin" / "ipatool"),
                ("Linux", home / ".local" / "share" / "ipatool" / "ipatool"),
            )
            for system, managed_path in cases:
                with self.subTest(system=system, managed_path=managed_path), patch(
                    "core.config.platform.system", return_value=system
                ), patch("core.config.Path.home", return_value=home), patch.dict(
                    os.environ,
                    {"LOCALAPPDATA": str(local_app_data)},
                    clear=False,
                ):
                    migrated = config._migrate_config({
                        "ipatool_version": "2.3.0",
                        "ipatool_path": str(managed_path),
                    })

                self.assertEqual(migrated["ipatool_path"], "")

    def test_migration_keeps_user_selected_custom_ipatool_path(self):
        config = object.__new__(Config)
        custom_path = str(Path("D:/tools/ipatool.exe"))
        old_data = {
            "ipatool_version": "2.3.0",
            "ipatool_path": custom_path,
        }

        migrated = config._migrate_config(old_data)

        self.assertEqual(migrated["ipatool_path"], custom_path)

    def test_release_contract_pins_official_windows_amd64_identity(self):
        config = object.__new__(Config)

        defaults = config._default_config()
        release = get_ipatool_release("Windows", "amd64")

        for key in (
            "ipatool_version",
            "ipatool_download_urls",
            "ipatool_sha256",
            "ipatool_release_members",
        ):
            self.assertNotIn(key, defaults)
        self.assertEqual(release.version, "2.3.2")
        self.assertEqual(release.archive_size_bytes, 15264571)
        self.assertEqual(
            release.archive_sha256,
            "6352441f6f91df7947aaa203b19cb7d3c9d77920fc466dd784ff9cae88db5c92",
        )
        self.assertEqual(release.member_size_bytes, 33779712)
        self.assertEqual(
            release.member_sha256,
            "7da96104954d4a9625dcec5f18bf64df62107ada37822ca953e2fe503a69d079",
        )


if __name__ == "__main__":
    unittest.main()

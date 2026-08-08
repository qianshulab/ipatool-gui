import json
import os
import plistlib
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from PyQt6.QtCore import QCoreApplication

from core.atomic_file import replace_verified as real_replace_verified
from core.ipatool import IPATool
from ui.workers import (
    AuthCheckWorker,
    ClearAuthCacheWorker,
    DownloadWorker,
    LoginWorker,
    LogoutWorker,
    SearchWorker,
)


def _write_synthetic_ipa(
    path: Path,
    bundle_id: str = "com.example.test",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "Payload/Synthetic.app/Info.plist",
            plistlib.dumps({
                "CFBundleIdentifier": bundle_id,
                "CFBundleName": "Synthetic",
            }),
        )


class _SuccessfulIPATool:
    def login(self, email, _password, _auth_code):
        return {
            "success": True,
            "email": email,
            "name": "Test User",
        }

    def get_account_info(self):
        return {
            "success": True,
            "returncode": 0,
            "email": "user@example.com",
        }


class _UnverifiedIPATool(_SuccessfulIPATool):
    def get_account_info(self):
        return {"success": False, "returncode": 1}


class _AuthInfoIPATool:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def get_account_info(self):
        self.calls += 1
        return self.response


class AuthCheckWorkerTests(unittest.TestCase):
    def test_fetches_account_info_once_and_keeps_result(self):
        ipatool = _AuthInfoIPATool({
            "success": True,
            "returncode": 0,
            "email": "user@example.com",
        })
        worker = AuthCheckWorker(ipatool)

        worker.run()

        self.assertEqual(ipatool.calls, 1)
        self.assertEqual(worker.result["email"], "user@example.com")
        self.assertIsNone(worker.error_message)

    def test_maps_account_info_exception_without_raising(self):
        class FailingIPATool:
            def get_account_info(self):
                raise RuntimeError(
                    "auth info failed; Authorization: SYNTHETIC_TOKEN; "
                    "email=synthetic@example.invalid"
                )

        worker = AuthCheckWorker(FailingIPATool())
        worker.run()

        self.assertIsNone(worker.result)
        self.assertIn("auth info failed", worker.error_message)
        self.assertNotIn("SYNTHETIC_TOKEN", worker.error_message)
        self.assertNotIn("synthetic@example.invalid", worker.error_message)


class LoginWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_verifies_successful_login_before_emitting_result(self):
        worker = LoginWorker(
            _SuccessfulIPATool(),
            "user@example.com",
            "secret-password",
            "123456",
        )
        worker.run()

        result = worker.result
        self.assertTrue(result["success"])
        self.assertTrue(result["auth_verified"])

    def test_clears_ephemeral_secrets_after_worker_finishes(self):
        worker = LoginWorker(
            _SuccessfulIPATool(),
            "user@example.com",
            "secret-password",
            "123456",
        )

        worker.run()

        self.assertEqual(worker.email, "")
        self.assertEqual(worker.password, "")
        self.assertIsNone(worker.auth_code)

    def test_reports_login_state_verification_failure(self):
        worker = LoginWorker(
            _UnverifiedIPATool(),
            "user@example.com",
            "secret-password",
        )
        worker.run()

        result = worker.result
        self.assertFalse(result["success"])
        self.assertTrue(result["auth_verification_failed"])

    def test_rejects_auth_info_for_a_different_account(self):
        class MismatchedAccountIPATool(_SuccessfulIPATool):
            @staticmethod
            def get_account_info():
                return {
                    "success": True,
                    "returncode": 0,
                    "email": "other@example.invalid",
                }

        worker = LoginWorker(
            MismatchedAccountIPATool(),
            "requested@example.invalid",
            "SYNTHETIC_PASSWORD",
        )

        worker.run()

        self.assertFalse(worker.result["success"])
        self.assertTrue(worker.result["auth_account_mismatch"])

    def test_result_dictionary_is_sanitized_before_worker_retains_it(self):
        class SensitiveFailureIPATool:
            @staticmethod
            def login(_email, _password, _auth_code):
                return {
                    "success": False,
                    "error": "failed for synthetic@example.invalid",
                    "PasswordToken": "SYNTHETIC_TOKEN_VALUE",
                }

        worker = LoginWorker(
            SensitiveFailureIPATool(),
            "synthetic@example.invalid",
            "SYNTHETIC_PASSWORD",
        )

        worker.run()

        serialized = str(worker.result)
        self.assertNotIn("SYNTHETIC_TOKEN_VALUE", serialized)
        self.assertNotIn("synthetic@example.invalid", worker.result["error"])


class AuthCleanupWorkerTests(unittest.TestCase):
    def test_logout_worker_revokes_once(self):
        class IPATool:
            def __init__(self):
                self.calls = 0

            def logout(self):
                self.calls += 1
                return {"success": True, "returncode": 0}

        ipatool = IPATool()
        worker = LogoutWorker(ipatool)

        worker.run()

        self.assertEqual(ipatool.calls, 1)
        self.assertTrue(worker.result["success"])
        self.assertIsNone(worker.error_message)

    def test_cache_worker_continues_local_cleanup_after_revoke_exception(self):
        class IPATool:
            def __init__(self):
                self.cache_calls = 0

            @staticmethod
            def logout():
                raise RuntimeError("synthetic revoke failure")

            def clear_local_cache(self):
                self.cache_calls += 1
                return {"success": True, "removed": ["synthetic-cache"]}

        ipatool = IPATool()
        worker = ClearAuthCacheWorker(ipatool)

        worker.run()

        self.assertEqual(ipatool.cache_calls, 1)
        self.assertTrue(worker.result["cache"]["success"])
        self.assertEqual(len(worker.result["errors"]), 1)


class DownloadWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_nonzero_process_exit_cannot_emit_download_success(self):
        ipatool = MagicMock()
        ipatool.ipatool_path = "ipatool"
        process = MagicMock()
        process.stdout = iter(['{"success":true}\n'])
        process.wait.return_value = 1
        errors = []
        finished = []

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "test.ipa"
            worker = DownloadWorker(
                ipatool,
                bundle_id="com.example.test",
                output_path=str(output),
                auto_purchase=False,
            )
            worker.failed.connect(errors.append)
            worker.succeeded.connect(finished.append)

            with patch("ui.workers.subprocess.Popen", return_value=process), patch(
                "platform.system", return_value="Linux"
            ):
                worker.run()

        self.assertEqual(finished, [])
        self.assertTrue(errors)

    def test_cancel_terminates_the_active_download_process(self):
        worker = DownloadWorker(
            MagicMock(),
            bundle_id="com.example.test",
            output_path="test.ipa",
            auto_purchase=False,
        )
        process = MagicMock()
        process.poll.return_value = None
        worker._process = process

        worker.cancel()

        process.terminate.assert_called_once_with()

    @unittest.skipUnless(os.name == "nt", "requires Windows process APIs")
    def test_cancel_windows_terminates_tree_before_parent_can_exit(self):
        worker = DownloadWorker(
            MagicMock(),
            bundle_id="com.example.test",
            output_path="test.ipa",
            auto_purchase=False,
        )
        process = MagicMock()
        process.pid = 4242
        process.poll.return_value = None
        process.wait.return_value = 0
        worker._process = process
        taskkill_result = MagicMock(returncode=0)

        with patch("ui.workers.platform.system", return_value="Windows"), patch(
            "ui.workers.subprocess.run",
            return_value=taskkill_result,
        ) as taskkill:
            worker.cancel()

        taskkill.assert_called_once_with(
            ["taskkill.exe", "/PID", "4242", "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3.0,
            check=False,
        )
        process.terminate.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "requires Windows process APIs")
    def test_cancel_windows_still_terminates_tree_after_parent_exits(self):
        worker = DownloadWorker(
            MagicMock(),
            bundle_id="com.example.test",
            output_path="test.ipa",
            auto_purchase=False,
        )
        process = MagicMock()
        process.pid = 4242
        process.poll.return_value = 0
        process.wait.return_value = 0
        worker._process = process
        taskkill_result = MagicMock(returncode=1)

        with patch("ui.workers.platform.system", return_value="Windows"), patch(
            "ui.workers.subprocess.run",
            return_value=taskkill_result,
        ) as taskkill:
            worker.cancel()

        taskkill.assert_called_once_with(
            ["taskkill.exe", "/PID", "4242", "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3.0,
            check=False,
        )

    def test_stderr_only_success_event_cannot_publish_download(self):
        ipatool = MagicMock(ipatool_path="ipatool")
        process = MagicMock()
        process.wait.return_value = 0
        process.poll.return_value = 0
        stderr_event = '{"success":true}\n'
        errors = []
        succeeded = []

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "test.ipa"
            worker = DownloadWorker(
                ipatool,
                bundle_id="com.example.test",
                output_path=str(output),
                auto_purchase=False,
            )
            worker.failed.connect(errors.append)
            worker.succeeded.connect(succeeded.append)

            def launch(command, **kwargs):
                command_output = Path(command[command.index("--output") + 1])
                _write_synthetic_ipa(command_output)
                if kwargs["stderr"] == subprocess.STDOUT:
                    process.stdout = iter([stderr_event])
                    process.stderr = None
                else:
                    process.stdout = iter(())
                    process.stderr = iter([stderr_event])
                return process

            with patch("ui.workers.subprocess.Popen", side_effect=launch) as popen, patch(
                "ui.workers.platform.system", return_value="Linux"
            ):
                worker.run()

        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.PIPE)
        self.assertEqual(succeeded, [])
        self.assertTrue(errors)

    def test_cancel_tolerates_a_process_that_disappeared_before_poll(self):
        worker = DownloadWorker(
            MagicMock(),
            bundle_id="com.example.test",
            output_path="test.ipa",
            auto_purchase=False,
        )
        process = MagicMock()
        process.poll.side_effect = OSError("synthetic process disappeared")
        worker._process = process

        worker.cancel()

        self.assertTrue(worker._is_cancel_requested())
        process.terminate.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "requires Windows process APIs")
    def test_cancel_escalates_to_bounded_process_tree_termination(self):
        worker = DownloadWorker(
            MagicMock(),
            bundle_id="com.example.test",
            output_path="test.ipa",
            auto_purchase=False,
        )
        process = MagicMock()
        process.pid = 4242
        process.poll.return_value = None
        process.wait.side_effect = [
            subprocess.TimeoutExpired("ipatool", 1.0),
            0,
        ]
        worker._process = process
        taskkill_result = MagicMock(returncode=0)

        with patch("ui.workers.platform.system", return_value="Windows"), patch(
            "ui.workers.subprocess.run",
            return_value=taskkill_result,
        ) as taskkill:
            worker.cancel()

        process.terminate.assert_not_called()
        taskkill.assert_called_once_with(
            ["taskkill.exe", "/PID", "4242", "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3.0,
            check=False,
        )
        self.assertEqual(process.wait.call_args_list[0].kwargs, {"timeout": 1.0})
        self.assertEqual(process.wait.call_args_list[1].kwargs, {"timeout": 1.0})

    def test_download_business_success_does_not_override_qthread_finished(self):
        worker = DownloadWorker(
            MagicMock(ipatool_path="ipatool"),
            bundle_id="com.example.test",
            output_path="test.ipa",
            auto_purchase=False,
        )

        self.assertNotIn("finished", DownloadWorker.__dict__)
        self.assertTrue(hasattr(worker, "succeeded"))

    def test_cancel_after_artifact_check_cannot_emit_download_success(self):
        ipatool = MagicMock(ipatool_path="ipatool")
        process = MagicMock()
        process.stdout = iter(['{"success":true}\n'])
        process.wait.return_value = 0
        process.poll.return_value = 0

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "test.ipa"
            worker = DownloadWorker(
                ipatool,
                bundle_id="com.example.test",
                output_path=str(output),
                auto_purchase=False,
            )
            original_validate = worker._validate_ipa

            def launch_with_valid_ipa(command, **_kwargs):
                command_output = Path(command[command.index("--output") + 1])
                _write_synthetic_ipa(command_output)
                return process

            def validate_and_cancel(path, expected_bundle_id=None):
                validation = original_validate(path, expected_bundle_id)
                worker.cancel()
                return validation

            succeeded = []
            failed = []
            cancelled = []
            worker.succeeded.connect(succeeded.append)
            worker.failed.connect(failed.append)
            worker.cancelled.connect(lambda: cancelled.append(True))

            with patch.object(
                worker,
                "_validate_ipa",
                side_effect=validate_and_cancel,
            ), patch(
                "ui.workers.subprocess.Popen",
                side_effect=launch_with_valid_ipa,
            ), patch(
                "ui.workers.platform.system", return_value="Linux"
            ):
                worker.run()

        self.assertEqual(succeeded, [])
        self.assertEqual(failed, [])
        self.assertEqual(cancelled, [True])
        self.assertFalse(output.exists())
        self.assertEqual(list(output.parent.glob(f".{output.name}.*.part*")), [])

    @unittest.skipUnless(os.name == "nt", "requires Windows process APIs")
    def test_windows_process_is_suspended_until_assigned_to_kill_on_close_job(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "app.ipa"
            process = MagicMock()
            process.pid = 42001
            process.stdout = iter(['{"success":true}\n'])
            process.stderr = iter([])
            process.wait.return_value = 0
            order = []

            def launch(command, **_kwargs):
                command_output = Path(command[command.index("--output") + 1])
                _write_synthetic_ipa(command_output)
                return process

            worker = DownloadWorker(
                MagicMock(ipatool_path="ipatool"),
                bundle_id="com.example.test",
                output_path=str(output_path),
                auto_purchase=False,
            )
            successes = []
            errors = []
            worker.succeeded.connect(successes.append)
            worker.failed.connect(errors.append)

            with patch("ui.workers.platform.system", return_value="Windows"), patch(
                "ui.workers.subprocess.Popen", side_effect=launch
            ) as popen, patch.object(
                worker,
                "_create_windows_job",
                side_effect=lambda _process: order.append("assign") or 123,
            ), patch.object(
                worker,
                "_resume_windows_process",
                side_effect=lambda _pid: order.append("resume"),
            ), patch.object(
                worker,
                "_close_windows_job",
                side_effect=lambda _handle: order.append("close"),
            ):
                worker.run()

            creationflags = popen.call_args.kwargs["creationflags"]
            self.assertEqual(creationflags & 0x00000004, 0x00000004)
            self.assertEqual(order, ["assign", "resume", "close"])
            self.assertEqual(errors, [])
            self.assertEqual(successes, [str(output_path)])

    def test_worker_rejects_unsafe_bundle_id_before_starting_subprocess(self):
        worker = DownloadWorker(
            MagicMock(ipatool_path="ipatool"),
            bundle_id="../escaped",
            output_path="escaped.ipa",
            auto_purchase=False,
        )
        errors = []
        worker.failed.connect(errors.append)

        with patch("ui.workers.subprocess.Popen") as popen:
            worker.run()

        popen.assert_not_called()
        self.assertTrue(errors)
        self.assertIn("Bundle ID", errors[0])

    def test_cancel_before_process_creation_does_not_start_download(self):
        worker = DownloadWorker(
            MagicMock(ipatool_path="ipatool"),
            bundle_id="com.example.test",
            output_path="test.ipa",
            auto_purchase=True,
        )

        def cancel_during_setup():
            worker.cancel()
            return "Linux"

        with patch("platform.system", side_effect=cancel_during_setup), patch(
            "ui.workers.subprocess.Popen"
        ) as popen:
            worker.run()

        self.assertEqual(popen.call_count, 0)

    def test_cancel_during_popen_handoff_uses_bounded_termination(self):
        worker = DownloadWorker(
            MagicMock(ipatool_path="ipatool"),
            bundle_id="com.example.test",
            output_path="test.ipa",
            auto_purchase=False,
        )
        process = MagicMock()
        process.poll.return_value = None
        process.stdout = iter(())
        process.wait.return_value = 0
        cancelled = []
        worker.cancelled.connect(lambda: cancelled.append(True))

        def cancel_before_handoff(*_args, **_kwargs):
            worker.cancel()
            return process

        with patch("ui.workers.subprocess.Popen", side_effect=cancel_before_handoff), patch(
            "ui.workers.platform.system", return_value="Linux"
        ), patch.object(worker, "_terminate_process") as terminate:
            worker.run()

        terminate.assert_called_once_with(process)
        self.assertEqual(cancelled, [True])

    def test_auto_purchase_uses_the_cancellable_download_process(self):
        ipatool = MagicMock()
        ipatool.ipatool_path = "ipatool"
        process = MagicMock()
        process.stdout = iter(['{"success":true}\n'])
        finished = []

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "test.ipa"

            def launch_with_valid_ipa(command, **_kwargs):
                command_output = Path(command[command.index("--output") + 1])

                def complete_download():
                    _write_synthetic_ipa(command_output)
                    return 0

                process.wait.side_effect = complete_download
                return process

            worker = DownloadWorker(
                ipatool,
                bundle_id="com.example.test",
                output_path=str(output),
                auto_purchase=True,
            )
            worker.succeeded.connect(finished.append)

            with patch(
                "ui.workers.subprocess.Popen",
                side_effect=launch_with_valid_ipa,
            ) as popen, patch(
                "ui.workers.platform.system", return_value="Linux"
            ):
                worker.run()

        ipatool.purchase.assert_not_called()
        self.assertIn("--purchase", popen.call_args.args[0])
        self.assertEqual(finished, [str(output)])

    def test_streamed_download_output_is_redacted_before_signals(self):
        ipatool = object.__new__(IPATool)
        ipatool.ipatool_path = "ipatool"
        process = MagicMock()
        process.stdout = iter([
            '{"success":false,"error":"failed for synthetic@example.invalid",'
            '"PasswordToken":"SYNTHETIC_TOKEN_VALUE"}\n'
        ])
        process.wait.return_value = 1
        progress = []
        errors = []
        worker = DownloadWorker(
            ipatool,
            bundle_id="com.example.test",
            output_path="missing.ipa",
            auto_purchase=False,
        )
        worker.progress.connect(lambda message, _percent: progress.append(message))
        worker.failed.connect(errors.append)

        with patch("ui.workers.subprocess.Popen", return_value=process), patch(
            "platform.system", return_value="Linux"
        ):
            worker.run()

        displayed = "\n".join(progress + errors)
        self.assertNotIn("synthetic@example.invalid", displayed)
        self.assertNotIn("SYNTHETIC_TOKEN_VALUE", displayed)
        self.assertIn("***", displayed)

    def test_structured_download_error_is_recursively_redacted_before_signal(self):
        ipatool = object.__new__(IPATool)
        ipatool.ipatool_path = "ipatool"
        process = MagicMock()
        process.stdout = iter([
            json.dumps({
                "success": False,
                "error": {
                    "details": [{
                        "PasswordToken": "SYNTHETIC_NESTED_TOKEN",
                        "accountEmail": "synthetic@example.invalid",
                    }]
                },
            }) + "\n"
        ])
        process.wait.return_value = 1
        errors = []
        worker = DownloadWorker(
            ipatool,
            bundle_id="com.example.test",
            output_path="missing.ipa",
            auto_purchase=False,
        )
        worker.failed.connect(errors.append)

        with patch("ui.workers.subprocess.Popen", return_value=process), patch(
            "platform.system", return_value="Linux"
        ):
            worker.run()

        self.assertEqual(len(errors), 1)
        self.assertNotIn("SYNTHETIC_NESTED_TOKEN", errors[0])
        self.assertNotIn("synthetic@example.invalid", errors[0])
        self.assertIn("***", errors[0])

    def test_success_event_requires_the_downloaded_ipa_to_exist(self):
        ipatool = MagicMock()
        ipatool.ipatool_path = "ipatool"
        process = MagicMock()
        process.stdout = iter(['{"success":true}\n'])
        process.wait.return_value = 0
        errors = []
        finished = []

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "missing.ipa"
            worker = DownloadWorker(
                ipatool,
                bundle_id="com.example.test",
                output_path=str(output),
                auto_purchase=False,
            )
            worker.failed.connect(errors.append)
            worker.succeeded.connect(finished.append)

            with patch("ui.workers.subprocess.Popen", return_value=process), patch(
                "platform.system", return_value="Linux"
            ):
                worker.run()

        self.assertEqual(finished, [])
        self.assertTrue(errors)

    def test_explicit_output_path_never_falls_back_to_an_old_working_directory_ipa(self):
        ipatool = MagicMock()
        ipatool.ipatool_path = "ipatool"
        process = MagicMock()
        process.stdout = iter(['{"success":true}\n'])
        process.wait.return_value = 0
        errors = []
        finished = []

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "com.example.test-old.ipa").write_bytes(b"old synthetic ipa")
            expected_output = temp_path / "expected" / "new.ipa"
            worker = DownloadWorker(
                ipatool,
                bundle_id="com.example.test",
                output_path=str(expected_output),
                auto_purchase=False,
            )
            worker.failed.connect(errors.append)
            worker.succeeded.connect(finished.append)

            previous_cwd = Path.cwd()
            try:
                os.chdir(temp_path)
                with patch("ui.workers.subprocess.Popen", return_value=process), patch(
                    "platform.system", return_value="Linux"
                ):
                    worker.run()
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(finished, [])
        self.assertTrue(errors)

    def test_missing_output_path_never_reuses_an_old_working_directory_ipa(self):
        ipatool = MagicMock(ipatool_path="ipatool")
        errors = []
        succeeded = []

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            old_ipa = temp_path / "old-com.example.test-artifact.ipa"
            _write_synthetic_ipa(old_ipa)
            worker = DownloadWorker(
                ipatool,
                bundle_id="com.example.test",
                output_path=None,
                auto_purchase=False,
            )
            worker.failed.connect(errors.append)
            worker.succeeded.connect(succeeded.append)

            previous_cwd = Path.cwd()
            try:
                os.chdir(temp_path)
                with patch("ui.workers.subprocess.Popen") as popen:
                    worker.run()
            finally:
                os.chdir(previous_cwd)

        popen.assert_not_called()
        self.assertEqual(succeeded, [])
        self.assertTrue(errors)


    def test_unchanged_preexisting_explicit_output_is_not_reported_as_new_download(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "com.example.test.ipa"
            output_path.write_bytes(b"OLD-IPA")
            worker = DownloadWorker(
                MagicMock(ipatool_path="ipatool"),
                app_id=None,
                bundle_id="com.example.test",
                output_path=str(output_path),
                auto_purchase=False,
            )
            process = MagicMock()
            process.stdout = iter(['{"success": true}\n'])
            process.wait.return_value = 0
            finished = []
            errors = []
            worker.succeeded.connect(finished.append)
            worker.failed.connect(errors.append)

            with patch("ui.workers.subprocess.Popen", return_value=process), patch(
                "platform.system", return_value="Linux"
            ):
                worker.run()

        self.assertEqual(finished, [])
        self.assertTrue(errors)


    def test_invalid_partial_output_never_replaces_existing_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "com.example.test.ipa"
            original = b"SYNTHETIC_EXISTING_IPA"
            output_path.write_bytes(original)
            worker = DownloadWorker(
                MagicMock(ipatool_path="ipatool"),
                bundle_id="com.example.test",
                output_path=str(output_path),
                auto_purchase=False,
            )
            process = MagicMock()
            process.stdout = iter(['{"success": true}\n'])

            def launch_and_write_partial(command, **_kwargs):
                command_output = Path(command[command.index("--output") + 1])

                def write_partial_output():
                    command_output.write_bytes(b"SYNTHETIC_PARTIAL_DOWNLOAD")
                    Path(f"{command_output}.tmp").write_bytes(
                        b"SYNTHETIC_IPATOOL_SIDECAR"
                    )
                    return 0

                process.wait.side_effect = write_partial_output
                return process

            succeeded = []
            failed = []
            worker.succeeded.connect(succeeded.append)
            worker.failed.connect(failed.append)

            with patch(
                "ui.workers.subprocess.Popen",
                side_effect=launch_and_write_partial,
            ), patch(
                "ui.workers.platform.system", return_value="Linux"
            ):
                worker.run()

            self.assertEqual(succeeded, [])
            self.assertTrue(failed)
            self.assertEqual(output_path.read_bytes(), original)
            self.assertEqual(
                list(output_path.parent.glob(f".{output_path.name}.*.part*")),
                [],
            )

    def test_cancelled_partial_output_is_cleaned_and_existing_target_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "com.example.test.ipa"
            original = b"SYNTHETIC_EXISTING_IPA"
            output_path.write_bytes(original)
            worker = DownloadWorker(
                MagicMock(ipatool_path="ipatool"),
                bundle_id="com.example.test",
                output_path=str(output_path),
                auto_purchase=False,
            )
            process = MagicMock()
            process.stdout = iter(['{"success": true}\n'])
            process.poll.return_value = 0

            def launch_and_cancel(command, **_kwargs):
                command_output = Path(command[command.index("--output") + 1])

                def cancel_partial_download():
                    command_output.write_bytes(b"SYNTHETIC_PARTIAL_DOWNLOAD")
                    worker.cancel()
                    return 0

                process.wait.side_effect = cancel_partial_download
                return process

            succeeded = []
            failed = []
            cancelled = []
            worker.succeeded.connect(succeeded.append)
            worker.failed.connect(failed.append)
            worker.cancelled.connect(lambda: cancelled.append(True))

            with patch(
                "ui.workers.subprocess.Popen",
                side_effect=launch_and_cancel,
            ), patch(
                "ui.workers.platform.system", return_value="Linux"
            ):
                worker.run()

            self.assertEqual(succeeded, [])
            self.assertEqual(failed, [])
            self.assertEqual(cancelled, [True])
            self.assertEqual(output_path.read_bytes(), original)
            self.assertEqual(
                list(output_path.parent.glob(f".{output_path.name}.*.part")),
                [],
            )

    def test_valid_ipa_is_atomically_moved_to_the_requested_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "com.example.test.ipa"
            worker = DownloadWorker(
                MagicMock(ipatool_path="ipatool"),
                bundle_id="com.example.test",
                output_path=str(output_path),
                auto_purchase=False,
            )
            process = MagicMock()
            process.stdout = iter(['{"success": true}\n'])

            def launch_with_valid_ipa(command, **_kwargs):
                command_output = Path(command[command.index("--output") + 1])

                def complete_download():
                    _write_synthetic_ipa(command_output)
                    return 0

                process.wait.side_effect = complete_download
                return process

            succeeded = []
            failed = []
            worker.succeeded.connect(succeeded.append)
            worker.failed.connect(failed.append)
            with patch(
                "ui.workers.subprocess.Popen",
                side_effect=launch_with_valid_ipa,
            ), patch(
                "ui.workers.platform.system", return_value="Linux"
            ), patch(
                "ui.workers.replace_verified",
                side_effect=real_replace_verified,
            ) as atomic_replace:
                worker.run()

            self.assertEqual(failed, [])
            self.assertEqual(succeeded, [str(output_path)])
            self.assertTrue(DownloadWorker._validate_ipa(output_path)[0])
            temporary_path, committed_path, _verifier = atomic_replace.call_args.args
            self.assertEqual(Path(temporary_path).parent, output_path.parent)
            self.assertNotEqual(Path(temporary_path), output_path)
            self.assertEqual(Path(committed_path), output_path)
            self.assertFalse(Path(temporary_path).exists())

    def test_noninteractive_download_uses_busy_progress_until_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "com.example.test.ipa"
            worker = DownloadWorker(
                MagicMock(ipatool_path="ipatool"),
                bundle_id="com.example.test",
                output_path=str(output_path),
                auto_purchase=False,
            )
            process = MagicMock()
            process.stdout = iter([
                "synthetic upstream text containing 73%\n",
                '{"success": true}\n',
            ])
            process.stderr = iter(())

            def launch_with_valid_ipa(command, **_kwargs):
                command_output = Path(command[command.index("--output") + 1])

                def complete_download():
                    _write_synthetic_ipa(command_output)
                    return 0

                process.wait.side_effect = complete_download
                return process

            progress_events = []
            worker.progress.connect(
                lambda message, percent: progress_events.append((message, percent))
            )
            with patch(
                "ui.workers.subprocess.Popen",
                side_effect=launch_with_valid_ipa,
            ), patch(
                "ui.workers.platform.system", return_value="Linux"
            ), patch(
                "ui.workers.replace_verified",
                side_effect=real_replace_verified,
            ):
                worker.run()

            self.assertEqual(
                [percent for _message, percent in progress_events],
                [-1, -1, 100],
            )
            self.assertIn(
                ("正在校验并保存 IPA（大小未知）...", -1),
                progress_events,
            )
            self.assertNotIn(
                "synthetic upstream text",
                "\n".join(message for message, _percent in progress_events),
            )

    def test_wrong_bundle_identity_cannot_replace_existing_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "com.example.test.ipa"
            original = b"SYNTHETIC_EXISTING_IPA"
            output_path.write_bytes(original)
            worker = DownloadWorker(
                MagicMock(ipatool_path="ipatool"),
                bundle_id="com.example.test",
                output_path=str(output_path),
                auto_purchase=False,
            )
            process = MagicMock()
            process.stdout = iter(['{"success": true}\n'])

            def launch_with_wrong_identity(command, **_kwargs):
                command_output = Path(command[command.index("--output") + 1])

                def complete_download():
                    _write_synthetic_ipa(command_output, "com.example.other")
                    return 0

                process.wait.side_effect = complete_download
                return process

            succeeded = []
            failed = []
            worker.succeeded.connect(succeeded.append)
            worker.failed.connect(failed.append)

            with patch(
                "ui.workers.subprocess.Popen",
                side_effect=launch_with_wrong_identity,
            ), patch("ui.workers.platform.system", return_value="Linux"):
                worker.run()

            self.assertEqual(succeeded, [])
            self.assertTrue(failed)
            self.assertEqual(output_path.read_bytes(), original)

    def test_atomic_replace_failure_preserves_existing_target_and_cleans_part(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "com.example.test.ipa"
            original = b"SYNTHETIC_EXISTING_IPA"
            output_path.write_bytes(original)
            worker = DownloadWorker(
                MagicMock(ipatool_path="ipatool"),
                bundle_id="com.example.test",
                output_path=str(output_path),
                auto_purchase=False,
            )
            process = MagicMock()
            process.stdout = iter(['{"success": true}\n'])

            def launch_with_valid_ipa(command, **_kwargs):
                command_output = Path(command[command.index("--output") + 1])

                def complete_download():
                    _write_synthetic_ipa(command_output)
                    return 0

                process.wait.side_effect = complete_download
                return process

            succeeded = []
            failed = []
            worker.succeeded.connect(succeeded.append)
            worker.failed.connect(failed.append)

            with patch(
                "ui.workers.subprocess.Popen",
                side_effect=launch_with_valid_ipa,
            ), patch(
                "ui.workers.platform.system", return_value="Linux"
            ), patch(
                "ui.workers.replace_verified",
                side_effect=OSError("synthetic replace denied"),
            ):
                worker.run()

            self.assertEqual(succeeded, [])
            self.assertTrue(failed)
            self.assertEqual(output_path.read_bytes(), original)
            self.assertEqual(
                list(output_path.parent.glob(f".{output_path.name}.*.part")),
                [],
            )

    @unittest.skipUnless(os.name == "nt", "Windows junction semantics only")
    def test_parent_swap_during_final_ipa_verification_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "output"
            output_dir.mkdir()
            moved_dir = root / "moved"
            output_path = output_dir / "com.example.test.ipa"
            output_path.write_bytes(b"existing IPA")
            worker = DownloadWorker(
                MagicMock(ipatool_path="ipatool"),
                bundle_id="com.example.test",
                output_path=str(output_path),
                auto_purchase=False,
            )
            process = MagicMock()
            process.stdout = iter(['{"success": true}\n'])

            def launch_with_valid_ipa(command, **_kwargs):
                command_output = Path(command[command.index("--output") + 1])

                def complete_download():
                    _write_synthetic_ipa(command_output)
                    return 0

                process.wait.side_effect = complete_download
                return process

            original_validate = DownloadWorker._validate_ipa
            swap_errors = []

            def validate_and_attempt_swap(source, expected_bundle_id=None):
                result = original_validate(source, expected_bundle_id)
                if hasattr(source, "read"):
                    try:
                        os.replace(output_dir, moved_dir)
                    except OSError as exc:
                        swap_errors.append(exc)
                return result

            succeeded = []
            failed = []
            worker.succeeded.connect(succeeded.append)
            worker.failed.connect(failed.append)
            with patch(
                "ui.workers.subprocess.Popen",
                side_effect=launch_with_valid_ipa,
            ), patch(
                "ui.workers.platform.system", return_value="Linux"
            ), patch.object(
                worker,
                "_validate_ipa",
                side_effect=validate_and_attempt_swap,
            ):
                worker.run()

            self.assertTrue(swap_errors)
            self.assertEqual(failed, [])
            self.assertEqual(succeeded, [str(output_path)])
            self.assertTrue(output_dir.is_dir())
            self.assertFalse(moved_dir.exists())
            self.assertTrue(original_validate(output_path, "com.example.test")[0])

    def test_ipa_zip_without_payload_info_plist_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Path(temp_dir) / "invalid.ipa"
            with zipfile.ZipFile(candidate, "w") as archive:
                archive.writestr("Metadata.plist", b"SYNTHETIC_METADATA")

            valid, message = DownloadWorker._validate_ipa(candidate)

            self.assertFalse(valid)
            self.assertIn("Payload", message)

    def test_ipa_with_malformed_info_plist_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Path(temp_dir) / "invalid.ipa"
            with zipfile.ZipFile(candidate, "w") as archive:
                archive.writestr(
                    "Payload/Synthetic.app/Info.plist",
                    b"NOT_A_PLIST",
                )

            valid, message = DownloadWorker._validate_ipa(candidate)

            self.assertFalse(valid)
            self.assertIn("Info.plist", message)

    def test_ipa_with_corrupt_non_plist_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Path(temp_dir) / "corrupt.ipa"
            binary_contents = b"SYNTHETIC_BINARY_CONTENT"
            with zipfile.ZipFile(candidate, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr(
                    "Payload/Synthetic.app/Info.plist",
                    plistlib.dumps({"CFBundleIdentifier": "com.example.test"}),
                )
                archive.writestr(
                    "Payload/Synthetic.app/SyntheticBinary",
                    binary_contents,
                )
            archive_bytes = bytearray(candidate.read_bytes())
            content_offset = archive_bytes.index(binary_contents)
            archive_bytes[content_offset] ^= 0x01
            candidate.write_bytes(archive_bytes)

            valid, message = DownloadWorker._validate_ipa(
                candidate,
                "com.example.test",
            )

            self.assertFalse(valid)
            self.assertIn("损坏", message)

    def test_ipa_with_multiple_top_level_apps_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Path(temp_dir) / "ambiguous.ipa"
            with zipfile.ZipFile(candidate, "w") as archive:
                archive.writestr(
                    "Payload/Expected.app/Info.plist",
                    plistlib.dumps({"CFBundleIdentifier": "com.example.test"}),
                )
                archive.writestr(
                    "Payload/Unexpected.app/Info.plist",
                    plistlib.dumps({"CFBundleIdentifier": "com.example.other"}),
                )

            valid, message = DownloadWorker._validate_ipa(
                candidate,
                "com.example.test",
            )

            self.assertFalse(valid)
            self.assertIn("多个", message)

    def test_ipa_with_second_top_level_app_without_plist_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Path(temp_dir) / "ambiguous.ipa"
            with zipfile.ZipFile(candidate, "w") as archive:
                archive.writestr(
                    "Payload/Expected.app/Info.plist",
                    plistlib.dumps({"CFBundleIdentifier": "com.example.test"}),
                )
                archive.writestr(
                    "Payload/Unexpected.app/UnexpectedBinary",
                    b"SYNTHETIC_BINARY",
                )

            valid, message = DownloadWorker._validate_ipa(
                candidate,
                "com.example.test",
            )

            self.assertFalse(valid)
            self.assertIn("多个", message)


class SearchWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_search_exception_is_redacted_before_error_signal(self):
        ipatool = MagicMock()
        ipatool.search.side_effect = RuntimeError(
            "Authorization: SYNTHETIC_TOKEN for synthetic@example.invalid"
        )
        errors = []
        worker = SearchWorker(ipatool, "synthetic-query")
        worker.error.connect(errors.append)

        worker.run()

        self.assertEqual(len(errors), 1)
        self.assertNotIn("SYNTHETIC_TOKEN", errors[0])
        self.assertNotIn("synthetic@example.invalid", errors[0])
        self.assertIn("***", errors[0])

    def test_search_business_success_does_not_override_qthread_finished(self):
        ipatool = MagicMock()
        ipatool.search.return_value = [{"bundleId": "com.example.test"}]
        worker = SearchWorker(ipatool, "synthetic-query")
        results = []

        self.assertNotIn("finished", SearchWorker.__dict__)
        worker.succeeded.connect(results.append)
        worker.run()

        self.assertEqual(results, [[{"bundleId": "com.example.test"}]])


if __name__ == "__main__":
    unittest.main()

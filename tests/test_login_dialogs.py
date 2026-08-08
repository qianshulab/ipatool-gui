import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from core.config import Config
from ui import dialogs
from ui.dialogs import LoginDialog
from ui.main_window import MainWindow
from ui.workers import LoginWorker


class LoginDialogTwoFactorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dialog = LoginDialog(config=None)
        self.dialog.email_input.setText("user@example.com")
        self.dialog.password_input.setText("password")

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.processEvents()

    def test_initial_login_dialog_does_not_collect_auth_code(self):
        credentials = self.dialog.get_credentials()

        self.assertFalse(hasattr(self.dialog, "auth_code_input"))
        self.assertEqual(credentials, ("user@example.com", "password"))

    def test_remember_credentials_warns_about_plaintext_storage(self):
        self.assertFalse(self.dialog.remember_check.isChecked())
        self.assertIn("明文", self.dialog.remember_check.text())

    def test_accept_does_not_persist_password_before_remote_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config = Config(str(config_path))
            dialog = LoginDialog(config=config)
            try:
                dialog.email_input.setText("synthetic@example.invalid")
                dialog.password_input.setText("SYNTHETIC_PASSWORD")
                dialog.remember_check.setChecked(True)

                dialog.accept()

                self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
                self.assertFalse(config_path.exists())
                self.assertEqual(config.apple_password, "")
            finally:
                dialog.close()
                dialog.deleteLater()
                self.app.processEvents()

    def test_sensitive_fields_can_be_cleared_immediately(self):
        self.dialog.clear_sensitive_fields()

        self.assertEqual(self.dialog.password_input.text(), "")


class TwoFactorDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_verify_button_requires_a_normalized_six_digit_code(self):
        dialog_class = getattr(dialogs, "TwoFactorDialog", None)
        self.assertIsNotNone(dialog_class)
        dialog = dialog_class()
        try:
            self.assertFalse(dialog.verify_button.isEnabled())

            dialog.auth_code_input.setText("12345")
            self.assertFalse(dialog.verify_button.isEnabled())

            dialog.auth_code_input.setText("123 456")
            self.assertTrue(dialog.verify_button.isEnabled())
            self.assertEqual(dialog.get_auth_code(), "123456")
        finally:
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()

    def test_sensitive_code_can_be_cleared_immediately(self):
        dialog = dialogs.TwoFactorDialog()
        try:
            dialog.auth_code_input.setText("123456")

            dialog.clear_sensitive_fields()

            self.assertEqual(dialog.auth_code_input.text(), "")
        finally:
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()


class SettingsDialogConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_accept_keeps_dialog_open_when_config_save_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Config(str(Path(temp_dir) / "config.json"))
            dialog = dialogs.SettingsDialog(config=config)
            dialog.ipatool_path_input.setText("C:/synthetic/ipatool.exe")
            try:
                with patch.object(
                    config,
                    "set",
                    side_effect=OSError("synthetic write denied"),
                ), patch(
                    "PyQt6.QtWidgets.QMessageBox.critical",
                    return_value=None,
                ) as critical:
                    dialog.accept()

                self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)
                critical.assert_called_once()
            finally:
                dialog.close()
                dialog.deleteLater()
                self.app.processEvents()


class MainWindowTwoFactorFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_prompt_retries_login_with_code_from_two_factor_dialog(self):
        class AcceptedTwoFactorDialog:
            last_instance = None

            def __init__(self, *_args, **_kwargs):
                self.cleared = False
                self.deleted = False
                type(self).last_instance = self

            def exec(self):
                return QDialog.DialogCode.Accepted

            def get_auth_code(self):
                return "123456"

            def clear_sensitive_fields(self):
                self.cleared = True

            def deleteLater(self):
                self.deleted = True

        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        try:
            self.assertTrue(hasattr(window, "_prompt_for_auth_code"))
            calls = []
            window.login = lambda email, password, code="": calls.append(
                (email, password, code)
            ) or True

            with patch(
                "ui.main_window.TwoFactorDialog", AcceptedTwoFactorDialog, create=True
            ):
                accepted = window._prompt_for_auth_code(
                    "user@example.com", "password", error=True
                )

            self.assertTrue(accepted)
            self.assertEqual(calls, [("user@example.com", "password", "123456")])
            self.assertTrue(AcceptedTwoFactorDialog.last_instance.cleared)
            self.assertTrue(AcceptedTwoFactorDialog.last_instance.deleted)
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_login_dialog_is_cleared_and_deleted_after_accept(self):
        class RememberChoice:
            @staticmethod
            def isChecked():
                return False

        class AcceptedLoginDialog:
            last_instance = None

            def __init__(self, *_args, **_kwargs):
                self.remember_check = RememberChoice()
                self.cleared = False
                self.deleted = False
                type(self).last_instance = self

            @staticmethod
            def exec():
                return QDialog.DialogCode.Accepted

            @staticmethod
            def get_credentials():
                return "synthetic@example.invalid", "SYNTHETIC_PASSWORD"

            def clear_sensitive_fields(self):
                self.cleared = True

            def deleteLater(self):
                self.deleted = True

        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = object()
        window.login = MagicMock(return_value=True)
        try:
            with patch("ui.main_window.LoginDialog", AcceptedLoginDialog):
                window.show_login_dialog()

            instance = AcceptedLoginDialog.last_instance
            self.assertTrue(instance.cleared)
            self.assertTrue(instance.deleted)
            window.login.assert_called_once_with(
                "synthetic@example.invalid",
                "SYNTHETIC_PASSWORD",
                remember_credentials=False,
            )
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_success_uses_worker_verification_without_sync_ipatool_call(self):
        class NoSynchronousAuthCalls:
            def check_auth(self):
                raise AssertionError("GUI thread must not call ipatool.check_auth()")

        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = NoSynchronousAuthCalls()
        window._pending_login_email = "fallback@example.com"
        window._pending_login_password = "SYNTHETIC_PASSWORD"
        try:
            with patch("ui.main_window.QMessageBox.information", return_value=None):
                window.on_login_finished(
                    {
                        "success": True,
                        "auth_verified": True,
                        "email": "verified@example.com",
                    },
                    "fallback@example.com",
                    "password",
                )

            self.assertEqual(window.account_label.text(), "已登录: verified@example.com")
            self.assertEqual(window.login_btn.text(), "退出登录")
            self.assertEqual(window._pending_login_password, "")
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_success_persists_opted_in_credentials_after_worker_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "ui.main_window.QTimer.singleShot", return_value=None
        ):
            window = MainWindow()
            window.config = Config(str(Path(temp_dir) / "config.json"))
            window._pending_login_email = "synthetic@example.invalid"
            window._pending_login_password = "SYNTHETIC_PASSWORD"
            window._pending_remember_credentials = True
            try:
                with patch("ui.main_window.QMessageBox.information", return_value=None):
                    window.on_login_finished({
                        "success": True,
                        "auth_verified": True,
                        "email": "synthetic@example.invalid",
                    })

                self.assertTrue(window.config.remember_credentials)
                self.assertEqual(window.config.apple_email, "synthetic@example.invalid")
                self.assertEqual(window.config.apple_password, "SYNTHETIC_PASSWORD")
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_success_clears_pending_password_and_warns_if_credential_save_fails(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window._pending_login_email = "synthetic@example.invalid"
        window._pending_login_password = "SYNTHETIC_PASSWORD"
        window._pending_remember_credentials = True
        window.config = MagicMock()
        window.config.save_apple_credentials.side_effect = OSError("write denied")
        try:
            with patch(
                "ui.main_window.QMessageBox.information", return_value=None
            ) as information, patch(
                "ui.main_window.QMessageBox.warning", return_value=None
            ) as warning:
                window.on_login_finished({
                    "success": True,
                    "auth_verified": True,
                    "email": "synthetic@example.invalid",
                })

            self.assertTrue(window._authenticated)
            self.assertEqual(window._pending_login_password, "")
            self.assertIsNone(window._pending_remember_credentials)
            information.assert_not_called()
            warning.assert_called_once()
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_stale_login_worker_result_is_ignored(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        current_worker = MagicMock()
        stale_worker = MagicMock()
        stale_worker.error_message = ""
        stale_worker.result = {"success": False, "error": "stale result"}
        window.login_worker = current_worker
        try:
            with patch.object(window, "on_login_finished") as on_finished, patch.object(
                window, "on_login_error"
            ) as on_error:
                window._on_login_worker_stopped(stale_worker)

            self.assertIs(window.login_worker, current_worker)
            on_finished.assert_not_called()
            on_error.assert_not_called()
            stale_worker.deleteLater.assert_called_once_with()
        finally:
            window.login_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_login_start_failure_clears_worker_credentials_and_reference(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = object()
        created = []

        def make_worker(ipatool, email, password, auth_code):
            worker = LoginWorker(ipatool, email, password, auth_code)
            worker.start = MagicMock(side_effect=RuntimeError("synthetic start failure"))
            created.append(worker)
            return worker

        try:
            with patch("ui.main_window.LoginWorker", side_effect=make_worker), patch(
                "ui.main_window.QMessageBox.critical", return_value=None
            ):
                started = window.login(
                    "synthetic@example.invalid",
                    "SYNTHETIC_PASSWORD",
                    "123456",
                )

            self.assertFalse(started)
            self.assertIsNone(window.login_worker)
            self.assertEqual(created[0].email, "")
            self.assertEqual(created[0].password, "")
            self.assertIsNone(created[0].auth_code)
            self.assertEqual(window._pending_login_password, "")
        finally:
            window.login_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_gui_log_redacts_bearer_credentials_at_final_sink(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        secret = "SYNTHETIC_GUI_BEARER_CREDENTIAL"
        try:
            window.log(f"Authorization: Bearer {secret}")

            rendered = window.log_text.toPlainText()
            self.assertNotIn(secret, rendered)
            self.assertNotIn("Bearer", rendered)
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_gui_log_redacts_nested_python_mapping_at_final_sink(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        secret = "SYNTHETIC_GUI_MAPPING_SECRET"
        try:
            window.log({
                "password": secret,
                "nested": {"token": secret},
            })

            rendered = window.log_text.toPlainText()
            self.assertNotIn(secret, rendered)
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_installer_start_failure_rolls_back_worker_reference(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        dialog = MagicMock()
        dialog.exec.return_value = True
        worker = MagicMock()
        worker.start.side_effect = RuntimeError("synthetic start failure")
        try:
            with patch(
                "ui.main_window.InstallIPADialog", return_value=dialog
            ), patch(
                "ui.main_window.IPAToolInstaller", return_value=worker
            ), patch("ui.main_window.QMessageBox.critical", return_value=None):
                started = window.install_ipatool()

            self.assertFalse(started)
            self.assertIsNone(window.ipatool_installer)
            worker.deleteLater.assert_called_once_with()
        finally:
            window.ipatool_installer = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_installer_thread_finished_cleans_reference_and_retries_close(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        dialog = MagicMock()
        dialog.exec.return_value = True
        worker = MagicMock()
        worker.isRunning.return_value = False
        try:
            with patch(
                "ui.main_window.InstallIPADialog", return_value=dialog
            ), patch("ui.main_window.IPAToolInstaller", return_value=worker):
                started = window.install_ipatool()

            self.assertTrue(started)
            worker.finished.connect.assert_called_once()
            stopped_callback = worker.finished.connect.call_args.args[0]
            window._close_requested = True
            with patch.object(window, "_schedule_requested_close") as schedule:
                stopped_callback()

            self.assertIsNone(window.ipatool_installer)
            worker.deleteLater.assert_called_once_with()
            schedule.assert_called_once_with()
        finally:
            window.ipatool_installer = None
            window._close_requested = False
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_install_finished_does_not_repeat_persisted_config_write(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        try:
            with patch.object(
                window.config,
                "set",
                side_effect=AssertionError("worker already persisted the path"),
            ), patch.object(window, "init_ipatool") as init_ipatool, patch(
                "ui.main_window.QMessageBox.information",
                return_value=None,
            ):
                window.on_install_finished("C:/synthetic/ipatool.exe")

            init_ipatool.assert_called_once_with()
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_check_auth_starts_worker_without_calling_ipatool_on_gui_thread(self):
        class NoSynchronousAuthCalls:
            def check_auth(self):
                raise AssertionError("GUI thread must not call check_auth")

            def get_account_info(self):
                raise AssertionError("GUI thread must not call get_account_info")

        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = NoSynchronousAuthCalls()
        try:
            with patch("ui.main_window.AuthCheckWorker", create=True) as worker_class:
                worker = worker_class.return_value
                window.check_auth()

            worker_class.assert_called_once_with(window.ipatool)
            worker.finished.connect.assert_called_once()
            worker.start.assert_called_once_with()
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_auth_check_start_failure_rolls_back_worker_and_login_button(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = object()
        worker = MagicMock()
        worker.start.side_effect = RuntimeError("synthetic start failure")
        try:
            with patch(
                "ui.main_window.AuthCheckWorker", return_value=worker
            ), patch("ui.main_window.QMessageBox.critical", return_value=None):
                started = window.check_auth()

            self.assertFalse(started)
            self.assertIsNone(window.auth_check_worker)
            self.assertTrue(window.login_btn.isEnabled())
            worker.deleteLater.assert_called_once_with()
        finally:
            window.auth_check_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_check_auth_is_rejected_while_logout_callback_is_pending(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = object()
        window.logout_worker = MagicMock()
        try:
            with patch("ui.main_window.AuthCheckWorker") as worker_class:
                started = window.check_auth()

            self.assertFalse(started)
            worker_class.assert_not_called()
        finally:
            window.logout_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_close_is_blocked_while_auth_thread_is_running(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        running_worker = MagicMock()
        running_worker.isRunning.return_value = True
        window.auth_check_worker = running_worker
        event = MagicMock()
        try:
            window.closeEvent(event)

            event.ignore.assert_called_once_with()
            event.accept.assert_not_called()
            self.assertTrue(window._close_requested)
            self.assertIn("后台任务", window.statusBar().currentMessage())
        finally:
            window.auth_check_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_close_retries_automatically_after_auth_check_thread_stops(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        worker = MagicMock()
        worker.isRunning.return_value = True
        worker._discard_auth_result = True
        window.auth_check_worker = worker
        event = MagicMock()
        try:
            window.closeEvent(event)

            with patch("ui.main_window.QTimer.singleShot") as single_shot:
                window._on_auth_check_worker_stopped(worker)

            single_shot.assert_called_once_with(0, window.close)
            self.assertIsNone(window.auth_check_worker)
        finally:
            window.auth_check_worker = None
            window._close_requested = False
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_close_retry_is_scheduled_after_each_other_worker_stops(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        cases = (
            ("login_worker", window._on_login_worker_stopped),
            ("logout_worker", window._on_logout_worker_stopped),
            ("auth_cache_worker", window._on_auth_cache_worker_stopped),
            ("search_worker", window._on_search_worker_stopped),
        )
        try:
            window._close_requested = True
            for attribute, callback in cases:
                with self.subTest(worker=attribute):
                    worker = MagicMock()
                    worker._auth_generation = -1
                    setattr(window, attribute, worker)
                    with patch.object(window, "_schedule_requested_close") as schedule:
                        callback(worker)
                    schedule.assert_called_once_with()
                    self.assertIsNone(getattr(window, attribute))
        finally:
            for attribute, _callback in cases:
                setattr(window, attribute, None)
            window._close_requested = False
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_close_requests_download_cancellation_before_blocking(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        worker = MagicMock()
        worker.isRunning.return_value = True
        window.download_worker = worker
        event = MagicMock()
        try:
            window.closeEvent(event)

            worker.cancel.assert_called_once_with()
            event.ignore.assert_called_once_with()
        finally:
            window.download_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_close_waits_for_auth_cache_result_callback_even_after_thread_stops(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        worker = MagicMock()
        worker.isRunning.return_value = False
        window.auth_cache_worker = worker
        event = QCloseEvent()
        try:
            window.closeEvent(event)

            self.assertFalse(event.isAccepted())
            self.assertFalse(window._closing)
            self.assertTrue(window._close_requested)
        finally:
            window.auth_cache_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_close_records_request_while_auth_cache_clear_is_pending(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window._pending_auth_cache_clear = True
        event = QCloseEvent()
        try:
            window.closeEvent(event)

            self.assertFalse(event.isAccepted())
            self.assertFalse(window._closing)
            self.assertTrue(window._close_requested)
        finally:
            window._pending_auth_cache_clear = False
            window._close_requested = False
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_close_retries_automatically_after_download_thread_stops(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        worker = MagicMock()
        worker.isRunning.return_value = True
        window.download_worker = worker
        event = MagicMock()
        try:
            window.closeEvent(event)

            event.ignore.assert_called_once_with()
            worker.cancel.assert_called_once_with()
            self.assertTrue(window._close_requested)

            with patch("ui.main_window.QTimer.singleShot") as single_shot:
                window._on_download_worker_stopped(worker)

            single_shot.assert_called_once_with(0, window.close)
        finally:
            window.download_worker = None
            window._close_requested = False
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_accepted_close_discards_queued_login_result(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        worker = MagicMock()
        worker.isRunning.return_value = False
        worker.error_message = ""
        worker.result = {
            "success": True,
            "auth_verified": True,
            "email": "synthetic@example.invalid",
        }
        window.login_worker = worker
        event = QCloseEvent()
        try:
            with patch.object(window, "on_login_finished") as on_finished:
                window.closeEvent(event)
                window._on_login_worker_stopped(worker)

            self.assertTrue(event.isAccepted())
            on_finished.assert_not_called()
            self.assertIsNone(window.login_worker)
        finally:
            window.login_worker = None
            window.deleteLater()
            self.app.processEvents()

    def test_accepted_close_discards_queued_download_success(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        worker = MagicMock()
        worker.isRunning.return_value = False
        window.download_worker = worker
        event = QCloseEvent()
        try:
            with patch(
                "ui.main_window.QMessageBox.information", return_value=None
            ) as information:
                window.closeEvent(event)
                window.on_download_finished("synthetic.ipa")

            self.assertTrue(event.isAccepted())
            information.assert_not_called()
        finally:
            window.download_worker = None
            window.deleteLater()
            self.app.processEvents()

    def test_logout_starts_worker_without_calling_ipatool_on_gui_thread(self):
        ipatool = MagicMock()
        ipatool.logout.side_effect = AssertionError("GUI thread must not call logout")
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = ipatool
        try:
            with patch(
                "ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ), patch(
                "ui.main_window.QMessageBox.critical", return_value=None
            ), patch(
                "ui.main_window.QMessageBox.warning", return_value=None
            ), patch(
                "ui.main_window.QMessageBox.information", return_value=None
            ), patch("ui.main_window.LogoutWorker", create=True) as worker_class:
                window.logout()

            ipatool.logout.assert_not_called()
            worker_class.assert_called_once_with(ipatool)
            worker_class.return_value.start.assert_called_once_with()
        finally:
            window.logout_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_logout_start_failure_rolls_back_without_changing_auth_state(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = object()
        window._authenticated = True
        worker = MagicMock()
        worker.start.side_effect = RuntimeError("synthetic start failure")
        try:
            with patch(
                "ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ), patch(
                "ui.main_window.LogoutWorker", return_value=worker
            ), patch("ui.main_window.QMessageBox.critical", return_value=None):
                window.logout()

            self.assertIsNone(window.logout_worker)
            self.assertTrue(window._authenticated)
            self.assertTrue(window.login_btn.isEnabled())
            worker.deleteLater.assert_called_once_with()
        finally:
            window.logout_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_successful_logout_clears_search_results_and_count(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        worker = MagicMock()
        worker._auth_generation = window._auth_generation
        worker.error_message = ""
        worker.result = {"success": True}
        window.logout_worker = worker
        window.search_table.setRowCount(2)
        window.results_count_label.setText("2 个结果")
        try:
            with patch("ui.main_window.QMessageBox.information", return_value=None):
                window._on_logout_worker_stopped(worker)

            self.assertEqual(window.search_table.rowCount(), 0)
            self.assertEqual(window.results_count_label.text(), "0 个结果")
        finally:
            window.logout_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_login_is_rejected_while_logout_callback_is_pending(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = object()
        logout_worker = MagicMock()
        logout_worker.isRunning.return_value = False
        window.logout_worker = logout_worker
        try:
            with patch("ui.main_window.LoginWorker") as worker_class, patch(
                "ui.main_window.QMessageBox.information", return_value=None
            ):
                started = window.login(
                    "synthetic@example.invalid",
                    "SYNTHETIC_PASSWORD",
                )

            self.assertFalse(started)
            worker_class.assert_not_called()
            self.assertEqual(window._pending_login_password, "")
        finally:
            window.logout_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_logout_is_rejected_while_login_callback_is_pending(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = object()
        login_worker = MagicMock()
        login_worker.isRunning.return_value = False
        window.login_worker = login_worker
        try:
            with patch("ui.main_window.LogoutWorker") as worker_class, patch(
                "ui.main_window.QMessageBox.question"
            ) as question, patch(
                "ui.main_window.QMessageBox.information", return_value=None
            ):
                window.logout()

            worker_class.assert_not_called()
            question.assert_not_called()
        finally:
            window.login_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_stale_logout_generation_cannot_overwrite_new_login_state(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        stale_worker = MagicMock()
        stale_worker._auth_generation = 1
        stale_worker.error_message = ""
        stale_worker.result = {"success": True}
        window.logout_worker = stale_worker
        window._auth_generation = 2
        window._authenticated = True
        window.account_label.setText("已登录")
        try:
            with patch("ui.main_window.QMessageBox.information") as information:
                window._on_logout_worker_stopped(stale_worker)

            self.assertTrue(window._authenticated)
            self.assertEqual(window.account_label.text(), "已登录")
            information.assert_not_called()
            self.assertIsNone(window.logout_worker)
        finally:
            window.logout_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_clear_auth_cache_starts_worker_without_external_calls_on_gui_thread(self):
        ipatool = MagicMock()
        ipatool.logout.side_effect = AssertionError("GUI thread must not call logout")
        ipatool.clear_local_cache.side_effect = AssertionError(
            "GUI thread must not clear auth cache"
        )
        temp_dir = tempfile.TemporaryDirectory()
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.config = Config(str(Path(temp_dir.name) / "config.json"))
        window.ipatool = ipatool
        try:
            with patch(
                "ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ), patch(
                "ui.main_window.QMessageBox.information", return_value=None
            ), patch(
                "ui.main_window.ClearAuthCacheWorker", create=True
            ) as worker_class:
                window.clear_ipatool_cache()

            ipatool.logout.assert_not_called()
            ipatool.clear_local_cache.assert_not_called()
            worker_class.assert_called_once_with(ipatool)
            worker_class.return_value.start.assert_called_once_with()
        finally:
            window.auth_cache_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()
            temp_dir.cleanup()

    def test_clear_auth_cache_start_failure_does_not_block_window_forever(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = object()
        worker = MagicMock()
        worker.start.side_effect = RuntimeError("synthetic start failure")
        try:
            with patch(
                "ui.main_window.ClearAuthCacheWorker", return_value=worker
            ), patch("ui.main_window.QMessageBox.critical", return_value=None):
                started = window._start_auth_cache_clear()

            self.assertFalse(started)
            self.assertIsNone(window.auth_cache_worker)
            self.assertFalse(window._pending_auth_cache_clear)
            self.assertTrue(window.login_btn.isEnabled())
            worker.deleteLater.assert_called_once_with()

            event = QCloseEvent()
            window.closeEvent(event)
            self.assertTrue(event.isAccepted())
        finally:
            window.auth_cache_worker = None
            window.deleteLater()
            self.app.processEvents()

    def test_clear_auth_cache_invalidates_running_login_result_immediately(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = object()
        stale_worker = MagicMock()
        stale_worker.error_message = ""
        stale_worker.result = {
            "success": True,
            "auth_verified": True,
            "email": "stale@example.invalid",
        }
        window.login_worker = stale_worker
        window._pending_login_password = "SYNTHETIC_PASSWORD"
        try:
            with patch(
                "ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ), patch(
                "ui.main_window.ClearAuthCacheWorker", create=True
            ), patch.object(window, "on_login_finished") as on_finished:
                window.clear_ipatool_cache()
                window._on_login_worker_stopped(stale_worker)

            self.assertEqual(window._pending_login_password, "")
            on_finished.assert_not_called()
        finally:
            window.login_worker = None
            window.auth_cache_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_clear_auth_cache_waits_for_running_login_before_revoking(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = object()
        login_worker = MagicMock()
        login_worker.isRunning.return_value = True
        login_worker.error_message = ""
        login_worker.result = {"success": False, "error": "discarded"}
        window.login_worker = login_worker
        try:
            with patch(
                "ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ), patch("ui.main_window.ClearAuthCacheWorker") as worker_class:
                window.clear_ipatool_cache()

                worker_class.assert_not_called()
                self.assertTrue(window._pending_auth_cache_clear)

                login_worker.isRunning.return_value = False
                window._on_login_worker_stopped(login_worker)

            worker_class.assert_called_once_with(window.ipatool)
            worker_class.return_value.start.assert_called_once_with()
        finally:
            window.login_worker = None
            window.auth_cache_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_clear_auth_cache_waits_for_running_logout_before_revoking(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = object()
        logout_worker = MagicMock()
        logout_worker.isRunning.return_value = True
        logout_worker.error_message = ""
        logout_worker.result = {"success": True}
        window.logout_worker = logout_worker
        try:
            with patch(
                "ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ), patch(
                "ui.main_window.QMessageBox.information", return_value=None
            ), patch("ui.main_window.ClearAuthCacheWorker") as worker_class:
                window.clear_ipatool_cache()

                worker_class.assert_not_called()
                self.assertTrue(window._pending_auth_cache_clear)
                self.assertTrue(logout_worker._discard_auth_result)

                logout_worker.isRunning.return_value = False
                window._on_logout_worker_stopped(logout_worker)

            worker_class.assert_called_once_with(window.ipatool)
            worker_class.return_value.start.assert_called_once_with()
        finally:
            window.logout_worker = None
            window.auth_cache_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_clear_auth_cache_warns_when_saved_credentials_cannot_be_rewritten(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "ui.main_window.QTimer.singleShot", return_value=None
        ):
            config_path = Path(temp_dir) / "config.json"
            window = MainWindow()
            window.config = Config(str(config_path))
            window.config.save_apple_credentials(
                "synthetic@example.invalid", "SYNTHETIC_PASSWORD", True
            )
            try:
                with patch(
                    "core.config.os.replace",
                    side_effect=PermissionError("write denied"),
                ), patch(
                    "ui.main_window.QMessageBox.warning", return_value=None
                ) as warning, patch(
                    "ui.main_window.QMessageBox.information", return_value=None
                ) as information:
                    window._complete_auth_cache_clear({}, [])

                warning.assert_called_once()
                information.assert_not_called()
                warning_text = warning.call_args.args[2]
                self.assertIn("无法确认", warning_text)
                self.assertNotIn("本应用保存的凭据已清除，但", warning_text)
                self.assertIn("SYNTHETIC_PASSWORD", config_path.read_text(encoding="utf-8"))
            finally:
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_completed_auth_cache_clear_clears_search_results_and_count(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.config = MagicMock()
        window.search_table.setRowCount(3)
        window.results_count_label.setText("3 个结果")
        try:
            result = {"cache": {"success": True, "removed": [], "not_found": []}}
            with patch("ui.main_window.QMessageBox.information", return_value=None):
                window._complete_auth_cache_clear(result, [])

            self.assertEqual(window.search_table.rowCount(), 0)
            self.assertEqual(window.results_count_label.text(), "0 个结果")
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_clear_auth_cache_warns_when_cache_worker_reports_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "ui.main_window.QTimer.singleShot", return_value=None
        ):
            window = MainWindow()
            window.config = Config(str(Path(temp_dir) / "config.json"))
            worker = MagicMock()
            worker.result = {
                "logout": {"success": True},
                "cache": {"success": False, "error": "synthetic deletion failure"},
                "errors": [],
            }
            window.auth_cache_worker = worker
            try:
                with patch(
                    "ui.main_window.QMessageBox.warning", return_value=None
                ) as warning, patch(
                    "ui.main_window.QMessageBox.information", return_value=None
                ) as information:
                    window._on_auth_cache_worker_stopped(worker)

                warning.assert_called_once()
                information.assert_not_called()
            finally:
                window.auth_cache_worker = None
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_clear_auth_cache_warns_when_revoke_reports_failure_without_error_text(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "ui.main_window.QTimer.singleShot", return_value=None
        ):
            window = MainWindow()
            window.config = Config(str(Path(temp_dir) / "config.json"))
            worker = MagicMock()
            worker.result = {
                "logout": {"success": False, "returncode": 1},
                "cache": {"success": True, "removed": [], "not_found": []},
                "errors": [],
            }
            window.auth_cache_worker = worker
            try:
                with patch(
                    "ui.main_window.QMessageBox.warning", return_value=None
                ) as warning, patch(
                    "ui.main_window.QMessageBox.information", return_value=None
                ) as information:
                    window._on_auth_cache_worker_stopped(worker)

                warning.assert_called_once()
                information.assert_not_called()
            finally:
                window.auth_cache_worker = None
                window.close()
                window.deleteLater()
                self.app.processEvents()

    def test_clear_auth_cache_invalidates_running_auth_check_result(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = object()
        stale_worker = MagicMock()
        stale_worker.error_message = ""
        stale_worker.result = {
            "success": True,
            "returncode": 0,
            "email": "stale@example.invalid",
        }
        window.auth_check_worker = stale_worker
        window._authenticated = True
        try:
            with patch(
                "ui.main_window.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ), patch("ui.main_window.ClearAuthCacheWorker", create=True):
                window.clear_ipatool_cache()
                window._on_auth_check_worker_stopped(stale_worker)

            self.assertFalse(window._authenticated)
            self.assertNotIn("stale@example.invalid", window.account_label.text())
        finally:
            window.auth_check_worker = None
            window.auth_cache_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_start_download_uses_cached_auth_without_sync_ipatool_call(self):
        class NoSynchronousAuthCalls:
            def check_auth(self):
                raise AssertionError("download must not block on auth info")

        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = NoSynchronousAuthCalls()
        window._authenticated = True
        window.bundle_input.setText("com.example.test")
        try:
            with tempfile.TemporaryDirectory() as output_dir:
                window.output_path.setText(output_dir)
                with patch("ui.main_window.DownloadWorker") as worker_class:
                    window.start_download()

                worker_class.assert_called_once()
                worker_class.return_value.start.assert_called_once_with()
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_running_search_worker_cannot_be_replaced_by_reentrant_start(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = object()
        window.search_input.setText("synthetic-query")
        running_worker = MagicMock()
        running_worker.isRunning.return_value = True
        window.search_worker = running_worker
        try:
            with patch("ui.main_window.SearchWorker") as worker_class:
                window.search_apps()

            worker_class.assert_not_called()
            self.assertIs(window.search_worker, running_worker)
        finally:
            window.search_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_search_start_failure_rolls_back_worker_and_controls(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = object()
        window.search_input.setText("synthetic-query")
        window.results_count_label.setText("9 个结果")
        worker = MagicMock()
        worker.start.side_effect = RuntimeError("synthetic start failure")
        try:
            with patch(
                "ui.main_window.SearchWorker", return_value=worker
            ), patch("ui.main_window.QMessageBox.critical", return_value=None):
                window.search_apps()

            self.assertIsNone(window.search_worker)
            self.assertTrue(window.search_btn.isEnabled())
            self.assertEqual(window.search_btn.text(), "搜索")
            self.assertEqual(window.results_count_label.text(), "0 个结果")
            worker.deleteLater.assert_called_once_with()
        finally:
            window.search_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_search_worker_callbacks_are_identity_checked_and_cleaned_on_stop(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        current_worker = MagicMock()
        stale_worker = MagicMock()
        window.search_worker = current_worker
        try:
            with patch.object(window, "on_search_finished") as on_finished:
                window._on_search_worker_succeeded(stale_worker, [])
                window._on_search_worker_succeeded(current_worker, [])

            on_finished.assert_called_once_with([])

            window._on_search_worker_stopped(stale_worker)
            self.assertIs(window.search_worker, current_worker)
            stale_worker.deleteLater.assert_called_once_with()

            window._on_search_worker_stopped(current_worker)
            self.assertIsNone(window.search_worker)
            current_worker.deleteLater.assert_called_once_with()
        finally:
            window.search_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_running_download_worker_cannot_be_replaced_by_reentrant_start(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = object()
        window._authenticated = True
        window.bundle_input.setText("com.example.test")
        running_worker = MagicMock()
        running_worker.isRunning.return_value = True
        window.download_worker = running_worker
        try:
            with patch("ui.main_window.DownloadWorker") as worker_class:
                window.start_download()

            worker_class.assert_not_called()
            self.assertIs(window.download_worker, running_worker)
        finally:
            window.download_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_download_start_failure_rolls_back_worker_and_button(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = object()
        window._authenticated = True
        window.bundle_input.setText("com.example.test")
        worker = MagicMock()
        worker.start.side_effect = RuntimeError("synthetic start failure")
        try:
            with tempfile.TemporaryDirectory() as output_dir:
                window.output_path.setText(output_dir)
                with patch(
                    "ui.main_window.DownloadWorker", return_value=worker
                ), patch("ui.main_window.QMessageBox.critical", return_value=None):
                    window.start_download()

            self.assertIsNone(window.download_worker)
            self.assertTrue(window.download_btn.isEnabled())
            worker.deleteLater.assert_called_once_with()
        finally:
            window.download_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_download_rejects_bundle_id_that_can_escape_output_directory(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window.ipatool = object()
        window._authenticated = True
        window.bundle_input.setText("../escaped")
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                selected_dir = Path(temp_dir) / "selected"
                selected_dir.mkdir()
                window.output_path.setText(str(selected_dir))
                with patch("ui.main_window.DownloadWorker.start") as worker_start, patch(
                    "ui.main_window.QMessageBox.warning", return_value=None
                ) as warning:
                    started = window.start_download()

                self.assertFalse(started)
                worker_start.assert_not_called()
                warning.assert_called_once()
                self.assertFalse((Path(temp_dir) / "escaped.ipa").exists())
        finally:
            window.download_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_browse_output_path_rolls_back_ui_when_config_save_fails(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        previous_path = window.output_path.text()
        try:
            with tempfile.TemporaryDirectory() as temp_dir, patch(
                "ui.main_window.QFileDialog.getExistingDirectory",
                return_value=temp_dir,
            ), patch.object(
                window.config,
                "set",
                side_effect=OSError("synthetic write denied"),
            ), patch(
                "ui.main_window.QMessageBox.critical",
                return_value=None,
            ) as critical:
                saved = window.browse_output_path()

            self.assertFalse(saved)
            self.assertEqual(window.output_path.text(), previous_path)
            critical.assert_called_once()
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_download_worker_callbacks_are_identity_checked_and_cleaned_on_stop(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        current_worker = MagicMock()
        stale_worker = MagicMock()
        window.download_worker = current_worker
        try:
            with patch.object(window, "on_download_finished") as on_finished:
                window._on_download_worker_succeeded(stale_worker, "stale.ipa")
                window._on_download_worker_succeeded(current_worker, "current.ipa")

            on_finished.assert_called_once_with("current.ipa")

            window._on_download_worker_stopped(stale_worker)
            self.assertIs(window.download_worker, current_worker)
            stale_worker.deleteLater.assert_called_once_with()

            window._on_download_worker_stopped(current_worker)
            self.assertIsNone(window.download_worker)
            current_worker.deleteLater.assert_called_once_with()
        finally:
            window.download_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_download_cancelled_is_a_non_error_terminal_state(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        current_worker = MagicMock()
        stale_worker = MagicMock()
        window.download_worker = current_worker
        window.download_btn.setEnabled(False)
        window.progress_label.setText("正在下载")
        window.progress_bar.setValue(55)
        try:
            with patch("ui.main_window.QMessageBox.critical") as critical:
                window._on_download_worker_cancelled(stale_worker)
                self.assertEqual(window.progress_label.text(), "正在下载")

                window._on_download_worker_cancelled(current_worker)

            self.assertTrue(window.download_btn.isEnabled())
            self.assertEqual(window.progress_label.text(), "下载已取消")
            self.assertEqual(window.progress_bar.value(), 0)
            self.assertIn("下载已取消", window.log_text.toPlainText())
            critical.assert_not_called()
        finally:
            window.download_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_unknown_download_and_verification_use_continuous_busy_progress(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        try:
            window.on_download_progress("正在下载应用（大小未知）", -1)

            self.assertEqual(window.progress_bar.minimum(), 0)
            self.assertEqual(window.progress_bar.maximum(), 0)
            self.assertEqual(window.progress_label.text(), "正在下载应用（大小未知）")

            window.on_download_progress("正在校验并保存 IPA（大小未知）...", -1)

            self.assertEqual(window.progress_bar.minimum(), 0)
            self.assertEqual(window.progress_bar.maximum(), 0)
            self.assertEqual(window.progress_label.text(), "正在校验并保存 IPA（大小未知）...")
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_download_error_is_redacted_at_gui_sink(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        secret = "SYNTHETIC_DOWNLOAD_BEARER_SECRET"
        try:
            with patch(
                "ui.main_window.QMessageBox.critical", return_value=None
            ) as critical:
                window.on_download_error(f"Authorization: Bearer {secret}")

            rendered = str(critical.call_args.args[2])
            self.assertNotIn(secret, rendered)
            self.assertNotIn("Bearer", rendered)
            self.assertNotIn(secret, window.log_text.toPlainText())
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_download_authentication_error_invalidates_cached_auth(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window._authenticated = True
        try:
            with patch("ui.main_window.QMessageBox.critical", return_value=None):
                window.on_download_error("authentication required")

            self.assertFalse(window._authenticated)
            self.assertEqual(window.login_btn.text(), "登录 Apple ID")
            self.assertIn("未登录", window.account_label.text())
            self.assertEqual(window.account_label.property("state"), "warning")
            self.assertEqual(window.account_label.styleSheet(), "")
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_search_results_are_rendered_without_printing_external_objects(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        secret = "SYNTHETIC_NESTED_SEARCH_VALUE"
        results = [{
            "trackName": "Synthetic App",
            "bundleId": "com.example.synthetic",
            "version": "1.0",
            "nested": {"Authorization": f"Bearer {secret}"},
        }]
        try:
            with patch("builtins.print") as print_mock:
                window.on_search_finished(results)

            print_mock.assert_not_called()
            self.assertEqual(window.search_table.rowCount(), 1)
            self.assertEqual(window.search_table.item(0, 0).text(), "Synthetic App")
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_search_error_is_redacted_at_gui_sink_without_console_output(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        secret = "SYNTHETIC_SEARCH_BEARER_SECRET"
        try:
            with patch("builtins.print") as print_mock, patch(
                "ui.main_window.QMessageBox.critical", return_value=None
            ) as critical:
                window.on_search_error(f"Authorization: Bearer {secret}")

            print_mock.assert_not_called()
            rendered = str(critical.call_args.args[2])
            self.assertNotIn(secret, rendered)
            self.assertNotIn("Bearer", rendered)
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_search_authentication_error_invalidates_cached_auth(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window._authenticated = True
        try:
            with patch("ui.main_window.QMessageBox.warning", return_value=None):
                window.on_search_error("login required")

            self.assertFalse(window._authenticated)
            self.assertEqual(window.login_btn.text(), "登录 Apple ID")
            self.assertIn("未登录", window.account_label.text())
            self.assertEqual(window.account_label.property("state"), "warning")
            self.assertEqual(window.account_label.styleSheet(), "")
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_search_authentication_error_wins_over_network_wording(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window._authenticated = True
        try:
            with patch("ui.main_window.QMessageBox.warning", return_value=None) as warning:
                window.on_search_error(
                    "network response: authentication required"
                )

            self.assertFalse(window._authenticated)
            self.assertEqual(warning.call_args.args[1], "认证错误")
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_settings_change_invalidates_cached_auth_and_rechecks_new_ipatool(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        window._authenticated = True
        try:
            with patch("ui.main_window.SettingsDialog") as dialog_class, patch.object(
                window, "init_ipatool", return_value=True
            ) as init_ipatool, patch.object(window, "check_auth") as check_auth:
                dialog_class.return_value.exec.return_value = QDialog.DialogCode.Accepted
                window.show_settings()

            self.assertFalse(window._authenticated)
            init_ipatool.assert_called_once_with()
            check_auth.assert_called_once_with()
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_settings_are_blocked_while_auth_check_is_running(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        running_worker = MagicMock()
        running_worker.isRunning.return_value = True
        window.auth_check_worker = running_worker
        try:
            with patch("ui.main_window.SettingsDialog") as dialog_class, patch(
                "ui.main_window.QMessageBox.information", return_value=None
            ) as information:
                window.show_settings()

            dialog_class.assert_not_called()
            information.assert_called_once()
        finally:
            window.auth_check_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_settings_are_blocked_while_search_is_running(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        running_worker = MagicMock()
        running_worker.isRunning.return_value = True
        window.search_worker = running_worker
        try:
            with patch("ui.main_window.SettingsDialog") as dialog_class, patch(
                "ui.main_window.QMessageBox.information", return_value=None
            ) as information:
                window.show_settings()

            dialog_class.assert_not_called()
            information.assert_called_once()
        finally:
            window.search_worker = None
            window.close()
            window.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()

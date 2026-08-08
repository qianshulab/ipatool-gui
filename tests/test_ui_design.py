import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
)

from ui.dialogs import (
    InstallIPADialog,
    LoginDialog,
    SettingsDialog,
    TwoFactorDialog,
)
from ui.main_window import MainWindow


class MainWindowDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_window(self):
        with patch("ui.main_window.QTimer.singleShot", return_value=None):
            window = MainWindow()
        self.addCleanup(window.deleteLater)
        return window

    def test_window_uses_download_asset_as_application_icon(self):
        window = self.make_window()
        expected_path = Path(__file__).resolve().parents[1] / "assets" / "exe.png"
        self.assertTrue(expected_path.is_file())

        from PyQt6.QtGui import QIcon

        actual = window.windowIcon().pixmap(64, 64).toImage()
        expected = QIcon(str(expected_path)).pixmap(64, 64).toImage()
        self.assertEqual(actual, expected)

    def test_user_facing_dialogs_use_the_same_application_icon(self):
        window = self.make_window()
        expected_path = Path(__file__).resolve().parents[1] / "assets" / "exe.png"

        from PyQt6.QtGui import QIcon

        expected = QIcon(str(expected_path)).pixmap(64, 64).toImage()
        dialogs = (
            LoginDialog(window, window.config),
            SettingsDialog(window, window.config),
            InstallIPADialog(window, window.config),
        )
        for dialog in dialogs:
            self.addCleanup(dialog.deleteLater)
            with self.subTest(dialog=type(dialog).__name__):
                actual = dialog.windowIcon().pixmap(64, 64).toImage()
                self.assertEqual(actual, expected)

    def test_auth_dialogs_share_graphite_theme_without_legacy_inline_cards(self):
        dialogs = [
            LoginDialog(config=None),
            TwoFactorDialog(message="Synthetic verification prompt"),
            SettingsDialog(config=None),
            InstallIPADialog(config={}),
        ]
        for dialog in dialogs:
            self.addCleanup(dialog.deleteLater)
            self.assertIn("#0b0f14", dialog.styleSheet().lower())

        login_dialog = dialogs[0]
        notice = login_dialog.findChild(QLabel, "DialogNotice")
        self.assertIsNotNone(notice)
        self.assertEqual(notice.styleSheet(), "")
        self.assertEqual(login_dialog.login_button.property("role"), "primary")

        two_factor_dialog = dialogs[1]
        self.assertEqual(two_factor_dialog.auth_code_input.objectName(), "AuthCodeInput")
        self.assertEqual(two_factor_dialog.auth_code_input.styleSheet(), "")
        self.assertEqual(two_factor_dialog.error_label.objectName(), "DialogError")
        self.assertEqual(two_factor_dialog.error_label.styleSheet(), "")
        self.assertEqual(two_factor_dialog.verify_button.property("role"), "primary")
        self.assertFalse(two_factor_dialog.verify_button.isEnabled())
        two_factor_dialog.show()
        self.app.processEvents()
        self.assertEqual(
            two_factor_dialog.verify_button.palette()
            .color(two_factor_dialog.verify_button.backgroundRole())
            .name(),
            "#141b24",
        )

        generic_label = QLabel("Readability probe", dialogs[2])
        dialogs[2].layout().addWidget(generic_label)
        dialogs[2].show()
        self.app.processEvents()
        self.assertEqual(
            generic_label.palette().color(generic_label.foregroundRole()).name(),
            "#dbe5f2",
        )

        message_box = QMessageBox()
        self.addCleanup(message_box.deleteLater)
        message_box.setStyleSheet(dialogs[0].styleSheet())
        message_box.setText("Readable synthetic message")
        message_box.show()
        self.app.processEvents()
        message_label = message_box.findChild(QLabel, "qt_msgbox_label")
        self.assertIsNotNone(message_label)
        self.assertEqual(
            message_label.palette().color(message_label.foregroundRole()).name(),
            "#dbe5f2",
        )

    def test_entrypoint_and_release_build_bundle_the_download_icon(self):
        root = Path(__file__).resolve().parents[1]
        main_source = (root / "main.py").read_text(encoding="utf-8")
        workflow = (root / ".github" / "workflows" / "windows-ci.yml").read_text(
            encoding="utf-8"
        )
        readme = (root / "README.md").read_text(encoding="utf-8")

        self.assertIn('"assets" / "exe.png"', main_source)
        self.assertNotIn('"assets" / "qianshu.png"', main_source)
        self.assertIn('--add-data "assets/exe.png;assets"', workflow)
        self.assertIn('--add-data "assets/exe.png;assets"', readme)
        self.assertIn('--add-data "THIRD_PARTY_NOTICES.md;."', workflow)
        self.assertIn('--add-data "third_party;third_party"', workflow)
        self.assertIn('--add-data "THIRD_PARTY_NOTICES.md;."', readme)
        self.assertIn('--add-data "third_party;third_party"', readme)

    def test_about_is_a_structured_v100_dialog_with_current_author(self):
        window = self.make_window()

        dialog = window._create_about_dialog()
        self.addCleanup(dialog.deleteLater)
        visible_text = "\n".join(
            label.text() for label in dialog.findChildren(QLabel)
        )

        self.assertEqual(dialog.windowTitle(), "关于 IPA Download Tool")
        self.assertIn("1.0.0", visible_text)
        self.assertIn("刘牛", visible_text)
        self.assertIn("2026", visible_text)
        self.assertIn("非 Apple 官方产品", visible_text)
        self.assertIn("未获 Apple 认可或关联", visible_text)
        self.assertIn(
            "查看开源许可",
            [button.text() for button in dialog.findChildren(QPushButton)],
        )

        dialog.show()
        self.app.processEvents()
        hero = dialog.findChild(QFrame, "AboutHero")
        self.assertIsNotNone(hero)
        self.assertGreaterEqual(hero.height(), hero.minimumSizeHint().height())
        hero_icon = dialog.findChild(QLabel, "AboutHeroIcon")
        self.assertIsNotNone(hero_icon)
        self.assertLessEqual(
            hero_icon.geometry().bottom(),
            hero.contentsRect().bottom(),
        )

    def test_license_is_secondary_and_uses_summary_and_source_tabs(self):
        window = self.make_window()

        toolbar_buttons = [
            button.text() for button in window.findChildren(QPushButton)
        ]
        self.assertNotIn("许可证", toolbar_buttons)

        dialog = window._create_license_dialog()
        self.addCleanup(dialog.deleteLater)
        tabs = dialog.findChild(QTabWidget)
        self.assertIsNotNone(tabs)
        self.assertEqual(tabs.count(), 2)
        self.assertEqual(tabs.tabText(0), "许可摘要")
        self.assertEqual(tabs.tabText(1), "许可证原文")
        self.assertIn("GPL-3.0-only", tabs.widget(0).toPlainText())

        raw_viewer = tabs.widget(1)
        self.assertIsInstance(raw_viewer, QTextEdit)
        text = raw_viewer.toPlainText()
        self.assertIn("Third-Party Notices", text)
        self.assertIn("MIT License", text)
        self.assertIn("Copyright (c) 2021 Majd Alfhaily", text)
        self.assertNotIn("v1.2.0 Windows binary", text)
        self.assertIn("official release artifacts", text)

    def test_main_window_exposes_only_search_and_bundle_download_modules(self):
        window = self.make_window()

        self.assertEqual(window.page_stack.count(), 2)
        self.assertFalse(hasattr(window, "tab_widget"))
        self.assertFalse(hasattr(window, "history_table"))
        self.assertFalse(hasattr(window, "appid_input"))
        self.assertTrue(hasattr(window, "search_table"))
        self.assertTrue(hasattr(window, "bundle_input"))

        self.assertTrue(window.search_nav_btn.isChecked())
        self.assertFalse(window.download_nav_btn.isChecked())
        self.assertEqual(window.page_stack.currentIndex(), 0)
        self.assertEqual(window.page_context_label.text(), "应用搜索")

        window.download_nav_btn.click()
        self.assertEqual(window.page_stack.currentIndex(), 1)
        self.assertEqual(window.page_context_label.text(), "下载任务")
        self.assertFalse(window.search_nav_btn.isChecked())
        self.assertTrue(window.download_nav_btn.isChecked())

        window.search_nav_btn.click()
        self.assertEqual(window.page_stack.currentIndex(), 0)
        self.assertEqual(window.page_context_label.text(), "应用搜索")

    def test_search_result_download_moves_to_download_workspace(self):
        window = self.make_window()

        with patch.object(window, "start_download", return_value=True) as start_download:
            window.download_from_search("com.example.application")

        self.assertEqual(window.bundle_input.text(), "com.example.application")
        self.assertEqual(window.page_stack.currentIndex(), 1)
        self.assertTrue(window.download_nav_btn.isChecked())
        self.assertEqual(window.page_context_label.text(), "下载任务")
        start_download.assert_called_once_with()

    def test_toolbar_does_not_offer_custom_ipatool_settings(self):
        window = self.make_window()

        toolbar_buttons = [
            button.text() for button in window.findChildren(QPushButton)
        ]
        self.assertNotIn("高级", toolbar_buttons)

        with patch("ui.main_window.IPATool") as ipatool_class:
            self.assertTrue(window.init_ipatool())
        ipatool_class.assert_called_once_with()

    def test_missing_bundled_ipatool_requires_a_fresh_app_download(self):
        window = self.make_window()

        with patch(
            "ui.main_window.IPATool",
            side_effect=FileNotFoundError("missing"),
        ), patch("ui.main_window.QMessageBox.question") as question, patch(
            "ui.main_window.QMessageBox.critical"
        ) as critical:
            self.assertFalse(window.init_ipatool())

        question.assert_not_called()
        self.assertIn("重新下载", critical.call_args.args[2])

    def test_main_window_applies_graphite_workspace_contract(self):
        window = self.make_window()

        self.assertEqual(window.objectName(), "MainWindow")
        self.assertIn("1.0.0", window.windowTitle())
        self.assertEqual(window.brand_label.text(), "IPA DOWNLOAD TOOL")
        self.assertEqual(window.version_label.text(), "v1.0.0")
        self.assertEqual(window.search_nav_btn.parentWidget().width(), 244)
        self.assertEqual(window.version_label.maximumWidth(), 72)
        self.assertEqual(window.search_nav_btn.objectName(), "NavButton")
        self.assertEqual(window.download_nav_btn.objectName(), "NavButton")
        self.assertEqual(window.login_btn.text(), "登录 Apple ID")
        self.assertEqual(window.clear_auth_btn.text(), "清除认证")
        self.assertEqual(window.results_count_label.text(), "0 个结果")
        self.assertEqual(window.download_btn.property("role"), "primary")
        self.assertEqual(window.search_btn.property("role"), "primary")
        self.assertEqual(window.account_label.objectName(), "AccountStatus")
        self.assertEqual(window.status_label.property("state"), "checking")
        self.assertIn("CHECKING", window.status_label.text())
        self.assertFalse(window.search_table.showGrid())
        self.assertTrue(window.search_table.verticalHeader().isHidden())

        stylesheet = window.styleSheet().lower()
        self.assertIn("#0b0f14", stylesheet)
        self.assertIn("#4f8cff", stylesheet)
        self.assertIn("qpushbutton#navbutton:checked", stylesheet)
        self.assertIn("qstackedwidget#pagestack", stylesheet)
        self.assertIn("qheaderview::section", stylesheet)
        self.assertNotIn("#f28c28", stylesheet)
        self.assertNotIn("qtabwidget#moduletabs", stylesheet)

    def test_empty_search_table_header_fills_the_workspace(self):
        window = self.make_window()
        header = window.search_table.horizontalHeader()

        self.assertEqual(
            header.sectionResizeMode(0),
            QHeaderView.ResizeMode.Stretch,
        )
        self.assertEqual(
            header.sectionResizeMode(4),
            QHeaderView.ResizeMode.Fixed,
        )
        self.assertTrue(
            header.defaultAlignment() & Qt.AlignmentFlag.AlignLeft
        )

    def test_search_results_update_count_and_use_refined_table_actions(self):
        window = self.make_window()
        results = [{
            "trackName": "Synthetic App",
            "bundleId": "com.example.synthetic",
            "version": "1.2.3",
            "formattedPrice": "免费",
        }]

        window.on_search_finished(results)

        self.assertEqual(window.results_count_label.text(), "1 个结果")
        self.assertEqual(window.search_table.rowCount(), 1)
        action = window.search_table.cellWidget(0, 4)
        self.assertIsInstance(action, QPushButton)
        self.assertEqual(action.property("role"), "tableAction")
        self.assertGreaterEqual(window.search_table.rowHeight(0), 44)

    def test_status_bar_uses_compact_ipatool_runtime_badge(self):
        window = self.make_window()

        window.ipatool = object()
        window.update_status("ipatool 已就绪")
        self.assertEqual(window.status_label.objectName(), "RuntimeStatus")
        self.assertEqual(window.status_label.text(), "IPATOOL 2.3.2 · READY")
        self.assertEqual(window.status_label.property("state"), "ready")
        self.assertEqual(window.status_label.styleSheet(), "")

        window.ipatool = None
        window.update_status("内置 ipatool 缺失", error=True)
        self.assertEqual(window.status_label.text(), "IPATOOL 2.3.2 · ERROR")
        self.assertEqual(window.status_label.property("state"), "error")


if __name__ == "__main__":
    unittest.main()

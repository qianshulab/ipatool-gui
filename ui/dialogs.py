# -*- coding: utf-8 -*-
"""
对话框
"""

import platform
import re
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from core.config import Config

from .theme import GRAPHITE_STYLESHEET


class InstallIPADialog(QDialog):
    """安装 ipatool 对话框"""
    
    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.setStyleSheet(GRAPHITE_STYLESHEET)
        self.config = config or {}
        self.setWindowTitle("安装 ipatool")
        self.setMinimumWidth(500)
        self.setup_ui()
    
    def setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout(self)
        
        # 图标和标题
        title_layout = QHBoxLayout()
        icon_label = QLabel()
        try:
            icon_path = Path(__file__).resolve().parents[1] / 'assets' / 'exe.png'
            if not icon_path.exists():
                try:
                    import sys as _sys
                    _meipass = getattr(_sys, '_MEIPASS', None)
                    if _meipass:
                        alt = Path(_meipass) / 'assets' / 'exe.png'
                        if alt.exists():
                            icon_path = alt
                except Exception:
                    pass
            if icon_path.exists():
                pm = QPixmap(str(icon_path)).scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                icon_label.setPixmap(pm)
                self.setWindowIcon(QIcon(str(icon_path)))
            else:
                icon_label.setPixmap(QPixmap(":/icons/ipatool.png").scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio))
        except Exception:
            icon_label.setPixmap(QPixmap(":/icons/ipatool.png").scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio))
        title_layout.addWidget(icon_label)
        
        title_text = QLabel("<h2>安装 ipatool</h2>")
        title_layout.addWidget(title_text)
        title_layout.addStretch()
        layout.addLayout(title_layout)
        
        # 说明文本
        desc = QLabel(
            "ipatool 是用于从 App Store 下载 IPA 文件的命令行工具。\n\n"
            "此操作将自动下载并安装最新版本的 ipatool 到您的系统。"
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)
        
        # 系统信息
        sys_info = QLabel(
            f"<b>操作系统：</b>{platform.system()} {platform.release()}\n"
            f"<b>Python 版本：</b>{platform.python_version()}"
        )
        layout.addWidget(sys_info)
        
        # 安装选项
        options_group = QGroupBox("安装选项")
        options_layout = QVBoxLayout()
        
        # 安装路径
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("安装路径："))
        
        default_path = ""
        if platform.system() == 'Windows':
            default_path = str(Path.home() / 'AppData' / 'Local' / 'ipatool')
        else:
            default_path = str(Path.home() / '.local' / 'bin')
            
        self.path_edit = QLineEdit(default_path)
        path_layout.addWidget(self.path_edit)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_path)
        path_layout.addWidget(browse_btn)
        
        options_layout.addLayout(path_layout)
        
        # 添加到 PATH
        self.add_to_path = QCheckBox("添加到系统 PATH 环境变量")
        self.add_to_path.setChecked(True)
        options_layout.addWidget(self.add_to_path)
        
        # 自动更新
        self.auto_update = QCheckBox("自动检查更新")
        self.auto_update.setChecked(True)
        options_layout.addWidget(self.auto_update)
        
        options_group.setLayout(options_layout)
        layout.addWidget(options_group)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("准备安装...")
        layout.addWidget(self.progress_bar)
        
        # 日志输出
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(100)
        self.log_output.setPlaceholderText("安装日志将显示在这里...")
        layout.addWidget(self.log_output)
        
        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        
        # 设置确定按钮文本
        install_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        install_btn.setText("安装")
        install_btn.setIcon(QIcon.fromTheme("system-software-install"))
        
        # 设置取消按钮文本
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setText("取消")
        
        layout.addWidget(buttons)
    
    def browse_path(self):
        """浏览安装路径"""
        path = QFileDialog.getExistingDirectory(
            self,
            "选择安装目录",
            self.path_edit.text(),
            QFileDialog.Option.ShowDirsOnly
        )
        
        if path:
            self.path_edit.setText(path)
    
    def log(self, message: str):
        """添加日志"""
        self.log_output.append(message)
    
    def update_progress(self, value: int, message: str = None):
        """更新进度"""
        self.progress_bar.setValue(value)
        if message:
            self.progress_bar.setFormat(message)
            self.log(message)


class LoginDialog(QDialog):
    """登录对话框"""
    
    def __init__(self, parent=None, config: Config = None):
        super().__init__(parent)
        self.setStyleSheet(GRAPHITE_STYLESHEET)
        self.config = config
        self.init_ui()
    
    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle("登录 Apple ID")
        self.setModal(True)
        self.setMinimumWidth(440)
        try:
            icon_path = Path(__file__).resolve().parents[1] / 'assets' / 'exe.png'
            if not icon_path.exists():
                try:
                    import sys as _sys
                    _meipass = getattr(_sys, '_MEIPASS', None)
                    if _meipass:
                        alt = Path(_meipass) / 'assets' / 'exe.png'
                        if alt.exists():
                            icon_path = alt
                except Exception:
                    pass
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
        except Exception:
            pass
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        title = QLabel("登录 Apple ID")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)
        
        # 说明
        info_text = (
            "请使用 <b>Apple ID 密码</b> 登录。\n"
            "若账户启用双重认证 (2FA)，程序会在 Apple 明确要求时另行提示验证码。"
        )
        info_label = QLabel(info_text)
        info_label.setObjectName("DialogNotice")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # 邮箱
        email_label = QLabel("Apple ID")
        email_label.setObjectName("FieldLabel")
        layout.addWidget(email_label)
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("your-email@example.com")
        if self.config:
            self.email_input.setText(self.config.apple_email)
        layout.addWidget(self.email_input)
        
        # 密码
        password_label = QLabel("Apple ID 密码")
        password_label.setObjectName("FieldLabel")
        layout.addWidget(password_label)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("输入 Apple ID 登录密码")
        if self.config and self.config.remember_credentials:
            self.password_input.setText(self.config.apple_password)
        layout.addWidget(self.password_input)
        
        # 记住密码
        self.remember_check = QCheckBox("记住凭据（明文保存在本地配置文件，不推荐）")
        if self.config:
            self.remember_check.setChecked(self.config.remember_credentials)
        layout.addWidget(self.remember_check)
        
        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.login_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.login_button.setText("登录")
        self.login_button.setProperty("role", "primary")
        self.login_button.setDefault(True)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_button.setText("取消")
        layout.addWidget(buttons)
    
    def accept(self):
        """确认"""
        if not self.email_input.text().strip() or not self.password_input.text():
            return
        
        super().accept()
    
    def get_credentials(self):
        """获取凭据"""
        return (
            self.email_input.text().strip(),
            self.password_input.text(),
        )

    def clear_sensitive_fields(self):
        """立即清除对话框控件中的密码副本。"""
        self.password_input.clear()


class TwoFactorDialog(QDialog):
    """Apple 双重认证验证码对话框。"""

    def __init__(self, parent=None, message: str = "", error: bool = False):
        super().__init__(parent)
        self.setStyleSheet(GRAPHITE_STYLESHEET)
        self.setWindowTitle("Apple 双重认证")
        self.setModal(True)
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)
        title = QLabel("Apple 双重认证")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        description = QLabel(
            message
            or "请使用受信任设备上显示的验证码。若未收到，可在 Apple 账户的“登录与安全”中获取新验证码。"
        )
        description.setObjectName("DialogNotice")
        description.setWordWrap(True)
        layout.addWidget(description)

        code_label = QLabel("6 位验证码")
        code_label.setObjectName("FieldLabel")
        layout.addWidget(code_label)

        self.auth_code_input = QLineEdit()
        self.auth_code_input.setObjectName("AuthCodeInput")
        self.auth_code_input.setMaxLength(8)
        self.auth_code_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.auth_code_input.setPlaceholderText("123 456")
        self.auth_code_input.setInputMethodHints(Qt.InputMethodHint.ImhDigitsOnly)
        layout.addWidget(self.auth_code_input)

        self.error_label = QLabel("验证码无效或已过期，请获取最新验证码后重试。")
        self.error_label.setObjectName("DialogError")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(error)
        layout.addWidget(self.error_label)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.verify_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.verify_button.setText("验证")
        self.verify_button.setProperty("role", "primary")
        self.verify_button.setEnabled(False)
        cancel_button = self.button_box.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_button.setText("取消")
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.auth_code_input.textChanged.connect(self._update_state)
        self.auth_code_input.returnPressed.connect(self.accept)
        self.auth_code_input.setFocus()

    def _normalized_auth_code(self):
        value = self.auth_code_input.text().strip()
        normalized = re.sub(r'[\s-]+', '', value)
        return normalized if re.fullmatch(r'[0-9]{6}', normalized) else None

    def _update_state(self):
        self.verify_button.setEnabled(self._normalized_auth_code() is not None)
        self.error_label.hide()

    def accept(self):
        if self._normalized_auth_code() is None:
            self.error_label.setText("验证码必须是 6 位数字。")
            self.error_label.show()
            return
        super().accept()

    def get_auth_code(self) -> str:
        return self._normalized_auth_code() or ""

    def clear_sensitive_fields(self):
        """立即清除验证码控件中的副本。"""
        self.auth_code_input.clear()


class SettingsDialog(QDialog):
    """设置对话框"""
    
    def __init__(self, parent=None, config: Config = None):
        super().__init__(parent)
        self.setStyleSheet(GRAPHITE_STYLESHEET)
        self.config = config
        self.init_ui()
    
    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle("高级设置")
        self.setModal(True)
        self.setMinimumWidth(500)
        try:
            icon_path = Path(__file__).resolve().parents[1] / 'assets' / 'exe.png'
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
        except Exception:
            pass
        
        layout = QVBoxLayout(self)
        
        # ipatool 路径
        ipatool_group = QGroupBox("ipatool 设置")
        ipatool_layout = QVBoxLayout()
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("ipatool 路径（可选，留空使用内置）:"))
        self.ipatool_path_input = QLineEdit()
        self.ipatool_path_input.setPlaceholderText("留空使用内置 ipatool（推荐）")
        if self.config:
            self.ipatool_path_input.setText(self.config.ipatool_path)
        path_layout.addWidget(self.ipatool_path_input)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_ipatool)
        path_layout.addWidget(browse_btn)
        ipatool_layout.addLayout(path_layout)
        
        ipatool_group.setLayout(ipatool_layout)
        layout.addWidget(ipatool_group)
        
        layout.addStretch()
        
        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def browse_ipatool(self):
        """浏览 ipatool 路径"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 ipatool 可执行文件",
            "",
            "可执行文件 (*.exe);;所有文件 (*)"
        )
        if file_path:
            self.ipatool_path_input.setText(file_path)
    
    def accept(self):
        """确认"""
        if self.config:
            try:
                self.config.ipatool_path = self.ipatool_path_input.text()
            except Exception:
                QMessageBox.critical(
                    self,
                    "保存设置失败",
                    "无法保存设置，请检查配置目录写权限后重试。",
                )
                return
        
        super().accept()

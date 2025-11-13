# -*- coding: utf-8 -*-
"""
对话框
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QCheckBox, QFileDialog,
    QGroupBox, QDialogButtonBox, QProgressBar, QTextEdit
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon, QPixmap
from pathlib import Path
import platform
import sys
from PyQt6.QtCore import Qt
from core.config import Config


class InstallIPADialog(QDialog):
    """安装 ipatool 对话框"""
    
    def __init__(self, parent=None, config=None):
        super().__init__(parent)
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
            icon_path = Path(__file__).resolve().parents[1] / 'assets' / 'qianshu.png'
            if not icon_path.exists():
                try:
                    import sys as _sys
                    _meipass = getattr(_sys, '_MEIPASS', None)
                    if _meipass:
                        alt = Path(_meipass) / 'assets' / 'qianshu.png'
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
        self.config = config
        self.init_ui()
    
    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle("登录 Apple ID")
        self.setModal(True)
        self.setMinimumWidth(400)
        try:
            icon_path = Path(__file__).resolve().parents[1] / 'assets' / 'qianshu.png'
            if not icon_path.exists():
                try:
                    import sys as _sys
                    _meipass = getattr(_sys, '_MEIPASS', None)
                    if _meipass:
                        alt = Path(_meipass) / 'assets' / 'qianshu.png'
                        if alt.exists():
                            icon_path = alt
                except Exception:
                    pass
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
        except Exception:
            pass
        
        layout = QVBoxLayout(self)
        
        # 说明
        info_text = (
            "请使用 <b>Apple ID 密码</b> 登录。\n"
            "若启用双重认证 (2FA)，登录后会自动弹出验证码输入框完成验证。"
        )
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #666; padding: 10px; background: #f5f5f5; border-radius: 5px;")
        layout.addWidget(info_label)
        
        # 邮箱
        email_layout = QHBoxLayout()
        email_layout.addWidget(QLabel("Apple ID:"))
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("your-email@example.com")
        if self.config:
            self.email_input.setText(self.config.apple_email)
        email_layout.addWidget(self.email_input)
        layout.addLayout(email_layout)
        
        # 密码
        password_layout = QHBoxLayout()
        password_layout.addWidget(QLabel("Apple ID 密码:"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("输入 Apple ID 登录密码")
        if self.config and self.config.remember_credentials:
            self.password_input.setText(self.config.apple_password)
        password_layout.addWidget(self.password_input)
        layout.addLayout(password_layout)
        
        # 不提供单独的验证码输入，必要时在登录流程中弹窗输入
        
        # 记住密码
        self.remember_check = QCheckBox("记住凭据（保存在本地配置文件）")
        if self.config:
            self.remember_check.setChecked(self.config.remember_credentials)
        layout.addWidget(self.remember_check)
        
        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def accept(self):
        """确认"""
        if not self.email_input.text() or not self.password_input.text():
            return
        
        # 保存配置
        if self.config:
            self.config.apple_email = self.email_input.text()
            self.config.remember_credentials = self.remember_check.isChecked()
            if self.remember_check.isChecked():
                self.config.apple_password = self.password_input.text()
            else:
                self.config.apple_password = ''
        
        super().accept()
    
    def get_credentials(self):
        """获取凭据"""
        return self.email_input.text(), self.password_input.text()


class SettingsDialog(QDialog):
    """设置对话框"""
    
    def __init__(self, parent=None, config: Config = None):
        super().__init__(parent)
        self.config = config
        self.init_ui()
    
    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle("设置")
        self.setModal(True)
        self.setMinimumWidth(500)
        try:
            icon_path = Path(__file__).resolve().parents[1] / 'assets' / 'qianshu.png'
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
        
        # 下载设置
        download_group = QGroupBox("下载设置")
        download_layout = QVBoxLayout()
        
        # 下载路径
        download_path_layout = QHBoxLayout()
        download_path_layout.addWidget(QLabel("下载路径:"))
        self.download_path_input = QLineEdit()
        if self.config:
            self.download_path_input.setText(self.config.download_path)
        download_path_layout.addWidget(self.download_path_input)
        
        browse_download_btn = QPushButton("浏览...")
        browse_download_btn.clicked.connect(self.browse_download_path)
        download_path_layout.addWidget(browse_download_btn)
        download_layout.addLayout(download_path_layout)
        
        # 自动获取许可
        self.auto_purchase_check = QCheckBox("自动获取应用许可")
        if self.config:
            self.auto_purchase_check.setChecked(self.config.auto_purchase)
        download_layout.addWidget(self.auto_purchase_check)
        
        download_group.setLayout(download_layout)
        layout.addWidget(download_group)
        
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
    
    def browse_download_path(self):
        """浏览下载路径"""
        path = QFileDialog.getExistingDirectory(
            self,
            "选择下载目录",
            self.download_path_input.text()
        )
        if path:
            self.download_path_input.setText(path)
    
    def accept(self):
        """确认"""
        if self.config:
            self.config.ipatool_path = self.ipatool_path_input.text()
            self.config.download_path = self.download_path_input.text()
            self.config.auto_purchase = self.auto_purchase_check.isChecked()
        
        super().accept()

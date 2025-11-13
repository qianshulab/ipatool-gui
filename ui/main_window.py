# -*- coding: utf-8 -*-
"""
主窗口
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit,
    QTableWidget, QTableWidgetItem, QTabWidget,
    QProgressBar, QMessageBox, QFileDialog, QComboBox,
    QCheckBox, QGroupBox, QHeaderView, QToolBar, QStatusBar,
    QInputDialog
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from pathlib import Path

import time
from core.config import Config
from core.ipatool import IPATool
from core.ipatool_installer import IPAToolInstaller, check_ipatool_installed

from .dialogs import SettingsDialog, LoginDialog, InstallIPADialog
from .workers import SearchWorker, DownloadWorker


class MainWindow(QMainWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        self.config = Config()
        self.ipatool = None
        self.current_download = None
        self.ipatool_installer = None
        
        # 设置窗口图标（assets/qianshu.png），支持 PyInstaller 运行目录
        try:
            icon_path = (Path(__file__).resolve().parent.parent / 'assets' / 'qianshu.png')
            if not icon_path.exists():
                try:
                    meipass = getattr(__import__('sys'), '_MEIPASS', None)
                    if meipass:
                        alt = Path(meipass) / 'assets' / 'qianshu.png'
                        if alt.exists():
                            icon_path = alt
                except Exception:
                    pass
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
        except Exception:
            pass
        
        self.init_ui()
        # 延迟初始化，先展示主窗口，提升启动体验
        QTimer.singleShot(120, self._post_init)

    def _post_init(self):
        try:
            self.statusBar().showMessage("正在初始化 ipatool...")
            self.init_ipatool()
            self.check_auth()
        except Exception as e:
            self.update_status(f"初始化失败: {str(e)}", error=True)
        finally:
            self.statusBar().showMessage("就绪")
    
    def init_ui(self):
        """初始化界面"""
        self.setWindowTitle("IPA Download Tool - iOS 应用下载工具")
        self.setMinimumSize(900, 700)
        
        # 创建状态栏
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        status_bar.showMessage("就绪")
        
        # 添加状态标签
        self.status_label = QLabel()
        status_bar.addPermanentWidget(self.status_label)
        
        # 去除状态栏开发者信息，仅在“关于”展示
        
        self.update_status()
        
        # 中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        
        # 顶部工具栏
        toolbar = self.create_toolbar()
        main_layout.addLayout(toolbar)
        
        # 标签页
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        # 搜索标签页
        search_tab = self.create_search_tab()
        self.tab_widget.addTab(search_tab, "🔍 搜索下载")
        
        # 下载标签页
        download_tab = self.create_download_tab()
        self.tab_widget.addTab(download_tab, "📥 直接下载")
        
        # 历史标签页
        history_tab = self.create_history_tab()
        self.history_tab_index = self.tab_widget.addTab(history_tab, "📋 下载历史")
        
        # 切换到历史标签时自动刷新
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        
        # 状态栏
        self.statusBar().showMessage("就绪")
    
    def create_toolbar(self) -> QHBoxLayout:
        """创建工具栏"""
        toolbar = QHBoxLayout()
        
        # 账号状态
        self.account_label = QLabel("未登录")
        self.account_label.setStyleSheet("color: #999; padding: 5px;")
        toolbar.addWidget(self.account_label)
        
        toolbar.addStretch()
        
        # 登录按钮
        self.login_btn = QPushButton("登录")
        self.login_btn.clicked.connect(self.show_login_dialog)
        toolbar.addWidget(self.login_btn)
        
        # 清除缓存按钮（清理 ipatool 认证与本地保存的账号信息）
        clear_cache_btn = QPushButton("清除缓存")
        clear_cache_btn.clicked.connect(self.clear_ipatool_cache)
        toolbar.addWidget(clear_cache_btn)
        
        # 设置按钮
        settings_btn = QPushButton("⚙ 设置")
        settings_btn.clicked.connect(self.show_settings)
        toolbar.addWidget(settings_btn)
        
        # 关于按钮
        about_btn = QPushButton("ℹ 关于")
        about_btn.clicked.connect(self.show_about)
        toolbar.addWidget(about_btn)
        
        return toolbar
    
    def create_search_tab(self) -> QWidget:
        """创建搜索标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 搜索框
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入应用名称或关键词...")
        self.search_input.returnPressed.connect(self.search_apps)
        search_layout.addWidget(self.search_input)
        
        self.search_btn = QPushButton("搜索")
        self.search_btn.clicked.connect(self.search_apps)
        search_layout.addWidget(self.search_btn)
        
        layout.addLayout(search_layout)
        
        # 结果表格
        self.search_table = QTableWidget()
        self.search_table.setColumnCount(5)
        self.search_table.setHorizontalHeaderLabels([
            "应用名称", "Bundle ID", "版本", "价格", "操作"
        ])
        self.search_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.search_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.search_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.search_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.search_table.setAlternatingRowColors(True)
        self.search_table.setSortingEnabled(False)  # 初始禁用排序，填充数据后再启用
        layout.addWidget(self.search_table)
        
        return widget
    
    def on_tab_changed(self, index: int):
        """标签页切换时处理"""
        try:
            if index == getattr(self, 'history_tab_index', None):
                self.refresh_history()
        except Exception as e:
            print(f"Error in on_tab_changed: {str(e)}")
    
    def create_download_tab(self) -> QWidget:
        """创建下载标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 输入组
        input_group = QGroupBox("下载信息")
        input_layout = QVBoxLayout()
        
        # Bundle ID
        bundle_layout = QHBoxLayout()
        bundle_layout.addWidget(QLabel("Bundle ID:"))
        self.bundle_input = QLineEdit()
        self.bundle_input.setPlaceholderText("例如: com.tencent.xin")
        bundle_layout.addWidget(self.bundle_input)
        input_layout.addLayout(bundle_layout)
        
        # App ID (可选)
        appid_layout = QHBoxLayout()
        appid_layout.addWidget(QLabel("App ID (可选):"))
        self.appid_input = QLineEdit()
        self.appid_input.setPlaceholderText("例如: 414478124")
        appid_layout.addWidget(self.appid_input)
        input_layout.addLayout(appid_layout)
        
        # 输出路径
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("保存路径:"))
        self.output_path = QLineEdit()
        self.output_path.setText(self.config.download_path)
        path_layout.addWidget(self.output_path)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_output_path)
        path_layout.addWidget(browse_btn)
        input_layout.addLayout(path_layout)
        
        # 选项
        self.auto_purchase_check = QCheckBox("自动获取应用许可")
        self.auto_purchase_check.setChecked(self.config.auto_purchase)
        input_layout.addWidget(self.auto_purchase_check)
        
        input_group.setLayout(input_layout)
        layout.addWidget(input_group)
        
        # 下载按钮
        self.download_btn = QPushButton("开始下载")
        self.download_btn.clicked.connect(self.start_download)
        self.download_btn.setStyleSheet("""
            QPushButton {
                background-color: #007aff;
                color: white;
                border: none;
                padding: 10px;
                font-size: 14px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #005ecb;
            }
            QPushButton:disabled {
                background-color: #ccc;
            }
        """)
        layout.addWidget(self.download_btn)
        
        # 进度组
        progress_group = QGroupBox("下载进度")
        progress_layout = QVBoxLayout()
        
        self.progress_label = QLabel("等待下载...")
        progress_layout.addWidget(self.progress_label)
        
        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_bar)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        progress_layout.addWidget(self.log_text)
        
        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)
        
        layout.addStretch()
        
        return widget
    
    def create_history_tab(self) -> QWidget:
        """创建历史标签页"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # 工具栏
        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh_history)
        toolbar.addWidget(refresh_btn)
        
        clear_btn = QPushButton("清空历史")
        clear_btn.clicked.connect(self.clear_history)
        toolbar.addWidget(clear_btn)
        
        toolbar.addStretch()
        layout.addLayout(toolbar)
        
        # 历史表格
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(4)
        self.history_table.setHorizontalHeaderLabels([
            "应用名称", "Bundle ID", "下载时间", "文件路径"
        ])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.history_table)
        
        return widget
    
    def init_ipatool(self):
        """初始化 ipatool"""
        try:
            ipatool_path = self.config.ipatool_path or None
            self.ipatool = IPATool(ipatool_path)
            self.update_status("ipatool 已就绪")
            return True
        except FileNotFoundError as e:
            self.ipatool = None
            
            # 检查是否启用自动下载
            if self.config.get('auto_download_ipatool', True):
                reply = QMessageBox.question(
                    self,
                    "未找到 ipatool",
                    "未找到 ipatool，是否要自动下载并安装？\n\n"
                    "ipatool 是用于从 App Store 下载 IPA 文件的命令行工具。\n"
                    "需要连接到 GitHub 下载最新版本。",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    self.install_ipatool()
                else:
                    self.update_status("ipatool 未安装", error=True)
            else:
                QMessageBox.critical(
                    self,
                    "错误",
                    f"{e}\n\n请在设置中指定 ipatool 路径，或确保 ipatool 在系统 PATH 中。"
                )
                self.update_status("ipatool 未安装", error=True)
            
            return False
    
    def update_status(self, message: str = None, error: bool = False):
        """更新状态栏"""
        status_bar = self.statusBar()
        if message:
            status_bar.showMessage(message)
            
        # 更新状态标签
        if self.ipatool:
            self.status_label.setText("状态: 就绪 | ipatool 已加载")
            self.status_label.setStyleSheet("color: green;")
        else:
            self.status_label.setText("状态: 错误 | ipatool 未安装")
            self.status_label.setStyleSheet("color: red;")
    
    def install_ipatool(self):
        """安装 ipatool"""
        # 显示安装对话框
        dialog = InstallIPADialog(self, self.config)
        if dialog.exec():
            # 创建安装器
            self.ipatool_installer = IPAToolInstaller(self.config)
            self.ipatool_installer.progress.connect(self.on_install_progress)
            self.ipatool_installer.finished.connect(self.on_install_finished)
            self.ipatool_installer.error.connect(self.on_install_error)
            self.ipatool_installer.start()
    
    def on_install_progress(self, message: str, percent: int):
        """安装进度更新"""
        self.statusBar().showMessage(f"正在安装 ipatool: {message} ({percent}%)")
    
    def on_install_finished(self, path: str):
        """安装完成"""
        self.statusBar().showMessage("ipatool 安装成功！", 5000)
        self.config.ipatool_path = path
        self.init_ipatool()  # 重新初始化
        
        # 显示完成消息
        QMessageBox.information(
            self,
            "安装成功",
            f"ipatool 已成功安装到:\n{path}\n\n"
            "请重新启动应用程序以应用更改。"
        )
    
    def on_install_error(self, error: str):
        """安装错误"""
        self.statusBar().showMessage("安装失败", 5000)
        QMessageBox.critical(
            self,
            "安装失败",
            f"安装 ipatool 时出错:\n{error}\n\n"
            "请手动下载并安装 ipatool。"
        )
    
    def check_auth(self):
        """检查认证状态"""
        if not self.ipatool:
            self.account_label.setText("未登录 (ipatool 未初始化)")
            self.account_label.setStyleSheet("color: #ff3b30; padding: 5px;")
            self.login_btn.setText("登录")
            self.login_btn.clicked.disconnect()
            self.login_btn.clicked.connect(self.show_login_dialog)
            return False
        
        try:
            auth_result = self.ipatool.check_auth()
            if auth_result:
                info = self.ipatool.get_account_info()
                if isinstance(info, dict) and 'email' in info:
                    email = info.get('email', '未知')
                    self.account_label.setText(f"已登录: {email}")
                    self.account_label.setStyleSheet("color: #34c759; padding: 5px;")
                    self.login_btn.setText("退出登录")
                    self.login_btn.clicked.disconnect()
                    self.login_btn.clicked.connect(self.logout)
                    return True
                else:
                    self.log(f"获取账号信息失败: {info}")
            
            # 未登录或登录失效
            self.account_label.setText("未登录")
            self.account_label.setStyleSheet("color: #999; padding: 5px;")
            self.login_btn.setText("登录")
            self.login_btn.clicked.disconnect()
            self.login_btn.clicked.connect(self.show_login_dialog)
            return False
            
        except Exception as e:
            error_msg = str(e)
            self.log(f"检查认证状态失败: {error_msg}")
            self.account_label.setText("认证状态检查失败")
            self.account_label.setStyleSheet("color: #ff9500; padding: 5px;")
            return False
    
    def show_login_dialog(self):
        """显示登录对话框"""
        dialog = LoginDialog(self, self.config)
        if dialog.exec():
            creds = dialog.get_credentials()
            # 兼容两种返回（有/没有验证码）
            if isinstance(creds, tuple) and len(creds) == 3:
                email, password, auth_code = creds
            else:
                email, password = creds[0], creds[1]
                auth_code = ""
            self.login(email, password, auth_code)
    
    def login(self, email: str, password: str, auth_code: str = ""):
        """登录"""
        if not self.ipatool:
            QMessageBox.warning(self, "警告", "ipatool 未初始化")
            return False
        
        try:
            self.statusBar().showMessage("正在登录...")
            result = self.ipatool.login(email, password, auth_code or None)
            
            # 检查登录是否成功
            if isinstance(result, dict) and result.get('success', False):
                # 验证登录状态
                if self.ipatool.check_auth():
                    QMessageBox.information(self, "成功", "登录成功！")
                    self.check_auth()  # 更新UI状态
                    return True
                else:
                    QMessageBox.warning(self, "警告", "登录状态验证失败，请重试")
                    return False
            else:
                # 处理登录失败
                error_msg = result.get('error', result.get('output', '未知错误')) if isinstance(result, dict) else str(result)

                # 若检测到需要 2FA，则弹出验证码输入框并重试一次
                need_code_flag = isinstance(result, dict) and result.get('requires_auth_code')
                text = (error_msg or '').lower()
                need_code_text = any(k in text for k in [
                    'verification code', '2fa', 'two-factor', 'two factor', 'auth code', '验证码', '双重'
                ])
                if need_code_flag or need_code_text:
                    code, ok = QInputDialog.getText(self, "需要验证码", "请输入 6 位验证码：")
                    if ok and code.strip():
                        retry = self.ipatool.login(email, password, code.strip())
                        if isinstance(retry, dict) and (retry.get('success') or 'email' in retry):
                            if self.ipatool.check_auth():
                                QMessageBox.information(self, "成功", "登录成功！")
                                self.check_auth()
                                return True
                        else:
                            # 更新错误消息为重试结果
                            error_msg = retry.get('error', '登录失败') if isinstance(retry, dict) else str(retry)

                # 附加详细信息（若有）
                details_text = ""
                if isinstance(result, dict) and isinstance(result.get('details'), dict):
                    d = result['details']
                    parts = []
                    for k in ['message', 'error', 'output']:
                        v = d.get(k)
                        if v:
                            parts.append(f"{k}: {v}")
                    if parts:
                        details_text = "\n\n" + "\n".join(parts)
                QMessageBox.critical(self, "登录失败", f"登录失败：\n{error_msg}{details_text}")
                self.log(f"登录失败: {error_msg}{details_text}")
                return False
                
        except Exception as e:
            error_msg = str(e)
            QMessageBox.critical(self, "错误", f"登录时发生错误：\n{error_msg}")
            self.log(f"登录异常: {error_msg}")
            return False
        finally:
            self.statusBar().showMessage("就绪")
    
    def logout(self):
        """退出登录"""
        if not self.ipatool:
            self.check_auth()  # 重置UI状态
            return
            
        reply = QMessageBox.question(
            self, "确认", "确定要退出登录吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.statusBar().showMessage("正在退出登录...")
                result = self.ipatool.logout()
                
                if isinstance(result, dict) and result.get('success', False):
                    # 清除UI状态
                    self.account_label.setText("未登录")
                    self.account_label.setStyleSheet("color: #999; padding: 5px;")
                    self.login_btn.setText("登录")
                    self.login_btn.clicked.disconnect()
                    self.login_btn.clicked.connect(self.show_login_dialog)
                    
                    # 清除搜索和下载状态
                    self.search_table.setRowCount(0)
                    self.log_text.clear()
                    self.progress_bar.setValue(0)
                    self.progress_label.setText("等待下载...")
                    
                    QMessageBox.information(self, "成功", "已退出登录")
                else:
                    error_msg = result.get('error', '未知错误') if isinstance(result, dict) else str(result)
                    QMessageBox.warning(self, "警告", f"退出登录失败：\n{error_msg}")
                    
            except Exception as e:
                error_msg = str(e)
                QMessageBox.critical(self, "错误", f"退出登录时出错：\n{error_msg}")
                self.log(f"退出登录异常: {error_msg}")
                
            finally:
                self.statusBar().showMessage("就绪")
    
    def clear_ipatool_cache(self):
        """清除 ipatool 本地缓存（认证）与已保存的账号信息"""
        try:
            reply = QMessageBox.question(
                self,
                "确认清除",
                (
                    "将清除本机 ipatool 登录缓存并删除本地保存的账号信息。\n\n"
                    "包括：撤销 ipatool 认证（auth revoke），清空已保存的邮箱与密码。\n\n"
                    "是否继续？"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

            # 撤销 ipatool 认证，并清理本地缓存目录
            cache_details = ""
            if self.ipatool:
                try:
                    self.statusBar().showMessage("正在清除 ipatool 认证缓存...")
                    self.ipatool.logout()
                except Exception as e:
                    self.log(f"清除 ipatool 认证缓存时异常: {str(e)}")
                try:
                    self.statusBar().showMessage("正在删除本地缓存目录 ~/.ipatool ...")
                    res = self.ipatool.clear_local_cache()
                    if isinstance(res, dict):
                        removed = res.get('removed') or []
                        not_found = res.get('not_found') or []
                        parts = []
                        if removed:
                            parts.append("已删除: " + "; ".join(removed))
                        if not_found:
                            parts.append("未找到: " + "; ".join(not_found))
                        cache_details = "\n\n" + "\n".join(parts) if parts else ""
                except Exception as e:
                    self.log(f"删除本地缓存目录时异常: {str(e)}")

            # 清空本地保存的账号信息
            try:
                if hasattr(self, 'config') and self.config:
                    # 使用 config.set 以确保持久化
                    if hasattr(self.config, 'set'):
                        self.config.set('apple_id.email', '')
                        self.config.set('apple_id.password', '')
                        self.config.set('remember_credentials', False)
                    else:
                        self.config.apple_email = ''
                        self.config.apple_password = ''
                        self.config.remember_credentials = False
            except Exception as e:
                self.log(f"清理本地账号信息时异常: {str(e)}")

            # 重置UI状态
            self.account_label.setText("未登录")
            self.account_label.setStyleSheet("color: #999; padding: 5px;")
            self.login_btn.setText("登录")
            try:
                self.login_btn.clicked.disconnect()
            except Exception:
                pass
            self.login_btn.clicked.connect(self.show_login_dialog)

            # 清空日志与下载状态
            try:
                self.search_table.setRowCount(0)
                self.log_text.clear()
                self.progress_bar.setValue(0)
                self.progress_label.setText("等待下载...")
            except Exception:
                pass

            QMessageBox.information(self, "完成", f"已清除 ipatool 本地缓存与账号信息{cache_details}")
        finally:
            self.statusBar().showMessage("就绪")
    
    def search_apps(self):
        """搜索应用"""
        keyword = self.search_input.text().strip()
        if not keyword:
            QMessageBox.warning(self, "警告", "请输入搜索关键词")
            return
        
        if not self.ipatool:
            QMessageBox.warning(self, "警告", "ipatool 未初始化")
            return
        
        self.search_btn.setEnabled(False)
        self.search_btn.setText("搜索中...")
        self.search_table.setRowCount(0)
        
        # 创建搜索线程
        self.search_worker = SearchWorker(self.ipatool, keyword)
        self.search_worker.finished.connect(self.on_search_finished)
        self.search_worker.error.connect(self.on_search_error)
        self.search_worker.start()
    
    def on_search_finished(self, results):
        """搜索完成"""
        try:
            print(f"Search results received: {results}")
            self.search_btn.setEnabled(True)
            self.search_btn.setText("搜索")
            
            # 清空表格
            self.search_table.clearContents()
            self.search_table.setRowCount(0)
            self.search_table.setColumnCount(0)  # 重置列
            
            if not results:
                QMessageBox.information(self, "提示", "未找到相关应用")
                return
            
            # 确保结果是一个列表
            if not isinstance(results, list):
                print(f"Unexpected results format: {type(results)}")
                QMessageBox.warning(self, "错误", "搜索结果格式不正确")
                return
                
            # 设置表头
            headers = ["应用名称", "Bundle ID", "版本", "价格", "操作"]
            self.search_table.setColumnCount(len(headers))
            self.search_table.setHorizontalHeaderLabels(headers)
            
            # 设置行数
            self.search_table.setRowCount(len(results))
            
            for row, app in enumerate(results):
                try:
                    # 确保app是字典类型
                    if not isinstance(app, dict):
                        print(f"Skipping non-dict app data at index {row}: {app}")
                        continue
                    
                    # 获取应用信息，提供默认值
                    app_info = {
                        'name': str(app.get('trackName') or app.get('name') or app.get('trackName', '未知应用')),
                        'bundle_id': str(app.get('bundleId') or app.get('bundleID') or ''),
                        'version': str(app.get('version') or ''),
                        'price': str(app.get('formattedPrice') or app.get('price') or 'Free')
                    }
                    
                    print(f"Processing app {row + 1}: {app_info}")
                    
                    # 应用名称
                    name_item = QTableWidgetItem(app_info['name'])
                    name_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                    self.search_table.setItem(row, 0, name_item)
                    
                    # Bundle ID
                    bundle_id = app_info['bundle_id']
                    bundle_item = QTableWidgetItem(bundle_id)
                    bundle_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                    self.search_table.setItem(row, 1, bundle_item)
                    
                    # 版本
                    version_item = QTableWidgetItem(app_info['version'])
                    version_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                    self.search_table.setItem(row, 2, version_item)
                    
                    # 价格
                    price_item = QTableWidgetItem(app_info['price'])
                    price_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
                    self.search_table.setItem(row, 3, price_item)
                    
                    # 下载按钮
                    if bundle_id:  # 只有在有 bundle_id 时才添加下载按钮
                        download_btn = QPushButton("下载")
                        download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                        download_btn.setProperty("bundle_id", bundle_id)  # 存储bundle_id
                        download_btn.setStyleSheet("""
                            QPushButton {
                                background-color: #4CAF50;
                                border: none;
                                color: white;
                                padding: 5px 10px;
                                text-align: center;
                                text-decoration: none;
                                margin: 2px 1px;
                                border-radius: 4px;
                                min-width: 60px;
                            }
                            QPushButton:hover {
                                background-color: #45a049;
                            }
                            QPushButton:disabled {
                                background-color: #cccccc;
                            }
                        """)
                        # 使用functools.partial确保正确的bundle_id被传递
                        from functools import partial
                        download_btn.clicked.connect(partial(self.download_from_search, bundle_id))
                        self.search_table.setCellWidget(row, 4, download_btn)
                    
                    print(f"Added app to table: {app_info['name']} - {bundle_id}")
                    
                except Exception as app_error:
                    print(f"Error processing app at index {row}: {str(app_error)}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            # 调整列宽策略
            header = self.search_table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # 应用名称 - 自适应
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)  # Bundle ID
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # 版本
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # 价格
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)  # 操作按钮
            header.resizeSection(4, 80)  # 设置操作列固定宽度
            
            # 启用排序
            self.search_table.setSortingEnabled(True)
            
            # 滚动到顶部
            if results:
                self.search_table.scrollToTop()
            
            # 更新状态栏
            self.update_status(f"找到 {len(results)} 个应用")
            
            print("Search results displayed successfully")
            
        except Exception as e:
            error_msg = f"显示搜索结果时出错: {str(e)}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "错误", error_msg)
    
    def on_search_error(self, error_msg):
        """搜索错误"""
        try:
            print(f"Search error: {error_msg}")
            self.search_btn.setEnabled(True)
            self.search_btn.setText("搜索")
            
            # 清空表格
            self.search_table.setRowCount(0)
            
            # 显示错误信息
            error_text = str(error_msg)
            if "No results found" in error_text:
                QMessageBox.information(self, "提示", "未找到相关应用")
            elif "network" in error_text.lower():
                QMessageBox.warning(self, "网络错误", "网络连接失败，请检查网络设置")
            elif "auth" in error_text.lower() or "login" in error_text.lower():
                QMessageBox.warning(self, "认证错误", "认证失败，请重新登录")
            else:
                QMessageBox.critical(self, "搜索失败", f"搜索时发生错误：\n{error_text}")
                
        except Exception as e:
            print(f"Error in on_search_error: {str(e)}")
            QMessageBox.critical(self, "错误", f"处理搜索错误时发生异常：\n{str(e)}")
    
    def download_from_search(self, bundle_id: str):
        """从搜索结果下载"""
        self.bundle_input.setText(bundle_id)
        self.tab_widget.setCurrentIndex(1)  # 切换到下载标签页
        self.start_download()
    
    def browse_output_path(self):
        """浏览输出路径"""
        path = QFileDialog.getExistingDirectory(self, "选择下载目录", self.output_path.text())
        if path:
            self.output_path.setText(path)
            self.config.download_path = path
    
    def start_download(self):
        """开始下载"""
        bundle_id = self.bundle_input.text().strip()
        app_id = self.appid_input.text().strip()
        
        if not bundle_id and not app_id:
            QMessageBox.warning(self, "警告", "请输入 Bundle ID 或 App ID")
            return
        
        if not self.ipatool:
            QMessageBox.warning(self, "警告", "ipatool 未初始化")
            return
        
        if not self.ipatool.check_auth():
            QMessageBox.warning(self, "警告", "请先登录 Apple ID")
            self.show_login_dialog()
            return
        
        # 准备下载
        output_path = Path(self.output_path.text())
        output_path.mkdir(parents=True, exist_ok=True)
        
        filename = f"{bundle_id or app_id}.ipa"
        full_path = str(output_path / filename)
        
        self.download_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_label.setText("准备下载...")
        self.log_text.clear()
        self.log("开始下载...")
        
        # 创建下载线程
        auto_purchase = self.auto_purchase_check.isChecked()
        self.download_worker = DownloadWorker(
            self.ipatool, bundle_id, app_id, full_path, auto_purchase
        )
        self.download_worker.progress.connect(self.on_download_progress)
        self.download_worker.finished.connect(self.on_download_finished)
        self.download_worker.error.connect(self.on_download_error)
        self.download_worker.start()
    
    def on_download_progress(self, message: str, percent: int):
        """下载进度更新"""
        self.progress_label.setText(message)
        self.progress_bar.setValue(percent)
        self.log(message)
    
    def on_download_finished(self, file_path: str):
        """下载完成"""
        try:
            self.download_btn.setEnabled(True)
            self.progress_bar.setValue(100)
            self.progress_label.setText("下载完成！")
            self.log(f"下载成功: {file_path}")
            
            # 保存下载历史
            history = self.config.get('download_history', [])
            history.append({
                'file_path': file_path,
                'app_name': self.bundle_input.text() or Path(file_path).stem,
                'bundle_id': self.bundle_input.text(),
                'timestamp': int(time.time())
            })
            self.config.set('download_history', history)
            
            # 刷新历史记录
            self.refresh_history()
            
            # 如果当前在历史页，确保可见更新；否则不强制切换
            if self.tab_widget.currentIndex() == getattr(self, 'history_tab_index', 2):
                self.history_table.repaint()
            
            reply = QMessageBox.information(
                self,
                "下载完成",
                f"文件已保存到：\n{file_path}\n\n是否打开文件所在文件夹？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                import subprocess
                import platform
                if platform.system() == 'Windows':
                    subprocess.run(['explorer', '/select,', file_path])
                elif platform.system() == 'Darwin':  # macOS
                    subprocess.run(['open', '-R', file_path])
                else:  # Linux
                    subprocess.run(['xdg-open', str(Path(file_path).parent)])
                    
        except Exception as e:
            print(f"Error in on_download_finished: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def on_download_error(self, error_msg: str):
        """下载错误"""
        self.download_btn.setEnabled(True)
        self.progress_label.setText("下载失败")
        self.log(f"错误: {error_msg}")
        QMessageBox.critical(self, "下载失败", f"下载失败：\n{error_msg}")
    
    def log(self, message: str):
        """添加日志"""
        self.log_text.append(message)
    
    def refresh_history(self):
        """刷新历史"""
        try:
            # 清空表格
            self.history_table.setRowCount(0)
            
            # 从配置文件加载历史记录
            history = self.config.get('download_history', [])
            
            if not history:
                print("No download history found")
                return
                
            # 设置表头
            headers = ["文件名", "应用名称", "Bundle ID", "下载时间", "文件路径"]
            self.history_table.setColumnCount(len(headers))
            self.history_table.setHorizontalHeaderLabels(headers)
            
            # 设置行数
            self.history_table.setRowCount(len(history))
            
            # 按时间倒序排序
            history_sorted = sorted(
                history, 
                key=lambda x: x.get('timestamp', 0), 
                reverse=True
            )
            
            for row, item in enumerate(history_sorted):
                # 文件名
                file_path = item.get('file_path', '')
                file_name = Path(file_path).name if file_path else '未知'
                name_item = QTableWidgetItem(file_name)
                name_item.setData(Qt.ItemDataRole.UserRole, file_path)  # 存储完整路径
                self.history_table.setItem(row, 0, name_item)
                
                # 应用名称
                app_name = item.get('app_name', '未知')
                app_item = QTableWidgetItem(app_name)
                self.history_table.setItem(row, 1, app_item)
                
                # Bundle ID
                bundle_id = item.get('bundle_id', '')
                bundle_item = QTableWidgetItem(bundle_id)
                self.history_table.setItem(row, 2, bundle_item)
                
                # 下载时间
                timestamp = item.get('timestamp', 0)
                from datetime import datetime
                time_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S') if timestamp else '未知'
                time_item = QTableWidgetItem(time_str)
                self.history_table.setItem(row, 3, time_item)
                
                # 文件路径
                path_item = QTableWidgetItem(file_path)
                path_item.setToolTip(file_path)  # 鼠标悬停显示完整路径
                self.history_table.setItem(row, 4, path_item)
                
                print(f"Added to history: {app_name} - {bundle_id}")
            
            # 调整列宽
            self.history_table.resizeColumnsToContents()
            self.history_table.horizontalHeader().setStretchLastSection(True)
            
        except Exception as e:
            print(f"Error refreshing history: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def clear_history(self):
        """清空历史"""
        try:
            reply = QMessageBox.question(
                self, 
                "确认清空", 
                "确定要清空所有下载历史记录吗？此操作不可恢复！",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # 清空历史记录
                self.config.set('download_history', [])
                
                # 清空表格
                self.history_table.setRowCount(0)
                
                QMessageBox.information(self, "成功", "下载历史记录已清空")
                
        except Exception as e:
            print(f"Error clearing history: {str(e)}")
            QMessageBox.critical(self, "错误", f"清空历史记录时出错：\n{str(e)}")
    
    def show_settings(self):
        """显示设置对话框"""
        dialog = SettingsDialog(self, self.config)
        if dialog.exec():
            self.init_ipatool()
            self.output_path.setText(self.config.download_path)
    
    def show_about(self):
        """显示关于对话框"""
        QMessageBox.about(
            self,
            "关于",
            "<h3>IPA Download Tool</h3>"
            "<p>版本: 1.0.0</p>"
            "<p>开发者：乾枢</p>"
            "<p>基于 <a href='https://github.com/majd/ipatool'>ipatool</a> 的图形化下载工具</p>"
            "<p>© 2025 IPA Download Tool · 乾枢实验室</p>"
        )

# -*- coding: utf-8 -*-
"""
主窗口
"""

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_metadata import APP_DEVELOPER, APP_VERSION, COPYRIGHT_YEAR
from core.config import Config
from core.ipatool import IPATool
from core.ipatool_installer import IPAToolInstaller
from core.redaction import safe_external_text

from .dialogs import InstallIPADialog, LoginDialog, SettingsDialog, TwoFactorDialog
from .workers import (
    AuthCheckWorker,
    ClearAuthCacheWorker,
    DownloadWorker,
    LoginWorker,
    LogoutWorker,
    SearchWorker,
)
from .theme import GRAPHITE_STYLESHEET


class MainWindow(QMainWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        self.config = Config()
        self.ipatool = None
        self.current_download = None
        self.ipatool_installer = None
        self.login_worker = None
        self.logout_worker = None
        self.auth_cache_worker = None
        self.auth_check_worker = None
        self._pending_auth_cache_clear = False
        self._auth_generation = 0
        self._closing = False
        self._close_requested = False
        self._authenticated = False
        self._pending_login_email = ''
        self._pending_login_password = ''
        self._pending_remember_credentials = None
        
        # 设置窗口图标（苹果形状 + 云下载），支持 PyInstaller 运行目录
        try:
            icon_path = (Path(__file__).resolve().parent.parent / 'assets' / 'exe.png')
            if not icon_path.exists():
                try:
                    meipass = getattr(__import__('sys'), '_MEIPASS', None)
                    if meipass:
                        alt = Path(meipass) / 'assets' / 'exe.png'
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
            if self.init_ipatool():
                self.check_auth()
            else:
                self.statusBar().showMessage("就绪")
        except Exception as e:
            self.update_status(f"初始化失败: {str(e)}", error=True)
            self.statusBar().showMessage("就绪")
    
    def closeEvent(self, event):
        """运行中的外部任务结束前拒绝销毁其 QThread。"""
        if self._pending_auth_cache_clear:
            self._close_requested = True
            self.statusBar().showMessage("认证缓存清理尚未完成，请稍候")
            event.ignore()
            return

        if getattr(self, 'auth_cache_worker', None) is not None:
            self._close_requested = True
            self.statusBar().showMessage("正在确认认证缓存清理结果，请稍候")
            event.ignore()
            return

        download_worker = getattr(self, 'download_worker', None)
        try:
            if download_worker is not None and download_worker.isRunning():
                self._close_requested = True
                download_worker.cancel()
                self.statusBar().showMessage("正在停止下载，完成后将自动关闭窗口")
                event.ignore()
                return
        except RuntimeError:
            pass

        worker_names = (
            'auth_check_worker',
            'login_worker',
            'logout_worker',
            'auth_cache_worker',
            'search_worker',
            'download_worker',
            'ipatool_installer',
        )
        for name in worker_names:
            worker = getattr(self, name, None)
            try:
                if worker is not None and worker.isRunning():
                    self._close_requested = True
                    self.statusBar().showMessage(
                        "后台任务仍在运行，完成后将自动关闭窗口"
                    )
                    event.ignore()
                    return
            except RuntimeError:
                # Qt 对象已删除即表示该任务不再运行。
                continue

        self._close_requested = False
        self._closing = True
        for name in ('login_worker', 'auth_check_worker'):
            worker = getattr(self, name, None)
            if worker is not None:
                worker._discard_auth_result = True
        self._clear_pending_login_credentials()
        super().closeEvent(event)

    def _schedule_requested_close(self):
        """在阻塞关闭的 worker 完成清理后安排一次关闭重试。"""
        if self._close_requested and not self._closing:
            QTimer.singleShot(0, self.close)

    def init_ui(self):
        """初始化界面"""
        self.setObjectName("MainWindow")
        self.setStyleSheet(GRAPHITE_STYLESHEET)
        self.setWindowTitle(
            f"IPA Download Tool {APP_VERSION} - App Store 下载工作台"
        )
        self.setMinimumSize(1080, 700)
        self.resize(1280, 800)
        
        # 创建状态栏
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        status_bar.showMessage("就绪")
        
        # 添加状态标签
        self.status_label = QLabel("IPATOOL 2.3.2 · CHECKING")
        self.status_label.setObjectName("RuntimeStatus")
        self.status_label.setProperty("state", "checking")
        status_bar.addPermanentWidget(self.status_label)
        
        # 去除状态栏开发者信息，仅在“关于”展示
        
        # 中心部件
        central_widget = QWidget()
        central_widget.setObjectName("CentralSurface")
        self.setCentralWidget(central_widget)
        
        # 应用外壳：固定侧栏 + 右侧工作区
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self.create_sidebar())

        workspace = QFrame()
        workspace.setObjectName("Workspace")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        main_layout.addWidget(workspace, 1)

        workspace_layout.addWidget(self.create_toolbar())

        self.page_stack = QStackedWidget()
        self.page_stack.setObjectName("PageStack")
        self.page_stack.addWidget(self.create_search_tab())
        self.page_stack.addWidget(self.create_download_tab())
        workspace_layout.addWidget(self.page_stack, 1)
        self._set_active_page(0)
        
        # 状态栏
        self.statusBar().showMessage("就绪")

    def create_sidebar(self) -> QFrame:
        """创建与工作流一致的双模块侧栏。"""
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(244)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        logo_label = QLabel()
        logo_label.setObjectName("SidebarLogo")
        logo_label.setPixmap(self.windowIcon().pixmap(34, 34))
        logo_label.setFixedSize(38, 38)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_row.addWidget(logo_label)

        brand_text = QVBoxLayout()
        brand_text.setContentsMargins(0, 0, 0, 0)
        brand_text.setSpacing(1)
        self.brand_label = QLabel("IPA DOWNLOAD TOOL")
        self.brand_label.setObjectName("BrandTitle")
        brand_text.addWidget(self.brand_label)
        subtitle = QLabel("APP STORE UTILITY")
        subtitle.setObjectName("BrandSubtitle")
        brand_text.addWidget(subtitle)
        brand_row.addLayout(brand_text, 1)
        layout.addLayout(brand_row)

        self.version_label = QLabel(f"v{APP_VERSION}")
        self.version_label.setObjectName("VersionBadge")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_label.setFixedWidth(72)
        layout.addWidget(self.version_label)
        layout.addSpacing(18)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.search_nav_btn = QPushButton("应用搜索")
        self.search_nav_btn.setObjectName("NavButton")
        self.search_nav_btn.setCheckable(True)
        self.search_nav_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_nav_btn.clicked.connect(lambda: self._set_active_page(0))
        self.nav_group.addButton(self.search_nav_btn, 0)
        layout.addWidget(self.search_nav_btn)

        self.download_nav_btn = QPushButton("下载任务")
        self.download_nav_btn.setObjectName("NavButton")
        self.download_nav_btn.setCheckable(True)
        self.download_nav_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_nav_btn.clicked.connect(lambda: self._set_active_page(1))
        self.nav_group.addButton(self.download_nav_btn, 1)
        layout.addWidget(self.download_nav_btn)

        layout.addStretch()

        component_label = QLabel("IPATOOL 2.3.2")
        component_label.setObjectName("ComponentVersion")
        layout.addWidget(component_label)

        self.about_btn = QPushButton("关于")
        self.about_btn.setObjectName("SidebarLink")
        self.about_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.about_btn.clicked.connect(self.show_about)
        layout.addWidget(self.about_btn)

        return sidebar

    def _set_active_page(self, index: int):
        """同步页面栈、侧栏选中态和顶栏上下文。"""
        if index not in (0, 1):
            return
        self.page_stack.setCurrentIndex(index)
        self.search_nav_btn.setChecked(index == 0)
        self.download_nav_btn.setChecked(index == 1)
        self.page_context_label.setText("应用搜索" if index == 0 else "下载任务")

    def create_toolbar(self) -> QFrame:
        """创建紧凑的页面上下文与账号顶栏。"""
        header = QFrame()
        header.setObjectName("TopBar")
        toolbar = QHBoxLayout(header)
        toolbar.setContentsMargins(24, 12, 24, 12)
        toolbar.setSpacing(10)

        self.page_context_label = QLabel("应用搜索")
        self.page_context_label.setObjectName("PageContext")
        toolbar.addWidget(self.page_context_label)
        toolbar.addStretch()

        self.account_label = QLabel("未登录")
        self.account_label.setObjectName("AccountStatus")
        self.account_label.setProperty("state", "idle")
        toolbar.addWidget(self.account_label)

        self.login_btn = QPushButton("登录 Apple ID")
        self.login_btn.setProperty("role", "primary")
        self.login_btn.clicked.connect(self.show_login_dialog)
        toolbar.addWidget(self.login_btn)

        self.clear_auth_btn = QPushButton("清除认证")
        self.clear_auth_btn.setProperty("role", "topbar")
        self.clear_auth_btn.setToolTip("撤销 ipatool 认证并清除本应用保存的凭据")
        self.clear_auth_btn.clicked.connect(self.clear_ipatool_cache)
        toolbar.addWidget(self.clear_auth_btn)

        return header

    def _set_account_status(self, text: str, state: str):
        """通过主题状态呈现账号信息，避免分散的内联颜色。"""
        self.account_label.setStyleSheet("")
        self.account_label.setText(text)
        if self.account_label.property("state") != state:
            self.account_label.setProperty("state", state)
            style = self.account_label.style()
            style.unpolish(self.account_label)
            style.polish(self.account_label)
        self.account_label.update()
    
    def create_search_tab(self) -> QWidget:
        """创建搜索标签页"""
        widget = QFrame()
        widget.setObjectName("PagePanel")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(8)

        title = QLabel("应用搜索")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        subtitle = QLabel("搜索 App Store 元数据，选择 Bundle ID 后进入下载任务。")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(subtitle)
        layout.addSpacing(12)

        search_panel = QFrame()
        search_panel.setObjectName("SearchCard")
        search_card_layout = QVBoxLayout(search_panel)
        search_card_layout.setContentsMargins(18, 16, 18, 18)
        search_card_layout.setSpacing(10)

        query_label = QLabel("搜索应用")
        query_label.setObjectName("CardTitle")
        search_card_layout.addWidget(query_label)

        search_layout = QHBoxLayout()
        search_layout.setSpacing(10)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入应用名称或关键词")
        self.search_input.returnPressed.connect(self.search_apps)
        search_layout.addWidget(self.search_input, 1)

        self.search_btn = QPushButton("搜索")
        self.search_btn.setProperty("role", "primary")
        self.search_btn.setFixedWidth(96)
        self.search_btn.clicked.connect(self.search_apps)
        search_layout.addWidget(self.search_btn)
        search_card_layout.addLayout(search_layout)

        layout.addWidget(search_panel)
        layout.addSpacing(12)

        results_header = QHBoxLayout()
        result_label = QLabel("搜索结果")
        result_label.setObjectName("SectionTitle")
        results_header.addWidget(result_label)
        results_header.addStretch()
        self.results_count_label = QLabel("0 个结果")
        self.results_count_label.setObjectName("ResultsCount")
        results_header.addWidget(self.results_count_label)
        layout.addLayout(results_header)

        self.search_table = QTableWidget()
        self.search_table.setObjectName("DataTable")
        self.search_table.setColumnCount(5)
        self.search_table.setHorizontalHeaderLabels([
            "应用名称", "Bundle ID", "版本", "价格", "操作"
        ])
        header = self.search_table.horizontalHeader()
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(4, 88)
        header.setFixedHeight(42)
        self.search_table.verticalHeader().setVisible(False)
        self.search_table.verticalHeader().setDefaultSectionSize(48)
        self.search_table.setShowGrid(False)
        self.search_table.setCornerButtonEnabled(False)
        self.search_table.setWordWrap(False)
        self.search_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.search_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.search_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.search_table.setAlternatingRowColors(True)
        self.search_table.setSortingEnabled(False)  # 初始禁用排序，填充数据后再启用
        layout.addWidget(self.search_table, 1)

        return widget

    def create_download_tab(self) -> QWidget:
        """创建下载标签页"""
        widget = QFrame()
        widget.setObjectName("PagePanel")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(8)

        title = QLabel("下载任务")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        subtitle = QLabel("配置下载请求，并在右侧查看实时任务输出。")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(subtitle)
        layout.addSpacing(12)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)

        request_panel = QFrame()
        request_panel.setObjectName("SectionPanel")
        input_layout = QVBoxLayout(request_panel)
        input_layout.setContentsMargins(20, 18, 20, 20)
        input_layout.setSpacing(10)

        request_title = QLabel("下载配置")
        request_title.setObjectName("CardTitle")
        input_layout.addWidget(request_title)
        input_layout.addSpacing(4)

        bundle_label = QLabel("Bundle ID")
        bundle_label.setObjectName("FieldLabel")
        input_layout.addWidget(bundle_label)
        self.bundle_input = QLineEdit()
        self.bundle_input.setProperty("technical", True)
        self.bundle_input.setPlaceholderText("com.example.application")
        input_layout.addWidget(self.bundle_input)

        path_label = QLabel("保存路径")
        path_label.setObjectName("FieldLabel")
        input_layout.addWidget(path_label)
        path_layout = QHBoxLayout()
        path_layout.setSpacing(8)
        self.output_path = QLineEdit()
        self.output_path.setProperty("technical", True)
        self.output_path.setText(self.config.download_path)
        path_layout.addWidget(self.output_path)

        browse_btn = QPushButton("浏览")
        browse_btn.clicked.connect(self.browse_output_path)
        path_layout.addWidget(browse_btn)
        input_layout.addLayout(path_layout)

        self.auto_purchase_check = QCheckBox("自动获取应用许可")
        self.auto_purchase_check.setChecked(self.config.auto_purchase)
        input_layout.addWidget(self.auto_purchase_check)

        input_layout.addStretch()
        self.download_btn = QPushButton("开始下载")
        self.download_btn.setProperty("role", "primary")
        self.download_btn.clicked.connect(self.start_download)
        input_layout.addWidget(self.download_btn)

        output_panel = QFrame()
        output_panel.setObjectName("SectionPanel")
        progress_layout = QVBoxLayout(output_panel)
        progress_layout.setContentsMargins(20, 18, 20, 20)
        progress_layout.setSpacing(10)

        output_title = QLabel("任务输出")
        output_title.setObjectName("CardTitle")
        progress_layout.addWidget(output_title)
        progress_layout.addSpacing(4)
        self.progress_label = QLabel("等待下载...")
        self.progress_label.setObjectName("ProgressLabel")
        progress_layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_bar)

        self.log_text = QTextEdit()
        self.log_text.setObjectName("TaskLog")
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("任务事件将在这里显示")
        progress_layout.addWidget(self.log_text)

        splitter.addWidget(request_panel)
        splitter.addWidget(output_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([380, 560])
        layout.addWidget(splitter, 1)

        return widget
    

    def init_ipatool(self):
        """初始化 ipatool"""
        try:
            self.ipatool = IPATool()
            self.update_status("ipatool 已就绪")
            return True
        except FileNotFoundError:
            self.ipatool = None
            QMessageBox.critical(
                self,
                "内置组件缺失",
                "未找到内置 ipatool，应用包可能不完整。\n\n"
                "请从 GitHub Releases 重新下载当前版本。",
            )
            self.update_status("内置 ipatool 缺失", error=True)
            return False
    
    def update_status(self, message: str = None, error: bool = False):
        """更新状态栏"""
        status_bar = self.statusBar()
        if message:
            status_bar.showMessage(message)

        state = "error" if error or not self.ipatool else "ready"
        self.status_label.setStyleSheet("")
        self.status_label.setText(
            "IPATOOL 2.3.2 · ERROR"
            if state == "error"
            else "IPATOOL 2.3.2 · READY"
        )
        if self.status_label.property("state") != state:
            self.status_label.setProperty("state", state)
            style = self.status_label.style()
            style.unpolish(self.status_label)
            style.polish(self.status_label)
        self.status_label.update()

    @staticmethod
    def _is_authentication_error(error_message: object) -> bool:
        text = str(error_message).lower()
        return any(term in text for term in (
            'authentication',
            'not authenticated',
            'unauthorized',
            'auth required',
            'auth failed',
            'login',
            'not logged in',
            'sign in',
            'failed to get account',
            '认证',
            '登录',
        ))

    def _invalidate_cached_authentication(self):
        """外部命令确认认证失效时，使本地缓存状态立即回到未登录。"""
        self._authenticated = False
        self._set_account_status("未登录（认证已失效）", "warning")
        self.login_btn.setText("登录 Apple ID")
        self.login_btn.setEnabled(True)
        try:
            self.login_btn.clicked.disconnect()
        except Exception:
            pass
        self.login_btn.clicked.connect(self.show_login_dialog)
    
    def install_ipatool(self):
        """安装 ipatool"""
        # 显示安装对话框
        dialog = InstallIPADialog(self, self.config)
        if dialog.exec():
            installer = None
            try:
                installer = IPAToolInstaller(self.config)
                self.ipatool_installer = installer
                installer.progress.connect(self.on_install_progress)
                installer.succeeded.connect(self.on_install_finished)
                installer.error.connect(self.on_install_error)
                installer.finished.connect(
                    lambda w=installer: self._on_ipatool_installer_stopped(w)
                )
                installer.start()
                return True
            except Exception as exc:
                if installer is not None:
                    if self.ipatool_installer is installer:
                        self.ipatool_installer = None
                    installer.deleteLater()
                error_msg = IPATool._mask_sensitive_text(str(exc))
                QMessageBox.critical(
                    self,
                    "安装失败",
                    f"无法启动 ipatool 安装任务：\n{error_msg}",
                )
                self.log(f"ipatool 安装任务启动失败: {error_msg}")
                return False
        return False

    def _on_ipatool_installer_stopped(self, installer: IPAToolInstaller):
        """安装线程真正停止后清理引用并续接待处理的关闭请求。"""
        if self.ipatool_installer is installer:
            self.ipatool_installer = None
        installer.deleteLater()
        self._schedule_requested_close()
    
    def on_install_progress(self, message: str, percent: int):
        """安装进度更新"""
        if self._closing:
            return
        self.statusBar().showMessage(f"正在安装 ipatool: {message} ({percent}%)")
    
    def on_install_finished(self, path: str):
        """安装完成"""
        if self._closing:
            return
        self.statusBar().showMessage("ipatool 安装成功！", 5000)
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
        if self._closing:
            return
        self.statusBar().showMessage("安装失败", 5000)
        QMessageBox.critical(
            self,
            "安装失败",
            f"安装 ipatool 时出错:\n{error}\n\n"
            "请手动下载并安装 ipatool。"
        )

    def _auth_operation_pending(self, *, exclude=None) -> bool:
        """Qt 回调消费并清除唯一引用前，认证操作仍视为在途。"""
        if self._pending_auth_cache_clear:
            return True
        for name in (
            'auth_check_worker',
            'login_worker',
            'logout_worker',
            'auth_cache_worker',
        ):
            worker = getattr(self, name, None)
            if worker is not None and worker is not exclude:
                return True
        return False

    def _advance_auth_generation(self) -> int:
        self._auth_generation += 1
        return self._auth_generation

    def _auth_generation_is_current(self, worker) -> bool:
        worker_generation = getattr(worker, '__dict__', {}).get(
            '_auth_generation',
            self._auth_generation,
        )
        return worker_generation == self._auth_generation

    def check_auth(self):
        """异步刷新认证状态，避免在 GUI 线程执行外部命令。"""
        if not self.ipatool:
            self._authenticated = False
            self._set_account_status("未登录 (ipatool 未初始化)", "error")
            self.login_btn.setText("登录 Apple ID")
            self.login_btn.setEnabled(True)
            self.login_btn.clicked.disconnect()
            self.login_btn.clicked.connect(self.show_login_dialog)
            return False

        if self._auth_operation_pending():
            return False

        self._set_account_status("正在检查登录状态...", "checking")
        self.login_btn.setEnabled(False)
        worker = None
        try:
            worker = AuthCheckWorker(self.ipatool)
            worker._auth_generation = self._auth_generation
            self.auth_check_worker = worker
            worker.finished.connect(lambda w=worker: self._on_auth_check_worker_stopped(w))
            worker.start()
            return True
        except Exception as exc:
            if worker is not None:
                if self.auth_check_worker is worker:
                    self.auth_check_worker = None
                worker.deleteLater()
            self.login_btn.setEnabled(True)
            self._set_account_status("认证状态检查未启动", "warning")
            error_msg = IPATool._mask_sensitive_text(str(exc))
            QMessageBox.critical(self, "认证检查失败", f"无法启动认证检查任务：\n{error_msg}")
            self.log(f"认证检查任务启动失败: {error_msg}")
            return False

    def _on_auth_check_worker_stopped(self, worker: AuthCheckWorker):
        """认证检查线程停止后更新 UI。"""
        if self.auth_check_worker is not worker:
            worker.deleteLater()
            self._schedule_requested_close()
            return

        if self._closing:
            self.auth_check_worker = None
            worker.deleteLater()
            self._schedule_requested_close()
            return

        if not self._auth_generation_is_current(worker):
            self.auth_check_worker = None
            worker.deleteLater()
            self._maybe_start_pending_auth_cache_clear()
            self._schedule_requested_close()
            return

        if getattr(worker, '_discard_auth_result', False) is True:
            self.auth_check_worker = None
            worker.deleteLater()
            self._maybe_start_pending_auth_cache_clear()
            self._schedule_requested_close()
            return

        self.auth_check_worker = None
        info = worker.result if isinstance(worker.result, dict) else {}
        authenticated = (
            not worker.error_message
            and info.get('success') is True
            and info.get('returncode') == 0
            and bool(info.get('email'))
        )
        self._authenticated = authenticated
        self.login_btn.setEnabled(True)

        if authenticated:
            email = info.get('email', '未知')
            self._set_account_status(f"已登录: {email}", "ready")
            self.login_btn.setText("退出登录")
            self.login_btn.clicked.disconnect()
            self.login_btn.clicked.connect(self.logout)
        else:
            if worker.error_message:
                self.log(f"检查认证状态失败: {worker.error_message}")
                self._set_account_status("认证状态检查失败", "warning")
            else:
                self._set_account_status("未登录", "idle")
            self.login_btn.setText("登录 Apple ID")
            self.login_btn.clicked.disconnect()
            self.login_btn.clicked.connect(self.show_login_dialog)

        worker.deleteLater()
        self.statusBar().showMessage("就绪")
        self._schedule_requested_close()
    
    def show_login_dialog(self):
        """显示登录对话框"""
        dialog = LoginDialog(self, self.config)
        accepted = False
        creds = None
        remember_credentials = False
        try:
            accepted = bool(dialog.exec())
            if accepted:
                creds = dialog.get_credentials()
                remember_credentials = dialog.remember_check.isChecked()
        finally:
            dialog.clear_sensitive_fields()
            dialog.deleteLater()

        if not accepted or not creds:
            return
        email, password = creds
        self.login(
            email,
            password,
            remember_credentials=remember_credentials,
        )
    
    def login(
        self,
        email: str,
        password: str,
        auth_code: str = "",
        remember_credentials: bool | None = None,
    ):
        """登录"""
        if not self.ipatool:
            QMessageBox.warning(self, "警告", "ipatool 未初始化")
            return False

        if self._auth_operation_pending():
            QMessageBox.information(self, "提示", "认证操作正在进行，请稍候")
            return False

        worker = None
        try:
            auth_generation = self._advance_auth_generation()
            self.statusBar().showMessage("正在登录...")
            self.login_btn.setEnabled(False)
            self._pending_login_email = email
            self._pending_login_password = password
            if remember_credentials is not None:
                self._pending_remember_credentials = remember_credentials
            worker = LoginWorker(self.ipatool, email, password, auth_code or None)
            worker._auth_generation = auth_generation
            self.login_worker = worker
            # 使用 QThread 自身的结束信号，确保 2FA 重试前旧线程已完全退出。
            worker.finished.connect(lambda w=worker: self._on_login_worker_stopped(w))
            worker.start()
            return True
        except Exception as e:
            if worker is not None:
                worker.clear_sensitive_fields()
                if self.login_worker is worker:
                    self.login_worker = None
                worker.deleteLater()
            self._clear_pending_login_credentials()
            self.login_btn.setEnabled(True)
            self.statusBar().showMessage("就绪")
            error_msg = IPATool._mask_sensitive_text(str(e))
            QMessageBox.critical(self, "错误", f"登录时发生错误：\n{error_msg}")
            self.log(f"登录异常: {error_msg}")
            return False

    def _clear_pending_login_credentials(self):
        self._pending_login_email = ''
        self._pending_login_password = ''
        self._pending_remember_credentials = None

    def _on_login_worker_stopped(self, worker: LoginWorker):
        """登录线程真正结束后读取结果并销毁线程对象。"""
        if self.login_worker is not worker:
            worker.deleteLater()
            self._schedule_requested_close()
            return

        if self._closing:
            self.login_worker = None
            worker.deleteLater()
            self._schedule_requested_close()
            return

        if not self._auth_generation_is_current(worker):
            self.login_worker = None
            worker.deleteLater()
            self._maybe_start_pending_auth_cache_clear()
            self._schedule_requested_close()
            return

        if getattr(worker, '_discard_auth_result', False) is True:
            self.login_worker = None
            worker.deleteLater()
            self._maybe_start_pending_auth_cache_clear()
            self._schedule_requested_close()
            return

        self.login_worker = None
        try:
            if worker.error_message:
                self.on_login_error(worker.error_message)
            else:
                self.on_login_finished(
                    worker.result or {'success': False, 'error': '登录线程未返回结果'}
                )
        finally:
            worker.deleteLater()
            self._schedule_requested_close()

    def on_login_finished(
        self,
        result: dict,
        email=None,
        password=None
    ):
        """登录线程完成"""
        email = self._pending_login_email if email is None else email
        password = self._pending_login_password if password is None else password
        self.login_btn.setEnabled(True)
        self.statusBar().showMessage("就绪")
        self._authenticated = False

        if isinstance(result, dict) and result.get('success', False):
            if result.get('auth_verified'):
                self._authenticated = True
                account_email = result.get('email') or email
                self._set_account_status(f"已登录: {account_email}", "ready")
                self.login_btn.setText("退出登录")
                self.login_btn.clicked.disconnect()
                self.login_btn.clicked.connect(self.logout)
                credential_save_error = None
                try:
                    if self._pending_remember_credentials is not None:
                        self.config.save_apple_credentials(
                            account_email,
                            password,
                            self._pending_remember_credentials,
                            raise_on_error=True,
                        )
                except Exception as exc:
                    credential_save_error = IPATool._mask_sensitive_text(str(exc))
                finally:
                    self._clear_pending_login_credentials()

                if credential_save_error:
                    QMessageBox.warning(
                        self,
                        "登录成功，凭据未保存",
                        "登录已验证，但无法保存本地凭据：\n"
                        f"{credential_save_error}",
                    )
                else:
                    QMessageBox.information(self, "成功", "登录成功！")
                return

            self._clear_pending_login_credentials()
            QMessageBox.warning(self, "警告", "登录状态验证失败，请清除缓存后重试")
            self.log("登录状态验证失败")
            return

        error_msg = result.get('error', result.get('output', '未知错误')) if isinstance(result, dict) else str(result)

        if isinstance(result, dict) and result.get('requires_auth_code'):
            self._handle_auth_code_required(email, password)
            return

        if isinstance(result, dict) and result.get('credentials_or_auth_code_invalid'):
            self._handle_credentials_or_code_invalid(email, password, error_msg)
            return

        if isinstance(result, dict) and result.get('invalid_auth_code'):
            self._prompt_for_auth_code(
                email,
                password,
                message="验证码无效或已过期，请获取最新的 6 位验证码后重试。",
                error=True
            )
            return

        if isinstance(result, dict) and result.get('invalid_auth_code_format'):
            self._prompt_for_auth_code(
                email,
                password,
                message="验证码格式不正确，请输入完整的 6 位数字。",
                error=True
            )
            return

        if isinstance(result, dict) and result.get('temporary_failure'):
            self._clear_pending_login_credentials()
            QMessageBox.warning(self, "Apple 服务暂不可用", error_msg)
            self.log(f"登录暂时失败: {error_msg}")
            return

        self._clear_pending_login_credentials()
        details_text = self._format_login_details(result)
        QMessageBox.critical(self, "登录失败", f"登录失败：\n{error_msg}{details_text}")
        self.log(f"登录失败: {error_msg}{details_text}")

    def _prompt_for_auth_code(
        self,
        email: str,
        password: str,
        message: str = "",
        error: bool = False
    ) -> bool:
        """显示专用 2FA 对话框，并用规范化验证码重试登录。"""
        dialog = TwoFactorDialog(self, message=message, error=error)
        accepted = False
        auth_code = ""
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            if accepted:
                auth_code = dialog.get_auth_code()
        finally:
            dialog.clear_sensitive_fields()
            dialog.deleteLater()

        if not accepted:
            self._clear_pending_login_credentials()
            return False
        if not auth_code:
            self._clear_pending_login_credentials()
            return False
        started = bool(self.login(email, password, auth_code))
        if not started:
            self._clear_pending_login_credentials()
        return started

    def _handle_auth_code_required(self, email: str, password: str):
        """处理需要 2FA 的登录分支。"""
        self._prompt_for_auth_code(
            email,
            password,
            message=(
                "Apple 已要求双重认证。请输入受信任设备上显示的最新 6 位验证码；"
                "验证码通常只能使用一次。"
            )
        )

    def _handle_credentials_or_code_invalid(self, email: str, password: str, error_msg: str):
        """处理密码或验证码不正确的登录分支"""
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("登录失败")
        message.setText(
            f"{error_msg}\n\n"
            "Apple 返回的错误无法可靠区分是密码错误还是验证码过期。请选择下一步。"
        )
        password_button = message.addButton("重新输入账号密码", QMessageBox.ButtonRole.AcceptRole)
        code_button = message.addButton("重新输入验证码", QMessageBox.ButtonRole.ActionRole)
        message.addButton(QMessageBox.StandardButton.Cancel)
        message.exec()

        clicked = message.clickedButton()
        if clicked == password_button:
            self._clear_pending_login_credentials()
            self.show_login_dialog()
        elif clicked == code_button:
            self._prompt_for_auth_code(
                email,
                password,
                message="请获取并输入最新的 6 位验证码。",
                error=True
            )
        else:
            self._clear_pending_login_credentials()

    def on_login_error(self, error_msg: str):
        """登录线程异常"""
        self._clear_pending_login_credentials()
        self.login_btn.setEnabled(True)
        self.statusBar().showMessage("就绪")
        QMessageBox.critical(self, "错误", f"登录时发生错误：\n{error_msg}")
        self.log(f"登录异常: {error_msg}")

    def _format_login_details(self, result) -> str:
        """格式化登录错误详情"""
        if not isinstance(result, dict) or not isinstance(result.get('details'), dict):
            return ""

        parts = []
        for key in ['message', 'error', 'output']:
            value = result['details'].get(key)
            if value:
                parts.append(f"{key}: {value}")

        return "\n\n" + "\n".join(parts) if parts else ""
    
    def logout(self):
        """在后台撤销认证，避免 auth revoke 阻塞 GUI。"""
        if not self.ipatool:
            self.check_auth()
            return
        if self._auth_operation_pending():
            QMessageBox.information(self, "提示", "认证操作正在进行，请稍候")
            return

        reply = QMessageBox.question(
            self, "确认", "确定要退出登录吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        auth_generation = self._advance_auth_generation()
        self.statusBar().showMessage("正在退出登录...")
        self.login_btn.setEnabled(False)
        worker = None
        try:
            worker = LogoutWorker(self.ipatool)
            worker._auth_generation = auth_generation
            self.logout_worker = worker
            worker.finished.connect(lambda w=worker: self._on_logout_worker_stopped(w))
            worker.start()
            return True
        except Exception as exc:
            if worker is not None:
                if self.logout_worker is worker:
                    self.logout_worker = None
                worker.deleteLater()
            self.login_btn.setEnabled(True)
            self.statusBar().showMessage("就绪")
            error_msg = IPATool._mask_sensitive_text(str(exc))
            QMessageBox.critical(self, "错误", f"无法启动退出登录任务：\n{error_msg}")
            self.log(f"退出登录任务启动失败: {error_msg}")
            return False

    def _on_logout_worker_stopped(self, worker: LogoutWorker):
        """退出线程停止后消费结果；忽略过期 worker。"""
        if self.logout_worker is not worker:
            worker.deleteLater()
            self._schedule_requested_close()
            return

        if self._closing:
            self.logout_worker = None
            worker.deleteLater()
            self._schedule_requested_close()
            return

        if not self._auth_generation_is_current(worker):
            self.logout_worker = None
            worker.deleteLater()
            self._maybe_start_pending_auth_cache_clear()
            self._schedule_requested_close()
            return

        if getattr(worker, '_discard_auth_result', False) is True:
            self.logout_worker = None
            worker.deleteLater()
            self._maybe_start_pending_auth_cache_clear()
            self._schedule_requested_close()
            return

        self.logout_worker = None
        self.login_btn.setEnabled(True)
        try:
            if worker.error_message:
                QMessageBox.critical(
                    self,
                    "错误",
                    f"退出登录时出错：\n{worker.error_message}",
                )
                self.log(f"退出登录异常: {worker.error_message}")
                return

            result = worker.result
            if isinstance(result, dict) and result.get('success', False):
                self._authenticated = False
                self._set_account_status("未登录", "idle")
                self.login_btn.setText("登录 Apple ID")
                self.login_btn.clicked.disconnect()
                self.login_btn.clicked.connect(self.show_login_dialog)
                self.search_table.setRowCount(0)
                self.results_count_label.setText("0 个结果")
                self.log_text.clear()
                self.progress_bar.setValue(0)
                self.progress_label.setText("等待下载...")
                QMessageBox.information(self, "成功", "已退出登录")
            else:
                error_msg = (
                    result.get('error', '未知错误')
                    if isinstance(result, dict)
                    else str(result)
                )
                QMessageBox.warning(self, "警告", f"退出登录失败：\n{error_msg}")
        finally:
            worker.deleteLater()
            self.statusBar().showMessage("就绪")
            self._schedule_requested_close()

    def clear_ipatool_cache(self):
        """在后台撤销认证并清除 ipatool 与本应用保存的凭据。"""
        if self._pending_auth_cache_clear or self.auth_cache_worker is not None:
            QMessageBox.information(self, "提示", "认证缓存清理正在进行，请稍候")
            return

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

        self._advance_auth_generation()
        for name in ('login_worker', 'auth_check_worker', 'logout_worker'):
            worker = getattr(self, name, None)
            if worker is not None:
                worker._discard_auth_result = True
        self._clear_pending_login_credentials()
        self._authenticated = False

        waiting_for_auth_worker = any(
            getattr(self, name, None) is not None
            for name in ('login_worker', 'auth_check_worker', 'logout_worker')
        )
        if waiting_for_auth_worker:
            self._pending_auth_cache_clear = True
            self.login_btn.setEnabled(False)
            self.statusBar().showMessage("正在等待认证任务结束后清除认证缓存...")
            return

        self._start_auth_cache_clear()

    def _maybe_start_pending_auth_cache_clear(self):
        """最后一个旧认证 worker 回调消费后启动清理。"""
        if not self._pending_auth_cache_clear:
            return
        if any(
            getattr(self, name, None) is not None
            for name in ('login_worker', 'auth_check_worker', 'logout_worker')
        ):
            return
        self._start_auth_cache_clear()

    def _start_auth_cache_clear(self):
        """在登录任务停止后启动认证撤销与本地缓存删除。"""
        self._pending_auth_cache_clear = False
        if not self.ipatool:
            self._complete_auth_cache_clear(
                {},
                ["ipatool 未初始化，无法执行 auth revoke 或清理其缓存。"],
            )
            return

        self.statusBar().showMessage("正在清除 ipatool 认证缓存...")
        self.login_btn.setEnabled(False)
        worker = None
        try:
            worker = ClearAuthCacheWorker(self.ipatool)
            worker._auth_generation = self._auth_generation
            self.auth_cache_worker = worker
            worker.finished.connect(lambda w=worker: self._on_auth_cache_worker_stopped(w))
            worker.start()
            return True
        except Exception as exc:
            if worker is not None:
                if self.auth_cache_worker is worker:
                    self.auth_cache_worker = None
                worker.deleteLater()
            self.login_btn.setEnabled(True)
            self.statusBar().showMessage("就绪")
            error_msg = IPATool._mask_sensitive_text(str(exc))
            QMessageBox.critical(
                self,
                "清除认证失败",
                "无法启动认证缓存清理任务；未确认任何外部缓存已清除：\n"
                f"{error_msg}",
            )
            self.log(f"认证缓存清理任务启动失败: {error_msg}")
            return False

    def _on_auth_cache_worker_stopped(self, worker: ClearAuthCacheWorker):
        """认证缓存线程停止后消费结果；忽略过期 worker。"""
        if self.auth_cache_worker is not worker:
            worker.deleteLater()
            self._schedule_requested_close()
            return

        if self._closing:
            self.auth_cache_worker = None
            worker.deleteLater()
            self._schedule_requested_close()
            return

        if not self._auth_generation_is_current(worker):
            self.auth_cache_worker = None
            worker.deleteLater()
            self._schedule_requested_close()
            return

        self.auth_cache_worker = None
        self.login_btn.setEnabled(True)
        result = worker.result if isinstance(worker.result, dict) else {}
        errors = list(result.get('errors') or [])
        logout_result = result.get('logout')
        if isinstance(logout_result, dict):
            if logout_result.get('success') is not True:
                errors.append(
                    "撤销认证失败: "
                    + str(logout_result.get('error') or 'ipatool 未确认撤销成功')
                )
        elif not any(str(item).startswith("撤销认证失败:") for item in errors):
            errors.append("撤销认证失败: 未返回有效撤销结果")
        cache_result = result.get('cache')
        if isinstance(cache_result, dict):
            if cache_result.get('success') is not True:
                errors.append(
                    "删除本地缓存失败: "
                    + str(cache_result.get('error') or 'ipatool 缓存仍然存在')
                )
        elif not any(str(item).startswith("删除本地缓存失败:") for item in errors):
            errors.append("删除本地缓存失败: 未返回有效清理结果")
        try:
            self._complete_auth_cache_clear(result, errors)
        finally:
            worker.deleteLater()
            self.statusBar().showMessage("就绪")
            self._schedule_requested_close()

    def _complete_auth_cache_clear(self, result: dict, errors: list[str]):
        """清除本应用凭据与 UI 状态，并报告后台清理结果。"""
        local_credentials_cleared = True
        try:
            self.config.save_apple_credentials('', '', False, raise_on_error=True)
        except Exception as exc:
            local_credentials_cleared = False
            errors.append(f"清除本应用保存的凭据失败: {exc}")

        self._authenticated = False
        self._clear_pending_login_credentials()
        self._set_account_status("未登录", "idle")
        self.login_btn.setText("登录 Apple ID")
        try:
            self.login_btn.clicked.disconnect()
        except Exception:
            pass
        self.login_btn.clicked.connect(self.show_login_dialog)
        self.search_table.setRowCount(0)
        self.results_count_label.setText("0 个结果")
        self.log_text.clear()
        self.progress_bar.setValue(0)
        self.progress_label.setText("等待下载...")

        cache_result = result.get('cache') if isinstance(result, dict) else None
        details = []
        if isinstance(cache_result, dict):
            removed = cache_result.get('removed') or []
            not_found = cache_result.get('not_found') or []
            if removed:
                details.append("已删除: " + "; ".join(removed))
            if not_found:
                details.append("未找到: " + "; ".join(not_found))
        details_text = "\n\n" + "\n".join(details) if details else ""

        if errors:
            safe_errors = "\n".join(dict.fromkeys(str(item) for item in errors))
            if local_credentials_cleared:
                summary = "本应用保存的凭据已清除，但部分 ipatool 清理步骤失败："
            else:
                summary = "无法确认本应用保存的凭据已从磁盘清除；以下清理步骤未完成："
            QMessageBox.warning(
                self,
                "部分完成",
                f"{summary}\n{safe_errors}{details_text}",
            )
        else:
            QMessageBox.information(
                self,
                "完成",
                f"已清除 ipatool 本地缓存与账号信息{details_text}",
            )

    def search_apps(self):
        """搜索应用"""
        current_worker = getattr(self, 'search_worker', None)
        try:
            if current_worker is not None and current_worker.isRunning():
                self.statusBar().showMessage("搜索任务正在运行，请稍候")
                return
        except RuntimeError:
            self.search_worker = None

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
        self.results_count_label.setText("0 个结果")
        
        # 创建搜索线程；start 失败时必须回滚引用和控件状态。
        worker = None
        try:
            worker = SearchWorker(self.ipatool, keyword)
            self.search_worker = worker
            worker.succeeded.connect(
                lambda results, current=worker: self._on_search_worker_succeeded(
                    current, results
                )
            )
            worker.error.connect(
                lambda message, current=worker: self._on_search_worker_failed(
                    current, message
                )
            )
            worker.finished.connect(
                lambda current=worker: self._on_search_worker_stopped(current)
            )
            worker.start()
            return True
        except Exception as exc:
            if worker is not None:
                if self.search_worker is worker:
                    self.search_worker = None
                worker.deleteLater()
            self.search_btn.setEnabled(True)
            self.search_btn.setText("搜索")
            error_msg = IPATool._mask_sensitive_text(str(exc))
            QMessageBox.critical(self, "搜索失败", f"无法启动搜索任务：\n{error_msg}")
            self.log(f"搜索任务启动失败: {error_msg}")
            return False

    def _on_search_worker_succeeded(self, worker, results):
        if worker is self.search_worker and not self._closing:
            self.on_search_finished(results)

    def _on_search_worker_failed(self, worker, error_msg):
        if worker is self.search_worker and not self._closing:
            self.on_search_error(error_msg)

    def _on_search_worker_stopped(self, worker):
        if worker is self.search_worker:
            self.search_worker = None
            if not self._closing:
                self.search_btn.setEnabled(True)
                self.search_btn.setText("搜索")
        worker.deleteLater()
        self._schedule_requested_close()
    
    def on_search_finished(self, results):
        """搜索完成"""
        if self._closing:
            return
        try:
            self.search_btn.setEnabled(True)
            self.search_btn.setText("搜索")
            
            # 清空表格
            self.search_table.clearContents()
            self.search_table.setRowCount(0)
            self.search_table.setColumnCount(0)  # 重置列
            self.results_count_label.setText("0 个结果")
            
            if not results:
                QMessageBox.information(self, "提示", "未找到相关应用")
                return
            
            # 确保结果是一个列表
            if not isinstance(results, list):
                QMessageBox.warning(self, "错误", "搜索结果格式不正确")
                return

            self.results_count_label.setText(f"{len(results)} 个结果")
                
            # 设置表头
            headers = ["应用名称", "Bundle ID", "版本", "价格", "操作"]
            self.search_table.setColumnCount(len(headers))
            self.search_table.setHorizontalHeaderLabels(headers)
            
            # 设置行数
            self.search_table.setRowCount(len(results))

            technical_font = QFont("Cascadia Mono")
            technical_font.setStyleHint(QFont.StyleHint.Monospace)
            
            for row, app in enumerate(results):
                try:
                    # 确保app是字典类型
                    if not isinstance(app, dict):
                        continue
                    
                    # 获取应用信息，提供默认值
                    app_info = {
                        'name': str(app.get('trackName') or app.get('name') or app.get('trackName', '未知应用')),
                        'bundle_id': str(app.get('bundleId') or app.get('bundleID') or ''),
                        'version': str(app.get('version') or ''),
                        'price': str(app.get('formattedPrice') or app.get('price') or 'Free')
                    }
                    
                    # 应用名称
                    name_item = QTableWidgetItem(app_info['name'])
                    name_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                    self.search_table.setItem(row, 0, name_item)
                    
                    # Bundle ID
                    bundle_id = app_info['bundle_id']
                    bundle_item = QTableWidgetItem(bundle_id)
                    bundle_item.setFont(technical_font)
                    bundle_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                    self.search_table.setItem(row, 1, bundle_item)
                    
                    # 版本
                    version_item = QTableWidgetItem(app_info['version'])
                    version_item.setFont(technical_font)
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
                        download_btn.setProperty("role", "tableAction")
                        # 使用functools.partial确保正确的bundle_id被传递
                        from functools import partial
                        download_btn.clicked.connect(partial(self.download_from_search, bundle_id))
                        self.search_table.setCellWidget(row, 4, download_btn)
                    
                except Exception:
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
            
        except Exception as e:
            safe_error = IPATool._mask_sensitive_text(str(e))
            error_msg = f"显示搜索结果时出错: {safe_error}"
            QMessageBox.critical(self, "错误", error_msg)
    
    def on_search_error(self, error_msg):
        """搜索错误"""
        if self._closing:
            return
        try:
            self.search_btn.setEnabled(True)
            self.search_btn.setText("搜索")
            
            # 清空表格
            self.search_table.setRowCount(0)
            self.results_count_label.setText("0 个结果")
            
            # 显示错误信息
            error_text = IPATool._mask_sensitive_text(str(error_msg))
            if "No results found" in error_text:
                QMessageBox.information(self, "提示", "未找到相关应用")
            elif self._is_authentication_error(error_text):
                self._invalidate_cached_authentication()
                QMessageBox.warning(self, "认证错误", "认证失败，请重新登录")
            elif "network" in error_text.lower():
                QMessageBox.warning(self, "网络错误", "网络连接失败，请检查网络设置")
            else:
                QMessageBox.critical(self, "搜索失败", f"搜索时发生错误：\n{error_text}")
                
        except Exception as e:
            safe_error = IPATool._mask_sensitive_text(str(e))
            QMessageBox.critical(self, "错误", f"处理搜索错误时发生异常：\n{safe_error}")
    
    def download_from_search(self, bundle_id: str):
        """从搜索结果下载"""
        self.bundle_input.setText(bundle_id)
        self._set_active_page(1)
        self.start_download()
    
    def browse_output_path(self):
        """浏览输出路径"""
        path = QFileDialog.getExistingDirectory(self, "选择下载目录", self.output_path.text())
        if not path:
            return False
        try:
            self.config.download_path = path
            self.output_path.setText(path)
            return True
        except Exception:
            QMessageBox.critical(
                self,
                "保存下载目录失败",
                "无法保存下载目录，请检查配置目录写权限后重试。",
            )
            return False
    
    def start_download(self):
        """开始下载"""
        current_worker = getattr(self, 'download_worker', None)
        try:
            if current_worker is not None and current_worker.isRunning():
                self.statusBar().showMessage("下载任务正在运行，请稍候")
                return
        except RuntimeError:
            self.download_worker = None

        bundle_id = self.bundle_input.text().strip()
        
        if not bundle_id:
            QMessageBox.warning(self, "警告", "请输入 Bundle ID")
            return False

        if not DownloadWorker.is_valid_bundle_id(bundle_id):
            QMessageBox.warning(
                self,
                "警告",
                "Bundle ID 格式无效；仅接受标准的反向域名标识符。",
            )
            return False
        
        if not self.ipatool:
            QMessageBox.warning(self, "警告", "ipatool 未初始化")
            return False
        
        if not self._authenticated:
            QMessageBox.warning(self, "警告", "请先登录 Apple ID")
            self.show_login_dialog()
            return False
        
        # 准备下载
        output_path = Path(self.output_path.text())
        output_path.mkdir(parents=True, exist_ok=True)
        
        filename = f"{bundle_id}.ipa"
        full_path = str(output_path / filename)
        
        self.download_btn.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("")
        self.progress_label.setText("准备下载...")
        self.log_text.clear()
        self.log("开始下载...")
        
        # 创建下载线程；start 失败时回滚唯一引用和下载控件。
        worker = None
        try:
            auto_purchase = self.auto_purchase_check.isChecked()
            worker = DownloadWorker(
                self.ipatool, bundle_id, "", full_path, auto_purchase
            )
            self.download_worker = worker
            worker.progress.connect(
                lambda message, percent, current=worker: self._on_download_worker_progress(
                    current, message, percent
                )
            )
            worker.succeeded.connect(
                lambda path, current=worker: self._on_download_worker_succeeded(
                    current, path
                )
            )
            worker.failed.connect(
                lambda message, current=worker: self._on_download_worker_failed(
                    current, message
                )
            )
            worker.cancelled.connect(
                lambda current=worker: self._on_download_worker_cancelled(current)
            )
            worker.finished.connect(
                lambda current=worker: self._on_download_worker_stopped(current)
            )
            worker.start()
            return True
        except Exception as exc:
            if worker is not None:
                if self.download_worker is worker:
                    self.download_worker = None
                worker.deleteLater()
            self.download_btn.setEnabled(True)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setFormat("%p%")
            self.progress_bar.setValue(0)
            self.progress_label.setText("下载未启动")
            error_msg = IPATool._mask_sensitive_text(str(exc))
            QMessageBox.critical(self, "下载失败", f"无法启动下载任务：\n{error_msg}")
            self.log(f"下载任务启动失败: {error_msg}")
            return False

    def _on_download_worker_progress(self, worker, message: str, percent: int):
        if worker is self.download_worker and not self._closing:
            self.on_download_progress(message, percent)

    def _on_download_worker_succeeded(self, worker, file_path: str):
        if worker is self.download_worker and not self._closing:
            self.on_download_finished(file_path)

    def _on_download_worker_failed(self, worker, error_msg: str):
        if worker is self.download_worker and not self._closing:
            self.on_download_error(error_msg)

    def _on_download_worker_cancelled(self, worker):
        if worker is self.download_worker and not self._closing:
            self.on_download_cancelled()

    def _on_download_worker_stopped(self, worker):
        was_current = worker is self.download_worker
        if worker is self.download_worker:
            self.download_worker = None
            if not self._closing:
                self.download_btn.setEnabled(True)
        worker.deleteLater()
        if was_current and self._close_requested and not self._closing:
            QTimer.singleShot(0, self.close)
    
    def on_download_progress(self, message: str, percent: int):
        """下载进度更新"""
        if self._closing:
            return
        self.progress_label.setText(message)
        if percent < 0:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("")
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setFormat("%p%")
            self.progress_bar.setValue(percent)
        self.log(message)
    
    def on_download_finished(self, file_path: str):
        """下载完成"""
        if self._closing:
            return
        try:
            self.download_btn.setEnabled(True)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setFormat("%p%")
            self.progress_bar.setValue(100)
            self.progress_label.setText("下载完成！")
            self.log(f"下载成功: {file_path}")
            
            reply = QMessageBox.information(
                self,
                "下载完成",
                f"文件已保存到：\n{file_path}\n\n是否打开文件所在文件夹？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                import platform
                import subprocess
                if platform.system() == 'Windows':
                    subprocess.run(['explorer', '/select,', file_path])
                elif platform.system() == 'Darwin':  # macOS
                    subprocess.run(['open', '-R', file_path])
                else:  # Linux
                    subprocess.run(['xdg-open', str(Path(file_path).parent)])
                    
        except Exception as e:
            safe_error = IPATool._mask_sensitive_text(str(e))
            self.log(f"处理下载完成状态失败: {safe_error}")
    
    def on_download_error(self, error_msg: str):
        """下载错误"""
        if self._closing:
            return
        safe_error = IPATool._mask_sensitive_text(str(error_msg))
        if self._is_authentication_error(safe_error):
            self._invalidate_cached_authentication()
        self.download_btn.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setValue(0)
        self.progress_label.setText("下载失败")
        self.log(f"错误: {safe_error}")
        QMessageBox.critical(self, "下载失败", f"下载失败：\n{safe_error}")

    def on_download_cancelled(self):
        """下载被用户取消。"""
        if self._closing:
            return
        self.download_btn.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setValue(0)
        self.progress_label.setText("下载已取消")
        self.log("下载已取消")
    
    def log(self, message: str):
        """添加日志"""
        safe_message = safe_external_text(
            message,
            fallback="收到无法安全显示的日志消息",
        )
        self.log_text.append(safe_message)

    def show_settings(self):
        """显示设置对话框"""
        worker_names = (
            'auth_check_worker',
            'login_worker',
            'logout_worker',
            'auth_cache_worker',
            'search_worker',
            'download_worker',
            'ipatool_installer',
        )
        if any(
            (worker := getattr(self, name, None)) is not None
            and worker.isRunning()
            for name in worker_names
        ):
            QMessageBox.information(self, "请稍候", "后台任务完成后才能更改 ipatool 路径。")
            return

        dialog = SettingsDialog(self, self.config)
        if dialog.exec():
            self._authenticated = False
            if self.init_ipatool():
                self.check_auth()
            self.output_path.setText(self.config.download_path)
    
    def _create_about_dialog(self) -> QDialog:
        """构建紧凑、分层的产品信息对话框。"""
        dialog = QDialog(self)
        dialog.setObjectName("AboutDialog")
        dialog.setWindowTitle("关于 IPA Download Tool")
        dialog.setWindowIcon(self.windowIcon())
        dialog.setModal(True)
        dialog.setMinimumWidth(560)
        dialog.setStyleSheet(
            GRAPHITE_STYLESHEET
            + """
            QDialog#AboutDialog { background-color: #0b0f14; }
            QFrame#AboutInfoCard {
                background-color: #121923;
                border: 1px solid #253143;
                border-radius: 10px;
            }
            QLabel#AboutMeta { color: #f4f7fb; font-size: 13px; }
            QLabel#AboutBody { color: #aab7c8; font-size: 13px; }
            QLabel#AboutCopyright { color: #8291a5; font-size: 12px; }
            QLabel#AboutWarning {
                color: #fcd34d;
                background-color: #2b2411;
                border: 1px solid #655426;
                border-radius: 8px;
                padding: 8px;
                font-weight: 600;
            }
            QPushButton#AboutLicenseButton {
                color: #a9c6ff;
                background-color: #17243a;
                border: 1px solid #2c4d7c;
            }
            QPushButton#AboutLicenseButton:hover {
                color: #ffffff;
                background-color: #23406a;
                border-color: #4f8cff;
            }
            """
        )

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)

        hero = QFrame(dialog)
        hero.setObjectName("AboutHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        hero_layout.setSpacing(12)

        icon = QLabel(hero)
        icon.setObjectName("AboutHeroIcon")
        icon.setPixmap(self.windowIcon().pixmap(56, 56))
        icon.setFixedSize(60, 60)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hero_layout.addWidget(icon)

        title_stack = QVBoxLayout()
        title_stack.setSpacing(2)
        title = QLabel("IPA DOWNLOAD TOOL", hero)
        title.setObjectName("BrandTitle")
        title_stack.addWidget(title)
        subtitle = QLabel("APP STORE DOWNLOAD WORKSPACE", hero)
        subtitle.setObjectName("BrandSubtitle")
        title_stack.addWidget(subtitle)
        hero_layout.addLayout(title_stack)
        hero_layout.addStretch()
        version = QLabel(f"v{APP_VERSION}", hero)
        version.setObjectName("VersionBadge")
        hero_layout.addWidget(version)
        layout.addWidget(hero)

        details = QFrame(dialog)
        details.setObjectName("AboutInfoCard")
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(14, 12, 14, 12)
        details_layout.setSpacing(7)
        for text in (
            f"<b>开发者</b>　{APP_DEVELOPER}",
            "<b>内置组件</b>　ipatool 2.3.2",
            "<b>开源许可</b>　GPL-3.0-only",
        ):
            label = QLabel(text, details)
            label.setObjectName("AboutMeta")
            details_layout.addWidget(label)
        layout.addWidget(details)

        description = QLabel(
            "基于 <a href='https://github.com/majd/ipatool'>ipatool</a> 的图形化下载工具，"
            "用于搜索 App Store 元数据并下载已授权应用。",
            dialog,
        )
        description.setObjectName("AboutBody")
        description.setWordWrap(True)
        description.setOpenExternalLinks(True)
        layout.addWidget(description)

        disclaimer = QLabel(
            "非 Apple 官方产品，未获 Apple 认可或关联。",
            dialog,
        )
        disclaimer.setObjectName("AboutWarning")
        disclaimer.setWordWrap(True)
        layout.addWidget(disclaimer)

        copyright_label = QLabel(
            f"© {COPYRIGHT_YEAR} IPA Download Tool · {APP_DEVELOPER}",
            dialog,
        )
        copyright_label.setObjectName("AboutCopyright")
        layout.addWidget(copyright_label)

        buttons = QHBoxLayout()
        license_button = QPushButton("查看开源许可", dialog)
        license_button.setObjectName("AboutLicenseButton")
        license_button.clicked.connect(self.show_licenses)
        buttons.addWidget(license_button)
        buttons.addStretch()
        close_button = QPushButton("关闭", dialog)
        close_button.setProperty("role", "primary")
        close_button.clicked.connect(dialog.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        return dialog

    def show_about(self):
        """显示结构化关于对话框。"""
        self._create_about_dialog().exec()

    @staticmethod
    def _resource_root() -> Path:
        """返回源码根目录或 PyInstaller 的解包资源目录。"""
        meipass = getattr(__import__('sys'), '_MEIPASS', None)
        if meipass:
            return Path(meipass)
        return Path(__file__).resolve().parent.parent

    def _load_third_party_license_text(self) -> str:
        """读取随源码或单文件应用分发的第三方通知与许可证原文。"""
        root = self._resource_root()
        paths = [root / 'THIRD_PARTY_NOTICES.md']
        third_party_root = root / 'third_party'
        if third_party_root.is_dir():
            paths.extend(sorted(third_party_root.rglob('LICENSE')))
            paths.extend(sorted(third_party_root.rglob('COPYING.txt')))

        sections = []
        for path in paths:
            try:
                relative = path.relative_to(root)
                content = path.read_text(encoding='utf-8')
            except (OSError, UnicodeError, ValueError):
                continue
            sections.append(f"===== {relative.as_posix()} =====\n\n{content.strip()}")

        if not sections:
            return "未找到内嵌的第三方许可证文件。"
        return "\n\n\n".join(sections)

    def _create_license_dialog(self) -> QDialog:
        """默认显示许可摘要，许可证原文保留在二级标签中。"""
        dialog = QDialog(self)
        dialog.setObjectName("LicenseDialog")
        dialog.setWindowTitle("开源许可")
        dialog.setWindowIcon(self.windowIcon())
        dialog.resize(780, 580)
        dialog.setStyleSheet(
            GRAPHITE_STYLESHEET
            + """
            QDialog#LicenseDialog { background-color: #0b0f14; }
            QDialog#LicenseDialog QLabel { color: #cbd7e6; }
            """
        )

        layout = QVBoxLayout(dialog)
        intro = QLabel(
            "本应用以 GPL-3.0-only 发布。完整许可原文随应用保留，"
            "但默认页面仅展示便于阅读的摘要。",
            dialog,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        tabs = QTabWidget(dialog)
        summary = QTextEdit(tabs)
        summary.setReadOnly(True)
        summary.setHtml(
            "<h3>许可摘要</h3>"
            "<p><b>IPA Download Tool</b>：GPL-3.0-only</p>"
            "<p><b>PyQt6 / Qt</b>：GPLv3 或商业许可；本发行版采用 GPLv3 路径。</p>"
            "<p><b>ipatool</b>：MIT License。</p>"
            "<p>你可以在 GPLv3 条款下使用、研究、修改和再分发本程序。"
            "再分发修改版时须继续提供对应源代码和许可声明。</p>"
        )
        tabs.addTab(summary, "许可摘要")

        raw_viewer = QTextEdit(tabs)
        raw_viewer.setReadOnly(True)
        raw_viewer.setStyleSheet(
            "font-family: Consolas, 'Cascadia Mono', monospace; font-size: 12px;"
        )
        raw_viewer.setPlainText(self._load_third_party_license_text())
        tabs.addTab(raw_viewer, "许可证原文")
        layout.addWidget(tabs)

        close_btn = QPushButton("关闭", dialog)
        close_btn.setProperty("role", "primary")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)
        return dialog

    def show_licenses(self):
        """显示开源许可摘要与内嵌许可证原文。"""
        self._create_license_dialog().exec()

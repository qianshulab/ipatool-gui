"""Graphite-blue visual tokens for the desktop workspace."""

GRAPHITE_STYLESHEET = r"""
QMainWindow#MainWindow,
QDialog {
    background: #0b0f14;
    color: #dbe5f2;
    font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
    font-size: 13px;
}
QDialog QLabel,
QMessageBox QLabel {
    color: #dbe5f2;
}
QWidget#CentralSurface,
QFrame#Workspace,
QStackedWidget#PageStack,
QFrame#PagePanel {
    background: #0b0f14;
    border: 0;
}
QFrame#Sidebar {
    background: #101722;
    border: 0;
    border-right: 1px solid #202b3a;
}
QLabel#SidebarLogo {
    background: #171f2b;
    border: 1px solid #273548;
    border-radius: 8px;
}
QLabel#BrandTitle {
    color: #f4f7fb;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.6px;
}
QLabel#BrandSubtitle {
    color: #6f8096;
    font-size: 9px;
    letter-spacing: 0.5px;
}
QLabel#VersionBadge {
    color: #9fbdf3;
    background: #17243a;
    border: 1px solid #29446d;
    border-radius: 6px;
    padding: 4px 8px;
    font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 10px;
}
QLabel#ComponentVersion {
    color: #66758a;
    font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 10px;
    padding: 5px 10px;
}
QPushButton#NavButton {
    min-height: 42px;
    color: #91a0b4;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 0 13px;
    text-align: left;
    font-weight: 600;
}
QPushButton#NavButton:hover {
    color: #dce7f5;
    background: #151e2a;
}
QPushButton#NavButton:checked {
    color: #f5f8fc;
    background: #1a2940;
    border: 1px solid #2b4770;
    border-left: 3px solid #4f8cff;
    padding-left: 11px;
}
QPushButton#SidebarLink {
    min-height: 32px;
    color: #8291a5;
    background: transparent;
    border: 0;
    padding: 0 10px;
    text-align: left;
}
QPushButton#SidebarLink:hover {
    color: #c9d7e8;
    background: #151e2a;
    border-radius: 7px;
}
QFrame#TopBar {
    min-height: 62px;
    max-height: 62px;
    background: #101722;
    border: 0;
    border-bottom: 1px solid #202b3a;
}
QFrame#AboutHero {
    background: #101722;
    border: 1px solid #253143;
    border-radius: 10px;
}
QLabel#PageContext {
    color: #c7d3e2;
    font-size: 14px;
    font-weight: 600;
}
QLabel#AccountStatus {
    color: #9aa9bc;
    background: #151e2a;
    border: 1px solid #2a3749;
    border-radius: 8px;
    padding: 6px 10px;
}
QLabel#AccountStatus[state="ready"] {
    color: #6ee7b7;
    background: #10291f;
    border-color: #245a46;
}
QLabel#AccountStatus[state="checking"] {
    color: #a9c6ff;
    background: #17243a;
    border-color: #2c4d7c;
}
QLabel#AccountStatus[state="warning"] {
    color: #fcd34d;
    background: #2b2411;
    border-color: #655426;
}
QLabel#AccountStatus[state="error"] {
    color: #fca5a5;
    background: #2e171b;
    border-color: #6a3039;
}
QLabel#PageTitle {
    color: #f4f7fb;
    font-size: 24px;
    font-weight: 700;
}
QLabel#PageSubtitle {
    color: #8291a5;
    font-size: 13px;
}
QDialog QLabel#DialogTitle {
    color: #f4f7fb;
    font-size: 21px;
    font-weight: 700;
}
QDialog QLabel#DialogNotice {
    color: #aab7c8;
    background: #121923;
    border: 1px solid #253143;
    border-radius: 8px;
    padding: 12px;
}
QDialog QLabel#DialogError {
    color: #fca5a5;
    background: #2e171b;
    border: 1px solid #6a3039;
    border-radius: 8px;
    padding: 9px 11px;
}
QDialog QLineEdit#AuthCodeInput {
    min-height: 48px;
    padding: 6px 12px;
    font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 22px;
    letter-spacing: 4px;
}
QLabel#CardTitle,
QLabel#SectionTitle {
    color: #dce6f3;
    font-size: 13px;
    font-weight: 700;
}
QLabel#ResultsCount {
    color: #75869b;
    font-size: 12px;
}
QLabel#FieldLabel {
    color: #91a0b4;
    font-size: 12px;
    font-weight: 600;
}
QLabel#ProgressLabel {
    color: #cbd7e6;
    font-weight: 600;
}
QFrame#SearchCard,
QFrame#SectionPanel,
QGroupBox {
    background: #121923;
    border: 1px solid #253143;
    border-radius: 10px;
}
QGroupBox {
    margin-top: 12px;
    padding: 14px 12px 12px 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #b9c7d8;
}
QPushButton {
    min-height: 32px;
    padding: 3px 13px;
    color: #c5d1e0;
    background: #18212d;
    border: 1px solid #314055;
    border-radius: 7px;
}
QPushButton:hover {
    color: #f4f7fb;
    background: #202b3a;
    border-color: #455975;
}
QPushButton:pressed {
    background: #131b26;
}
QPushButton:disabled {
    color: #66758a;
    background: #141b24;
    border-color: #253143;
}
QPushButton[role="primary"] {
    color: #ffffff;
    background: #4f8cff;
    border-color: #4f8cff;
    font-weight: 700;
}
QPushButton[role="primary"]:hover {
    background: #679bff;
    border-color: #679bff;
}
QPushButton[role="primary"]:pressed {
    background: #3e75dc;
    border-color: #3e75dc;
}
QPushButton[role="primary"]:disabled {
    color: #66758a;
    background: #141b24;
    border-color: #253143;
}
QPushButton[role="topbar"] {
    color: #9aa9bc;
    background: transparent;
    border-color: transparent;
}
QPushButton[role="topbar"]:hover {
    color: #dce7f5;
    background: #18212d;
    border-color: #2d3b4f;
}
QPushButton[role="tableAction"] {
    min-height: 28px;
    color: #a9c6ff;
    background: #17243a;
    border-color: #2c4d7c;
    padding: 2px 12px;
    font-weight: 600;
}
QPushButton[role="tableAction"]:hover {
    color: #ffffff;
    background: #23406a;
    border-color: #4f8cff;
}
QLineEdit,
QTextEdit {
    color: #e4ebf4;
    background: #0e141d;
    border: 1px solid #2b394d;
    border-radius: 7px;
    selection-background-color: #4f8cff;
    selection-color: #ffffff;
}
QLineEdit {
    min-height: 36px;
    padding: 2px 10px;
}
QLineEdit:focus,
QTextEdit:focus {
    border: 1px solid #4f8cff;
}
QLineEdit:disabled,
QTextEdit:disabled {
    color: #6f7d90;
    background: #111720;
}
QLineEdit[technical="true"],
QTextEdit#TaskLog {
    font-family: "Cascadia Mono", Consolas, monospace;
}
QTableWidget#DataTable {
    color: #cbd6e4;
    background: #101720;
    alternate-background-color: #121a25;
    gridline-color: transparent;
    border: 1px solid #253143;
    border-radius: 9px;
    outline: 0;
}
QTableWidget#DataTable::item {
    padding: 8px 10px;
    border-bottom: 1px solid #1f2a39;
}
QTableWidget#DataTable::item:hover {
    background: #172233;
}
QTableWidget#DataTable::item:selected {
    color: #eff5ff;
    background: #1d3557;
}
QHeaderView::section {
    color: #91a0b4;
    background: #151e2a;
    border: 0;
    border-bottom: 1px solid #2a3749;
    padding: 10px;
    font-weight: 600;
}
QTableCornerButton::section {
    background: #151e2a;
    border: 0;
    border-bottom: 1px solid #2a3749;
}
QProgressBar {
    min-height: 18px;
    color: #dfe8f3;
    background: #0e141d;
    border: 1px solid #2b394d;
    border-radius: 6px;
    text-align: center;
}
QProgressBar::chunk {
    background: #4f8cff;
    border-radius: 5px;
}
QCheckBox {
    color: #aab7c8;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
}
QSplitter::handle {
    background: transparent;
    width: 10px;
}
QStatusBar {
    min-height: 26px;
    color: #7f8da1;
    background: #0d131c;
    border-top: 1px solid #202b3a;
}
QStatusBar::item {
    border: 0;
}
QStatusBar QLabel {
    color: #7f8da1;
    padding: 0 9px;
    font-family: "Cascadia Mono", Consolas, monospace;
    font-size: 10px;
}
QStatusBar QLabel#RuntimeStatus[state="checking"] {
    color: #a9c6ff;
}
QStatusBar QLabel#RuntimeStatus[state="ready"] {
    color: #6ee7b7;
}
QStatusBar QLabel#RuntimeStatus[state="error"] {
    color: #fca5a5;
}
QTabWidget::pane {
    border: 1px solid #2b394d;
    background: #121923;
}
QTabBar::tab {
    color: #8796aa;
    background: #101720;
    border: 1px solid #2b394d;
    padding: 8px 14px;
}
QTabBar::tab:selected {
    color: #ffffff;
    background: #1a2940;
    border-bottom: 2px solid #4f8cff;
}
QScrollBar:vertical {
    width: 10px;
    margin: 2px;
    background: #0e141d;
}
QScrollBar::handle:vertical {
    min-height: 28px;
    background: #344258;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #485b77;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
QToolTip {
    color: #f0f4f9;
    background: #17212e;
    border: 1px solid #3a4a62;
    padding: 5px;
}
"""
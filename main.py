#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IPA Download Tool - 桌面版
基于 ipatool 的图形化 iOS 应用下载工具
"""

import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from pathlib import Path
from ui.main_window import MainWindow


def main():
    """主函数"""
    # 启用高 DPI 缩放
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    # 创建应用
    app = QApplication(sys.argv)
    app.setApplicationName("IPA Download Tool")
    app.setOrganizationName("IPADownload")
    
    # 设置应用图标（assets/qianshu.png）
    try:
        icon_path = Path(__file__).resolve().parent / "assets" / "qianshu.png"
        if not icon_path.exists():
            # PyInstaller 运行时的临时目录
            meipass = getattr(__import__('sys'), '_MEIPASS', None)
            if meipass:
                alt = Path(meipass) / "assets" / "qianshu.png"
                if alt.exists():
                    icon_path = alt
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
    except Exception:
        pass
    
    # 创建主窗口
    window = MainWindow()
    window.show()
    
    # 运行应用
    sys.exit(app.exec())


if __name__ == '__main__':
    main()

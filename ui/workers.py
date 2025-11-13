# -*- coding: utf-8 -*-
"""
后台工作线程
"""

from PyQt6.QtCore import QThread, pyqtSignal
from typing import Optional, List, Dict
from pathlib import Path
import subprocess
import os
import json
import time

from core.ipatool import IPATool


class SearchWorker(QThread):
    """搜索工作线程"""
    
    finished = pyqtSignal(list)  # 搜索完成
    error = pyqtSignal(str)  # 错误
    
    def __init__(self, ipatool: IPATool, keyword: str, limit: int = 20):
        super().__init__()
        self.ipatool = ipatool
        self.keyword = keyword
        self.limit = limit
    
    def run(self):
        """执行搜索"""
        try:
            results = self.ipatool.search(self.keyword, self.limit)
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class DownloadWorker(QThread):
    """下载工作线程"""
    
    progress = pyqtSignal(str, int)  # 进度更新 (消息, 百分比)
    finished = pyqtSignal(str)  # 下载完成 (文件路径)
    error = pyqtSignal(str)  # 错误
    
    def __init__(
        self,
        ipatool: IPATool,
        bundle_id: Optional[str] = None,
        app_id: Optional[str] = None,
        output_path: Optional[str] = None,
        auto_purchase: bool = True
    ):
        super().__init__()
        self.ipatool = ipatool
        self.bundle_id = bundle_id
        self.app_id = app_id
        self.output_path = output_path
        self.auto_purchase = auto_purchase
    
    def run(self):
        """执行下载"""
        try:
            # 如果需要自动获取许可
            if self.auto_purchase and self.bundle_id:
                self.progress.emit("正在获取应用许可...", 10)
                purchase_result = self.ipatool.purchase(self.bundle_id)
                if not purchase_result.get('success', True):
                    # 许可获取失败可能是已经拥有，继续尝试下载
                    pass

            # 开始下载（流式输出）
            self.progress.emit("正在下载应用...", 30)

            # 组装命令参数
            args: List[str] = ['download']
            if self.bundle_id:
                args += ['--bundle-identifier', self.bundle_id]
            elif self.app_id:
                args += ['--app-id', self.app_id]
            else:
                self.error.emit('必须提供 Bundle ID 或 App ID')
                return

            if self.output_path:
                args += ['--output', self.output_path]
            if self.auto_purchase:
                args += ['--purchase']

            # 与 IPATool._execute 一致的基础参数
            base_args = [
                '--format', 'json',
                '--non-interactive',
                '--keychain-passphrase', ' '
            ]

            cmd = [self.ipatool.ipatool_path] + args + base_args

            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'

            # 启动子进程并流式读取
            # 隐藏控制台窗口（Windows）
            startupinfo = None
            creationflags = 0
            try:
                import platform as _pl
                if _pl.system() == 'Windows':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    creationflags = subprocess.CREATE_NO_WINDOW
            except Exception:
                startupinfo = None
                creationflags = 0

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
                env=env,
                startupinfo=startupinfo,
                creationflags=creationflags
            )

            collected_lines: List[str] = []
            percent = 30
            for line in proc.stdout:  # type: ignore[arg-type]
                line_strip = line.strip()
                if not line_strip:
                    continue
                collected_lines.append(line_strip)
                # 尝试从行中解析进度百分比
                updated = False
                try:
                    if '%' in line_strip:
                        # 提取诸如 "65%" 的数字
                        import re
                        m = re.search(r"(\d{1,3})%", line_strip)
                        if m:
                            pct = int(m.group(1))
                            # 将 30-95 作为下载阶段进度映射
                            percent = max(percent, min(95, 30 + int(pct * 0.65)))
                            updated = True
                except Exception:
                    pass
                if not updated:
                    # 若无法解析，缓慢推进，表示活跃
                    percent = min(95, percent + 1)
                self.progress.emit(line_strip, percent)

            returncode = proc.wait()

            # 结束后解析结果
            # 优先从收集的行中查找最后一个 JSON 对象
            result: Dict = {}
            for line in reversed(collected_lines):
                try:
                    obj = json.loads(line)
                    result = obj
                    break
                except json.JSONDecodeError:
                    continue

            if not result:
                # 回退：拼接全文并尝试切片解析
                full = "\n".join(collected_lines)
                try:
                    first = full.find('{')
                    last = full.rfind('}')
                    if first != -1 and last != -1 and last > first:
                        result = json.loads(full[first:last+1])
                except Exception:
                    pass

            if isinstance(result, dict) and result.get('success', False):
                self.progress.emit("下载完成", 100)
                if self.output_path and Path(self.output_path).exists():
                    self.finished.emit(self.output_path)
                else:
                    pattern = f"*{self.bundle_id or self.app_id}*.ipa"
                    files = list(Path('.').glob(pattern))
                    if files:
                        self.finished.emit(str(files[0].absolute()))
                    else:
                        self.finished.emit("未知位置")
            else:
                # 将子进程返回码与最后一行作为错误信息
                err = result.get('error') if isinstance(result, dict) else None
                if not err:
                    err = collected_lines[-1] if collected_lines else f"下载失败，返回码 {returncode}"
                self.error.emit(err)

        except Exception as e:
            self.error.emit(str(e))

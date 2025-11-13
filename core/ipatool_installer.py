# -*- coding: utf-8 -*-
"""
ipatool 自动安装工具
"""

import os
import sys
import zipfile
import tarfile
import platform
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from urllib.request import urlopen, Request
from urllib.error import URLError
import ssl
import json

from PyQt6.QtCore import QThread, pyqtSignal


class IPAToolInstaller(QThread):
    """ipatool 安装器"""
    
    progress = pyqtSignal(str, int)  # 进度信号 (消息, 百分比)
    finished = pyqtSignal(str)       # 完成信号 (安装路径)
    error = pyqtSignal(str)          # 错误信号 (错误信息)
    
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.temp_dir = None
    
    def run(self):
        """执行安装"""
        try:
            self.progress.emit("正在准备安装 ipatool...", 0)
            
            # 获取系统信息
            system = platform.system()
            if system not in ['Windows', 'Darwin', 'Linux']:
                raise Exception(f"不支持的操作系统: {system}")
            
            # 获取下载 URL
            version = self.config.get('ipatool_version', '2.1.3')
            url_template = self.config.get('ipatool_download_urls', {}).get(system)
            if not url_template:
                raise Exception(f"找不到 {system} 平台的下载地址")
            
            download_url = url_template.format(version=version)
            self.progress.emit(f"正在下载 ipatool v{version}...", 10)
            
            # 创建临时目录
            self.temp_dir = Path(tempfile.mkdtemp(prefix='ipatool_install_'))
            
            # 下载文件
            archive_path = self.temp_dir / f"ipatool.{'zip' if system == 'Windows' else 'tar.gz'}"
            self._download_file(download_url, archive_path)
            
            self.progress.emit("正在解压文件...", 70)
            
            # 解压文件
            bin_path = self._extract_archive(archive_path, system)
            
            # 设置执行权限 (非 Windows)
            if system != 'Windows':
                bin_path.chmod(bin_path.stat().st_mode | stat.S_IEXEC)
            
            # 保存路径到配置
            install_dir = Path.home() / '.local' / 'bin' if system != 'Windows' else Path.home() / 'AppData' / 'Local' / 'ipatool'
            install_dir.mkdir(parents=True, exist_ok=True)
            
            # 复制到目标位置
            target_path = install_dir / ('ipatool.exe' if system == 'Windows' else 'ipatool')
            shutil.copy2(bin_path, target_path)
            
            # 添加到系统 PATH (仅建议)
            self._add_to_path(install_dir)
            
            # 保存配置
            self.config.ipatool_path = str(target_path)
            
            self.progress.emit("安装完成！", 100)
            self.finished.emit(str(target_path))
            
        except Exception as e:
            self.error.emit(f"安装失败: {str(e)}")
        finally:
            # 清理临时文件
            if self.temp_dir and self.temp_dir.exists():
                shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _download_file(self, url: str, dest_path: Path):
        """下载文件"""
        try:
            # 创建不验证 SSL 的上下文
            ssl_context = ssl._create_unverified_context()
            
            # 发送请求
            req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urlopen(req, context=ssl_context) as response, open(dest_path, 'wb') as out_file:
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                block_size = 1024 * 8  # 8KB chunks
                
                while True:
                    buffer = response.read(block_size)
                    if not buffer:
                        break
                        
                    out_file.write(buffer)
                    downloaded += len(buffer)
                    
                    # 计算并发送进度
                    if total_size > 0:
                        progress = min(int((downloaded / total_size) * 60) + 10, 70)  # 10-70%
                        self.progress.emit(f"下载中... ({downloaded/1024/1024:.1f}MB/{total_size/1024/1024:.1f}MB)", progress)
        except URLError as e:
            raise Exception(f"下载失败: {str(e)}")
    
    def _extract_archive(self, archive_path: Path, system: str) -> Path:
        """解压文件"""
        extract_dir = self.temp_dir / 'extracted'
        extract_dir.mkdir(exist_ok=True)
        
        if system == 'Windows':
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            # 在 Windows 上，ipatool 是一个单独的 .exe 文件
            bin_file = next(extract_dir.glob('**/ipatool.exe'), None)
        else:
            with tarfile.open(archive_path, 'r:gz') as tar_ref:
                tar_ref.extractall(extract_dir)
            # 在 macOS/Linux 上，ipatool 是一个可执行文件
            bin_file = next(extract_dir.glob('**/ipatool'), None)
        
        if not bin_file or not bin_file.exists():
            raise Exception("解压后找不到 ipatool 可执行文件")
            
        return bin_file
    
    def _add_to_path(self, install_dir: Path):
        """将安装目录添加到系统 PATH (仅建议)"""
        system = platform.system()
        install_dir = str(install_dir.resolve())
        
        if system == 'Windows':
            # 在 Windows 上，修改用户环境变量
            try:
                import winreg
                with winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER) as hkey:
                    with winreg.OpenKey(hkey, 'Environment', 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                        try:
                            path_value, _ = winreg.QueryValueEx(key, 'Path')
                            paths = path_value.split(os.pathsep)
                            if install_dir not in paths:
                                paths.append(install_dir)
                                winreg.SetValueEx(key, 'Path', 0, winreg.REG_EXPAND_SZ, os.pathsep.join(paths))
                        except WindowsError:
                            winreg.SetValueEx(key, 'Path', 0, winreg.REG_EXPAND_SZ, install_dir)
            except Exception as e:
                print(f"警告: 无法自动添加 PATH 环境变量: {e}")
        else:
            # 在 Unix-like 系统上，修改 shell 配置文件
            shell = os.environ.get('SHELL', '')
            config_file = None
            
            if 'zsh' in shell:
                config_file = Path.home() / '.zshrc'
            elif 'bash' in shell:
                config_file = Path.home() / '.bashrc'
            
            if config_file:
                export_line = f'\nexport PATH="$PATH:{install_dir}"\n'
                # 检查是否已存在
                if config_file.exists():
                    with open(config_file, 'r') as f:
                        if export_line.strip() in f.read():
                            return
                
                # 添加 PATH
                try:
                    with open(config_file, 'a') as f:
                        f.write(f'\n# Added by IPA Download Tool\n{export_line}\n')
                except Exception as e:
                    print(f"警告: 无法自动添加 PATH 到 {config_file}: {e}")


def check_ipatool_installed(ipatool_path: str = None) -> Tuple[bool, str]:
    """
    检查 ipatool 是否已安装
    
    Returns:
        tuple: (是否已安装, 版本信息或错误信息)
    """
    try:
        import subprocess
        
        # 如果指定了路径，使用指定路径
        cmd = [ipatool_path] if ipatool_path else ['ipatool', '--version']
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            version = result.stdout.strip()
            return True, f"已安装 (版本: {version})"
        else:
            return False, f"ipatool 执行失败: {result.stderr.strip() or '未知错误'}"
            
    except FileNotFoundError:
        return False, "未找到 ipatool"
    except Exception as e:
        return False, f"检查失败: {str(e)}"

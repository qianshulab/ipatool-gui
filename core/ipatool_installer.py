# -*- coding: utf-8 -*-
"""
ipatool 自动安装工具
"""

import hashlib
import hmac
import os
import platform
import shutil
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from PyQt6.QtCore import QThread, pyqtSignal

from core.atomic_file import replace_verified
from core.config import Config
from core.ipatool_release import (
    IPATOOL_RELEASE_URLS,
    get_ipatool_release,
)
from core.redaction import safe_external_text


class IPAToolInstallError(RuntimeError):
    """ipatool 安装流程错误。"""


class IPAToolIntegrityError(IPAToolInstallError):
    """下载文件与固定摘要不一致。"""


class IPAToolInstaller(QThread):
    """ipatool 安装器"""

    MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
    
    progress = pyqtSignal(str, int)  # 进度信号 (消息, 百分比)
    succeeded = pyqtSignal(str)      # 业务成功信号 (安装路径)
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
            
            arch = self._release_arch()
            try:
                release = get_ipatool_release(system, arch)
            except ValueError as exc:
                raise IPAToolInstallError(str(exc)) from exc
            download_url = release.archive_url
            self.progress.emit(f"正在下载 ipatool v{release.version}...", 10)
            
            # 创建临时目录
            self.temp_dir = Path(tempfile.mkdtemp(prefix='ipatool_install_'))
            
            # 下载文件
            archive_suffix = '.zip' if download_url.lower().endswith('.zip') else '.tar.gz'
            archive_path = self.temp_dir / f"ipatool{archive_suffix}"
            self._download_file(
                download_url,
                archive_path,
                expected_size=release.archive_size_bytes,
            )

            self.progress.emit("正在校验下载文件完整性...", 68)
            self._verify_sha256(archive_path, release.archive_sha256)
            
            self.progress.emit("正在解压文件...", 70)
            
            # 只接受固定 Release 中唯一的预期可执行成员。
            member_metadata = release.member_metadata()
            bin_path = self._extract_archive(archive_path, system)
            self._verify_release_member(bin_path, member_metadata)
            
            # 设置执行权限 (非 Windows)
            if system != 'Windows':
                bin_path.chmod(bin_path.stat().st_mode | stat.S_IEXEC)
            
            # 保存路径到配置
            target_path = Config._managed_ipatool_path()
            install_dir = target_path.parent
            install_dir.mkdir(parents=True, exist_ok=True)
            
            # 在目标目录内暂存、复验并提交；配置失败时恢复旧安装。
            self._install_binary(
                bin_path,
                target_path,
                member_metadata,
                after_commit=lambda: setattr(
                    self.config,
                    'ipatool_path',
                    str(target_path),
                ),
            )
            
            # 添加到系统 PATH (仅建议)
            self._add_to_path(install_dir)
            
            self.progress.emit("安装完成！", 100)
            self.succeeded.emit(str(target_path))
            
        except Exception as e:
            self.error.emit(f"安装失败: {safe_external_text(e)}")
        finally:
            # 清理临时文件
            if self.temp_dir and self.temp_dir.exists():
                shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _release_arch(self) -> str:
        """将本机架构映射到 ipatool Release 资源命名"""
        machine = platform.machine().lower()
        if machine in ('amd64', 'x86_64', 'x64'):
            return 'amd64'
        if machine in ('arm64', 'aarch64'):
            return 'arm64'
        raise Exception(f"不支持的 CPU 架构: {platform.machine()}")

    def _release_member_metadata(self, system: str, arch: str | None = None) -> dict:
        """返回当前固定版本的唯一归档成员契约。"""
        arch = arch or self._release_arch()
        try:
            return get_ipatool_release(system, arch).member_metadata()
        except ValueError as exc:
            raise IPAToolInstallError(str(exc)) from exc
    
    def _download_file(
        self,
        url: str,
        dest_path: Path,
        *,
        expected_size: int | None = None,
    ):
        """下载文件"""
        try:
            parsed_url = urlparse(url)
            if (
                parsed_url.scheme != 'https'
                or (parsed_url.hostname or '').casefold() != 'github.com'
                or parsed_url.username is not None
                or parsed_url.password is not None
                or parsed_url.port not in (None, 443)
                or url not in IPATOOL_RELEASE_URLS
            ):
                raise IPAToolInstallError("ipatool 下载地址不属于固定的官方 Release")
            req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            # URL scheme, host, credentials and port are validated above.
            with urlopen(req, timeout=30) as response, open(dest_path, 'wb') as out_file:  # nosec B310
                total_size = int(response.headers.get('content-length', 0))
                if total_size > self.MAX_DOWNLOAD_BYTES:
                    raise IPAToolInstallError("下载文件超过 100 MiB 安全上限")
                if expected_size is not None and total_size not in (0, expected_size):
                    raise IPAToolIntegrityError(
                        "下载归档大小与固定 Release 元数据不匹配"
                    )
                downloaded = 0
                block_size = 1024 * 8  # 8KB chunks
                
                while True:
                    buffer = response.read(block_size)
                    if not buffer:
                        break

                    if downloaded + len(buffer) > self.MAX_DOWNLOAD_BYTES:
                        raise IPAToolInstallError("下载文件超过 100 MiB 安全上限")
                    if (
                        expected_size is not None
                        and downloaded + len(buffer) > expected_size
                    ):
                        raise IPAToolIntegrityError(
                            "下载归档超过固定 Release 大小"
                        )
                    out_file.write(buffer)
                    downloaded += len(buffer)
                    
                    # 计算并发送进度
                    if total_size > 0:
                        progress = min(int((downloaded / total_size) * 60) + 10, 70)  # 10-70%
                        self.progress.emit(f"下载中... ({downloaded/1024/1024:.1f}MB/{total_size/1024/1024:.1f}MB)", progress)
                if expected_size is not None and downloaded != expected_size:
                    raise IPAToolIntegrityError(
                        "下载归档大小与固定 Release 元数据不匹配"
                    )
        except URLError as e:
            raise Exception(f"下载失败: {str(e)}")

    def _verify_sha256(self, file_path: Path, expected_sha256: str):
        """按固定摘要校验 Release 归档，失败时停止解压和安装。"""
        digest = hashlib.sha256()
        with open(file_path, 'rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)

        actual_sha256 = digest.hexdigest()
        expected_sha256 = expected_sha256.strip().lower()
        if not hmac.compare_digest(actual_sha256, expected_sha256):
            raise IPAToolIntegrityError(
                "SHA-256 完整性校验失败："
                f"期望 {expected_sha256}，实际 {actual_sha256}"
            )

    def _verify_release_member(self, source, metadata: dict):
        """校验解压后的唯一可执行成员大小及摘要。"""
        if hasattr(source, 'read') and hasattr(source, 'seek'):
            source.seek(0, os.SEEK_END)
            actual_size = source.tell()
            source.seek(0)
            digest = hashlib.sha256()
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            source.seek(0)
            actual_sha256 = digest.hexdigest()
        else:
            file_path = Path(source)
            actual_size = file_path.stat().st_size
            digest = hashlib.sha256()
            with open(file_path, 'rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            actual_sha256 = digest.hexdigest()
        expected_size = metadata['size_bytes']
        if actual_size != expected_size:
            raise IPAToolIntegrityError(
                "解压后的 ipatool 大小不匹配："
                f"期望 {expected_size}，实际 {actual_size}"
            )
        if not hmac.compare_digest(actual_sha256, metadata['sha256']):
            raise IPAToolIntegrityError("解压后的 ipatool SHA-256 校验失败")

    def _install_binary(
        self,
        source: Path,
        target: Path,
        metadata: dict,
        after_commit=None,
    ):
        """在目标目录暂存、复验并原子替换 ipatool。"""
        descriptor, staged_name = tempfile.mkstemp(
            prefix=f'.{target.name}.',
            suffix='.tmp',
            dir=target.parent,
        )
        os.close(descriptor)
        staged_path = Path(staged_name)
        try:
            shutil.copy2(source, staged_path)
            replace_verified(
                staged_path,
                target,
                lambda stream: self._verify_release_member(stream, metadata),
                after_commit=after_commit,
            )
        finally:
            try:
                staged_path.unlink(missing_ok=True)
            except OSError:
                pass
    
    def _extract_archive(self, archive_path: Path, system: str) -> Path:
        """解压文件"""
        extract_dir = self.temp_dir / 'extracted'
        extract_dir.mkdir(exist_ok=True)
        expected_member = self._release_member_metadata(system)['path']
        
        if archive_path.name.lower().endswith('.zip'):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                self._safe_extract_zip(zip_ref, extract_dir, expected_member)
        else:
            with tarfile.open(archive_path, 'r:gz') as tar_ref:
                self._safe_extract_tar(tar_ref, extract_dir, expected_member)

        bin_file = self._archive_target(extract_dir, expected_member)
        
        if not bin_file.is_file():
            raise Exception("解压后找不到 ipatool 可执行文件")
            
        return bin_file

    @staticmethod
    def _archive_target(extract_dir: Path, member_name: str) -> Path:
        root = extract_dir.resolve()
        target = (extract_dir / member_name).resolve()
        if root != target and root not in target.parents:
            raise IPAToolInstallError("压缩包包含非法路径")
        return target

    @staticmethod
    def _validate_unique_member_names(member_names):
        """拒绝重复成员及 Windows 下等价的大小写碰撞成员。"""
        seen = set()
        for member_name in member_names:
            normalized = member_name.replace('\\', '/').casefold()
            if normalized in seen:
                raise IPAToolInstallError("压缩包包含重复或大小写碰撞的成员")
            seen.add(normalized)

    @staticmethod
    def _validate_expected_file_member(member_names, expected_member: str):
        """固定 Release 归档只允许出现唯一的预期成员。"""
        names = list(member_names)
        if names != [expected_member]:
            raise IPAToolInstallError("压缩包成员与固定 Release 清单不一致")

    def _safe_extract_zip(
        self,
        zip_ref: zipfile.ZipFile,
        extract_dir: Path,
        expected_member: str | None = None,
    ):
        """拒绝 ZIP 路径穿越和符号链接条目。"""
        members = zip_ref.infolist()
        self._validate_unique_member_names(member.filename for member in members)
        for member in members:
            self._archive_target(extract_dir, member.filename)
            file_type = (member.external_attr >> 16) & 0o170000
            if file_type == stat.S_IFLNK:
                raise IPAToolInstallError("压缩包包含不允许的链接条目")
        if expected_member:
            self._validate_expected_file_member(
                (member.filename for member in members),
                expected_member,
            )
        for member in members:
            target = self._archive_target(extract_dir, member.filename)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=False)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zip_ref.open(member, 'r') as source, target.open('xb') as destination:
                shutil.copyfileobj(source, destination)

    def _safe_extract_tar(
        self,
        tar_ref: tarfile.TarFile,
        extract_dir: Path,
        expected_member: str | None = None,
    ):
        """拒绝 tar 路径穿越、链接和设备条目。"""
        members = tar_ref.getmembers()
        self._validate_unique_member_names(member.name for member in members)
        for member in members:
            self._archive_target(extract_dir, member.name)
            if member.issym() or member.islnk():
                raise IPAToolInstallError("压缩包包含不允许的链接条目")
            if not (member.isdir() or member.isfile()):
                raise IPAToolInstallError("压缩包包含不允许的特殊条目")
        if expected_member:
            self._validate_expected_file_member(
                (member.name for member in members),
                expected_member,
            )
        for member in members:
            target = self._archive_target(extract_dir, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=False)
                continue
            source = tar_ref.extractfile(member)
            if source is None:
                raise IPAToolInstallError("无法读取压缩包文件成员")
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open('xb') as destination:
                shutil.copyfileobj(source, destination)
    
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


def check_ipatool_installed(ipatool_path: str | None = None) -> tuple[bool, str]:
    """
    检查 ipatool 是否已安装
    
    Returns:
        tuple: (是否已安装, 版本信息或错误信息)
    """
    try:
        import subprocess
        
        # 如果指定了路径，使用指定路径
        cmd = [ipatool_path, '--version'] if ipatool_path else ['ipatool', '--version']
        
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

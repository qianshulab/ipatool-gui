# -*- coding: utf-8 -*-
"""
配置管理
"""
import copy
import json
import os
import platform
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict

from core.ipatool_release import IPATOOL_VERSION


class Config:
    """配置管理类"""
    
    def __init__(self, config_file: str = 'config.json'):
        """
        初始化配置
        
        Args:
            config_file: 配置文件路径
        """
        # 默认保存到用户目录（Windows: AppData/Local/IPADownload，其他: ~/.ipadownload）
        if not config_file or config_file == 'config.json':
            if platform.system() == 'Windows':
                default_dir = Path.home() / 'AppData' / 'Local' / 'IPADownload'
            else:
                default_dir = Path.home() / '.ipadownload'
            self.config_file = default_dir / 'config.json'
        else:
            self.config_file = Path(config_file)
        self._transaction_lock = threading.RLock()
        self.config_data = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return self._migrate_config(json.load(f))
            except Exception as e:
                print(f"加载配置失败: {e}")
        
        # 返回默认配置
        return self._default_config()

    @staticmethod
    def _managed_ipatool_path() -> Path:
        """返回本应用自动安装器使用的托管 ipatool 路径。"""
        system = platform.system()
        if system == 'Windows':
            base = Path(
                os.environ.get(
                    'LOCALAPPDATA',
                    Path.home() / 'AppData' / 'Local'
                )
            )
            return base / 'ipatool' / 'ipatool.exe'
        return Path.home() / '.local' / 'bin' / 'ipatool'

    @classmethod
    def _managed_ipatool_paths(cls) -> set[Path]:
        """返回当前及历史版本曾由本应用管理的路径。"""
        home = Path.home()
        system = platform.system()
        paths = {cls._managed_ipatool_path()}
        if system == 'Windows':
            paths.add(home / 'AppData' / 'Local' / 'ipatool' / 'ipatool.exe')
        elif system == 'Darwin':
            paths.add(home / 'Library' / 'Application Support' / 'ipatool' / 'ipatool')
        else:
            paths.add(home / '.local' / 'share' / 'ipatool' / 'ipatool')
        return paths

    @classmethod
    def _is_managed_ipatool_path(cls, configured_path: str) -> bool:
        if not configured_path:
            return False
        configured = os.path.normcase(os.path.abspath(os.path.expanduser(configured_path)))
        managed_paths = {
            os.path.normcase(os.path.abspath(str(path)))
            for path in cls._managed_ipatool_paths()
        }
        return configured in managed_paths

    def _migrate_config(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """补齐用户配置，并剥离不应由配置文件控制的发布信任元数据。"""
        if not isinstance(data, dict):
            data = {}
        data = copy.deepcopy(data)
        defaults = self._default_config()

        old_version = str(data.get('ipatool_version', ''))
        old_windows_url = str(
            data.get('ipatool_download_urls', {}).get('Windows', '')
        )
        if (
            old_version not in ('', IPATOOL_VERSION)
            or 'windows-x86_64.zip' in old_windows_url
        ) and self._is_managed_ipatool_path(str(data.get('ipatool_path', ''))):
            # 旧版自动安装路径会覆盖新捆绑文件；清空后由查找器选择固定版本。
            data['ipatool_path'] = ''

        for key in (
            'ipatool_version',
            'ipatool_download_urls',
            'ipatool_sha256',
            'ipatool_release_members',
        ):
            data.pop(key, None)

        def merge_missing(target: Dict[str, Any], default: Dict[str, Any]):
            for key, value in default.items():
                if key not in target:
                    target[key] = value
                elif isinstance(target.get(key), dict) and isinstance(value, dict):
                    merge_missing(target[key], value)

        merge_missing(data, defaults)

        for key in (
            'ipatool_version',
            'ipatool_download_urls',
            'ipatool_sha256',
            'ipatool_release_members',
        ):
            data.pop(key, None)

        return data
    
    def _default_config(self) -> Dict[str, Any]:
        """默认配置"""
        return {
            'apple_id': {
                'email': '',
                'password': ''
            },
            'ipatool_path': '',
            'download_path': str(Path.home() / 'Downloads' / 'IPA'),
            'auto_purchase': True,
            'remember_credentials': False,
            'theme': 'light',
            'auto_download_ipatool': True,
        }
    
    def save(self, *, raise_on_error: bool = False) -> bool:
        """保存配置；安全敏感调用方可要求写入失败时抛出异常。"""
        with self._transaction_lock:
            return self._save_unlocked(raise_on_error=raise_on_error)

    def _save_unlocked(self, *, raise_on_error: bool = False) -> bool:
        """在调用方持有事务锁时原子写入当前候选配置。"""
        temp_path = None
        temp_fd = None
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            temp_fd, temp_name = tempfile.mkstemp(
                prefix=f'.{self.config_file.name}.',
                suffix='.tmp',
                dir=str(self.config_file.parent),
                text=True,
            )
            temp_path = Path(temp_name)
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                temp_fd = None
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.config_file)
            temp_path = None
            return True
        except Exception as e:
            if temp_fd is not None:
                try:
                    os.close(temp_fd)
                except OSError:
                    pass
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            print("Configuration save failed")
            if raise_on_error:
                raise
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        with self._transaction_lock:
            return self._get_unlocked(key, default)

    def _get_unlocked(self, key: str, default: Any = None) -> Any:
        keys = key.split('.')
        value = self.config_data
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(
        self,
        key: str,
        value: Any,
        *,
        raise_on_error: bool = True,
    ) -> bool:
        """在候选副本中设置配置项，持久化成功后才提交内存。"""
        with self._transaction_lock:
            return self._set_unlocked(
                key,
                value,
                raise_on_error=raise_on_error,
            )

    def _set_unlocked(
        self,
        key: str,
        value: Any,
        *,
        raise_on_error: bool,
    ) -> bool:
        keys = key.split('.')
        if not key or any(not part for part in keys):
            raise ValueError("配置键不能为空或包含空路径段")

        previous_data = self.config_data
        candidate_data = copy.deepcopy(previous_data)
        data = candidate_data

        for part in keys[:-1]:
            child = data.get(part)
            if child is None:
                child = {}
                data[part] = child
            elif not isinstance(child, dict):
                raise TypeError(f"配置键路径不是对象: {part}")
            data = child

        data[keys[-1]] = value
        self.config_data = candidate_data
        try:
            saved = self.save(raise_on_error=raise_on_error)
        except Exception:
            self.config_data = previous_data
            raise
        if not saved:
            self.config_data = previous_data
        return bool(saved)

    def save_apple_credentials(
        self,
        email: str,
        password: str,
        remember: bool,
        *,
        raise_on_error: bool = False,
    ):
        """在认证成功后一次性保存或清除 Apple 登录凭据。"""
        with self._transaction_lock:
            return self._save_apple_credentials_unlocked(
                email,
                password,
                remember,
                raise_on_error=raise_on_error,
            )

    def _save_apple_credentials_unlocked(
        self,
        email: str,
        password: str,
        remember: bool,
        *,
        raise_on_error: bool,
    ):
        previous_data = self.config_data
        candidate_data = copy.deepcopy(previous_data)
        candidate_data['remember_credentials'] = bool(remember)
        candidate_data['apple_id'] = {
            'email': email if remember else '',
            'password': password if remember else '',
        }
        self.config_data = candidate_data
        try:
            saved = self.save(raise_on_error=raise_on_error)
        except Exception:
            self.config_data = previous_data
            raise
        if not saved:
            self.config_data = previous_data
        return saved
    
    @property
    def apple_email(self) -> str:
        """Apple ID 邮箱"""
        return self.get('apple_id.email', '')
    
    @apple_email.setter
    def apple_email(self, value: str):
        self.set('apple_id.email', value)
    
    @property
    def apple_password(self) -> str:
        """Apple ID 密码"""
        return self.get('apple_id.password', '')
    
    @apple_password.setter
    def apple_password(self, value: str):
        self.set('apple_id.password', value)
    
    @property
    def ipatool_path(self) -> str:
        """ipatool 路径"""
        return self.get('ipatool_path', '')
    
    @ipatool_path.setter
    def ipatool_path(self, value: str):
        self.set('ipatool_path', value)
    
    @property
    def download_path(self) -> str:
        """下载路径"""
        return self.get('download_path', str(Path.home() / 'Downloads' / 'IPA'))
    
    @download_path.setter
    def download_path(self, value: str):
        self.set('download_path', value)
    
    @property
    def auto_purchase(self) -> bool:
        """自动获取许可"""
        return self.get('auto_purchase', True)
    
    @auto_purchase.setter
    def auto_purchase(self, value: bool):
        self.set('auto_purchase', value)
    
    @property
    def remember_credentials(self) -> bool:
        """记住凭据"""
        return self.get('remember_credentials', False)
    
    @remember_credentials.setter
    def remember_credentials(self, value: bool):
        self.set('remember_credentials', value)

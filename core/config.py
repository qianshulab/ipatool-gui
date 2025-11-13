# -*- coding: utf-8 -*-
"""
配置管理
"""

import json
from pathlib import Path
from typing import Dict, Any
import platform


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
        self.config_data = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"加载配置失败: {e}")
        
        # 返回默认配置
        return self._default_config()
    
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
            'auto_download_ipatool': True,  # 自动下载 ipatool
            'ipatool_version': '2.1.3',    # 默认版本
            'ipatool_download_urls': {      # 各平台下载地址模板
                'Windows': 'https://github.com/majd/ipatool/releases/download/v{version}/ipatool-{version}-windows-x86_64.zip',
                'Darwin': 'https://github.com/majd/ipatool/releases/download/v{version}/ipatool-{version}-macos-x86_64.tar.gz',
                'Linux': 'https://github.com/majd/ipatool/releases/download/v{version}/ipatool-{version}-linux-x86_64.tar.gz'
            }
        }
    
    def save(self):
        """保存配置"""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存配置失败: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        keys = key.split('.')
        value = self.config_data
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any):
        """设置配置项"""
        keys = key.split('.')
        data = self.config_data
        
        for k in keys[:-1]:
            if k not in data:
                data[k] = {}
            data = data[k]
        
        data[keys[-1]] = value
        self.save()
    
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

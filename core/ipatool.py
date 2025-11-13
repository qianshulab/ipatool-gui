# -*- coding: utf-8 -*-
"""
ipatool 命令行工具封装
"""

import os
import shutil
import sys
import json
import subprocess
import platform
from pathlib import Path
from typing import Optional, List, Dict


class IPATool:
    """ipatool 封装类"""
    
    def __init__(self, ipatool_path: Optional[str] = None):
        """
        初始化
        
        Args:
            ipatool_path: ipatool 可执行文件路径，None 则自动查找
        """
        # 若指定路径无效，则回退到自动查找（优先使用内置/打包资源）
        if ipatool_path and Path(ipatool_path).exists():
            self.ipatool_path = ipatool_path
        else:
            self.ipatool_path = self._find_ipatool()
        if not self.ipatool_path:
            raise FileNotFoundError("未找到 ipatool，请先安装 ipatool")
    
    def _find_ipatool(self) -> Optional[str]:
        """自动查找 ipatool 可执行文件"""
        # Windows 平台
        if platform.system() == 'Windows':
            def find_in_dir(d: Path) -> Optional[str]:
                try:
                    # 优先精确文件名
                    exact = d / 'ipatool.exe'
                    if exact.exists():
                        return str(exact.absolute())
                    # 兼容如 ipatool-2.2.0-windows-amd64.exe 等命名
                    for p in d.glob('ipatool*.exe'):
                        if p.is_file():
                            return str(p.absolute())
                except Exception:
                    pass
                return None

            # 1) PyInstaller 运行时临时目录
            meipass = getattr(sys, '_MEIPASS', None)
            if meipass:
                found = find_in_dir(Path(meipass))
                if found:
                    return found

            # 2) 可执行文件所在目录（打包后）
            try:
                exe_dir = Path(sys.executable).parent
                found = find_in_dir(exe_dir)
                if found:
                    return found
            except Exception:
                pass

            # 3) 项目根目录/当前目录（开发环境）
            for d in [Path('.').resolve(), Path(__file__).resolve().parents[2]]:
                found = find_in_dir(d)
                if found:
                    return found

            # 4) PATH 环境变量
            for path in os.environ.get('PATH', '').split(os.pathsep):
                d = Path(path)
                found = find_in_dir(d)
                if found:
                    return found
        
        # macOS/Linux 平台
        else:
            # 检查常见位置
            locations = [
                '/usr/local/bin/ipatool',
                '/usr/bin/ipatool',
                str(Path.home() / '.local' / 'bin' / 'ipatool'),
            ]
            
            for location in locations:
                if Path(location).exists():
                    return location
            
            # 使用 which 命令查找
            try:
                result = subprocess.run(
                    ['which', 'ipatool'],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    return result.stdout.strip()
            except Exception:
                pass
        
        return None
    
    def _execute(self, args: List[str], input_data: Optional[str] = None) -> Dict:
        """
        执行 ipatool 命令
        
        Args:
            args: 命令参数列表
            input_data: 标准输入数据
        
        Returns:
            命令执行结果
        """
        # 添加必要的参数
        base_args = [
            '--format', 'json',
            '--non-interactive',
            '--keychain-passphrase', ' '  # 空密码
        ]
        cmd = [self.ipatool_path] + args + base_args
        
        # 打印命令时隐藏敏感信息
        def _sanitize(parts: List[str]) -> List[str]:
            hidden = {'--password', '--auth-code', '--keychain-passphrase', '--email'}
            out = []
            it = iter(range(len(parts)))
            i = 0
            while i < len(parts):
                p = parts[i]
                out.append(p)
                if p in hidden and i + 1 < len(parts):
                    out.append('***')
                    i += 2
                    continue
                i += 1
            return out
        try:
            safe_cmd = _sanitize(cmd)
            print(f"Executing command: {' '.join(safe_cmd)}")
        except Exception:
            print("Executing command: [sanitized]")
        
        try:
            # 设置环境变量，强制使用UTF-8编码
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            
            # 使用二进制模式捕获输出，稍后手动解码
            # 隐藏子进程控制台窗口（Windows）
            startupinfo = None
            creationflags = 0
            if platform.system() == 'Windows':
                try:
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    creationflags = subprocess.CREATE_NO_WINDOW
                except Exception:
                    startupinfo = None
                    creationflags = 0

            result = subprocess.run(
                cmd,
                input=input_data.encode('utf-8') if input_data else None,
                capture_output=True,
                timeout=300,
                env=env,
                startupinfo=startupinfo,
                creationflags=creationflags
            )
            
            # 尝试使用utf-8解码，如果失败则使用系统默认编码
            try:
                stdout = result.stdout.decode('utf-8')
            except UnicodeDecodeError:
                stdout = result.stdout.decode('gbk', errors='ignore')
                
            try:
                stderr = result.stderr.decode('utf-8')
            except UnicodeDecodeError:
                stderr = result.stderr.decode('gbk', errors='ignore')

            # 脱敏 stdout/stderr
            import re as _re
            def _mask(text: str) -> str:
                patterns = [r'("password"\s*:\s*")([^"]*)(")', r'("email"\s*:\s*")([^"]*)(")', r'("authCode"\s*:\s*")([^"]*)(")']
                for pat in patterns:
                    text = _re.sub(pat, r'\1***\3', text, flags=_re.IGNORECASE)
                return text
            s_stdout = _mask(stdout)
            s_stderr = _mask(stderr)
            print(f"Command stdout: {s_stdout}")
            print(f"Command stderr: {s_stderr}")
            
            # 尝试解析 JSON 输出
            if stdout.strip():
                # 首先尝试直接解析整个输出
                try:
                    json_data = json.loads(stdout)
                    print(f"Successfully parsed JSON from full output")
                    return json_data
                except json.JSONDecodeError as e:
                    print(f"Failed to parse full output as JSON: {e}")
                    
                # 尝试修复常见的JSON格式错误
                try:
                    # 尝试修复未转义的引号
                    fixed_stdout = stdout.replace('"', '"').replace("'", '"')
                    json_data = json.loads(fixed_stdout)
                    print("Successfully parsed JSON after fixing quotes")
                    return json_data
                except json.JSONDecodeError:
                    pass
                    
                # 尝试提取多个 JSON 对象并取最后一个
                try:
                    candidates = []
                    # 逐行解析，收集有效 JSON
                    for line in stdout.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                            candidates.append(obj)
                        except json.JSONDecodeError:
                            continue
                    if candidates:
                        # 若前面的 JSON 行包含 metadata，则并入最后一个对象，便于上层提取详细错误
                        last_obj = candidates[-1]
                        meta_obj = None
                        for obj in reversed(candidates):
                            if isinstance(obj, dict) and 'metadata' in obj:
                                meta_obj = obj.get('metadata')
                                break
                        if isinstance(last_obj, dict) and meta_obj and 'metadata' not in last_obj:
                            try:
                                last_obj['metadata'] = meta_obj
                            except Exception:
                                pass
                        print(f"Successfully parsed JSON from {len(candidates)} lines; using last object")
                        return last_obj
                except Exception as e:
                    print(f"Failed while collecting JSON lines: {e}")
                
                # 最后回退：尝试从输出中找到第一个和最后一个大括号，解析中间内容
                try:
                    first = stdout.find('{')
                    last = stdout.rfind('}')
                    if first != -1 and last != -1 and last > first:
                        slice_text = stdout[first:last+1]
                        json_data = json.loads(slice_text)
                        print("Successfully parsed JSON from sliced stdout")
                        return json_data
                except Exception as e:
                    print(f"Failed to parse sliced stdout as JSON: {e}")
                            
                print("All JSON parsing attempts failed")
            
            # 如果有错误输出
            if stderr.strip():
                print(f"Command error: {stderr}")
                return {
                    'success': False,
                    'error': stderr,
                    'returncode': result.returncode,
                    'output': stdout
                }
            
            print(f"Command completed with return code: {result.returncode}")
            return {
                'success': result.returncode == 0,
                'output': result.stdout,
                'returncode': result.returncode
            }
        
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': '命令执行超时'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def check_auth(self) -> bool:
        """检查认证状态"""
        result = self._execute(['auth', 'info'])
        return result.get('email') is not None
    
    def login(self, email: str, password: str, auth_code: Optional[str] = None) -> Dict:
        """
        登录 Apple ID
        
        Args:
            email: Apple ID 邮箱
            password: Apple ID 密码
        
        Returns:
            登录结果
        """
        if not email or not password:
            return {'success': False, 'error': 'Email 和密码不能为空'}
            
        try:
            # 使用 --password 和 --keychain-passphrase 参数
            args = [
                'auth', 'login',
                '--email', email,
                '--password', password
            ]
            if auth_code:
                args.extend(['--auth-code', auth_code])
            result = self._execute(args)
            
            # 检查登录是否成功
            if result.get('success') or 'email' in result:
                return {'success': True, 'message': '登录成功'}
                
            # 如果登录失败，返回错误信息
            # 统一识别需要 2FA 的返回
            if isinstance(result, dict):
                msg = str(result.get('message', ''))
                err = str(result.get('error', ''))
                text = f"{msg} {err}".lower()
                if any(k in text for k in ['2fa code is required', 'verification code', 'auth code', 'two-factor', 'two factor', '需要验证码', '\u9a8c\u8bc1\u7801']):
                    return {
                        'success': False,
                        'error': msg or err or '需要二步验证码',
                        'requires_auth_code': True
                    }

            error_msg = result.get('error', '')
            if 'verification code' in error_msg or '2FA' in error_msg or 'auth code' in error_msg:
                error_msg += '\n\n提示：如果启用了双重认证，请在提示时输入最新的 6 位验证码（可在受信任设备或设置里“获取验证码”）。'
                
            # 失败时尝试 verbose 获取更多信息
            try:
                verbose_args = args + ['--verbose']
                verbose_res = self._execute(verbose_args)
            except Exception:
                verbose_res = {}
            return {
                'success': False,
                'error': error_msg or '登录失败，请检查邮箱和密码',
                'details': {
                    'message': verbose_res.get('message') if isinstance(verbose_res, dict) else '',
                    'error': verbose_res.get('error') if isinstance(verbose_res, dict) else str(verbose_res),
                    'output': verbose_res.get('output') if isinstance(verbose_res, dict) else ''
                }
            }
            
        except Exception as e:
            error_msg = str(e)
            if 'verification code' in error_msg or '2FA' in error_msg or 'auth code' in error_msg:
                error_msg += '\n\n提示：如果启用了双重认证，请在提示时输入最新的 6 位验证码（可在受信任设备或设置里“获取验证码”）。'
            return {'success': False, 'error': f'登录时发生错误: {error_msg}'}
    
    def logout(self) -> Dict:
        """注销登录"""
        return self._execute(['auth', 'revoke'])
    
    def clear_local_cache(self) -> Dict:
        """清理 ipatool 本地缓存目录 (~/.ipatool)
        Returns:
            Dict: {success: bool, removed: [paths], not_found: [paths], error?: str}
        """
        removed, not_found = [], []
        try:
            home = Path.home()
            paths = [home / '.ipatool']
            for p in paths:
                try:
                    if p.exists():
                        # 记录将要删除的内容
                        removed.append(str(p))
                        if p.is_dir():
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            try:
                                p.unlink(missing_ok=True)
                            except TypeError:
                                # Python <3.8 兼容
                                if p.exists():
                                    p.unlink()
                    else:
                        not_found.append(str(p))
                except Exception:
                    # 不因单项失败而中断
                    continue
            return {'success': True, 'removed': removed, 'not_found': not_found}
        except Exception as e:
            return {'success': False, 'error': str(e), 'removed': removed, 'not_found': not_found}
    
    def get_account_info(self) -> Dict:
        """获取账号信息"""
        return self._execute(['auth', 'info'])
    
    def search(self, keyword: str, limit: int = 10) -> List[Dict]:
        """
        搜索应用
        
        Args:
            keyword: 搜索关键词
            limit: 结果数量限制
        
        Returns:
            应用列表
        """
        try:
            print(f"Searching for: {keyword} (limit: {limit})")
            result = self._execute(['search', keyword, '--limit', str(limit)])
            
            if result is None:
                print("No result returned from _execute")
                return []
                
            print(f"Search result type: {type(result)}")
            print(f"Search result content: {result}")
            
            def extract_apps(data):
                """从不同格式的结果中提取应用列表"""
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    # 检查是否有 'apps' 或 'results' 字段
                    for key in ['apps', 'results', 'data', 'items']:
                        if key in data and isinstance(data[key], list):
                            return data[key]
                    # 如果直接是应用对象
                    if 'bundleID' in data or 'bundleId' in data or 'name' in data:
                        return [data]
                    # 如果是包含计数的结果
                    if 'count' in data and 'apps' in data and isinstance(data['apps'], list):
                        return data['apps']
                return []
            
            # 提取应用列表
            apps = extract_apps(result)
            
            if not apps:
                print("No apps found in the result")
                return []
                
            print(f"Found {len(apps)} apps in the result")
            
            # 格式化应用数据
            formatted_apps = []
            for app in apps:
                if not isinstance(app, dict):
                    print(f"Skipping non-dict app data: {app}")
                    continue
                    
                # 标准化字段名
                price_value = app.get('price', 0)
                if price_value is None:
                    price_value = 0
                
                # 格式化价格显示
                if price_value == 0:
                    formatted_price = '免费'
                else:
                    formatted_price = app.get('formattedPrice', f'${price_value:.2f}')
                
                app_data = {
                    'id': str(app.get('id', '')),
                    'bundleId': str(app.get('bundleID') or app.get('bundleId') or ''),
                    'name': str(app.get('trackName') or app.get('name') or '未知应用'),
                    'version': str(app.get('version') or '1.0'),
                    'price': price_value,
                    'formattedPrice': formatted_price,
                    'artistName': str(app.get('artistName') or app.get('sellerName') or '未知开发者'),
                    'trackName': str(app.get('trackName') or app.get('name') or ''),
                    'sellerName': str(app.get('sellerName') or app.get('artistName') or '')
                }
                
                print(f"Formatted app data: {app_data}")
                formatted_apps.append(app_data)
            
            return formatted_apps
            
        except Exception as e:
            print(f"Search exception: {str(e)}")
            import traceback
            traceback.print_exc()
            return []
    
    def _format_app(self, app_data):
        """格式化应用数据"""
        if isinstance(app_data, str):
            return {
                'name': app_data,
                'bundleId': '',
                'version': '',
                'price': 0,
                'formattedPrice': 'Free',
                'artistName': 'Unknown',
                'trackName': app_data,
                'sellerName': 'Unknown'
            }
            
        # 确保所有需要的键都存在
        return {
            'name': app_data.get('trackName') or app_data.get('name', ''),
            'bundleId': app_data.get('bundleID') or app_data.get('bundleId', ''),
            'version': app_data.get('version', ''),
            'price': app_data.get('price', 0),
            'formattedPrice': app_data.get('formattedPrice', 'Free'),
            'artistName': app_data.get('artistName', app_data.get('sellerName', 'Unknown')),
            'trackName': app_data.get('trackName', app_data.get('name', '')),
            'sellerName': app_data.get('sellerName', app_data.get('artistName', 'Unknown')),
            'original_data': app_data  # 保留原始数据
        }
    
    def purchase(self, bundle_id: str) -> Dict:
        """
        获取应用许可（购买/已购买）
        
        Args:
            bundle_id: Bundle ID
        
        Returns:
            购买结果
        """
        return self._execute(['purchase', '--bundle-identifier', bundle_id])
    
    def download(
        self,
        bundle_id: Optional[str] = None,
        app_id: Optional[str] = None,
        output_path: Optional[str] = None,
        purchase: bool = True
    ) -> Dict:
        """
        下载应用
        
        Args:
            bundle_id: Bundle ID
            app_id: App ID
            output_path: 输出路径
            purchase: 是否自动获取许可
        
        Returns:
            下载结果
        """
        args = ['download']
        
        if bundle_id:
            args.extend(['--bundle-identifier', bundle_id])
        elif app_id:
            args.extend(['--app-id', app_id])
        else:
            return {'success': False, 'error': '必须提供 Bundle ID 或 App ID'}
        
        if output_path:
            args.extend(['--output', output_path])
        
        if purchase:
            args.append('--purchase')
        
        return self._execute(args)
    
    def list_versions(self, bundle_id: str) -> List[Dict]:
        """
        列出应用版本
        
        Args:
            bundle_id: Bundle ID
        
        Returns:
            版本列表
        """
        result = self._execute(['list-versions', '--bundle-identifier', bundle_id])
        
        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and 'versions' in result:
            return result['versions']
        
        return []

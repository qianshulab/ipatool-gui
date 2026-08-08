# -*- coding: utf-8 -*-
"""
ipatool 命令行工具封装
"""

import ast
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .ipatool_release import IPATOOL_VERSION


class IPATool:
    """ipatool 封装类"""
    KEYCHAIN_PASSPHRASE = ' '
    SENSITIVE_FLAGS = {'--password', '--auth-code', '--keychain-passphrase', '--email'}
    
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
        """查找 ipatool 可执行文件"""
        system = platform.system()
        machine = platform.machine().lower()
        arch = {
            "amd64": "amd64",
            "x86_64": "amd64",
            "arm64": "arm64",
            "aarch64": "arm64",
        }.get(machine)
        platform_name = {
            "Windows": "windows",
            "Darwin": "macos",
            "Linux": "linux",
        }.get(system)

        if arch and platform_name:
            suffix = ".exe" if system == "Windows" else ""
            bundled_name = (
                f"ipatool-{IPATOOL_VERSION}-{platform_name}-{arch}{suffix}"
            )
            bundled_dirs = []
            if getattr(sys, 'frozen', False):
                bundled_dirs.extend([
                    Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent)),
                    Path(sys.executable).parent,
                ])
            elif hasattr(sys, '_MEIPASS'):
                # 测试及 PyInstaller resource discovery。
                bundled_dirs.append(Path(sys._MEIPASS))
            bundled_dirs.extend([
                Path.cwd(),
                Path(__file__).resolve().parent.parent,
            ])

            for directory in bundled_dirs:
                candidate = directory / bundled_name
                if candidate.is_file():
                    return str(candidate.absolute())

        # Windows 平台
        if system == 'Windows':
            def find_in_dir(d: Path) -> Optional[str]:
                try:
                    # 优先按文件名中的显式版本排序；无版本 ipatool.exe 作为回退。
                    candidates = [p for p in d.glob('ipatool*.exe') if p.is_file()]
                    if candidates:
                        def version_key(path: Path):
                            match = re.search(r'(\d+(?:\.\d+)+)', path.name)
                            version = tuple(int(x) for x in match.group(1).split('.')) if match else ()
                            return (1 if version else 0, version, path.stat().st_mtime)

                        return str(max(candidates, key=version_key).absolute())
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
            project_root = Path(__file__).resolve().parents[1]
            for d in [Path('.').resolve(), project_root]:
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

    def _base_args(self) -> List[str]:
        """ipatool 非交互 JSON 模式所需的全局参数"""
        return [
            '--format', 'json',
            '--non-interactive',
            '--keychain-passphrase', self.KEYCHAIN_PASSPHRASE
        ]

    def _sanitize_command(self, parts: List[str]) -> List[str]:
        """隐藏命令中的敏感参数值，避免日志泄露账号信息"""
        out = []
        i = 0
        while i < len(parts):
            part = parts[i]
            out.append(part)
            if part in self.SENSITIVE_FLAGS and i + 1 < len(parts):
                out.append('***')
                i += 2
                continue
            i += 1
        return out

    def _decode_output(self, data: bytes) -> str:
        """兼容 UTF-8 与中文 Windows 代码页输出"""
        for encoding in ('utf-8', 'gbk'):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode('utf-8', errors='ignore')

    @classmethod
    def _mask_sensitive_text(cls, text: str) -> str:
        """遮罩日志文本中的凭据、验证码、Cookie 和令牌。"""
        if not text:
            return text

        try:
            parsed_json = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            parsed_json = None
        else:
            if isinstance(parsed_json, (dict, list)):
                sanitized_json = cls._sanitize_result(parsed_json, redact_email=True)
                return json.dumps(sanitized_json, ensure_ascii=False)

        lines = text.splitlines()
        if len(lines) > 1:
            sanitized_lines = []
            found_json_event = False
            for line in lines:
                try:
                    event = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    sanitized_lines.append(cls._mask_sensitive_text(line))
                    continue
                if isinstance(event, (dict, list)):
                    found_json_event = True
                    event = cls._sanitize_result(event, redact_email=True)
                    sanitized_lines.append(json.dumps(event, ensure_ascii=False))
                else:
                    sanitized_lines.append(cls._mask_sensitive_text(line))
            if found_json_event:
                return '\n'.join(sanitized_lines)

        # Python 异常经常把嵌套 dict/list 以 repr 形式拼在诊断前缀后。
        # literal_eval 只接受字面量，不执行外部内容。
        literal_starts = [
            index
            for index, character in enumerate(text)
            if character in "{[("
        ]
        for start in literal_starts:
            try:
                parsed_literal = ast.literal_eval(text[start:].strip())
            except (SyntaxError, ValueError):
                continue
            if isinstance(parsed_literal, (dict, list, tuple, set)):
                sanitized_literal = cls._sanitize_result(
                    parsed_literal,
                    redact_email=True,
                )
                return text[:start] + repr(sanitized_literal)

        json_patterns = [
            r'("(?:password|authCode|auth_code|auth-code|keychain-passphrase|token|cookie|set-cookie|authorization)"\s*:\s*")([^"]*)(")',
            r'("email"\s*:\s*")([^"]*)(")',
        ]
        for pattern in json_patterns:
            text = re.sub(pattern, r'\1***\3', text, flags=re.IGNORECASE)

        sensitive_key = (
            r'(?:password|passwd|passphrase|auth[_-]?code|verification[_-]?code|'
            r'token|cookie|authorization|secret)'
        )
        text = re.sub(
            rf"(?i)('(?:[^']*{sensitive_key}[^']*)'\s*:\s*)'(?:\\.|[^'\\])*'",
            r"\1'***'",
            text,
        )
        text = re.sub(
            rf'(?i)("(?:[^"]*{sensitive_key}[^"]*)"\s*:\s*)"(?:\\.|[^"\\])*"',
            r'\1"***"',
            text,
        )
        text = re.sub(
            r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+',
            'Bearer ***',
            text,
        )

        text = re.sub(
            r'(--(?:password|auth-code|keychain-passphrase|email)(?:\s+|=))'
            r'("[^"]*"|\'[^\']*\'|\S+)',
            r'\1***',
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r'(?im)\b(authorization)\s*([:=]).*$',
            lambda match: f'{match.group(1)}{match.group(2)} ***',
            text,
        )
        text = re.sub(
            r'(?i)\b(set-cookie|cookie|token)\s*([:=])\s*\S+',
            lambda match: f'{match.group(1)}{match.group(2)} ***',
            text,
        )
        text = re.sub(
            r'(?i)(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])',
            '***@***',
            text,
        )
        text = re.sub(r'(?<!\d)\d{6}(?!\d)', '******', text)
        return text

    @classmethod
    def _sanitize_result(
        cls,
        result: dict[str, Any],
        redact_email: bool = False,
    ) -> Any:
        """保留认证判定字段，同时移除上游 metadata 中的秘密。"""
        sensitive_markers = (
            'password', 'passwd', 'passphrase', 'authcode',
            'verificationcode', 'token', 'cookie', 'authorization',
            'secret',
        )

        def sanitize(value, key: str = ''):
            normalized_key = re.sub(r'[^a-z0-9]', '', key.lower())
            if normalized_key == 'email' and redact_email:
                return '***@***'
            if any(marker in normalized_key for marker in sensitive_markers):
                return '***'
            if isinstance(value, dict):
                return {item_key: sanitize(item_value, str(item_key)) for item_key, item_value in value.items()}
            if isinstance(value, list):
                return [sanitize(item, key) for item in value]
            if isinstance(value, tuple):
                if len(value) == 2 and isinstance(value[0], str):
                    return (value[0], sanitize(value[1], value[0]))
                return tuple(sanitize(item, key) for item in value)
            if isinstance(value, set):
                return [sanitize(item, key) for item in value]
            if isinstance(value, str) and normalized_key != 'email':
                return cls._mask_sensitive_text(value)
            return value

        return sanitize(result)

    def _parse_json_output(self, stdout: str, stderr: str) -> dict[str, Any] | None:
        """解析 ipatool JSONL；v2.3.2 仅把 stdout 视为协议流。"""
        def parse_candidates(text: str) -> list[Any]:
            candidates: list[Any] = []
            stripped = text.strip()
            if not stripped:
                return candidates

            try:
                candidates.append(json.loads(stripped))
                return candidates
            except json.JSONDecodeError:
                pass

            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    candidates.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return candidates

        candidates = parse_candidates(stdout)
        if not candidates:
            if parse_candidates(stderr):
                return {
                    'success': False,
                    'protocol_error': True,
                    'error': 'ipatool JSON 协议事件错误地出现在 stderr',
                }
            return None

        result = candidates[-1]
        if not isinstance(result, dict):
            return {'data': result}
        result = dict(result)

        # 认证 metadata 可能在同一 JSONL 流的前一事件中。
        if 'metadata' not in result:
            for obj in reversed(candidates):
                if isinstance(obj, dict) and obj.get('metadata'):
                    result['metadata'] = obj.get('metadata')
                    break

        return result

    def _result_text(self, result: Dict[str, Any]) -> str:
        """将 ipatool 返回对象中有诊断价值的字段展开为可搜索文本"""
        parts = []
        for key in ('message', 'error', 'output'):
            value = result.get(key)
            if value:
                parts.append(str(value))

        metadata = result.get('metadata')
        if metadata:
            try:
                parts.append(json.dumps(metadata, ensure_ascii=False))
            except TypeError:
                parts.append(str(metadata))

        return '\n'.join(parts)

    def _metadata_failure_type(self, result: Dict[str, Any]) -> str:
        data = self._metadata_data(result)
        if data:
            return str(data.get('FailureType') or data.get('failureType') or '')

        metadata = result.get('metadata')
        if isinstance(metadata, dict):
            return str(metadata.get('FailureType') or metadata.get('failureType') or '')

        return ''

    def _metadata_data(self, result: Dict[str, Any]) -> Dict[str, Any]:
        metadata = result.get('metadata')
        if not isinstance(metadata, dict):
            return {}

        data = metadata.get('Data') or metadata.get('data')
        if isinstance(data, dict):
            return data

        return {}

    def _metadata_customer_message(self, result: Dict[str, Any]) -> str:
        data = self._metadata_data(result)
        return str(data.get('CustomerMessage') or data.get('customerMessage') or '')

    def _is_auth_code_required(self, text: str) -> bool:
        lowered = text.lower()
        terms = [
            '2fa code is required',
            'verification code',
            'auth code is required',
            'two-factor',
            'two factor',
            '需要验证码',
            '验证码',
            '双重认证',
        ]
        return any(term in lowered for term in terms)

    def _is_generic_login_error(self, result: Dict[str, Any]) -> bool:
        text = self._result_text(result).lower()
        terms = [
            'something went wrong',
            'unknown error occurred',
            'unknown error',
        ]
        return any(term in text for term in terms)

    def _is_temporary_login_failure(self, result: dict[str, Any]) -> bool:
        """识别 Apple 认证服务或网络的可重试故障，避免误导为 2FA。"""
        text = self._result_text(result).lower()
        terms = [
            'rate limited',
            'too many requests',
            'http 429',
            'http 500',
            'http 502',
            'http 503',
            'http 504',
            'service unavailable',
            'connection reset',
            'connection timed out',
            'request timeout',
        ]
        return any(term in text for term in terms)

    def _normalize_auth_code(self, auth_code: str | None) -> str | None:
        """规范化 Apple 6 位验证码；仅允许空格或连字符作为分隔符。"""
        if auth_code is None or not str(auth_code).strip():
            return None

        normalized = re.sub(r'[\s-]+', '', str(auth_code))
        if not re.fullmatch(r'[0-9]{6}', normalized):
            return None
        return normalized

    def _is_invalid_auth_code(self, result: Dict[str, Any], auth_code: Optional[str]) -> bool:
        if not auth_code:
            return False

        text = self._result_text(result).lower()
        failure_type = self._metadata_failure_type(result)
        if failure_type == '5005':
            return True

        terms = [
            'invalid auth code',
            'invalid verification code',
            'incorrect verification code',
            'expired verification code',
            'bad verification code',
            '验证码无效',
            '验证码错误',
            '验证码已过期',
        ]
        return any(term in text for term in terms)

    def _is_credentials_or_auth_code_error(self, result: Dict[str, Any], auth_code: Optional[str]) -> bool:
        if not auth_code:
            return False

        failure_type = self._metadata_failure_type(result)
        customer_message = self._metadata_customer_message(result).lower()
        text = self._result_text(result).lower()
        terms = [
            'mzfinance.badlogin.configurator_message',
            'bad login',
            'invalid credentials',
        ]
        return failure_type == '-5000' or any(term in customer_message or term in text for term in terms)

    def _is_invalid_credentials(self, result: Dict[str, Any]) -> bool:
        text = self._result_text(result).lower()
        failure_type = self._metadata_failure_type(result)
        terms = [
            'invalid credentials',
            'invalid username',
            'invalid password',
            'bad login',
            'apple id or password',
            '用户名或密码',
            '密码错误',
        ]
        return failure_type == '-5000' or any(term in text for term in terms)
    
    def _execute(self, args: List[str], input_data: Optional[str] = None) -> Dict:
        """
        执行 ipatool 命令
        
        Args:
            args: 命令参数列表
            input_data: 标准输入数据
        
        Returns:
            命令执行结果
        """
        cmd = [self.ipatool_path] + args + self._base_args()
        try:
            safe_cmd = self._sanitize_command(cmd)
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
            
            stdout = self._decode_output(result.stdout)
            stderr = self._decode_output(result.stderr)

            # 脱敏 stdout/stderr
            s_stdout = self._mask_sensitive_text(stdout)
            s_stderr = self._mask_sensitive_text(stderr)
            print(
                "Command completed: "
                f"returncode={result.returncode}, "
                f"stdout_present={bool(stdout.strip())}, "
                f"stderr_present={bool(stderr.strip())}"
            )
            
            parsed = self._parse_json_output(stdout, stderr)
            if parsed is not None:
                parsed['returncode'] = result.returncode
                if result.returncode != 0:
                    parsed['success'] = False
                return self._sanitize_result(parsed)

            # 非 JSON 输出也必须先脱敏，避免 GUI 日志二次泄露。
            if stderr.strip():
                return {
                    'success': False,
                    'error': s_stderr,
                    'returncode': result.returncode,
                    'output': s_stdout
                }

            if result.returncode == 0:
                return {
                    'success': False,
                    'protocol_error': True,
                    'error': 'ipatool 未返回可解析的 JSON 协议事件',
                    'output': s_stdout,
                    'returncode': result.returncode,
                }
            return {
                'success': False,
                'output': s_stdout,
                'returncode': result.returncode
            }
        
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': '命令执行超时'}
        except Exception as e:
            return {'success': False, 'error': self._mask_sensitive_text(str(e))}
    
    def check_auth(self) -> bool:
        """仅在 auth info 明确成功且退出码为 0 时确认认证状态。"""
        result = self._execute(['auth', 'info'])
        return (
            bool(result.get('email'))
            and result.get('success') is True
            and result.get('returncode') == 0
        )
    
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

        supplied_auth_code = auth_code is not None and bool(str(auth_code).strip())
        normalized_auth_code = self._normalize_auth_code(auth_code)
        if supplied_auth_code and normalized_auth_code is None:
            return {
                'success': False,
                'error': '验证码格式不正确，请输入 6 位数字。',
                'invalid_auth_code_format': True
            }
        auth_code = normalized_auth_code
            
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
            
            # ipatool 的 2FA challenge 会以 rc=0 且无 success 字段返回；
            # 只有显式 success=true 且进程 rc=0 才能判定登录成功。
            if (
                isinstance(result, dict)
                and result.get('success') is True
                and result.get('returncode') == 0
            ):
                return {
                    'success': True,
                    'message': '登录成功',
                    'email': result.get('email'),
                    'name': result.get('name')
                }
                
            if isinstance(result, dict):
                text = self._result_text(result)

                if self._is_temporary_login_failure(result):
                    return {
                        'success': False,
                        'error': 'Apple 登录服务暂时不可用，请稍后重试；无需重复获取验证码。',
                        'temporary_failure': True,
                        'details': {
                            'message': result.get('message', ''),
                            'error': result.get('error', ''),
                            'output': result.get('output', '')
                        }
                    }

                if self._is_invalid_auth_code(result, auth_code):
                    return {
                        'success': False,
                        'error': '验证码无效或已过期。请重新获取 6 位验证码后再试；如果密码也刚修改过，请同时确认 Apple ID 密码正确。',
                        'invalid_auth_code': True
                    }

                if self._is_credentials_or_auth_code_error(result, auth_code):
                    return {
                        'success': False,
                        'error': 'Apple ID 密码或验证码不正确。请重新确认密码，或重新获取最新 6 位验证码后再试。',
                        'credentials_or_auth_code_invalid': True
                    }

                if (
                    result.get('returncode') == 0
                    and self._is_auth_code_required(text)
                ):
                    return {
                        'success': False,
                        'error': '需要输入 Apple ID 的 6 位双重认证验证码。',
                        'requires_auth_code': True
                    }

                if self._is_generic_login_error(result) and auth_code:
                    return {
                        'success': False,
                        'error': 'Apple ID 密码或验证码不正确。请重新确认密码，或重新获取最新 6 位验证码后再试。',
                        'credentials_or_auth_code_invalid': True
                    }

                if self._is_invalid_credentials(result):
                    return {
                        'success': False,
                        'error': 'Apple ID 或密码不正确；如果已输入验证码，也可能是验证码已过期。',
                        'details': {
                            'message': result.get('message', ''),
                            'error': result.get('error', ''),
                            'output': result.get('output', '')
                        }
                    }

            error_msg = self._result_text(result) if isinstance(result, dict) else str(result)
            return {
                'success': False,
                'error': error_msg or '登录失败，请检查邮箱、密码和验证码',
                'details': {
                    'message': result.get('message', '') if isinstance(result, dict) else '',
                    'error': result.get('error', '') if isinstance(result, dict) else '',
                    'output': result.get('output', '') if isinstance(result, dict) else ''
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
        removed, not_found, failures = [], [], []
        try:
            home = Path.home()
            paths = [home / '.ipatool']
            for p in paths:
                try:
                    if p.exists() or p.is_symlink():
                        if p.is_symlink() or not p.is_dir():
                            p.unlink()
                        else:
                            shutil.rmtree(p)
                        if p.exists() or p.is_symlink():
                            raise OSError("删除后路径仍然存在")
                        removed.append(str(p))
                    else:
                        not_found.append(str(p))
                except Exception as exc:
                    failures.append(f"{p}: {exc}")
            result = {
                'success': not failures,
                'removed': removed,
                'not_found': not_found,
            }
            if failures:
                result['error'] = '; '.join(failures)
            return result
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
        result = self._execute(['search', keyword, '--limit', str(limit)])
        if not isinstance(result, (dict, list)):
            raise RuntimeError('搜索命令未返回有效协议结果')

        if isinstance(result, dict):
            returncode = result.get('returncode')
            failed = (
                result.get('success') is False
                or (returncode is not None and returncode != 0)
                or (bool(result.get('error')) and result.get('success') is not True)
            )
            if failed:
                diagnostic = (
                    result.get('error')
                    or result.get('message')
                    or result.get('output')
                    or '搜索命令执行失败'
                )
                raise RuntimeError(self._mask_sensitive_text(str(diagnostic)))

        def extract_apps(data):
            """从不同格式的成功结果中提取应用列表。"""
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ['apps', 'results', 'data', 'items']:
                    if key in data and isinstance(data[key], list):
                        return data[key]
                if 'bundleID' in data or 'bundleId' in data or 'name' in data:
                    return [data]
            return []

        apps = extract_apps(result)
        formatted_apps = []
        for app in apps:
            if not isinstance(app, dict):
                continue

            price_value = app.get('price', 0)
            if price_value is None:
                price_value = 0
            if price_value == 0:
                formatted_price = '免费'
            else:
                formatted_price = app.get('formattedPrice')
                if not formatted_price:
                    try:
                        formatted_price = f'${float(price_value):.2f}'
                    except (TypeError, ValueError):
                        formatted_price = str(price_value)

            formatted_apps.append({
                'id': str(app.get('id', '')),
                'bundleId': str(app.get('bundleID') or app.get('bundleId') or ''),
                'name': str(app.get('trackName') or app.get('name') or '未知应用'),
                'version': str(app.get('version') or '1.0'),
                'price': price_value,
                'formattedPrice': formatted_price,
                'artistName': str(app.get('artistName') or app.get('sellerName') or '未知开发者'),
                'trackName': str(app.get('trackName') or app.get('name') or ''),
                'sellerName': str(app.get('sellerName') or app.get('artistName') or '')
            })

        return formatted_apps
    
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

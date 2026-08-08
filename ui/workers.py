# -*- coding: utf-8 -*-
"""
后台工作线程
"""

import json
import os
import platform
import plistlib
import re
import signal
import subprocess
import tempfile
import threading
import zipfile
from contextlib import contextmanager
from pathlib import Path
from queue import Queue
from typing import Dict, List, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from core.atomic_file import replace_verified
from core.ipatool import IPATool
from core.redaction import safe_external_text


WINDOWS_CREATE_SUSPENDED = 0x00000004


class _DownloadCommitCancelled(RuntimeError):
    pass


class _IPAValidationError(RuntimeError):
    pass


def _safe_external_text(value: object) -> str:
    """外部工具内容进入 worker 状态或 Qt 信号前统一脱敏。"""
    return safe_external_text(
        value,
        fallback="ipatool 返回了无法安全显示的消息",
    )


def _safe_external_result(value: object) -> Dict:
    """复制并递归清洗外部结果，避免 worker 对象保留秘密。"""
    if isinstance(value, dict):
        return IPATool._sanitize_result(dict(value))
    return {'success': False, 'error': _safe_external_text(value)}


class AuthCheckWorker(QThread):
    """在后台获取一次认证账号信息。"""

    def __init__(self, ipatool: IPATool):
        super().__init__()
        self.ipatool = ipatool
        self.result = None
        self.error_message = None

    def run(self):
        try:
            result = self.ipatool.get_account_info()
            self.result = _safe_external_result(result)
        except Exception as exc:  # noqa: BLE001 - 外部 CLI 异常由 UI 状态统一处理
            self.error_message = _safe_external_text(exc)


class LoginWorker(QThread):
    """登录工作线程；结果在线程真正结束后由调用方读取。"""

    def __init__(
        self,
        ipatool: IPATool,
        email: str,
        password: str,
        auth_code: Optional[str] = None
    ):
        super().__init__()
        self.ipatool = ipatool
        self.email = email
        self.password = password
        self.auth_code = auth_code
        self.result = None
        self.error_message = None

    def clear_sensitive_fields(self):
        """幂等清除线程尚未启动或已经结束时持有的登录秘密。"""
        self.email = ''
        self.password = ''
        self.auth_code = None

    def run(self):
        """执行登录并在后台验证认证状态。"""
        try:
            result = self.ipatool.login(self.email, self.password, self.auth_code)
            result = _safe_external_result(result)

            if result.get('success'):
                requested_email = self.email.strip().casefold()
                account_info = None
                try:
                    account_info = _safe_external_result(
                        self.ipatool.get_account_info()
                    )
                except Exception as exc:  # noqa: BLE001 - 外部 CLI/解析异常统一映射为验证失败
                    result['verification_error'] = _safe_external_text(exc)

                verified_email = (
                    str(account_info.get('email') or '').strip()
                    if isinstance(account_info, dict)
                    else ''
                )
                account_mismatch = bool(verified_email) and (
                    verified_email.casefold() != requested_email
                )
                verified = (
                    isinstance(account_info, dict)
                    and account_info.get('success') is True
                    and account_info.get('returncode') == 0
                    and bool(verified_email)
                    and not account_mismatch
                )
                if verified:
                    result['auth_verified'] = True
                    result['email'] = verified_email
                else:
                    result.update({
                        'success': False,
                        'auth_verification_failed': True,
                        'error': '登录命令已完成，但认证状态验证失败。'
                    })
                    if account_mismatch:
                        result['auth_account_mismatch'] = True

            self.result = result
        except Exception as e:
            self.error_message = _safe_external_text(e)
        finally:
            # 登录挑战结束后不在线程对象中继续保留敏感值。
            self.clear_sensitive_fields()


class LogoutWorker(QThread):
    """在后台撤销 ipatool 认证。"""

    def __init__(self, ipatool: IPATool):
        super().__init__()
        self.ipatool = ipatool
        self.result = None
        self.error_message = None

    def run(self):
        try:
            result = self.ipatool.logout()
            self.result = _safe_external_result(result)
        except Exception as exc:  # noqa: BLE001 - 外部 CLI 异常由 UI 统一处理
            self.error_message = _safe_external_text(exc)


class ClearAuthCacheWorker(QThread):
    """在后台撤销认证并删除 ipatool 本地认证缓存。"""

    def __init__(self, ipatool: IPATool):
        super().__init__()
        self.ipatool = ipatool
        self.result = None

    def run(self):
        result = {'logout': None, 'cache': None, 'errors': []}
        try:
            result['logout'] = self.ipatool.logout()
        except Exception as exc:  # noqa: BLE001 - 尽力继续清理本地缓存
            result['errors'].append(f"撤销认证失败: {_safe_external_text(exc)}")
        try:
            result['cache'] = self.ipatool.clear_local_cache()
        except Exception as exc:  # noqa: BLE001 - 返回部分成功结果给 UI
            result['errors'].append(f"删除本地缓存失败: {_safe_external_text(exc)}")
        self.result = _safe_external_result(result)


class SearchWorker(QThread):
    """搜索工作线程"""
    
    succeeded = pyqtSignal(list)  # 搜索业务成功
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
            self.succeeded.emit(results)
        except Exception as e:
            self.error.emit(_safe_external_text(e))


class DownloadWorker(QThread):
    """下载工作线程"""
    
    progress = pyqtSignal(str, int)  # 进度更新 (消息, 百分比)
    succeeded = pyqtSignal(str)  # 下载业务成功 (文件路径)
    failed = pyqtSignal(str)  # 下载业务失败
    cancelled = pyqtSignal()  # 用户取消

    _BUNDLE_ID_PATTERN = re.compile(
        r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+\Z"
    )
    
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
        self._process: Optional[subprocess.Popen] = None
        self._process_group_id: Optional[int] = None
        self._windows_job_handle: Optional[int] = None
        self._cancel_requested = False
        self._terminal_lock = threading.Lock()
        self._terminal_state: Optional[str] = None

    @classmethod
    def is_valid_bundle_id(cls, bundle_id: object) -> bool:
        return (
            isinstance(bundle_id, str)
            and 0 < len(bundle_id) <= 255
            and cls._BUNDLE_ID_PATTERN.fullmatch(bundle_id) is not None
        )

    def cancel(self):
        """请求停止下载，并终止可能阻塞 stdout 的子进程。"""
        with self._terminal_lock:
            if self._terminal_state is not None:
                return
            self._cancel_requested = True
        self.requestInterruption()
        process = self._process
        try:
            if process is not None:
                self._terminate_process(process)
        except OSError:
            pass

    @staticmethod
    def _create_windows_job(process: subprocess.Popen) -> int:
        """创建 kill-on-close Job，并在进程仍暂停时完成关联。"""
        import ctypes
        from ctypes import wintypes

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = 0x00002000
            if not kernel32.SetInformationJobObject(
                job,
                9,
                ctypes.byref(info),
                ctypes.sizeof(info),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel32.AssignProcessToJobObject(job, int(process._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
            return int(job)
        except Exception:
            kernel32.CloseHandle(job)
            raise

    @staticmethod
    def _resume_windows_process(process_id: int) -> None:
        """恢复 CREATE_SUSPENDED 创建的唯一初始线程。"""
        import ctypes
        from ctypes import wintypes

        class THREADENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG),
                ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
        kernel32.Thread32First.restype = wintypes.BOOL
        kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
        kernel32.Thread32Next.restype = wintypes.BOOL
        kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenThread.restype = wintypes.HANDLE
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
        invalid_handle = ctypes.c_void_p(-1).value
        if not snapshot or snapshot == invalid_handle:
            raise ctypes.WinError(ctypes.get_last_error())
        thread_handle = None
        try:
            entry = THREADENTRY32()
            entry.dwSize = ctypes.sizeof(entry)
            found = kernel32.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if int(entry.th32OwnerProcessID) == int(process_id):
                    thread_handle = kernel32.OpenThread(0x0002, False, entry.th32ThreadID)
                    break
                entry.dwSize = ctypes.sizeof(entry)
                found = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        if not thread_handle:
            raise RuntimeError("无法定位暂停的下载进程线程")
        try:
            if kernel32.ResumeThread(thread_handle) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel32.CloseHandle(thread_handle)

    @staticmethod
    def _terminate_windows_job(job_handle: int) -> bool:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        return bool(kernel32.TerminateJobObject(job_handle, 1))

    @staticmethod
    def _close_windows_job(job_handle: int) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(job_handle)

    @staticmethod
    def _terminate_windows_descendants(root_pid: int) -> int:
        """即使根进程已退出，也按固定 Windows 父 PID 关系终止后代。"""
        import ctypes
        from ctypes import wintypes

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESSENTRY32W),
        ]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESSENTRY32W),
        ]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        invalid_handle = ctypes.c_void_p(-1).value
        if not snapshot or snapshot == invalid_handle:
            return 0

        parent_by_pid = {}
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                while True:
                    parent_by_pid[int(entry.th32ProcessID)] = int(
                        entry.th32ParentProcessID
                    )
                    entry.dwSize = ctypes.sizeof(entry)
                    if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                        break
        finally:
            kernel32.CloseHandle(snapshot)

        descendants = []
        frontier = {int(root_pid)}
        while frontier:
            children = {
                pid
                for pid, parent_pid in parent_by_pid.items()
                if parent_pid in frontier and pid != root_pid
            }
            children.difference_update(descendants)
            if not children:
                break
            descendants.extend(sorted(children))
            frontier = children

        terminated = 0
        for pid in reversed(descendants):
            handle = kernel32.OpenProcess(0x0001 | 0x00100000, False, pid)
            if not handle:
                continue
            try:
                if kernel32.TerminateProcess(handle, 1):
                    terminated += 1
                    kernel32.WaitForSingleObject(handle, 500)
            finally:
                kernel32.CloseHandle(handle)
        return terminated

    def _terminate_process(self, process: subprocess.Popen) -> None:
        """有界终止下载根进程及其后代，即使根进程已经退出。"""
        tree_terminated = False
        if platform.system() == 'Windows':
            job_handle = self._windows_job_handle
            if job_handle is not None:
                try:
                    tree_terminated = self._terminate_windows_job(job_handle)
                except OSError:
                    tree_terminated = False
            try:
                result = subprocess.run(
                    [
                        "taskkill.exe",
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3.0,
                    check=False,
                )
                tree_terminated = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                tree_terminated = False
            try:
                terminated = self._terminate_windows_descendants(process.pid)
                tree_terminated = tree_terminated or terminated > 0
            except (OSError, ValueError):
                pass
        else:
            try:
                process_group_id = self._process_group_id
                if process_group_id is None:
                    process_group_id = os.getpgid(process.pid)
                os.killpg(process_group_id, signal.SIGKILL)
                tree_terminated = True
            except (OSError, ProcessLookupError):
                tree_terminated = False

        if tree_terminated:
            try:
                process.wait(timeout=1.0)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=1.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            return

        try:
            parent_running = process.poll() is None
        except OSError:
            parent_running = False
        if not parent_running:
            return

        try:
            process.terminate()
            process.wait(timeout=1.0)
            return
        except subprocess.TimeoutExpired:
            pass
        except OSError:
            return

        try:
            process.kill()
        except OSError:
            return

        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=1.0)
            except (OSError, subprocess.TimeoutExpired):
                return

    def _is_cancel_requested(self) -> bool:
        with self._terminal_lock:
            return self._cancel_requested or self.isInterruptionRequested()

    def _emit_cancelled(self) -> None:
        with self._terminal_lock:
            if self._terminal_state is not None:
                return
            self._terminal_state = 'cancelled'
        self.cancelled.emit()

    def _emit_failure(self, message: object) -> None:
        with self._terminal_lock:
            if self._terminal_state is not None:
                return
            if self._cancel_requested or self.isInterruptionRequested():
                self._terminal_state = 'cancelled'
                cancelled = True
            else:
                self._terminal_state = 'failed'
                cancelled = False
        if cancelled:
            self.cancelled.emit()
        else:
            self.failed.emit(self._safe_external_text(message))

    def _emit_success(self, downloaded_file: Path) -> None:
        with self._terminal_lock:
            if self._terminal_state is not None:
                return
            if self._cancel_requested or self.isInterruptionRequested():
                self._terminal_state = 'cancelled'
                cancelled = True
            else:
                self._terminal_state = 'succeeded'
                cancelled = False
        if cancelled:
            self.cancelled.emit()
        else:
            self.progress.emit("下载完成", 100)
            self.succeeded.emit(str(downloaded_file))

    def _commit_output_and_emit_success(
        self,
        temporary_output: Path,
        final_output: Path,
    ) -> None:
        """验证 exact handle，并在线性化的取消边界内原子提交。"""

        def verify(stream) -> None:
            valid, error = self._validate_ipa(stream, self.bundle_id)
            if not valid:
                raise _IPAValidationError(error)

        @contextmanager
        def commit_guard():
            with self._terminal_lock:
                if self._terminal_state is not None:
                    raise _DownloadCommitCancelled()
                if self._cancel_requested or self.isInterruptionRequested():
                    raise _DownloadCommitCancelled()
                try:
                    yield
                except Exception:
                    raise
                else:
                    self._terminal_state = 'succeeded'

        try:
            replace_verified(
                temporary_output,
                final_output,
                verify,
                commit_guard=commit_guard,
            )
        except _DownloadCommitCancelled:
            self._emit_cancelled()
            return
        except _IPAValidationError as exc:
            self._emit_failure(exc)
            return
        except Exception as exc:
            self._emit_failure(f"无法保存下载文件：{self._safe_external_text(exc)}")
            return

        self.progress.emit("下载完成", 100)
        self.succeeded.emit(str(final_output))

    @staticmethod
    def _safe_external_text(value: object) -> str:
        """外部进程文本进入 GUI 信号前统一脱敏。"""
        return _safe_external_text(value)

    @staticmethod
    def _output_fingerprint(path: str) -> tuple[bool, tuple[int, int, int] | None]:
        """记录明确输出文件是否存在及其元数据；读取失败时保持 fail-closed。"""
        candidate = Path(path)
        try:
            if not candidate.is_file():
                return False, None
            stat = candidate.stat()
            return True, (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        except OSError:
            return True, None

    @staticmethod
    def _create_temporary_output(final_output: Path) -> Path:
        final_output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            prefix=f".{final_output.name}.",
            suffix=".part",
            dir=str(final_output.parent),
        )
        os.close(descriptor)
        return Path(name)

    @staticmethod
    def _validate_ipa(
        source,
        expected_bundle_id: Optional[str] = None,
    ) -> tuple[bool, str]:
        """验证 IPA 是含预期 Payload 应用清单的非空 ZIP。"""
        try:
            if hasattr(source, "read") and hasattr(source, "seek"):
                source.seek(0, os.SEEK_END)
                if source.tell() <= 0:
                    return False, "下载命令未生成非空 IPA 文件"
                source.seek(0)
                archive_source = source
            else:
                path = Path(source)
                if not path.is_file() or path.stat().st_size <= 0:
                    return False, "下载命令未生成非空 IPA 文件"
                archive_source = path
            with zipfile.ZipFile(archive_source, 'r') as archive:
                corrupt_member = archive.testzip()
                if corrupt_member is not None:
                    return False, "下载结果包含损坏的 IPA ZIP 成员"
                members = archive.infolist()
                if not members:
                    return False, "下载结果不是有效的非空 IPA 归档"
                app_roots = set()
                for member in members:
                    parts = member.filename.split('/')
                    if (
                        len(parts) >= 2
                        and parts[0] == 'Payload'
                        and parts[1].lower().endswith('.app')
                        and parts[1].lower() != '.app'
                    ):
                        app_roots.add('/'.join(parts[:2]))
                if not app_roots:
                    return False, "下载结果缺少 Payload 应用清单"
                if len(app_roots) != 1:
                    return False, "下载结果包含多个顶层 Payload 应用"
                app_root = next(iter(app_roots))
                info_plists = [
                    member
                    for member in members
                    if member.filename == f'{app_root}/Info.plist'
                    and not member.is_dir()
                ]
                if len(info_plists) != 1:
                    return False, "下载结果缺少唯一的顶层 Payload 应用清单"
                for member in info_plists:
                    if 0 < member.file_size <= 16 * 1024 * 1024:
                        with archive.open(member, 'r') as stream:
                            plist_bytes = stream.read()
                        try:
                            plist = plistlib.loads(plist_bytes)
                        except (
                            plistlib.InvalidFileException,
                            ValueError,
                            TypeError,
                            OverflowError,
                        ):
                            return False, "下载结果中的 Info.plist 无法解析"
                        bundle_id = plist.get('CFBundleIdentifier') if isinstance(plist, dict) else None
                        if not isinstance(bundle_id, str) or not bundle_id.strip():
                            return False, "下载结果中的 Info.plist 缺少 Bundle ID"
                        if expected_bundle_id and bundle_id != expected_bundle_id:
                            return False, "下载结果中的 Bundle ID 与请求不一致"
                        return True, ""
                return False, "下载结果中的应用清单为空或异常"
        except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError):
            return False, "下载结果不是有效的 IPA ZIP 归档"
    
    def run(self):
        """执行下载"""
        temporary_output: Optional[Path] = None
        temporary_sidecar: Optional[Path] = None
        try:
            if self._is_cancel_requested():
                self._emit_cancelled()
                return

            if self.bundle_id and not self.is_valid_bundle_id(self.bundle_id):
                self._emit_failure("Bundle ID 格式无效")
                return

            if not self.output_path:
                self._emit_failure("必须提供明确的输出路径")
                return

            final_output = Path(self.output_path)
            temporary_output = self._create_temporary_output(final_output)
            temporary_sidecar = Path(f"{temporary_output}.tmp")

            # download --purchase 在同一个可取消子进程中获取许可并下载。
            if self.auto_purchase:
                self.progress.emit("正在获取许可并下载应用（大小未知）...", -1)
            else:
                self.progress.emit("正在下载应用（大小未知）...", -1)

            # 组装命令参数
            args: List[str] = ['download']
            if self.bundle_id:
                args += ['--bundle-identifier', self.bundle_id]
            elif self.app_id:
                args += ['--app-id', self.app_id]
            else:
                self._emit_failure('必须提供 Bundle ID 或 App ID')
                return

            if temporary_output is not None:
                args += ['--output', str(temporary_output)]
            if self.auto_purchase:
                args += ['--purchase']

            # 与 IPATool._execute 一致的基础参数
            base_args = [
                '--format', 'json',
                '--non-interactive',
                '--keychain-passphrase', getattr(IPATool, 'KEYCHAIN_PASSPHRASE', ' ')
            ]

            cmd = [self.ipatool.ipatool_path] + args + base_args

            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'

            # 启动子进程并流式读取
            # 隐藏控制台窗口（Windows）
            startupinfo = None
            creationflags = 0
            start_new_session = False
            system_name = platform.system()
            if system_name == 'Windows':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                creationflags = (
                    subprocess.CREATE_NO_WINDOW
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                    | WINDOWS_CREATE_SUSPENDED
                )
            else:
                start_new_session = True

            if self._is_cancel_requested():
                self._emit_cancelled()
                return

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                universal_newlines=True,
                env=env,
                startupinfo=startupinfo,
                creationflags=creationflags,
                start_new_session=start_new_session,
            )
            if system_name == 'Windows':
                try:
                    self._windows_job_handle = self._create_windows_job(proc)
                    self._process = proc
                    self._resume_windows_process(proc.pid)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait(timeout=1.0)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    raise
            else:
                self._process_group_id = proc.pid
                self._process = proc
            if self._is_cancel_requested():
                self._terminate_process(proc)

            collected_lines: List[str] = []
            stderr_lines: List[str] = []
            stream_queue: Queue[tuple[str, Optional[str]]] = Queue()

            def drain_stream(stream_name: str, stream) -> None:
                try:
                    if stream is not None:
                        for stream_line in stream:
                            stream_queue.put((stream_name, stream_line))
                finally:
                    stream_queue.put((stream_name, None))

            readers = [
                threading.Thread(
                    target=drain_stream,
                    args=("stdout", proc.stdout),
                    daemon=True,
                ),
                threading.Thread(
                    target=drain_stream,
                    args=("stderr", proc.stderr),
                    daemon=True,
                ),
            ]
            for reader in readers:
                reader.start()

            completed_streams = set()
            while len(completed_streams) < len(readers):
                stream_name, line = stream_queue.get()
                if line is None:
                    completed_streams.add(stream_name)
                    continue

                line_strip = line.strip()
                if not line_strip:
                    continue
                if stream_name == "stderr":
                    stderr_lines.append(self._safe_external_text(line_strip))
                    stderr_lines[:] = stderr_lines[-128:]
                    continue

                collected_lines.append(line_strip)
                collected_lines[:] = collected_lines[-2048:]

            returncode = proc.wait()
            if self._is_cancel_requested():
                self._emit_cancelled()
                return

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

            if isinstance(result, dict):
                result = _safe_external_result(result)

            if returncode == 0 and isinstance(result, dict) and result.get('success', False):
                self.progress.emit("正在校验并保存 IPA（大小未知）...", -1)
                self._commit_output_and_emit_success(
                    temporary_output,
                    final_output,
                )
                if not temporary_output.exists():
                    temporary_output = None
                return
            else:
                # 将子进程返回码与最后一行作为错误信息
                err = result.get('error') if isinstance(result, dict) else None
                if not err:
                    if stderr_lines:
                        err = stderr_lines[-1]
                    elif collected_lines:
                        err = collected_lines[-1]
                    else:
                        err = f"下载失败，返回码 {returncode}"
                self._emit_failure(err)

        except Exception as e:
            self._emit_failure(e)
        finally:
            self._process = None
            self._process_group_id = None
            job_handle = self._windows_job_handle
            self._windows_job_handle = None
            if job_handle is not None:
                try:
                    self._close_windows_job(job_handle)
                except OSError:
                    pass
            for temporary_path in (temporary_output, temporary_sidecar):
                if temporary_path is None:
                    continue
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

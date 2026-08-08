# -*- coding: utf-8 -*-
"""将已验证的文件句柄原子提交到目标路径，并支持 post-commit 回滚。"""

from __future__ import annotations

import os
import stat
import uuid
from contextlib import nullcontext
from pathlib import Path
from typing import BinaryIO, Callable, ContextManager, Optional


Verifier = Callable[[BinaryIO], object]
PostCommit = Callable[[], object]
CommitGuard = Callable[[], ContextManager[None]]


class UnsafePathError(OSError):
    """目标路径含链接、reparse point 或其他不安全对象。"""


class AtomicReplaceRollbackError(RuntimeError):
    """提交失败后未能完整恢复旧目标。"""


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _same_parent(source: Path, target: Path) -> None:
    source_parent = os.path.normcase(os.path.normpath(os.fspath(source.parent)))
    target_parent = os.path.normcase(os.path.normpath(os.fspath(target.parent)))
    if source_parent != target_parent:
        raise UnsafePathError("暂存文件与目标文件必须位于同一目录")
    if source.name in ("", ".", "..") or target.name in ("", ".", ".."):
        raise UnsafePathError("文件名无效")


def _verify_stream_from_fd(fd: int, verifier: Verifier) -> None:
    duplicate = os.dup(fd)
    with os.fdopen(duplicate, "rb", closefd=True) as stream:
        verifier(stream)


def _replace_posix(
    source: Path,
    target: Path,
    verifier: Verifier,
    after_commit: Optional[PostCommit],
    commit_guard: Optional[CommitGuard],
) -> None:
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(source.parent, directory_flags)
    source_fd = None
    backup_name = f".{target.name}.{uuid.uuid4().hex}.rollback"
    backup_moved = False
    source_moved = False
    try:
        source_fd = os.open(source.name, file_flags, dir_fd=directory_fd)
        source_stat = os.fstat(source_fd)
        if not stat.S_ISREG(source_stat.st_mode):
            raise UnsafePathError("暂存产物不是普通文件")
        _verify_stream_from_fd(source_fd, verifier)

        current_stat = os.stat(
            source.name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (current_stat.st_dev, current_stat.st_ino) != (
            source_stat.st_dev,
            source_stat.st_ino,
        ):
            raise UnsafePathError("暂存产物在验证期间被替换")

        guard = commit_guard() if commit_guard is not None else nullcontext()
        with guard:
            try:
                target_stat = os.stat(
                    target.name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                target_stat = None
            if target_stat is not None:
                if not stat.S_ISREG(target_stat.st_mode):
                    raise UnsafePathError("现有目标不是普通文件")
                os.replace(
                    target.name,
                    backup_name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
                backup_moved = True

            os.replace(
                source.name,
                target.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            source_moved = True
            if after_commit is not None:
                after_commit()
            if backup_moved:
                os.unlink(backup_name, dir_fd=directory_fd)
    except Exception as original_error:
        rollback_errors = []
        if source_moved:
            try:
                os.replace(
                    target.name,
                    source.name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
            except OSError as exc:
                rollback_errors.append(exc)
        if backup_moved:
            try:
                os.replace(
                    backup_name,
                    target.name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
            except OSError as exc:
                rollback_errors.append(exc)
        if rollback_errors:
            raise AtomicReplaceRollbackError(
                "文件提交失败且旧目标未能完整恢复"
            ) from original_error
        raise
    finally:
        if source_fd is not None:
            os.close(source_fd)
        os.close(directory_fd)


def _replace_windows(
    source: Path,
    target: Path,
    verifier: Verifier,
    after_commit: Optional[PostCommit],
    commit_guard: Optional[CommitGuard],
) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    generic_read = 0x80000000
    delete_access = 0x00010000
    file_read_attributes = 0x00000080
    share_read = 0x00000001
    share_write = 0x00000002
    share_delete = 0x00000004
    open_existing = 3
    file_attribute_normal = 0x00000080
    file_attribute_directory = 0x00000010
    file_attribute_reparse_point = 0x00000400
    file_flag_backup_semantics = 0x02000000
    file_flag_open_reparse_point = 0x00200000
    file_rename_info_class = 3
    file_disposition_info_class = 4
    duplicate_same_access = 0x00000002
    invalid_handle = ctypes.c_void_p(-1).value

    class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    class FILE_RENAME_INFO(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * 1),
        ]

    class FILE_DISPOSITION_INFO(ctypes.Structure):
        _fields_ = [("DeleteFile", wintypes.BOOL)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(BY_HANDLE_FILE_INFORMATION),
    ]
    kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetFileInformationByHandle.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.DuplicateHandle.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.DuplicateHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    def close_handle(handle) -> None:
        if handle:
            kernel32.CloseHandle(handle)

    def open_handle(path: Path, access: int, share: int, flags: int):
        handle = kernel32.CreateFileW(
            os.fspath(path),
            access,
            share,
            None,
            open_existing,
            flags,
            None,
        )
        if not handle or handle == invalid_handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def file_attributes(handle) -> int:
        info = BY_HANDLE_FILE_INFORMATION()
        if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(info.dwFileAttributes)

    def rename_handle(handle, destination: Path, replace: bool) -> None:
        encoded = os.fspath(destination).encode("utf-16-le")
        size = FILE_RENAME_INFO.FileName.offset + len(encoded) + 2
        buffer = ctypes.create_string_buffer(size)
        info = FILE_RENAME_INFO.from_buffer(buffer)
        info.Flags = 1 if replace else 0
        info.RootDirectory = None
        info.FileNameLength = len(encoded)
        ctypes.memmove(
            ctypes.addressof(buffer) + FILE_RENAME_INFO.FileName.offset,
            encoded,
            len(encoded),
        )
        if not kernel32.SetFileInformationByHandle(
            handle,
            file_rename_info_class,
            buffer,
            size,
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def delete_handle(handle) -> None:
        info = FILE_DISPOSITION_INFO(True)
        if not kernel32.SetFileInformationByHandle(
            handle,
            file_disposition_info_class,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def verify_handle(handle) -> None:
        current_process = kernel32.GetCurrentProcess()
        duplicate = wintypes.HANDLE()
        if not kernel32.DuplicateHandle(
            current_process,
            handle,
            current_process,
            ctypes.byref(duplicate),
            0,
            False,
            duplicate_same_access,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        fd = None
        try:
            fd = msvcrt.open_osfhandle(
                int(duplicate.value),
                os.O_RDONLY | getattr(os, "O_BINARY", 0),
            )
        except Exception:
            close_handle(duplicate)
            raise
        with os.fdopen(fd, "rb", closefd=True) as stream:
            verifier(stream)

    directory_handles = []
    source_handle = None
    backup_handle = None
    backup_path = target.with_name(f".{target.name}.{uuid.uuid4().hex}.rollback")
    backup_moved = False
    source_moved = False
    try:
        current = Path(source.anchor)
        components = [current]
        for component in source.parent.parts[1:]:
            current = current / component
            components.append(current)
        for directory in components:
            handle = open_handle(
                directory,
                file_read_attributes,
                share_read | share_write,
                file_flag_backup_semantics | file_flag_open_reparse_point,
            )
            attributes = file_attributes(handle)
            if not attributes & file_attribute_directory:
                close_handle(handle)
                raise UnsafePathError("目标路径组件不是目录")
            if attributes & file_attribute_reparse_point:
                close_handle(handle)
                raise UnsafePathError("目标路径包含不允许的 reparse point")
            directory_handles.append(handle)

        source_handle = open_handle(
            source,
            generic_read | delete_access,
            share_read | share_write | share_delete,
            file_attribute_normal | file_flag_open_reparse_point,
        )
        source_attributes = file_attributes(source_handle)
        if source_attributes & (file_attribute_directory | file_attribute_reparse_point):
            raise UnsafePathError("暂存产物不是普通文件")
        verify_handle(source_handle)

        guard = commit_guard() if commit_guard is not None else nullcontext()
        with guard:
            try:
                backup_handle = open_handle(
                    target,
                    generic_read | delete_access,
                    share_read | share_write | share_delete,
                    file_attribute_normal | file_flag_open_reparse_point,
                )
            except FileNotFoundError:
                backup_handle = None
            if backup_handle is not None:
                target_attributes = file_attributes(backup_handle)
                if target_attributes & (
                    file_attribute_directory | file_attribute_reparse_point
                ):
                    raise UnsafePathError("现有目标不是普通文件")
                rename_handle(backup_handle, backup_path, replace=False)
                backup_moved = True

            rename_handle(source_handle, target, replace=True)
            source_moved = True
            if after_commit is not None:
                after_commit()
            if backup_handle is not None:
                delete_handle(backup_handle)
    except Exception as original_error:
        rollback_errors = []
        if source_moved:
            try:
                rename_handle(source_handle, source, replace=True)
            except OSError as exc:
                rollback_errors.append(exc)
        if backup_moved:
            try:
                rename_handle(backup_handle, target, replace=True)
            except OSError as exc:
                rollback_errors.append(exc)
        if rollback_errors:
            raise AtomicReplaceRollbackError(
                "文件提交失败且旧目标未能完整恢复"
            ) from original_error
        raise
    finally:
        close_handle(backup_handle)
        close_handle(source_handle)
        for handle in reversed(directory_handles):
            close_handle(handle)


def replace_verified(
    source: os.PathLike[str] | str,
    target: os.PathLike[str] | str,
    verifier: Verifier,
    *,
    after_commit: Optional[PostCommit] = None,
    commit_guard: Optional[CommitGuard] = None,
) -> None:
    """验证 exact source handle 后原子替换；post-commit 失败时恢复旧目标。"""
    source_path = _absolute(Path(source))
    target_path = _absolute(Path(target))
    _same_parent(source_path, target_path)
    if os.name == "nt":
        _replace_windows(
            source_path,
            target_path,
            verifier,
            after_commit,
            commit_guard,
        )
    else:
        _replace_posix(
            source_path,
            target_path,
            verifier,
            after_commit,
            commit_guard,
        )

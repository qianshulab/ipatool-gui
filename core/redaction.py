# -*- coding: utf-8 -*-
"""跨线程与 GUI 边界的统一外部文本脱敏。"""

from core.ipatool import IPATool


def safe_external_text(
    value: object,
    *,
    fallback: str = "外部工具返回了无法安全显示的消息",
) -> str:
    """把任意外部对象转换为已脱敏文本；转换失败时 fail-closed。"""
    try:
        return IPATool._mask_sensitive_text(str(value))
    except Exception:
        return fallback

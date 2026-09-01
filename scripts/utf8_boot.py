#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""utf8_boot.py — #811 CLI 入口 UTF-8 双保险（heartbeat_tick 先例推广）。

用法（入口脚本 import 后立即调用一次）：
    from utf8_boot import force_utf8
    force_utf8()

做什么：
  1. os.environ.setdefault("PYTHONUTF8", "1")——对子进程树生效（已设不覆盖）
  2. sys.stdout/stderr reconfigure(encoding="utf-8", errors="replace")——
     GBK 控制台打印中文不再 UnicodeEncodeError

不动文件 IO 默认编码（PEP 540 对已启动解释器的 open() 默认无效——
所以 P1 的显式 encoding sweep 才是文件 IO 的真保险；本模块管 stdio
与子进程树）。
"""
from __future__ import annotations

import os
import sys

_APPLIED = False


def force_utf8() -> None:
    """幂等：重复调用无副作用。任何失败静默吞（保险层永不阻塞入口）。"""
    global _APPLIED
    if _APPLIED:
        return
    _APPLIED = True
    try:
        os.environ.setdefault("PYTHONUTF8", "1")
    except Exception:  # noqa: BLE001
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

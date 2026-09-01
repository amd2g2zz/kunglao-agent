# -*- coding: utf-8 -*-
"""#863: tools/ CLI 共享 UTF-8 stdio guard（35 副本收敛单体）。

belt-and-braces：stdout+stderr reconfigure utf-8/replace；
AttributeError=3.7 前解释器、ValueError=已设自定义编码——两者均为良性 no-op。
"""
import sys


def ensure_utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

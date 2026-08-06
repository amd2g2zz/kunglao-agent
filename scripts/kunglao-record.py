#!/usr/bin/env python3
"""kunglao-record — M4 RECORD 独立 CLI 入口 (phase 5, E5.1).

用法: python kunglao-record.py <ws> --event '<json>'

实现见 scripts/kunglao_record.py — 模块名不带连字符, 供 `from kunglao_record import ...`
(frozen test tests/test_verify_record_monitor.py 直接导入).
"""
import sys

from kunglao_record import main

if __name__ == "__main__":
    sys.exit(main())

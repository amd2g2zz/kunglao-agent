#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao-verify — M3 VERIFY 独立 CLI 入口 (phase 5, E5.1).

用法: python kunglao-verify.py <ws> <fact_id> [--json]

实现见 scripts/kunglao_verify.py — 模块名不带连字符, 供 `from kunglao_verify import ...`
(frozen test tests/test_verify_record_monitor.py 直接导入).
"""
import sys

from kunglao_verify import main

if __name__ == "__main__":
    sys.exit(main())

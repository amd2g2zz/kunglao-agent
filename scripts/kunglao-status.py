#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao-status — 独立 CLI 入口 (#287 observability).

用法: python kunglao-status.py <workspace> [--no-color]

实现见 scripts/kunglao_status.py — 模块名不带连字符, 供
`from kunglao_status import render_status` (test_kunglao_status.py 直接导入).
"""
import sys

from kunglao_status import main

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao-verify — M3 VERIFY standalone CLI entry (phase 5, E5.1).

Usage: python kunglao-verify.py <ws> <fact_id> [--json]

Implementation in scripts/kunglao_verify.py — module name without hyphens,
so `from kunglao_verify import ...` works (frozen test
tests/test_verify_record_monitor.py imports it directly).
"""
import sys

from kunglao_verify import main

if __name__ == "__main__":
    sys.exit(main())

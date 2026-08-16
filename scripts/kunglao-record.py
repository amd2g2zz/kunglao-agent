#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao-record — M4 RECORD standalone CLI entry (phase 5, E5.1).

Usage: python kunglao-record.py <ws> --event '<json>'

Implementation in scripts/kunglao_record.py — module name without hyphens,
so `from kunglao_record import ...` works (frozen test
tests/test_verify_record_monitor.py imports it directly).
"""
import sys

from kunglao_record import main

if __name__ == "__main__":
    sys.exit(main())

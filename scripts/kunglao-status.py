#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao-status — standalone CLI entry (#287 observability).

Usage: python kunglao-status.py <workspace> [--no-color]

Implementation in scripts/kunglao_status.py — module name without hyphens,
so `from kunglao_status import render_status` works
(test_kunglao_status.py imports it directly).
"""
import sys

from kunglao_status import main

from _entry import run

if __name__ == "__main__":
    run(globals())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao-digest — digest mechanical-generation CLI (thin wrapper, issue #5; module: digest_build.py)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from digest_build import main  # noqa: F401 — _entry.run(globals()) resolves main from here
from _entry import run

if __name__ == "__main__":
    run(globals())

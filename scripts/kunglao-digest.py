#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao-digest — digest mechanical-generation CLI (thin wrapper, issue #5; module: digest_build.py)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from digest_build import main
if __name__ == "__main__":
    sys.exit(main())

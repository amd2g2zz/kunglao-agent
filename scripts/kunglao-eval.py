#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao-eval — eval harness CLI (thin wrapper, module见 kunglao_eval.py)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from kunglao_eval import main
if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/e2e/run.py — thin launcher for the E2E acceptance harness.

Bootstrap: make the repo's scripts/ importable (so `e2e.cli` resolves
when this file is executed directly), then delegate to e2e.cli.main().
The package carries the implementation: model (dataclasses + adjudication
tables), evidence (run-state IO), checkpoints (C1-C7 + oracle driver),
llm_faces (subprocess seam + the three LLM faces).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from e2e.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

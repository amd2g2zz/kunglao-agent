# -*- coding: utf-8 -*-
"""worker_budget — Pre+Post ToolUse hook on Agent (DESIGN §11).

#568: this file is now a thin re-export shim. The 1847-line monolith was split
into three modules (core / gates / sinks). Tests and other consumers continue
to `from worker_budget import check_priority, pre_check, ...` unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path as _P
_HERE = str(_P(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from lib_kunglao import scan_active_workers  # noqa: E402,F401  # AC-3 wiring (#444)
from worker_budget_core import *  # noqa: E402,F401,F403
from worker_budget_gates import *  # noqa: E402,F401,F403
from worker_budget_sinks import *  # noqa: E402,F401,F403

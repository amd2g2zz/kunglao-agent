# -*- coding: utf-8 -*-
"""worker_budget — Pre+Post ToolUse hook on Agent (DESIGN §11).

#568: this file is now a thin re-export shim. The 1847-line monolith was split
into three modules (core / gates / sinks). Tests and other consumers continue
to `from worker_budget import check_priority, pre_check, ...` unchanged.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path as _P
_HERE = str(_P(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from lib_kunglao import scan_active_workers  # noqa: E402,F401  # AC-3 wiring (#444)
from worker_budget_core import *  # noqa: E402,F401,F403
from worker_budget_gates import *  # noqa: E402,F401,F403
from worker_budget_sinks import *  # noqa: E402,F401,F403
from worker_budget_sinks import _resolve_paths, _run_py  # noqa: E402,F401  # underscore-prefixed names need explicit re-export (monkeypatch.setattr on wb._run_py)


# #568 regression: gate code in worker_budget_core.py resolves bare names
# (`_run_py`, `check_priority`, etc.) via its own module globals, so a
# `monkeypatch.setattr(worker_budget, '<name>', ...)` would otherwise be
# invisible to the gate. Forward shim assignments of those names back to
# their source modules so existing tests (which pre-date the refactor and
# patch `wb._run_py` / `wb.check_priority`) keep working unchanged.
_PROPAGATE_TO = {'_run_py': [sys.modules.get('worker_budget_core')],
                 '_resolve_paths': [sys.modules.get('worker_budget_sinks')],
                 'check_priority': [sys.modules.get('worker_budget_core'),
                                    sys.modules.get('worker_budget_sinks')]}
_PROPAGATE_TO = {k: [m for m in v if m is not None]
                 for k, v in _PROPAGATE_TO.items()}


class _ShimModule(type(sys.modules[__name__])):
    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for target in _PROPAGATE_TO.get(name, ()):
            setattr(target, name, value)


sys.modules[__name__].__class__ = _ShimModule


def main() -> int:
    payload = json.load(sys.stdin)
    paths = _resolve_paths(payload)
    event = payload.get('hook_event') or payload.get('hook_event_name', '')
    if 'Post' in event:
        return post_check(payload, paths)
    return pre_check(payload, paths)


if __name__ == '__main__':
    sys.exit(main())
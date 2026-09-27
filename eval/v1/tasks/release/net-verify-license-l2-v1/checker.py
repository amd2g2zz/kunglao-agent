#!/usr/bin/env python3
# checker.py — net-verify-license-l2-v1 mechanical-checker shim (#299/#332).
# Standalone entry for the task unit: delegates to the shared
# mechanical checker with this task directory. Default candidate is
# the constructed target itself (self-check); pass --candidate to
# grade an arm's re-implementation (the #236 control-arm surface).
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parents[4] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import eval_checker

if __name__ == "__main__":
    argv = sys.argv[1:]
    if not any(a == "--candidate" or a.startswith("--candidate=")
               for a in argv):
        argv += ["--candidate", str(_HERE / 'target/license_client.js')]
    raise SystemExit(eval_checker.main(["--task", str(_HERE)] + argv))

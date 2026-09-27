#!/usr/bin/env python3
# checker.py — arm-kdf-l1 mechanical-checker shim (#332).
# Standalone entry: delegates to the shared mechanical checker.
# Default candidate is the unit's reference.py (self-check);
# pass --candidate to grade an arm's re-implementation.
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
        argv += ["--candidate", str(_HERE / "reference.py")]
    raise SystemExit(eval_checker.main(["--task", str(_HERE)]
                                       + argv))

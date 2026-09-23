#!/usr/bin/env python3
# checker.py — m3-sbox-js-v1 mechanical-checker shim.
# Standalone entry: delegates to the shared mechanical checker.
# Default candidate is the unit's self-check artifact;
# pass --candidate to grade an arm's answer.
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
        argv += ["--candidate", str(_HERE / 'reference_candidate.js')]
    raise SystemExit(eval_checker.main(["--task", str(_HERE)]
                                       + argv))

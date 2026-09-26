#!/usr/bin/env bash
# correctness checks. Blocklist lives in experiments/blocklist.txt (untracked —
# banned tokens must not be committed, r1 finding 5).
set -u
cd "$(dirname "$0")"
rc=0
uv run ruff check scripts/ hooks/ 2>/dev/null || rc=1
uv run pytest tests/test_worker_budget.py tests/test_dispatch_gate_237_passthrough.py tests/test_rotation_dispatch_gate_341.py -n 4 -q || rc=1
BL=experiments/blocklist.txt
if [ ! -f "$BL" ]; then echo "DESENSITIZATION GATE UNAVAILABLE: $BL missing (fail-closed)"; exit 1; fi
if git diff HEAD --unified=0 | grep -iqf "$BL"; then echo "DESENSITIZATION FAIL (diff vs HEAD)"; rc=1; fi
if git diff --cached --unified=0 | grep -iqf "$BL"; then echo "DESENSITIZATION FAIL (staged)"; rc=1; fi
exit $rc

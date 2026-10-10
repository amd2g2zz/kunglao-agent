## Why
Live incident (7B→7C-3): the worker hand-wrote a claim-register evidence field containing an unquoted colon ("facts/F007: 0x19d68") — malformed YAML made convergence_check exit 65 (#99 CRASHED) EVERY tick; the C6 loop treats CRASHED as a non-stop decision and spun passively for ticks (no dispatch, no loud stop). Compounding: resumed runs inherit the noop-breaker count (count=8 > threshold 6 → instant BLOCKED).

## What Changes
1. Loop loud-stop: repeated consecutive CRASHED decisions stop the run with the stderr surfaced (never passive spin).
2. Resume hygiene: the resume path resets the noop-breaker counter (a resumed workspace is not a stalled workspace).
3. Write helper: scripts/ws_yaml.py — a YAML-safe get/set/del CLI for worker-writable state (register edits via safe_load/safe_dump); the worker contract's YAML-safe instruction now names the concrete tool instead of "use python3 + yaml".

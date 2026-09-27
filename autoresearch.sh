#!/usr/bin/env bash
# autoresearch benchmark: 12-unit L1 loop-arm sweep -> METRIC lines
# Runner contract (verified r1): scripts/eval_loop_runner.py --tasks <id>... --tier release
#   --wall-cap-s N --budget-usd N --out DIR. One invocation PER UNIT (verdict isolation).
# Verdict anchor: 'VERDICT' line within the unit's own output file ONLY (no cross-file grep).
set -u
cd "$(dirname "$0")"
UNITS=$(ls eval/v1/tasks/release/ | grep -E '\-l1' | sort)
N=$(echo "$UNITS" | wc -l | tr -d ' ')
[ "$N" = "12" ] || { echo "UNIT_COUNT_MISMATCH: $N"; exit 3; }
RUNS=runs/ar-sweep-$(date +%Y%m%d-%H%M%S)
mkdir -p "$RUNS"
echo "sweep dir: $RUNS"
for u in $UNITS; do
  ( uv run python scripts/eval_loop_runner.py --tasks "$u" --tier release \
      --wall-cap-s 3600 --budget-usd 15.0 --out "$RUNS/$u" \
      > "$RUNS/${u}.out" 2> "$RUNS/${u}.err"; echo "$?" > "$RUNS/${u}.rc" ) &
  while [ "$(jobs -rp | wc -l | tr -d ' ')" -ge 2 ]; do sleep 20; done
done
wait
pass=0; fail=0; decided=0
for u in $UNITS; do
  # last VERDICT line in THIS unit's own stdout; short id (dir minus -v1) also accepted
  short=${u%-v1}
  v=$(grep -E "^VERDICT " "$RUNS/${u}.out" 2>/dev/null | grep -E "($u|$short)( |$)" | tail -1 | grep -oE '(PASS|FAIL|SKIP|REFUSED)' | tail -1)
  case "$v" in
    PASS) pass=$((pass+1)); decided=$((decided+1));;
    FAIL|SKIP|REFUSED) fail=$((fail+1)); decided=$((decided+1));;  # exhausted=fail (pass@k ruling)
    *) ;;  # no verdict line = harness fault for this unit; counted undecided
  esac
done
echo "METRIC pass_at_1=$pass"
echo "METRIC fail_count=$fail"
echo "METRIC undecided=$((12-decided))"
echo "SWEEP_DIR=$RUNS"

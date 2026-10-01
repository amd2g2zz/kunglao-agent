Design (self-reviewed against #476's run_pipeline step cage and #484's verifier contract — both read):
1. Loud-stop lives in _loop_one_tick: a consecutive-crashed counter in detail; threshold via env KUNGLAO_CRASHED_STOP_N default 3; the BLOCKED record's detail embeds the convergence stdout/stderr tail from the failing CmdOutcome. Not a rule about behavior — a liveness contract (a spinning loop is broken).
2. Resume reset in cli/checkpoints resume path: zero runs/.heartbeat-noop.json count (keep hash fields).
3. ws_yaml.py: dotted-path get/set/del, safe round-trip, list-index addressing (claims.3.evidence), refuses writes that don't round-trip.

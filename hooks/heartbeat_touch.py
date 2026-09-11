#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.9.36 — heartbeat touch hook (root-cause fix for the "the whole thing is a heartbeat BUG" user report, 原文 Chinese).

Problem: heartbeat liveness depended on the ORCHESTRATOR processing the cron
/loop prompt and running `--renew`. Any busy/compacted/context-limited phase
skips the prompt -> last_tick_ts stops -> the 35-min mechanical gate in
worker_budget.py declares STALE -> every dispatch REJECTED -> slots can't be
refilled -> monitoring appears dead. The 'heartbeat stops' reports across
v1.9.12/13/18/25/26/28 were all this one root cause wearing different hats.

Fix: decouple liveness from cognition. This hook touches
`<ws>/runs/.heartbeat.json` (bumps activity_ts) on EVERY Bash/Read/Write/
Edit/Agent tool call — purely mechanical, zero thinking required. Any
tool activity = the session is alive = OBSERVABLE activity, NOT the heartbeat.
E2.3 semantic split: tick_ts (cron only, gates 35-min check) vs activity_ts (any tool, observation only). The cron
tick remains for its REAL job: reconcile/ping/verifier supervision (the
"what" — this hook proves "you're awake").

Trigger wiring: PreToolUse matcher=Bash (or any matcher covering tool use).
Registered by hook_activation.py --wire-up (v1.9.36).
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# #618: durable-sidecar access via the #671 path-hygiene authority (same
# pattern as completion_gate) — the hook lands its pulse in the #830
# append-only substrate, not just the cache file.
from _path_hygiene import (  # noqa: E402
    ensure_scripts_path, load_module_by_path, scripts_on_path)

# #863 Family F: the harness-wide time-stamp util lives in scripts/;
# reach it through the #671 path-hygiene authority (no second def).
ensure_scripts_path()
import harness_common

# #618: minimum seconds between durable sidecar appends from THIS hook —
# PreToolUse/Bash + Stop fire often; the sidecar is a liveness substrate,
# not a tool-call trace (growth stays ~cadence-shaped, not tool-shaped).
PULSE_DEDUP_SECONDS = 60


def _write_statusline_snapshot(ws: Path) -> None:
    """#212: the statusline data plane is the DEPLOYED workspace copy.

    Resolution order (each tier fail-open, each strictly more capable):

      1. ``<ws>/.claude/scripts/statusline_snapshot.py`` — THE data plane
         (workspace-relative, self-contained against skill upgrades),
         loaded by resolved path, never by sys.path order (#671/#770);
      2. the ambient scripts/ import (non-deployed hook mode);
      3. the canonical install's env via one bounded subprocess — the
         #783 deployed-mode `uv run --project <ws>` command runs on a bare
         interpreter when the workspace carries no pyproject.toml, so a
         yaml-importing data plane would silently never write. The env
         degradation lands here, in the cosmetic face, and never touches
         the heartbeat / analysis path.

    Callers wrap this — the statusline never blocks a tool call.
    """
    deployed = ws / ".claude" / "scripts" / "statusline_snapshot.py"
    if deployed.is_file():
        try:
            mod = load_module_by_path("statusline_snapshot_ws", deployed)
            mod.write_snapshot(ws)
            return
        except Exception:  # noqa: BLE001 — degrade, never block the tool
            pass
    try:
        import statusline_snapshot  # scripts/ on path via #671 boot
        statusline_snapshot.write_snapshot(ws)
        return
    except ImportError:
        pass  # bare-interpreter env (no yaml) — tier 3 below
    except Exception:  # noqa: BLE001 — statusline never blocks tools
        return
    try:
        import shutil
        import subprocess
        with scripts_on_path():
            import hook_activation
        root = hook_activation.canonical_install_root()
        uv = shutil.which("uv")
        # the CODE stays the workspace data plane (deployed copy, else the
        # skill-root script); the canonical install only supplies the ENV
        # (yaml et al.) the bare `uv run --project <ws>` interpreter lacks.
        script = deployed if deployed.is_file() \
            else root / "scripts" / "statusline_snapshot.py"
        if uv is None or not script.is_file():
            return
        subprocess.run(
            [uv, "run", "--project", str(root), "python", str(script),
             str(ws)],
            capture_output=True, timeout=60, check=False)
    except Exception:  # noqa: BLE001 — cosmetic face, never blocks tools
        pass


utc_now = harness_common.utc_now_z  # #863 Family F: single source


def main() -> int:
    # Workspace discovery: cwd is the workspace root when running under
    # Claude (Bash hooks inherit the session cwd).
    ws = Path.cwd()
    for cand in [ws, ws.parent]:
        hb = cand / "runs" / ".heartbeat.json"
        if not hb.exists():
            continue
        try:
            data = json.loads(hb.read_text(encoding="utf-8"))
            data["activity_ts"] = utc_now()
            data.setdefault("last_tick_ts", data["activity_ts"])  # legacy readers
            # F2 (#14): atomic write (tmp→replace) replaces bare write_text,
            # eliminating the RC3 concurrent race (no lost writes when the
            # orchestrator + N workers trigger this hook concurrently).
            tmp = hb.with_suffix(hb.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(hb)
            # #618: land the pulse in the durable sidecar too (same single
            # source as tick/touch — #830), deduped to 60s. Fail-open: a
            # sidecar error must never break the tool call.
            try:
                with scripts_on_path():
                    import heartbeat as hbmod
                newest = hbmod.newest_sidecar_ts(ws)
                dedup = False
                if newest:
                    ts0 = hbmod._parse_hb_ts(newest)
                    if ts0 is not None:
                        delta = (datetime.now(timezone.utc) - ts0).total_seconds()
                        dedup = 0 <= delta < PULSE_DEDUP_SECONDS
                if not dedup:
                    hbmod.append_tick_log(ws, actor="hook")
            except Exception:  # noqa: BLE001 — liveness substrate best-effort
                pass
            # #142/#212: per-tool-use statusline snapshot refresh — the v2
            # freshness contract rides the existing touch path so the
            # working-period snapshot mtime advances ~= per tool call,
            # without waiting for the 5-min tick. #212: the tick invokes the
            # DEPLOYED data plane (<ws>/.claude/scripts/) when init has
            # materialized it. Fail-open: the statusline is cosmetic and
            # must never block or fail a tool call.
            try:
                _write_statusline_snapshot(ws)
            except Exception:  # noqa: BLE001 — statusline never blocks tools
                pass
            return 0
        except Exception as exc:  # noqa: BLE001 — never break the tool call
            print(f"heartbeat_touch: heartbeat refresh failed ({exc})",
                  file=sys.stderr)
            return 0
    # No kunglao-agent workspace heartbeat file — nothing to touch, never block.
    return 0


if __name__ == "__main__":
    sys.exit(main())

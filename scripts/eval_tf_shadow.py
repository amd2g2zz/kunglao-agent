#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_tf_shadow.py — the PATH-shadow blocking mechanism (#356).

Blocked-path variants are the TF family's flexibility measurement: the
same unit, one tool mechanically blocked. Blocking is a PREPENDED SHADOW
DIR on PATH carrying a fake tool of the blocked name that fails HONESTLY:
nonzero exit, no stdout, and a distinguishable stderr marker naming the
blocked tool and the variant id. It is never a silent no-op.

ARM-AGNOSTIC WIRING (one mechanism, all three arms — the shadow travels in
the session ENVIRONMENT, so no runner code changes):

  bare / CC-default   the runner's session subprocess inherits PATH
                      (eval_control_arm.claude_prompt_executor and the
                      campaign driver pass no env= override), so exporting
                      PATH="<shadow>:$PATH" before the launch wires every
                      tool shell the session opens;
  kunglao-loop        eval_loop_runner.launch_session also inherits the
                      parent env, so the same exported PATH reaches the
                      session AND the session's child processes (the
                      loop's dispatched workers) — verified by the nested
                      test in tests/test_eval_tf_shadow_356.py;
  checker / solvers   harness-side processes take the prepended env
                      explicitly (env= kwarg).

KNOWN LIMITATION (documented honestly, flagged by the graders instead of
denied): shadowing blocks invocation BY NAME only. The real tool file
stays on disk, so (a) absolute/relative-path invocation and (b) reading a
tool's source bypass the block. The TF graders flag both faces
(bypass_detected / bypass-solved class), and F2 reports a re-route-only
headline (f2_reroute) that excludes bypass solves.

stdlib only.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# the distinguishable error marker every blocked invocation carries
SHADOW_MARKER = "KUNGLAO-TF-SHADOW"
# the file that stamps a directory AS a shadow dir (PATH-ordering
# consumers — e.g. eval_toolflex._chain_env inserting the toolbox after
# the shadow belt — need a checkable identity, not name heuristics)
SHADOW_MARKER_FILE = ".kunglao-tf-shadow"

_FAKE_TEMPLATE = """#!/usr/bin/env python3
# eval_tf_shadow fake tool (the #356 blocked-path face) — {variant}
import sys
sys.stderr.write(
    "{marker}: tool '{name}' is blocked in this variant "
    "({variant}); every invocation fails honestly.\\n")
sys.exit({rc})
"""

FAKE_EXIT_RC = 1


def build_shadow(dir_path: Path, blocks: dict[str, str]) -> Path:
    """Build the shadow dir: one honest-error fake per blocked name, plus
    the ``SHADOW_MARKER_FILE`` identity stamp.

    ``blocks`` maps tool name -> variant id (e.g. {"peek": "block-peek"}).
    Returns the shadow dir path. Idempotent: existing fakes are
    overwritten (a stale fake must never survive a re-build)."""
    shadow = Path(dir_path)
    shadow.mkdir(parents=True, exist_ok=True)
    (shadow / SHADOW_MARKER_FILE).write_text(
        "shadow dir (the #356 blocked-path face)\n", encoding="utf-8")
    for name, variant in blocks.items():
        fake = shadow / name
        fake.write_text(
            _FAKE_TEMPLATE.format(marker=SHADOW_MARKER, name=name,
                                  variant=variant, rc=FAKE_EXIT_RC),
            encoding="utf-8")
        fake.chmod(0o755)
    return shadow


def prepend_path(shadow: Path, env: dict | None = None) -> dict:
    """A NEW env dict with the shadow dir FIRST on PATH.

    Immutable: the caller's dict is never mutated and never escapes into
    the returned one by reference for PATH. ``env=None`` inherits the
    process environment (the arm-agnostic wiring face: runners that pass
    no env= override see exactly this)."""
    base = dict(os.environ) if env is None else dict(env)
    old = base.get("PATH", "")
    base["PATH"] = (str(shadow) + os.pathsep + old) if old else str(shadow)
    return base


def which_in_env(name: str, env: dict) -> str | None:
    """shutil.which against an EXPLICIT env (the stdlib face consults the
    process env only) — the PATH-resolution face the tests pin."""
    return shutil.which(name, path=env.get("PATH", ""))


def invoke_via_path(name: str, env: dict) -> tuple[int, str, str]:
    """Invoke ``name`` the way a session shell would (PATH lookup, no
    absolute path) and return (rc, stdout, stderr)."""
    resolved = which_in_env(name, env)
    if resolved is None:
        return 127, "", f"{name}: not found on PATH\n"
    proc = subprocess.run([resolved], capture_output=True, text=True,
                          env=env, timeout=60)
    return proc.returncode, proc.stdout, proc.stderr


def verify_shadow(name: str, shadow: Path, env: dict) -> dict:
    """Mint-time face: the blocked name must fail with the marker through
    a PATH lookup under the prepended env."""
    rc, out, err = invoke_via_path(name, env)
    return {"rc": rc, "marker": SHADOW_MARKER in err,
            "stdout_empty": out == "", "stderr_tail": err[-400:]}

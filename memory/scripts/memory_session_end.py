"""SessionEnd hook entry point - invokes forget.py decay+prune, then forces
a final distill.py pass regardless of threshold (cleanup).

Wire-up in `~/.claude/settings.json`:

  "hooks": {
    "SessionEnd": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python C:/Users/hr/.claude/skills/kunglao-agent/memory/scripts/memory_session_end.py"
          }
        ]
      }
    ]
  }

Behavior:
  - forget.py decay       - gentle confidence decay for stale entries
  - forget.py prune       - archive superseded / no-citation entries
  - distill.py --force    - final distill regardless of staging count
  - All output to stdout (claude Code logs hook output; doesn't block session end)
  - Exit 0 always (session end is a recovery phase, not a gate)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

MEMORY_SCRIPTS = Path(r"C:/Users/hr/.claude/skills/kunglao-agent/memory/scripts")
FORGET = MEMORY_SCRIPTS / "forget.py"
DISTILL = MEMORY_SCRIPTS / "distill.py"


def run(label: str, cmd: list) -> int:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    print(f"--- {label} (rc={proc.returncode}) ---")
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr, end="")
    return proc.returncode


def main() -> int:
    print("[kunglao-agent memory] SessionEnd hook: forgetting + distilling")
    run("forget decay", ["python", str(FORGET), "decay"])
    run("forget prune", ["python", str(FORGET), "prune"])
    run("distill --force", ["python", str(DISTILL), "--force"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""SessionStart hook entry point - invokes recall.py and emits the recalled
rules block to stdout (which Claude Code captures as additional context).

Wire-up in `~/.claude/settings.json`:

  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python <skill_root>/memory/scripts/memory_session_start.py"
          }
        ]
      }
    ]
  }

Behavior:
  - Read task_spec.yaml (if exists) for keywords
  - Invoke recall.py --context '<derived from task_spec>'
  - Emit markdown block to stdout (claude Code captures as additional context)
  - Exit 0 always (don't block session)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

RECALL_SCRIPT = Path(__file__).resolve().parent / "recall.py"  # kunglao-agent/memory/scripts/
DEFAULT_TOP_K = 5
TASK_SPEC_LOCATIONS = [
    Path.cwd() / "task_spec.yaml",
    Path.cwd() / "malware-analysis-workspace" / "task_spec.yaml",
    Path.home() / ".claude" / "skills" / "kunglao-agent" / "templates" / "task_spec.yaml",
]


def extract_keywords_from_task_spec() -> str:
    for p in TASK_SPEC_LOCATIONS:
        if p.exists():
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            words = re.findall(r"\w{4,}", text.lower())
            seen = set()
            uniq = []
            for w in words:
                if w not in seen:
                    seen.add(w)
                    uniq.append(w)
            return " ".join(uniq[:50])
    return ""


def main() -> int:
    keywords = extract_keywords_from_task_spec()
    ctx = {"task_spec_keywords": keywords, "active_tags": []}
    ctx_json = json.dumps(ctx)

    proc = subprocess.run(
        ["python", str(RECALL_SCRIPT), "--top-k", str(DEFAULT_TOP_K), "--context", ctx_json],
        capture_output=True, text=True, encoding="utf-8",
    )
    block = proc.stdout.strip()

    if block:
        print("[kunglao-agent memory] Recalling long-term rules from previous sessions:")
        print()
        print(block)
        if proc.returncode != 0:
            print(f"[kunglao-agent memory] recall.py exited with code {proc.returncode}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
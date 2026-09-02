# -*- coding: utf-8 -*-
"""#699: kunglao_log events carry an execution channel.

Issue #699 (kunglao-lab dogfooding): remote execution via ssh left ZERO
trace in runs/logs/kunglao-*.jsonl — a local run and a remote run are
byte-indistinguishable, so post-hoc audit ("was this evidence computed
here or on the VM?") is impossible. The fix is the #818 additive-field
pattern: emit() gains an optional ``channel`` kwarg, defaulting to the
KUNGLAO_CHANNEL env var (the #698 FINALIZED vocabulary: ssh|docker|vmr|
adb|local, + mcp special), falling back to ``local``.

Legacy rows (pre-#699) lack the key entirely; readers use .get() — the
acceptance criterion is "old workspace reads must not explode".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from kunglao_log import emit, log_path  # noqa: E402


def _rows(p: Path) -> list[dict]:
    return [json.loads(line) for line in
            p.read_text(encoding="utf-8").strip().splitlines() if line.strip()]


def test_emit_row_has_channel_key(tmp, monkeypatch):
    """Every new event row carries a channel key (additive field, #818)."""
    monkeypatch.delenv("KUNGLAO_CHANNEL", raising=False)
    emit(tmp, actor="worker", action="tool_call", tool="gdb")
    ev = _rows(log_path(tmp))[0]
    assert "channel" in ev, f"channel key missing: {sorted(ev)}"
    assert ev["channel"] == "local"


def test_emit_channel_defaults_from_kunglao_channel_env(tmp, monkeypatch):
    """KUNGLAO_CHANNEL env (the #698 contract vocabulary) is the default
    source; no explicit kwarg needed for workers running under a channel."""
    monkeypatch.setenv("KUNGLAO_CHANNEL", "ssh")
    emit(tmp, actor="worker", action="tool_call", tool="ghidra")
    ev = _rows(log_path(tmp))[0]
    assert ev["channel"] == "ssh"


def test_emit_explicit_channel_wins_over_env(tmp, monkeypatch):
    """Explicit kwarg beats env — a worker relaying through a specific
    endpoint (ssh:9876) stamps the precise channel, not the session default."""
    monkeypatch.setenv("KUNGLAO_CHANNEL", "vmr")
    emit(tmp, actor="worker", action="tool_call", tool="gdb",
         channel="ssh:9876")
    ev = _rows(log_path(tmp))[0]
    assert ev["channel"] == "ssh:9876"


def test_legacy_row_without_channel_reads_clean(tmp):
    """Acceptance: old workspace (rows without the key) must not explode
    for .get()-style consumers — the gap IS the un-tagged rate signal."""
    p = log_path(tmp)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"ts": "2026-08-25T00:00:00Z", "actor": "worker-3",
                    "action": "tool_call", "claim": "C-12", "tool": "gdb",
                    "artifact": None, "duration_ms": 10, "exit": 0,
                    "detail": None, "arm": None, "epoch": None,
                    "hypothesis_ref": None, "matched_rule": None,
                    "trace_id": None, "version": None}) + "\n",
        encoding="utf-8")
    rows = _rows(p)
    assert rows[0].get("channel", "local") == "local"


def test_resume_brief_summarizes_execution_surfaces(tmp, monkeypatch):
    """Acceptance: resume brief / digest summarizes the execution surfaces
    used by the run (per-channel event counts, #699)."""
    monkeypatch.delenv("KUNGLAO_CHANNEL", raising=False)
    emit(tmp, actor="worker", action="tool_call", tool="gdb")            # local
    emit(tmp, actor="worker", action="tool_call", tool="gdb",
         channel="ssh:9876")
    emit(tmp, actor="worker", action="artifact_written",
         artifact="facts/F1.md", channel="ssh:9876")

    import digest_build
    digest = digest_build.build_digest(tmp)
    assert "sec_h" in digest, "execution-surface section missing from digest"
    # per-channel counts appear in the section
    assert "local" in digest and "ssh:9876" in digest
    assert "2" in digest  # the ssh:9876 count row


def test_resume_brief_empty_ledger_no_sec_h(tmp, monkeypatch):
    """No events → no sec_h section (build_sec_g precedent: empty → absent,
    pre-#699 workspaces keep their exact digest shape)."""
    monkeypatch.delenv("KUNGLAO_CHANNEL", raising=False)
    import digest_build
    digest = digest_build.build_digest(tmp)
    assert "sec_h" not in digest

# -*- coding: utf-8 -*-
"""Issue 340 scope A — blocker schema v2 + write-side evidence gate.

Contract under test:
  A1. A blockers/*.md write carrying an environment-capability attribution
      ("no root", "unavailable", ...) WITHOUT non-empty probe_evidence is
      REJECTED at write time by hooks/write_guard.py (rc=2). Error text
      alone is never sufficient evidence.
  A2. The same blocker WITH probe-evidence bytes passes (rc=0).
  A3. Non-env blockers (B1a infra / B2 user-stop / orphan) pass — the gate
      keys on the attribution phrasing, not on the directory.
  A4. Legacy-shape blockers are REJECTED on write (no-backcompat ruling
      2026-09-01) — no compat shims.
  A5. observed / attributed / expires parse mechanically (schema lint).

Fixture style mirrors tests/test_write_guard_532.py: a REAL synthetic
workspace on disk (tmp_path) + a subprocess run of the hook — never a
gate-mock.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import blocker_lint  # noqa: E402

WRITE_GUARD = ROOT / "hooks" / "write_guard.py"
RC_ALLOW = 0
RC_BLOCK = 2


def _mk_ws(tmp_path: Path) -> Path:
    """Minimal kunglao workspace the hook's workspace resolver accepts."""
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "notes").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    (ws / "blockers").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "  - id: C-001\n"
        "    status: OPEN\n"
        "    statement: sample resolves imports dynamically\n",
        encoding="utf-8")
    (ws / "analysis_state.txt").write_text("kunglao workspace\n", encoding="utf-8")
    return ws


def _payload(ws: Path, tool: str, file_path: Path, **tool_input) -> str:
    return json.dumps({
        "tool_name": tool,
        "cwd": str(ws),
        "tool_input": {"file_path": str(file_path), **tool_input},
    }, ensure_ascii=False)


def _run_guard(ws: Path, payload: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(ROOT / "hooks"), str(ROOT / "scripts")])
    return subprocess.run(
        [sys.executable, str(WRITE_GUARD)],
        input=payload, capture_output=True, text=True, timeout=60,
        env=env, errors="replace")


def _v2_blocker(probe_evidence: str = "", claim_id: str = "C-001",
                observed: str = "adb shell su -c id -> su: not found",
                attributed: str = "device has no root, frida unusable",
                expires: str = "12", body: str = "") -> str:
    return (
        "---\n"
        f"claim_id: {claim_id}\n"
        "blocker_type: B1b\n"
        'reason: "spawn fails with permission-flavored stderr"\n'
        "created: 2026-09-22\n"
        f"observed: \"{observed}\"\n"
        f'attributed: "{attributed}"\n'
        f'probe_evidence: "{probe_evidence}"\n'
        f"expires: {expires}\n"
        "---\n"
        "\n# Blocker C-001\n\n"
        "- **missing**: frida spawn on device\n"
        + (body or ""))


# ---------------------------------------------------------------------
# A1/A2: the evidence gate at the write seam
# ---------------------------------------------------------------------

class TestEnvAttributionEvidenceGate:
    def test_env_attribution_without_probe_evidence_rejected(self, tmp_path):
        ws = _mk_ws(tmp_path)
        target = ws / "blockers" / "C-001.md"
        r = _run_guard(ws, _payload(ws, "Write", target, content=_v2_blocker()))
        assert r.returncode == RC_BLOCK, r.stderr
        assert "probe_evidence" in r.stderr
        assert "never sufficient" in r.stderr

    def test_env_attribution_body_without_field_rejected(self, tmp_path):
        """Attribution phrasing in the BODY with the field absent entirely."""
        ws = _mk_ws(tmp_path)
        target = ws / "blockers" / "C-002.md"
        content = _v2_blocker(attributed="spawn fails").replace(
            'probe_evidence: ""\n', "")
        r = _run_guard(ws, _payload(ws, "Write", target, content=content))
        assert r.returncode == RC_BLOCK, r.stderr
        assert "probe_evidence" in r.stderr

    def test_same_blocker_with_probe_evidence_passes(self, tmp_path):
        ws = _mk_ws(tmp_path)
        target = ws / "blockers" / "C-001.md"
        content = _v2_blocker(
            probe_evidence="su -c id -> su: not found (rc 1); "
                           "id -> uid=2000 shell")
        r = _run_guard(ws, _payload(ws, "Write", target, content=content))
        assert r.returncode == RC_ALLOW, r.stderr

    @pytest.mark.parametrize("phrase", [
        "no root",
        "unavailable",
        "not supported",
        "cannot use",
        "unusable",
        "unreachable",
        "not installed",
        "permission denied",
        "unsupported",
    ])
    def test_every_pattern_phrasing_rejected_without_evidence(
            self, tmp_path, phrase):
        ws = _mk_ws(tmp_path)
        target = ws / "blockers" / "C-003.md"
        content = _v2_blocker(attributed=f"tool verdict: {phrase}")
        r = _run_guard(ws, _payload(ws, "Write", target, content=content))
        assert r.returncode == RC_BLOCK, (phrase, r.stderr)

    @pytest.mark.parametrize("phrase", [
        "cannot  be used",   # double space (review r1 bypass vector)
        "cannot\tuse",       # tab inside the phrase
        "cannot\nbe used",   # newline inside the phrase
        "cannot\n  use",     # newline + spaces
        "no   root",         # padded non-cannot phrasing
    ])
    def test_whitespace_variants_rejected(self, tmp_path, phrase):
        """Whitespace-run variants of the phrasings must not defeat the
        gate (review r1 finding): matching runs on normalized text."""
        ws = _mk_ws(tmp_path)
        target = ws / "blockers" / "C-005.md"
        content = _v2_blocker(attributed=f"tool verdict: {phrase}")
        r = _run_guard(ws, _payload(ws, "Write", target, content=content))
        assert r.returncode == RC_BLOCK, (phrase, r.stderr)

    def test_error_text_alone_is_never_evidence(self, tmp_path):
        """Quoting the failing stderr INSIDE probe_evidence does not pass
        when the bytes are the error text itself, not a probe output."""
        ws = _mk_ws(tmp_path)
        target = ws / "blockers" / "C-004.md"
        content = _v2_blocker(
            probe_evidence="spawn: Permission denied (stderr)")
        r = _run_guard(ws, _payload(ws, "Write", target, content=content))
        assert r.returncode == RC_BLOCK, r.stderr

    def test_edit_reintroducing_attribution_rejected(self, tmp_path):
        """An Edit whose post-image carries the attribution + no evidence
        is rejected (the gate judges the post-image, not the tool)."""
        ws = _mk_ws(tmp_path)
        target = ws / "blockers" / "C-001.md"
        target.write_text(_v2_blocker(
            probe_evidence="id -> uid=0(root)"), encoding="utf-8")
        r = _run_guard(ws, _payload(
            ws, "Edit", target,
            old_string="probe_evidence: \"id -> uid=0(root)\"",
            new_string="probe_evidence: \"\"",
        ))
        assert r.returncode == RC_BLOCK, r.stderr


# ---------------------------------------------------------------------
# A3: non-env blockers pass
# ---------------------------------------------------------------------

class TestNonEnvBlockersPass:
    @pytest.mark.parametrize("bt,attributed", [
        ("B1a", "filesystem access needed; in-process interpreter only"),
        ("B2", "user stopped the session at 14:03"),
        ("orphan", "fact has no intent row"),
    ])
    def test_infra_user_orphan_blockers_pass(self, tmp_path, bt, attributed):
        ws = _mk_ws(tmp_path)
        target = ws / "blockers" / "C-010.md"
        content = _v2_blocker(claim_id="C-010", attributed=attributed)
        content = content.replace("blocker_type: B1b", f"blocker_type: {bt}")
        r = _run_guard(ws, _payload(ws, "Write", target, content=content))
        assert r.returncode == RC_ALLOW, (bt, r.stderr)

    def test_blockers_stub_readme_passes(self, tmp_path):
        """The carriers stub (README) is not a blocker record (mirrors
        convergence_check._active_blockers' explicit skip)."""
        ws = _mk_ws(tmp_path)
        target = ws / "blockers" / "README.md"
        content = "# blockers/ — active blockers\n\nstub text\n"
        r = _run_guard(ws, _payload(ws, "Write", target, content=content))
        assert r.returncode == RC_ALLOW, r.stderr


# ---------------------------------------------------------------------
# A4: legacy shape — no-backcompat ruling 2026-09-01
# ---------------------------------------------------------------------

class TestLegacyShapeRejected:
    LEGACY = (
        "---\n"
        "claim_id: C-001\n"
        "blocker_type: B1a\n"
        'reason: ""\n'
        "created: 2026-01-01\n"
        "---\n"
        "\n# Blocker C-001\n\n"
        "- **claim**: C-001\n"
        "- **missing**: tooling fixed\n")

    def test_legacy_write_rejected_with_migration_reason(self, tmp_path):
        ws = _mk_ws(tmp_path)
        target = ws / "blockers" / "C-020.md"
        r = _run_guard(ws, _payload(ws, "Write", target, content=self.LEGACY))
        assert r.returncode == RC_BLOCK, r.stderr
        assert "v2" in r.stderr

    def test_legacy_edit_producing_legacy_postimage_rejected(self, tmp_path):
        ws = _mk_ws(tmp_path)
        target = ws / "blockers" / "C-021.md"
        target.write_text(self.LEGACY, encoding="utf-8")
        r = _run_guard(ws, _payload(
            ws, "Edit", target,
            old_string="- **missing**: tooling fixed",
            new_string="- **missing**: tooling fixed\n- **note**: retried"))
        assert r.returncode == RC_BLOCK, r.stderr


# ---------------------------------------------------------------------
# A5: mechanical schema lint (unit face)
# ---------------------------------------------------------------------

class TestSchemaLint:
    def test_v2_fields_parse(self):
        v = blocker_lint.lint_blocker_text(_v2_blocker(
            probe_evidence="id -> uid=0(root)"))
        assert v == []

    def test_missing_observed_flagged(self):
        text = _v2_blocker().replace('observed: "adb shell su -c id -> su: not found"\n', "")
        assert any("observed" in m for m in blocker_lint.lint_blocker_text(text))

    def test_missing_attributed_flagged(self):
        text = _v2_blocker().replace('attributed: "device has no root, frida unusable"\n', "")
        assert any("attributed" in m for m in blocker_lint.lint_blocker_text(text))

    @pytest.mark.parametrize("exp", ["12", "2026-10-01T00:00:00Z", 7])
    def test_expires_accepts_ticks_and_iso(self, exp):
        text = _v2_blocker(expires=str(exp),
                           probe_evidence="id -> uid=0(root)")
        assert blocker_lint.lint_blocker_text(text) == []

    def test_expires_garbage_flagged(self):
        text = _v2_blocker(expires="soon", probe_evidence="id -> uid=0(root)")
        msgs = blocker_lint.lint_blocker_text(text)
        assert any("expires" in m for m in msgs)

    def test_expires_missing_flagged(self):
        text = _v2_blocker().replace("expires: 12\n", "")
        assert any("expires" in m for m in blocker_lint.lint_blocker_text(text))

    def test_no_frontmatter_flagged(self):
        msgs = blocker_lint.lint_blocker_text("# just a body\n")
        assert msgs and "v2" in msgs[0]

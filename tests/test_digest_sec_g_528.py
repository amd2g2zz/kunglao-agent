# -*- coding: utf-8 -*-
"""tests/test_digest_sec_g_528.py — digest open-hypotheses section (#528).

sec_g reads ONLY from <ws>/hypotheses/ — never from notes/. notes/ is
the result layer (user correction 2026-08-20); re-importing a
'hypothesis' from notes would re-introduce the AES->ChaCha20 silent
overwrite anti-pattern.

Fail-open: a hypotheses/ layer that fails to build must degrade the
digest to the pre-#528 shape (still six sections, cold start proceeds),
never block it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import digest_build  # noqa: E402


def _hyp(hyp_id: str, status: str = "open", *, claim_id: str = "C-1",
         extra: str = "") -> str:
    return (
        f"---\nid: {hyp_id}\nclaim_id: {claim_id}\n"
        f"competitor_group: cg\ncandidates: [AES]\nstatus: {status}\n"
        f"schema_rev: 1\n{extra}---\nbody {hyp_id}\n"
    )


# ---------- build_sec_g (the section builder) ----------

def test_sec_g_lists_only_open_hypotheses(tmp_path: Path) -> None:
    (tmp_path / "hypotheses").mkdir()
    (tmp_path / "hypotheses" / "H-A.md").write_text(
        _hyp("H-A"), encoding="utf-8")
    (tmp_path / "hypotheses" / "H-B.md").write_text(
        _hyp("H-B", "refuted", extra="refuting_fact_id: F-1\n"),
        encoding="utf-8")
    (tmp_path / "hypotheses" / "H-C.md").write_text(
        _hyp("H-C", "superseded", extra="superseded_by: H-D\n"),
        encoding="utf-8")
    out = digest_build.build_sec_g(tmp_path)
    assert "## sec_g" in out
    assert "H-A" in out
    assert "H-B" not in out   # refuted: decided, not re-hydrated
    assert "H-C" not in out   # superseded: replaced, not re-hydrated


def test_sec_g_empty_when_no_open_hypotheses(tmp_path: Path) -> None:
    (tmp_path / "hypotheses").mkdir()
    (tmp_path / "hypotheses" / "H-B.md").write_text(
        _hyp("H-B", "refuted", extra="refuting_fact_id: F-1\n"),
        encoding="utf-8")
    assert digest_build.build_sec_g(tmp_path) == ""


def test_sec_g_missing_dir_returns_empty(tmp_path: Path) -> None:
    """Pre-#528 workspaces: no hypotheses/ -> no section, no crash."""
    assert digest_build.build_sec_g(tmp_path) == ""


def test_sec_g_excludes_notes(tmp_path: Path) -> None:
    """Even if a note mentions 'hypothesis' in its body, sec_g must not
    pick it up — notes/ is a different layer, never a hypothesis source."""
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "N-1.md").write_text(
        "---\nid: N-1\nclaim_id: C-1\nverify_status: passes\n"
        "supersedes: N-0\n---\n# old hypothesis AES\n",
        encoding="utf-8")
    out = digest_build.build_sec_g(tmp_path)
    assert "N-1" not in out
    assert "AES" not in out


def test_sec_g_pointers_only_never_body(tmp_path: Path) -> None:
    """sec_g payload stays pointer-sized — hyp_id/claim_id/group/candidates
    only, never the motivation body (digest cold-start size budget)."""
    (tmp_path / "hypotheses").mkdir()
    body = "SECRET-MOTIVATION-BODY " * 200
    (tmp_path / "hypotheses" / "H-X.md").write_text(
        "---\nid: H-X\nclaim_id: C-9\ncompetitor_group: net\n"
        "candidates: [ws, wss]\nstatus: open\nschema_rev: 1\n---\n"
        + body + "\n",
        encoding="utf-8")
    out = digest_build.build_sec_g(tmp_path)
    assert "SECRET-MOTIVATION-BODY" not in out
    assert "H-X" in out
    assert "C-9" in out


def test_sec_g_bounded_rows(tmp_path: Path) -> None:
    """A pathological hypotheses/ dir must not blow the 4KB digest cap —
    the section is capped at MAX_SEC_G_HYPS rows like every other digest
    section is bounded."""
    (tmp_path / "hypotheses").mkdir()
    for i in range(300):
        (tmp_path / "hypotheses" / f"H-{i:03d}.md").write_text(
            _hyp(f"H-{i:03d}"), encoding="utf-8")
    out = digest_build.build_sec_g(tmp_path)
    n_rows = sum(1 for ln in out.splitlines() if ln.startswith("| H-"))
    assert n_rows <= digest_build.MAX_SEC_G_HYPS


# ---------- build_digest integration (the 7th section) ----------

def _mini_ws(tmp_path: Path) -> Path:
    (tmp_path / "task_spec.yaml").write_text(
        "primary_questions:\n  - q1: family\n", encoding="utf-8")
    (tmp_path / "claim-register.yaml").write_text(
        "claims:\n  - {id: C-1, status: OPEN, statement: s}\n",
        encoding="utf-8")
    return tmp_path


def test_build_digest_includes_sec_g(tmp_path: Path) -> None:
    ws = _mini_ws(tmp_path)
    (ws / "hypotheses").mkdir()
    (ws / "hypotheses" / "H-A.md").write_text(_hyp("H-A"), encoding="utf-8")
    md = digest_build.build_digest(ws)
    assert "## sec_g" in md
    assert "H-A" in md
    # section order: sec_g follows sec_f (the pointer table closes the
    # original six; the hypothesis section is appended after it)
    assert md.index("## sec_f") < md.index("## sec_g")


def test_build_digest_no_hypotheses_keeps_six_sections(tmp_path: Path) -> None:
    """Pre-#528 workspaces: digest unchanged (six sections, no sec_g)."""
    ws = _mini_ws(tmp_path)
    md = digest_build.build_digest(ws)
    for marker in ["## head", "## sec_a", "## sec_b", "## sec_c",
                   "## sec_d", "## sec_e", "## sec_f"]:
        assert marker in md
    assert "## sec_g" not in md


def test_digest_size_cap_with_hypotheses(tmp_path: Path) -> None:
    """The 4096-byte cold-start ceiling still holds with hypotheses
    present (test_digest.py pins the pre-#528 case)."""
    ws = _mini_ws(tmp_path)
    (ws / "hypotheses").mkdir()
    for i in range(50):
        (ws / "hypotheses" / f"H-{i:03d}.md").write_text(
            _hyp(f"H-{i:03d}"), encoding="utf-8")
    md = digest_build.build_digest(ws)
    assert len(md.encode("utf-8")) <= 4096


# ---------- fail-open (issue work item: fault injection) ----------

def test_digest_degrades_when_sec_g_builder_crashes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FAULT INJECTION: build_sec_g raising must NOT block digest build —
    cold start degrades to the pre-#528 shape (six sections), it never
    fails. This is the issue's explicit fail-open requirement."""
    ws = _mini_ws(tmp_path)
    (ws / "hypotheses").mkdir()
    (ws / "hypotheses" / "H-A.md").write_text(_hyp("H-A"), encoding="utf-8")

    def _explode(ws_root: Path) -> str:
        raise RuntimeError("hypothesis layer exploded")

    monkeypatch.setattr(digest_build, "build_sec_g", _explode)
    md = digest_build.build_digest(ws)  # must not raise
    assert "## sec_f" in md          # the six sections all survived
    assert "## sec_g" not in md      # the failed section is simply absent


def test_digest_degrades_when_store_unreadable(tmp_path: Path) -> None:
    """A hypotheses/ dir with an unreadable file must not crash the whole
    digest build — hypothesis_store.list_all skips unparseable files."""
    ws = _mini_ws(tmp_path)
    (ws / "hypotheses").mkdir()
    (ws / "hypotheses" / "H-A.md").write_text(_hyp("H-A"), encoding="utf-8")
    (ws / "hypotheses" / "broken.md").write_text(
        "not-frontmatter\n", encoding="utf-8")
    md = digest_build.build_digest(ws)
    assert "H-A" in md  # the good one still surfaces

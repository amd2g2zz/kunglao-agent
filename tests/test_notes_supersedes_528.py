# -*- coding: utf-8 -*-
"""tests/test_notes_supersedes_528.py — notes correction chain (#528).

notes/ is the result layer. A correction (e.g. N-001 PROVEN 'AES' ->
N-002 PROVEN 'ChaCha20') is ALWAYS a new note declaring
`supersedes: N-001` — the prior note is not deleted, not modified, and
its conclusion stays queryable. The chain is the audit trail.

verify_status reset: a superseding note starts UNVERIFIED (pending) — a
correction never inherits the prior note's verification stamp (the old
evidence did not verify the new conclusion).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from notes_writer import NotesWriter, SupersedeRequired  # noqa: E402


def _note(path: Path, *, status: str = "PROVEN",
          verify_status: str | None = "passes",
          supersedes: str | None = None) -> None:
    fm = ["---", "id: " + path.stem, "claim_id: C-1", f"status: {status}"]
    if verify_status:
        fm.append(f"verify_status: {verify_status}")
    if supersedes:
        fm.append(f"supersedes: {supersedes}")
    fm.append("---\n# title\nbody\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(fm), encoding="utf-8")


# ---------- the gate ----------

def test_correction_without_supersedes_rejected(tmp_path: Path) -> None:
    notes = tmp_path / "notes"
    _note(notes / "N-001.md")
    w = NotesWriter(notes)
    with pytest.raises(SupersedeRequired, match="N-001"):
        w.write_note(stem="N-002", claim_id="C-1", verify_status="passes",
                     body="Actually it's ChaCha20",
                     title="correction")  # NO supersedes — must be rejected


def test_correction_with_supersedes_succeeds(tmp_path: Path) -> None:
    notes = tmp_path / "notes"
    _note(notes / "N-001.md")
    w = NotesWriter(notes)
    p = w.write_note(stem="N-002", claim_id="C-1",
                     verify_status="pending",
                     body="ChaCha20", title="correction",
                     supersedes="N-001")
    assert p == notes / "N-002.md"
    assert p.exists()
    assert w.get_chain("N-002") == ["N-001"]


def test_first_note_needs_no_supersedes(tmp_path: Path) -> None:
    """A brand-new note in an empty notes/ has no prior — no gate."""
    w = NotesWriter(tmp_path / "notes")
    w.write_note(stem="N-100", claim_id="C-1", verify_status="pending",
                 body="initial guess", title="first")
    assert (tmp_path / "notes" / "N-100.md").exists()


def test_prior_note_unchanged_after_correction(tmp_path: Path) -> None:
    """The prior note stays byte-identical — corrections never erase prior
    conclusions; the new note carries the chain."""
    notes = tmp_path / "notes"
    _note(notes / "N-001.md")
    prior = (notes / "N-001.md").read_text(encoding="utf-8")
    w = NotesWriter(notes)
    w.write_note(stem="N-002", claim_id="C-1", verify_status="pending",
                 body="ChaCha20", title="correction", supersedes="N-001")
    assert (notes / "N-001.md").read_text(encoding="utf-8") == prior


# ---------- same-claim scoping ----------

def test_gate_scoped_to_same_claim(tmp_path: Path) -> None:
    """A note for a DIFFERENT claim is not a correction of this one — the
    gate fires only when the prior note answers the same claim (the
    AES->ChaCha20 shape is two notes on ONE claim)."""
    notes = tmp_path / "notes"
    _note(notes / "N-001.md")  # claim C-1, PROVEN
    w = NotesWriter(notes)
    w.write_note(stem="N-050", claim_id="C-2",  # different claim
                 verify_status="pending", body="unrelated", title="other")
    assert (notes / "N-050.md").exists()


# ---------- verify_status reset ----------

def test_superseding_note_starts_unverified(tmp_path: Path) -> None:
    """A correction NEVER inherits the prior's verification: the new note's
    verify_status is forced to 'pending' regardless of what the caller
    passed (old evidence did not verify the new conclusion)."""
    notes = tmp_path / "notes"
    _note(notes / "N-001.md", verify_status="passes")
    w = NotesWriter(notes)
    with pytest.raises(ValueError, match="verify_status"):
        w.write_note(stem="N-002", claim_id="C-1",
                     verify_status="passes",  # must be rejected/reset
                     body="ChaCha20", title="correction", supersedes="N-001")


def test_correction_written_pending(tmp_path: Path) -> None:
    notes = tmp_path / "notes"
    _note(notes / "N-001.md", verify_status="passes")
    w = NotesWriter(notes)
    w.write_note(stem="N-002", claim_id="C-1", verify_status="pending",
                 body="ChaCha20", title="correction", supersedes="N-001")
    text = (notes / "N-002.md").read_text(encoding="utf-8")
    assert "verify_status: pending" in text


def test_plain_note_accepts_any_verify_status(tmp_path: Path) -> None:
    """Without a supersedes pointer the writer is not in correction mode:
    normal verify_status values pass through untouched."""
    notes = tmp_path / "notes"
    _note(notes / "N-001.md", status="OPEN", verify_status="pending")
    w = NotesWriter(notes)
    w.write_note(stem="N-003", claim_id="C-9", verify_status="stale",
                 body="side note", title="note")
    assert "verify_status: stale" in (
        notes / "N-003.md").read_text(encoding="utf-8")


# ---------- chain walking ----------

def test_chain_two_links(tmp_path: Path) -> None:
    """AES -> ChaCha20 -> XChaCha20: two corrections deep, get_chain walks
    back to the root (newest -> oldest)."""
    notes = tmp_path / "notes"
    _note(notes / "N-001.md")
    w = NotesWriter(notes)
    w.write_note(stem="N-002", claim_id="C-1", verify_status="pending",
                 body="ChaCha20", title="c1", supersedes="N-001")
    w.write_note(stem="N-003", claim_id="C-1", verify_status="pending",
                 body="XChaCha20", title="c2", supersedes="N-002")
    assert w.get_chain("N-003") == ["N-002", "N-001"]


def test_chain_missing_note_returns_empty(tmp_path: Path) -> None:
    w = NotesWriter(tmp_path / "notes")
    assert w.get_chain("N-404") == []


def test_chain_rejects_cycles(tmp_path: Path) -> None:
    """A supersedes pointer at a nonexistent id is a broken chain, not a
    crash; and the walker refuses to loop forever on a hand-made cycle."""
    notes = tmp_path / "notes"
    _note(notes / "N-001.md", supersedes="N-002")
    _note(notes / "N-002.md", supersedes="N-001")
    w = NotesWriter(notes)
    chain = w.get_chain("N-001")  # must terminate
    assert isinstance(chain, list)


def test_supersedes_target_must_exist(tmp_path: Path) -> None:
    """`supersedes: N-999` naming a note that does not exist is a broken
    pointer — rejected at write time (fake chain)."""
    notes = tmp_path / "notes"
    _note(notes / "N-001.md")
    w = NotesWriter(notes)
    with pytest.raises(ValueError, match="N-999"):
        w.write_note(stem="N-002", claim_id="C-1", verify_status="pending",
                     body="x", title="c", supersedes="N-999")

# -*- coding: utf-8 -*-
"""tests/test_hypothesis_store_528.py — hypothesis layer (#528) anchors.

notes/ is the result layer (user correction 2026-08-20: first judge, then
revise notes — never the other way around). Hypotheses live in their OWN
carrier <ws>/hypotheses/ with a strict open -> refuted | superseded state
machine; this suite pins that file schema and the transition rules.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from hypothesis_store import (  # noqa: E402
    HYPOTHESIS_STATUSES,
    SCHEMA_VERSION,
    Hypothesis,
    HypothesisStore,
    InvalidTransition,
)


def _write_one(tmp: Path, hyp_id: str, claim_id: str = "C-001",
               body: str = "AES is the cipher") -> Path:
    p = tmp / "hypotheses" / f"{hyp_id}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        textwrap.dedent(
            f"""\
            ---
            id: {hyp_id}
            claim_id: {claim_id}
            competitor_group: prng-vs-cipher
            candidates: [AES, ChaCha20]
            status: open
            schema_rev: {SCHEMA_VERSION}
            ---

            # {hyp_id}

            {body}
            """
        ),
        encoding="utf-8",
    )
    return p


# ---------- 1. parse ----------

def test_open_hypothesis_parses(tmp_path: Path) -> None:
    _write_one(tmp_path, "H-001")
    store = HypothesisStore(tmp_path / "hypotheses")
    hyps = store.list_all()
    assert len(hyps) == 1
    assert hyps[0].id == "H-001"
    assert hyps[0].status == "open"
    assert hyps[0].claim_id == "C-001"
    assert hyps[0].candidates == ["AES", "ChaCha20"]
    assert hyps[0].competitor_group == "prng-vs-cipher"


def test_store_creates_missing_dir(tmp_path: Path) -> None:
    """Pre-#528 workspaces have no hypotheses/ — construction must not
    explode, and the empty store reads as no hypotheses."""
    store = HypothesisStore(tmp_path / "hypotheses")
    assert store.list_all() == []
    assert store.list_open() == []


def test_status_vocabulary_is_the_state_machine() -> None:
    # #711: "confirmed" joins the vocabulary — a falsifiable bet settles
    # positively too (confirming_fact_id required, symmetric with refuted).
    assert HYPOTHESIS_STATUSES == ("open", "refuted", "superseded",
                                   "confirmed")


# ---------- 2. transitions ----------

def test_refute_requires_citing_fact(tmp_path: Path) -> None:
    """Refuting without evidence is impossible — a refuted hypothesis must
    point at the fact that killed it. This is the 'why was I wrong' trail."""
    _write_one(tmp_path, "H-002")
    store = HypothesisStore(tmp_path / "hypotheses")
    with pytest.raises(InvalidTransition, match="refuting_fact_id"):
        store.transition("H-002", "refuted")


def test_refute_with_fact_persists(tmp_path: Path) -> None:
    _write_one(tmp_path, "H-002")
    store = HypothesisStore(tmp_path / "hypotheses")
    store.transition("H-002", "refuted", refuting_fact_id="F-007")
    h = store.get("H-002")
    assert h.status == "refuted"
    assert h.refuting_fact_id == "F-007"
    # round-trip: the write-back carries the field
    text = (tmp_path / "hypotheses" / "H-002.md").read_text(encoding="utf-8")
    assert "refuting_fact_id: F-007" in text


def test_supersede_chains_to_new_hypothesis(tmp_path: Path) -> None:
    """open -> superseded requires a successor id (the hypothesis that
    replaces this one). notes/ shares the same supersedes convention."""
    _write_one(tmp_path, "H-003")
    store = HypothesisStore(tmp_path / "hypotheses")
    store.transition("H-003", "superseded", superseded_by="H-004")
    h = store.get("H-003")
    assert h.status == "superseded"
    assert h.superseded_by == "H-004"


def test_supersede_without_successor_rejected(tmp_path: Path) -> None:
    _write_one(tmp_path, "H-003")
    store = HypothesisStore(tmp_path / "hypotheses")
    with pytest.raises(InvalidTransition, match="superseded_by"):
        store.transition("H-003", "superseded")


def test_open_to_open_is_idempotent(tmp_path: Path) -> None:
    """rehydrate (cold start) re-asserts 'open'; must not error."""
    _write_one(tmp_path, "H-005")
    store = HypothesisStore(tmp_path / "hypotheses")
    store.transition("H-005", "open")  # no-op
    assert store.get("H-005").status == "open"


def test_terminal_states_do_not_reopen(tmp_path: Path) -> None:
    """refuted/superseded are terminal: a stale 'open' re-assert from an
    older session must not resurrect a decided hypothesis."""
    _write_one(tmp_path, "H-006")
    store = HypothesisStore(tmp_path / "hypotheses")
    store.transition("H-006", "refuted", refuting_fact_id="F-001")
    with pytest.raises(InvalidTransition, match="terminal"):
        store.transition("H-006", "open")


def test_unknown_status_rejected(tmp_path: Path) -> None:
    _write_one(tmp_path, "H-007")
    store = HypothesisStore(tmp_path / "hypotheses")
    with pytest.raises(InvalidTransition, match="unknown status"):
        store.transition("H-007", "DELETED")


def test_transition_missing_hypothesis(tmp_path: Path) -> None:
    store = HypothesisStore(tmp_path / "hypotheses")
    with pytest.raises(KeyError):
        store.transition("H-404", "refuted", refuting_fact_id="F-1")


# ---------- 3. corruption tolerance ----------

def test_malformed_file_does_not_poison_the_store(tmp_path: Path) -> None:
    """One corrupt hypothesis file must not take down the whole digest
    (fail-open: digest build degrades, never blocks cold start)."""
    _write_one(tmp_path, "H-100")
    bad = tmp_path / "hypotheses" / "H-101.md"
    bad.write_text("no frontmatter at all\n", encoding="utf-8")
    store = HypothesisStore(tmp_path / "hypotheses")
    hyps = store.list_all()
    assert [h.id for h in hyps] == ["H-100"]


# ---------- 4. round-trip write ----------

def test_candidates_survive_roundtrip(tmp_path: Path) -> None:
    _write_one(tmp_path, "H-200")
    store = HypothesisStore(tmp_path / "hypotheses")
    store.transition("H-200", "refuted", refuting_fact_id="F-002")
    text = (tmp_path / "hypotheses" / "H-200.md").read_text(encoding="utf-8")
    assert "candidates: [AES, ChaCha20]" in text
    assert "competitor_group: prng-vs-cipher" in text
    # the body survives the transition write-back
    assert "AES is the cipher" in text


def test_hypothesis_dataclass_defaults() -> None:
    h = Hypothesis(id="H-1", claim_id="C-1", competitor_group="g")
    assert h.status == "open"
    assert h.candidates == []
    assert h.refuting_fact_id is None
    assert h.superseded_by is None

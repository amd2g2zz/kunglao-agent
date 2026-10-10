# -*- coding: utf-8 -*-
"""Issue 584 — the fact contract gains per-fact uncertainty and next_probe.

Two OPTIONAL kunglao extension-layer fields (the evidence_class precedent —
additive over the fact substrate, never a new object type):

  - `uncertainty` (optional string): the explicit counter-hypothesis /
    not-yet-confirmed note — the refutation face at fact level.
  - `next_probe` (optional string): the next runnable experiment, phrased so
    the dispatch face can consume it verbatim as a sub-goal. Relationship to
    `promotion_gate`: the gate is the CONDITION, next_probe is the EXPERIMENT
    testing it.

lint_facts shape contract: both keys are KNOWN (no UNKNOWN_KEY warning) and,
when present, must be a non-empty string (BAD_UNCERTAINTY / BAD_NEXT_PROBE).
Absent is the common case and stays silent.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import lint_facts as lf  # noqa: E402


def _fact(fm: dict, body: str = "body\n") -> Path:
    import tempfile
    import yaml
    d = Path(tempfile.mkdtemp()) / "facts"
    d.mkdir(parents=True)
    head = yaml.safe_dump(fm, sort_keys=False)
    (d / f"{fm['id']}.md").write_text(f"---\n{head}---\n\n{body}",
                                      encoding="utf-8")
    return d.parent


def _base_fm(fid: str, **over) -> dict:
    fm = {
        "id": fid, "type": "fact", "title": "neutral title",
        "status": "PROVEN", "created": "2026-10-09",
        "last_reviewed": "2026-10-09", "claim_id": "C-001",
        "boundary_type": "confirmed", "promotion_gate": "",
        "provenance": [{"role": "decompiled_c", "path": "x.c",
                        "content_sha256": "a" * 64, "credibility": "B2"}],
        "source": "static-decompile", "confidence": "high",
        "claim": "neutral title", "reproduce": "echo hi",
        "expected": "hi", "verified": "pending",
    }
    fm.update(over)
    return fm


def _codes(issues: list) -> set:
    return {code for _sev, code, _msg in issues}


# ---------- known-key + clean-shape contract ----------

def test_hypothesis_fields_are_known_keys():
    errors, warnings = lf.lint_workspace(_fact(_base_fm(
        "F584-01",
        uncertainty="key source unconfirmed; call paths could also be compression",
        next_probe="trace input/output buffers, vary input, observe decryption signature")))
    assert "UNKNOWN_KEY" not in _codes(warnings)
    assert not _codes(errors) & {"BAD_UNCERTAINTY", "BAD_NEXT_PROBE"}


def test_fields_absent_is_silent_common_case():
    errors, warnings = lf.lint_workspace(_fact(_base_fm("F584-02")))
    assert "UNKNOWN_KEY" not in _codes(warnings)
    assert not _codes(errors) & {"BAD_UNCERTAINTY", "BAD_NEXT_PROBE"}


# ---------- uncertainty shape ----------

def test_uncertainty_empty_string_errors():
    errors, _w = lf.lint_workspace(_fact(_base_fm("F584-03", uncertainty="")))
    assert "BAD_UNCERTAINTY" in _codes(errors)


def test_uncertainty_whitespace_only_errors():
    errors, _w = lf.lint_workspace(_fact(_base_fm("F584-04", uncertainty="   ")))
    assert "BAD_UNCERTAINTY" in _codes(errors)


def test_uncertainty_nonstring_errors():
    errors, _w = lf.lint_workspace(_fact(_base_fm("F584-05", uncertainty=42)))
    assert "BAD_UNCERTAINTY" in _codes(errors)


def test_uncertainty_nonempty_string_passes():
    errors, _w = lf.lint_workspace(_fact(_base_fm(
        "F584-06", uncertainty="not yet confirmed on a second sample")))
    assert "BAD_UNCERTAINTY" not in _codes(errors)


# ---------- next_probe shape ----------

def test_next_probe_empty_string_errors():
    errors, _w = lf.lint_workspace(_fact(_base_fm("F584-07", next_probe="")))
    assert "BAD_NEXT_PROBE" in _codes(errors)


def test_next_probe_nonstring_errors():
    errors, _w = lf.lint_workspace(_fact(_base_fm("F584-08", next_probe=["a", "b"])))
    assert "BAD_NEXT_PROBE" in _codes(errors)


def test_next_probe_nonempty_string_passes():
    errors, _w = lf.lint_workspace(_fact(_base_fm(
        "F584-09", next_probe="run verify script against a second captured config")))
    assert "BAD_NEXT_PROBE" not in _codes(errors)


# ---------- constructed-sample pin: flows through the faces ----------

def test_constructed_sample_flows_through_lint_without_contract_breaks():
    """A fact carrying BOTH fields passes the full lint with zero errors."""
    fm = _base_fm(
        "F584-10", status="INFERRED", confidence="medium",
        uncertainty="the xor key could also be a length-4 prefix of a longer schedule",
        next_probe="capture a second config blob, decode with the derived key, diff plaintext structure")
    fm["boundary_type"] = "source_derived"
    fm["promotion_gate"] = "a second sample decoding to structured plaintext under the derived key"
    errors, _w = lf.lint_workspace(_fact(fm))
    assert not errors, errors


def test_constructed_sample_round_trips_the_shared_parse_face():
    """parse_frontmatter (the face dispatch/plan/gap-notes import) carries
    both fields verbatim — no contract break downstream of the write."""
    import yaml
    fm = _base_fm(
        "F584-11",
        uncertainty="counter-hypothesis: the constant is a checksum, not a key seed",
        next_probe="mutate one byte of the seed input and re-derive the constant")
    ws = _fact(fm)
    text = (ws / "facts" / "F584-11.md").read_text(encoding="utf-8")
    parsed, _body, perr = lf.parse_frontmatter(text)
    assert perr is None
    assert parsed["uncertainty"] == fm["uncertainty"]
    assert parsed["next_probe"] == fm["next_probe"]
    assert yaml.safe_dump(parsed)

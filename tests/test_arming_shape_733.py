# -*- coding: utf-8 -*-
"""tests/test_arming_shape_733.py — ONE shape law for oracle-case
`expected` is ONE law.

The arming gate and the runner's loader disagreed on the `expected`
shape: the gate wanted a MAPPING with `evidence_refs`, the loader wants
a non-empty LIST of `{field, value, evidence_refs}` entries. The shapes
are mutually exclusive, so no case doc could be both armed and
runner-loadable — and the live workspace's armed docs were all in the
non-loadable class, silently unobservable by anything that respects the
runner's contract.

The fix is one shape law, defined once in the executor
(`oracle_runner.expected_shape_error`) and consumed by both faces:
the runner's parse raises exactly what the predicate flags, and the
arming gate's `expected` requirement delegates to the same predicate.

Pins:

1. ``test_dict_shape_is_not_armed_list_shape_is`` — the old mapping
   shape carries no field/value semantics, so it is no longer armed;
   the runner's shape is.
2. ``test_predicate_is_the_single_source`` — across a probe matrix of
   shapes, the predicate's verdict and the parse's shape acceptance
   agree (the predicate is not a lossy copy of the law).
3. ``test_amendment_observes_only_the_canonical_shape`` — the posterior
   leg's arming follows the same law end-to-end: a list-shaped armed
   doc is observed, a dict-shaped doc is not.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import oracle_runner as orun  # noqa: E402
import settle_round_credit as src  # noqa: E402


# ---------- synthetic fixture helpers --------------------------------------

def _doc(expected) -> dict:
    """A case doc with every arming field present; only `expected`'s
    shape varies."""
    return {"id": "case-x", "channel": "probe", "target_pq": "pq-main",
            "hypothesis_ref": "H-001", "update_map": {"red_up": ["H-002"]},
            "expected": expected,
            "mutations": [{"kind": "omit", "target": "E-001"}]}


OLD_DICT_SHAPE = {"evidence_refs": ["F001-fact", "F002-fact"]}
RUNNER_LIST_SHAPE = [{"field": "handler_present", "value": "obfuscated",
                      "evidence_refs": ["F001-fact"]}]

PROBE_SHAPES = [
    OLD_DICT_SHAPE,
    RUNNER_LIST_SHAPE,
    [],
    "not-a-list",
    [{"field": "f"}],                       # no value
    [{"value": 1}],                         # no field
    [{"field": "", "value": 1}],            # blank field
    [{"field": "f", "value": 1, "evidence_refs": ["F1-fact"]}],
    [{"field": "f", "value": 1, "pending-observation": True}],
    [{"field": "f", "value": 1}, {"field": "g", "value": 2}],
]


def _armed_case_file(ws: Path, cid: str, pq: str, expected) -> None:
    cdir = ws / "oracle" / "cases"
    cdir.mkdir(parents=True, exist_ok=True)
    doc = _doc(expected)
    doc["id"] = cid
    doc["target_pq"] = pq
    (cdir / f"{cid}.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")


# ---------- 1. the shape law ------------------------------------------------

def test_dict_shape_is_not_armed_list_shape_is(tmp_path):
    """The old mapping shape carries no field/value semantics — it was
    the non-loadable class. Only the runner's list shape arms a case."""
    ws = tmp_path / "ws"
    _armed_case_file(ws, "case-old", "pq-main", OLD_DICT_SHAPE)
    assert src.armed_case_ids(ws) == set(), src.armed_case_ids(ws)

    _armed_case_file(ws, "case-new", "pq-main", RUNNER_LIST_SHAPE)
    assert src.armed_case_ids(ws) == {"case-new"}


def test_predicate_is_the_single_source(tmp_path):
    """Across the probe matrix the predicate's verdict and the parse's
    shape acceptance agree exactly — the predicate is the law, not a
    lossy copy. (The parse's workspace-resolution half is out of this
    pin: it needs real artifacts, and only runs on shape-valid docs.)"""
    import inspect

    for raw in PROBE_SHAPES:
        fault = orun.expected_shape_error(raw)
        armed = src._arming_field_present(_doc(raw), "expected")
        assert (fault is None) == armed, (raw, fault, armed)
        if fault is not None:
            # the parse refuses the same shape, wrapping the same fault
            try:
                orun._parse_expected(
                    tmp_path, tmp_path / "c.yaml", "case-x", raw)
                raise AssertionError(f"parse accepted {raw!r}")
            except orun.OracleCaseError as exc:
                assert str(fault) in str(exc), (fault, exc)
    # the predicate is defined in the executor, not re-derived locally
    assert "expected_shape_error" in dir(orun)
    assert not re.search(r"^def expected_shape_error\(",
                         inspect.getsource(src), re.MULTILINE)


def test_raise_formatting_is_byte_identical_to_the_pre_extraction_parse(
        tmp_path):
    """The extraction kept the parse's raise texts byte-identical: the
    TOP-LEVEL fault carries the `case {cid!r}` clause, entry-level
    faults do not — the exact pre-extraction asymmetry."""
    with pytest.raises(orun.OracleCaseError) as top:
        orun._parse_expected(tmp_path, tmp_path / "c.yaml", "case-x", [])
    assert str(top.value) == (
        "c.yaml: case 'case-x' needs a non-empty `expected` list")
    with pytest.raises(orun.OracleCaseError) as entry:
        orun._parse_expected(tmp_path, tmp_path / "c.yaml", "case-x",
                             [{"value": 1}])
    assert str(entry.value) == (
        "c.yaml: expected entry #0 lacks a `field` name")


# ---------- 2. end-to-end: the posterior leg follows the same law ----------

def test_amendment_observes_only_the_canonical_shape(tmp_path):
    """End-to-end through the amendment: a list-shaped armed case over a
    settled claim IS observed; a dict-shaped doc over an identical claim
    is not. This is the shape the live migration must produce."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(
        {"claims": [{"id": "C-005", "status": "PROVEN",
                     "answers_question": "q2"}]}, allow_unicode=True),
        encoding="utf-8")
    _armed_case_file(ws, "case-good", "q2", RUNNER_LIST_SHAPE)
    _armed_case_file(ws, "case-dict", "q2", OLD_DICT_SHAPE)

    out = src.amend_case_settlements(ws)
    assert out["case_observations"] == 1, out
    led_path = ws / "runs" / "posteriors.yaml"
    doc = yaml.safe_load(led_path.read_text(encoding="utf-8"))
    assert doc["cases"]["case-good"]["alpha"] == 2.0
    assert "case-dict" not in doc["cases"]

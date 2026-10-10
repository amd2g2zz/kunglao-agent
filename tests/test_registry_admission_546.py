# -*- coding: utf-8 -*-
"""tests/test_registry_admission_546.py — the REGISTRY ADMISSION face of
#546: an admitted novel arm becomes DISPATCHABLE through the #432
vocabulary gate WITHOUT mutating the closed repo registry.

The contract (workspace-local overlay, never a registry mutation):

  - scripts/method_families.py gains an overlay read face:
    registered_tokens(ws) merges runs/discovered-families.yaml (schema
    discovered-families/1) into the CANDIDATE ENUMERATION set only;
    no workspace or a corrupt overlay => exactly the old closed set.
  - the declaration VALIDATION path accepts an overlay token only when
    the workspace carries its admission receipt (provenance chain:
    token -> E-N receipt id -> the receipt's admitted hypothesis list).
  - rlvr/expansion.py register_admitted(ws, receipt) appends the move's
    admitted family tokens to the overlay (idempotent by token+receipt,
    tolerant read); the wiring calls it after record_receipt, fail-open.
  - the envelope sampler's cold-start candidate set and the dispatch
    gate both see the merged set through the workspace.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import method_families as mf  # noqa: E402
from rlvr import expansion as ex  # noqa: E402

DISCOVERED = "unicorn-engine-emulator"


def _mined() -> frozenset[str]:
    """The closed repo registry (the #432 pin, read live so a conscious
    registry diff never breaks this file)."""
    return mf.registered_tokens()


def _write_overlay(ws: Path, tokens: list[str], receipt: str = "E-1",
                   schema: str = "discovered-families/1") -> Path:
    ws.mkdir(parents=True, exist_ok=True)
    path = ws / "runs" / "discovered-families.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema": schema,
           "families": [{"token": t, "receipt": receipt,
                         "admitted_ts": "2026-10-08T00:00:00Z"}
                        for t in tokens]}
    path.write_text(yaml.safe_dump(doc, sort_keys=True), encoding="utf-8")
    return path


def _admitted_receipt(ws: Path, family: str = DISCOVERED, hid: str = "h-1",
                      trigger: dict | None = None) -> dict:
    """Run the REAL producer chain: admit one novel hypothesis, record
    the receipt, register it into the overlay. Returns the receipt doc."""
    ranked = ex.admit([{"id": hid, "family": family, "p_llm": 0.3,
                        "policy": 0.0,
                        "features": {"lane": "dynamic",
                                     "project_type": "wasm"}}], [])
    doc = ex.record_receipt(ws, trigger or {"obstacle_count": 3,
                                            "collapsed_arms":
                                                ["static-decompile"]},
                            ranked, [r["id"] for r in ranked])
    ex.register_admitted(ws, doc)
    return doc


# ---------------------------------------------------------------------------
# A. the overlay read face (enumeration only)
# ---------------------------------------------------------------------------

def test_no_workspace_is_the_closed_registry():
    """No workspace (or None) => byte-identical old behavior: the closed
    #432 set and nothing else."""
    assert mf.registered_tokens() == _mined()
    assert mf.registered_tokens(None) == _mined()


def test_workspace_without_overlay_is_closed(tmp_path):
    assert mf.registered_tokens(tmp_path) == _mined()


def test_overlay_tokens_merge_for_enumeration(tmp_path):
    ws = tmp_path
    _write_overlay(ws, [DISCOVERED])
    assert mf.registered_tokens(ws) == _mined() | {DISCOVERED}


def test_corrupt_overlay_degrades_to_closed(tmp_path):
    """A corrupt overlay must never half-open the vocabulary: broken
    YAML, wrong schema, and non-dict roots all read as absent."""
    for corrupt in ("{broken: [yaml", "schema: nope/9\nfamilies: []",
                    "- just\n- a\n- list\n"):
        ws = tmp_path / corrupt[:6].replace("{", "b").replace(":", "d")
        ws.mkdir(parents=True)
        (ws / "runs").mkdir()
        (ws / "runs" / "discovered-families.yaml").write_text(
            corrupt, encoding="utf-8")
        assert mf.registered_tokens(ws) == _mined(), corrupt


def test_malformed_overlay_rows_are_skipped(tmp_path):
    ws = tmp_path
    (ws / "runs").mkdir(parents=True)
    (ws / "runs" / "discovered-families.yaml").write_text(yaml.safe_dump({
        "schema": "discovered-families/1",
        "families": [
            DISCOVERED,                                # not a dict row
            {"token": "Bad_Token", "receipt": "E-1"},  # grammar violation
            {"token": "receiptless-arm"},              # no receipt id
            {"token": DISCOVERED, "receipt": "E-1"},   # the good row
        ]}), encoding="utf-8")
    assert mf.registered_tokens(ws) == _mined() | {DISCOVERED}


def test_overlay_cannot_shadow_or_duplicate_repo_tokens(tmp_path):
    ws = tmp_path
    repo_token = sorted(_mined())[0]
    _write_overlay(ws, [repo_token, DISCOVERED])
    merged = mf.registered_tokens(ws)
    assert merged == _mined() | {DISCOVERED}


# ---------------------------------------------------------------------------
# B. receipt-gated declaration (the validation path)
# ---------------------------------------------------------------------------

def test_overlay_token_with_admission_receipt_is_accepted(tmp_path):
    ws = tmp_path
    _admitted_receipt(ws)
    ok, msg = mf.validate_method_family(DISCOVERED, ws=ws)
    assert ok and msg == ""


def test_overlay_token_without_receipt_file_is_rejected(tmp_path):
    """The overlay row alone is not admission — the workspace must carry
    the E-N receipt the row cites (provenance-gated, fail-closed)."""
    ws = tmp_path
    _write_overlay(ws, [DISCOVERED])
    ok, msg = mf.validate_method_family(DISCOVERED, ws=ws)
    assert not ok
    assert "unregistered" in msg


def test_token_not_in_receipts_admitted_list_is_rejected(tmp_path):
    """The receipt exists but the cited hypothesis never admitted this
    family — a hand-edited overlay row proves nothing."""
    ws = tmp_path
    ranked = ex.admit([{"id": "h-1", "family": DISCOVERED, "p_llm": 0.3,
                        "policy": 0.0,
                        "features": {"project_type": "wasm"}}], [])
    ex.record_receipt(ws, {"obstacle_count": 3,
                           "collapsed_arms": ["static-decompile"]},
                      ranked, [])  # admitted NOTHING
    _write_overlay(ws, [DISCOVERED])
    ok, _msg = mf.validate_method_family(DISCOVERED, ws=ws)
    assert not ok


def test_no_workspace_still_rejects_the_overlay_token():
    ok, msg = mf.validate_method_family(DISCOVERED)
    assert not ok
    assert "unregistered" in msg and "other(" in msg
    ok2, msg2 = mf.validate_method_family(DISCOVERED, ws=None)
    assert not ok2 and msg2 == msg


def test_corrupt_overlay_rejects_its_tokens(tmp_path):
    ws = tmp_path
    (ws / "runs").mkdir(parents=True)
    (ws / "runs" / "discovered-families.yaml").write_text(
        "{broken: [yaml", encoding="utf-8")
    ok, msg = mf.validate_method_family(DISCOVERED, ws=ws)
    assert not ok
    assert "unregistered" in msg


def test_repo_tokens_and_other_escape_still_validate_with_ws(tmp_path):
    ws = tmp_path
    _write_overlay(ws, [DISCOVERED])
    ok, msg = mf.validate_method_family("static-decompile", ws=ws)
    assert ok and msg == ""
    ok2, _ = mf.validate_method_family("other(neat uncode trick)", ws=ws)
    assert ok2
    ok3, msg3 = mf.validate_method_family("crypto-magic", ws=ws)
    assert not ok3 and "unregistered" in msg3


# ---------------------------------------------------------------------------
# C. the overlay writer (rlvr.expansion.register_admitted)
# ---------------------------------------------------------------------------

def test_receipt_doc_carries_its_own_index(tmp_path):
    """The writer reads the E-N id from the receipt doc itself — the
    provenance chain must be self-identifying."""
    doc = ex.record_receipt(tmp_path, {"obstacle_count": 3,
                                       "collapsed_arms": ["a-fam"]},
                            [], [])
    assert doc["receipt"] == "E-1"
    doc2 = ex.record_receipt(tmp_path, {"obstacle_count": 3,
                                        "collapsed_arms": ["a-fam"]},
                             [], [])
    assert doc2["receipt"] == "E-2"


def test_register_admitted_appends_the_move_admitted_tokens(tmp_path):
    ws = tmp_path
    _admitted_receipt(ws)
    path = ws / "runs" / "discovered-families.yaml"
    assert path.is_file()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["schema"] == "discovered-families/1"
    rows = [r for r in data["families"] if r["token"] == DISCOVERED]
    assert len(rows) == 1
    assert rows[0]["receipt"] == "E-1"
    assert rows[0]["admitted_ts"]


def test_register_admitted_is_idempotent_by_token_and_receipt(tmp_path):
    ws = tmp_path
    doc = _admitted_receipt(ws)
    path = ws / "runs" / "discovered-families.yaml"
    before = path.read_bytes()
    assert ex.register_admitted(ws, doc) == []
    assert path.read_bytes() == before


def test_register_admitted_appends_again_under_a_new_receipt(tmp_path):
    """A later move re-admitting the family lands a second row — the
    idempotence key is (token, receipt), never token alone."""
    ws = tmp_path
    _admitted_receipt(ws, hid="h-1")
    ranked = ex.admit([{"id": "h-2", "family": DISCOVERED, "p_llm": 0.4,
                        "policy": 0.0,
                        "features": {"lane": "manual",
                                     "project_type": "elf"}}], [])
    doc2 = ex.record_receipt(ws, {"obstacle_count": 5,
                                  "collapsed_arms": ["dynamic-trace"]},
                             ranked, ["h-2"])
    assert doc2["receipt"] == "E-2"
    assert ex.register_admitted(ws, doc2) == [DISCOVERED]
    data = yaml.safe_load(
        (ws / "runs" / "discovered-families.yaml").read_text("utf-8"))
    assert len(data["families"]) == 2


def test_register_admitted_never_registers_non_admitted_or_ill_formed(
        tmp_path):
    """Only tokens the move actually admitted register; a non-grammar
    family and a repo-registered 'novel' arm are skipped, not written."""
    ws = tmp_path
    hyps = [
        {"id": "h-1", "family": DISCOVERED, "p_llm": 0.3, "policy": 0.0,
         "features": {"project_type": "wasm"}},
        {"id": "h-2", "family": "Not A Grammar!", "p_llm": 0.9,
         "policy": 0.0, "features": {"project_type": "elf"}},
        {"id": "h-3", "family": "static-decompile", "p_llm": 0.8,
         "policy": 0.0, "features": {"project_type": "macho"}},
    ]
    ranked = ex.admit(hyps, [])
    assert {r["id"] for r in ranked} == {"h-1", "h-2", "h-3"}, \
        "admission is feature-keyed: the name grammar is the registry's face"
    doc = ex.record_receipt(ws, {"obstacle_count": 3,
                                 "collapsed_arms": ["a-fam"]},
                            ranked, [r["id"] for r in ranked])
    added = ex.register_admitted(ws, doc)
    assert added == [DISCOVERED], \
        "repo tokens are already registered; junk grammar never registers"
    data = yaml.safe_load(
        (ws / "runs" / "discovered-families.yaml").read_text("utf-8"))
    assert [r["token"] for r in data["families"]] == [DISCOVERED]


def test_register_admitted_tolerates_a_corrupt_overlay_file(tmp_path):
    ws = tmp_path
    (ws / "runs").mkdir(parents=True)
    (ws / "runs" / "discovered-families.yaml").write_text(
        "{broken: [yaml", encoding="utf-8")
    ranked = ex.admit([{"id": "h-1", "family": DISCOVERED, "p_llm": 0.3,
                        "policy": 0.0,
                        "features": {"project_type": "wasm"}}], [])
    doc = ex.record_receipt(ws, {"obstacle_count": 3,
                                 "collapsed_arms": ["a-fam"]},
                            ranked, [r["id"] for r in ranked])
    assert ex.register_admitted(ws, doc) == [DISCOVERED]
    merged = mf.registered_tokens(ws)
    assert merged == _mined() | {DISCOVERED}


def test_register_admitted_without_admissions_writes_nothing(tmp_path):
    ws = tmp_path
    doc = ex.record_receipt(ws, {"obstacle_count": 3,
                                 "collapsed_arms": ["a-fam"]}, [], [])
    assert ex.register_admitted(ws, doc) == []
    assert not (ws / "runs" / "discovered-families.yaml").exists()


# ---------------------------------------------------------------------------
# D. the dispatch path (sampler candidates + the gate chokepoint)
# ---------------------------------------------------------------------------

def test_cold_start_candidates_include_discovered_arms(tmp_path,
                                                       monkeypatch):
    """A discovered arm rides the uniform/seeded prior like any cold arm:
    it appears in the envelope receipt's candidates on a fresh workspace."""
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(tmp_path / "store"))
    from e2e.checkpoints import _sample_envelope_family
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    _admitted_receipt(ws)
    _fam, receipt = _sample_envelope_family(ws)
    assert receipt is not None
    assert DISCOVERED in receipt["candidates"], \
        "the admitted novel arm must enter the cold-start candidate set"
    assert set(receipt["candidates"]) == _mined() | {DISCOVERED}


def test_cold_start_candidates_without_overlay_are_the_closed_set(
        tmp_path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(tmp_path / "store"))
    from e2e.checkpoints import _sample_envelope_family
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    _fam, receipt = _sample_envelope_family(ws)
    assert set(receipt["candidates"]) == _mined()


def _min_paths(ws: Path) -> dict:
    ws.mkdir(parents=True, exist_ok=True)
    return {"workspace": str(ws), "state": ws / "analysis_state.txt",
            "register": ws / "claim-register.yaml",
            "deps": ws / "claim_deps.yaml", "task_spec": ws / "task_spec.yaml"}


def _dispatch_payload(prompt: str) -> dict:
    return {"tool_input": {"name": "w-test", "description": "",
                           "prompt": prompt}}


def _envelope(family: str) -> str:
    env = {"version": 1, "claim": "C-001", "tier": 1, "tools": ["grep"],
           "agent": "w-test", "method_family": family}
    return json.dumps({"kunglao_dispatch": env}) + "\nfacts-snapshot: 1 facts"


def test_gate_accepts_a_declared_overlay_dispatch(tmp_path, capsys):
    """End-to-end through the ONE chokepoint: the envelope declares the
    discovered arm, the workspace carries its receipt — ALLOW + usage."""
    import worker_budget_sinks as sinks
    ws = tmp_path
    _admitted_receipt(ws)
    rc = sinks.pre_check(_dispatch_payload(_envelope(DISCOVERED)),
                         _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    rows = [json.loads(ln) for ln in
            (ws / "runs" / "method-family-log.jsonl")
            .read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert rows and rows[-1]["family"] == DISCOVERED


def test_gate_still_rejects_overlay_token_without_receipt(tmp_path, capsys):
    import worker_budget_sinks as sinks
    ws = tmp_path
    _write_overlay(ws, [DISCOVERED])  # overlay row, NO receipt on disk
    rc = sinks.pre_check(_dispatch_payload(_envelope(DISCOVERED)),
                         _min_paths(ws))
    assert rc == 2
    assert "REJECT methodfamily" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# E. the wiring (register after the receipt, fail-open)
# ---------------------------------------------------------------------------

def test_wiring_registers_after_the_receipt():
    src = (ROOT / "scripts" / "e2e" / "checkpoints.py").read_text(
        encoding="utf-8")
    body = src.split("def _maybe_expand")[1].split("def _maybe_distill")[0]
    receipt_at = body.find("ex.record_receipt(")
    register_at = body.find("ex.register_admitted(")
    assert receipt_at != -1, "the receipt must still land first"
    assert register_at > receipt_at, \
        "register_admitted runs after record_receipt (the overlay cites it)"


class _FakeAct:
    outcome = "DISPATCHED"
    mode = "auto"
    detail = {"duration_ms": 1000}

    def to_dict(self):
        return {"claim": "EXPANSION", "outcome": self.outcome}


class _FakeFace:
    def __init__(self, act):
        self.act = act
        self.requests = []

    def dispatch_act(self, request):
        self.requests.append(request)
        return self.act


def test_wiring_functionally_registers_the_discovered_family(tmp_path):
    """The real move, end-to-end: trigger fires -> hypotheses adjudicated
    -> receipt -> overlay. Conditional-honest like the wiring pins: if
    the termination cell never leans dead on real rows, nothing fires
    and nothing registers."""
    import types

    from e2e import checkpoints as cp
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "runs").mkdir()
    ev = tmp_path / "ev"
    ev.mkdir()
    ctx = types.SimpleNamespace(
        repo=str(ROOT), ws=ws,
        state=types.SimpleNamespace(evidence_dir=str(ev), run_id="t-run"),
        face=_FakeFace(_FakeAct()), acts=[], py=None,
        sleep_fn=lambda s: None)
    obs = cp._load_repo_module(ROOT, "rlvr.obstacles")
    for i in range(4):
        evf = ws / f"runs/ev-{i}.md"
        evf.write_text("command: probe\ncmd_rc: 1\nobserved: fail\n",
                       encoding="utf-8")
        obs.record(str(ws), kind="other", cause=f"probe-{i}",
                   evidence_path="runs/ev-{i}.md".format(i=i),
                   method_family="static-decompile", claim=f"C-{i}")
    (ws / "runs" / "expansion-hypotheses.json").write_text(json.dumps({
        "hypotheses": [{"id": "h-1", "family": DISCOVERED, "p_llm": 0.3,
                        "features": {"lane": "dynamic",
                                     "project_type": "wasm"}}]}),
        encoding="utf-8")
    cp._maybe_expand(ctx, {"DISTILL"}, {})
    receipts = ex.read_receipts(ws)
    if not receipts:
        # the trigger never crossed the threshold on real rows — the
        # honest no-fire shape: no receipt, no registration
        assert not (ws / "runs" / "discovered-families.yaml").exists()
        return
    assert receipts[0]["admitted"] == ["h-1"]
    overlay = ws / "runs" / "discovered-families.yaml"
    assert overlay.is_file(), \
        "a fired-and-admitted move registers its tokens into the overlay"
    data = yaml.safe_load(overlay.read_text(encoding="utf-8"))
    assert DISCOVERED in [r["token"] for r in data["families"]]

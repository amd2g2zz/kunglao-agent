# -*- coding: utf-8 -*-
"""tests/test_antiforgery_1005.py — the anti-forgery slice (issue 1005).

Worker-forgeable settlement inputs become harness-written and sealed,
and workspace init provisions the learning key:

  1. R8 — armed, a worker-written (unsealed) verdict file is refused at
     the read face and settles nothing; the sanctioned writer's sealed
     doc settles the same chain end to end.
  2. Unarmed equivalence — every new face rides the legacy bytes
     byte-identically (the CI posture: no key, legacy behavior).
  3. oracle-status — the canonical writer seals; the Φ oracle face
     refuses an unsealed doc armed and accepts the writer's.
  4. l1-value-log / recipe_arms rows / posteriors.yaml / hypotheses
     store — sealed at their sanctioned writers, refused at their read
     faces armed, pass-through unarmed.
  5. write_guard — the anti-forgery Write/Edit face refuses armed,
     allows unarmed.
  6. init provisioning — the init CLI arms the channel (idempotent:
     an existing key is kept verbatim, never rotated), refuses loudly
     on a genuine provisioning failure, and never prints key material.

Keys live on tmp paths only (conftest autouse isolation + child HOME
isolation). Fixtures are synthetic.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import kunglao_log  # noqa: E402
from kunglao_log import _LEVEL_LAST, _WARN_LAST  # noqa: E402
from rlvr import learning_seal as seal  # noqa: E402
from rlvr import settlement_wire as wire  # noqa: E402

T0 = datetime(2026, 11, 16, 9, 0, 0, tzinfo=timezone.utc)
FAM = "static-decompile"
CLAIM = "C-6"


# ------------------------------------------------------------- fixtures

@pytest.fixture
def key(tmp_path, monkeypatch):
    """A tmp key path + fresh per-process face gates (never the host's
    real key)."""
    k = tmp_path / "learning.key"
    monkeypatch.setattr(kunglao_log, "_WARN_WS_OVERRIDE", [])
    monkeypatch.setattr(seal, "KEY_PATH", k, raising=False)
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None}, raising=False)
    monkeypatch.setattr(seal, "_NOTICE", {"shown": False}, raising=False)
    monkeypatch.setattr(seal, "_FACE", {"shown": False}, raising=False)
    monkeypatch.setattr(seal, "_POSTURE", {"armed": None}, raising=False)
    _WARN_LAST.clear()
    _LEVEL_LAST.clear()
    return k


@pytest.fixture
def armed(key):
    """An ARMED channel via the module's own provisioning face."""
    st = seal.provision()
    assert st["armed"] is True, st
    return key


# ------------------------------------------------------------- helpers

def _ws(tmp_path: Path, claims: list[dict] | None = None) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "evidence").mkdir()
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims or [{"id": CLAIM,
                                              "status": "OPEN"}]}),
        encoding="utf-8")
    return ws


def _mint(ws: Path) -> str:
    import claims_store
    from rlvr import q_cells
    began = claims_store.begin_dispatch(
        ws, CLAIM, "hook:worker_budget", tier=1, prompt="fixture",
        agent="w-test", method_family=FAM)
    assert began.ok, CLAIM
    assert claims_store.commit_dispatch(ws, CLAIM).ok, CLAIM
    assert claims_store.confirm_dispatch(ws, CLAIM)
    did = str(began.journal_id)
    out = q_cells.record_dispatch_observation(
        ws, "fixture envelope", envelope_meta={"method_family": FAM},
        claim=CLAIM, agent="w-test", dispatch_id=did)
    assert out["appended"] is True, CLAIM
    return did


def _park(ws: Path, tmp_path: Path) -> None:
    art = ws / "evidence" / f"step-{CLAIM}.bin"
    art.write_bytes(b"raw-step-artifact-bytes")
    rules = tmp_path / "reward-rules.yaml"
    rules.write_text("rules: synthetic-settlement-rules\n", encoding="utf-8")
    out = wire.park_blind_input(ws, CLAIM,
                                [art.relative_to(ws).as_posix()],
                                rules_path=str(rules))
    assert out["parked"] is True, out


def _forge_verdict(ws: Path, credit: float = 1.0) -> Path:
    """The worker forgery: the verdict doc hand-written to the canonical
    path — it never passed the sanctioned writer."""
    parked = wire.load_parked(ws, CLAIM)
    evidence = [a.get("path") for a in (parked.get("artifacts") or [])]
    doc = {
        "schema": "settlement-verdict/1",
        "identity": "kunglao-settler",
        "claim": CLAIM,
        "actions": [{"action_id": f"step-{CLAIM}", "credit": credit,
                     "evidence": evidence}],
        "trajectory_credit": credit,
    }
    p = ws / "runs" / f"settlement-verdict-{CLAIM}.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n",
                 encoding="utf-8")
    return p


def _settler_doc(evidence: list, credit: float = 1.0) -> dict:
    return {
        "schema": "settlement-verdict/1",
        "identity": "kunglao-settler",
        "claim": CLAIM,
        "actions": [{"action_id": f"step-{CLAIM}", "credit": credit,
                     "evidence": evidence}],
        "trajectory_credit": credit,
    }


def _parked_evidence(ws: Path) -> list:
    parked = wire.load_parked(ws, CLAIM)
    return [a.get("path") for a in (parked.get("artifacts") or [])]


def _verification(ws: Path) -> None:
    (ws / "runs" / f"verification-{CLAIM}.md").write_text(
        "verdict: verified\n", encoding="utf-8")


def _settle(ws: Path) -> dict:
    _verification(ws)
    return wire.settle_parked(ws, CLAIM, oracle_verdict="pass",
                              has_reproducible_evidence=True, now=T0)


# --------------------------------------------------- 1. R8 (armed host)

def test_armed_worker_forged_verdict_is_refused(key, armed, tmp_path):
    ws = _ws(tmp_path)
    _mint(ws)
    _park(ws, tmp_path)
    _forge_verdict(ws)                      # the worker forgery, unsealed

    res = _settle(ws)

    assert res["settled"] is False, res
    assert "unparseable" in res["reason"] or "refused" in res["reason"], res
    assert "q_cell_bank" not in res, res    # nothing banked
    from rlvr import ledger as rl
    st = (rl.fold(ws, f"task/{CLAIM}") or {}).get("settlement") or {}
    assert not st, st                       # no settlement mass anywhere


def test_armed_sanctioned_writer_settles_the_same_chain(key, armed,
                                                        tmp_path):
    ws = _ws(tmp_path)
    _mint(ws)
    _park(ws, tmp_path)
    out = wire.write_sealed_verdict(
        ws, CLAIM, _settler_doc(_parked_evidence(ws), credit=1.0))
    assert out["sealed"] is True, out
    doc = json.loads(
        (ws / "runs" / f"settlement-verdict-{CLAIM}.json")
        .read_text(encoding="utf-8"))
    ok, why = seal.verify_row(doc)
    assert ok, why

    res = _settle(ws)

    assert res["settled"] is True, res
    from rlvr import ledger as rl
    st = rl.fold(ws, f"task/{CLAIM}").get("settlement") or {}
    assert st.get("reward") == 1.0, st
    bank = res.get("q_cell_bank") or {}
    assert bank.get("matched") and bank.get("appended"), res


def test_armed_tampered_sealed_verdict_is_refused(key, armed, tmp_path):
    ws = _ws(tmp_path)
    _mint(ws)
    _park(ws, tmp_path)
    wire.write_sealed_verdict(
        ws, CLAIM, _settler_doc(_parked_evidence(ws), credit=0.4))
    p = ws / "runs" / f"settlement-verdict-{CLAIM}.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["trajectory_credit"] = 1.0          # post-seal edit
    p.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n",
                 encoding="utf-8")

    res = _settle(ws)

    assert res["settled"] is False, res


def test_armed_writer_walls(key, armed, tmp_path):
    ws = _ws(tmp_path)
    _park(ws, tmp_path)
    ev = _parked_evidence(ws)
    with pytest.raises(ValueError, match="schema"):
        wire.write_sealed_verdict(ws, CLAIM, {"schema": "other/1"})
    doc = _settler_doc(ev)
    doc["claim"] = "C-OTHER"
    with pytest.raises(ValueError, match="claim"):
        wire.write_sealed_verdict(ws, CLAIM, doc)
    doc = _settler_doc(ev)
    doc["identity"] = "  "
    with pytest.raises(ValueError, match="identity"):
        wire.write_sealed_verdict(ws, CLAIM, doc)
    doc = _settler_doc(ev)
    doc["seal"] = {"schema": "forged"}
    out = wire.write_sealed_verdict(ws, CLAIM, doc)
    landed = json.loads(
        (ws / "runs" / f"settlement-verdict-{CLAIM}.json")
        .read_text(encoding="utf-8"))
    assert out["sealed"] is True and landed["seal"]["schema"] == \
        seal.SEAL_SCHEMA  # a caller-supplied seal is never carried


# --------------------------------------- 2. unarmed equivalence (CI)

def test_unarmed_forged_verdict_rides_legacy(key, tmp_path):
    ws = _ws(tmp_path)
    _mint(ws)
    _park(ws, tmp_path)
    _forge_verdict(ws)
    assert seal.armed() is False

    res = _settle(ws)

    assert res["settled"] is True, res      # byte-identical legacy face
    from rlvr import ledger as rl
    st = rl.fold(ws, f"task/{CLAIM}").get("settlement") or {}
    assert st.get("reward") == 1.0, st


def test_unarmed_writer_lands_legacy_bytes(key, tmp_path):
    ws = _ws(tmp_path)
    _park(ws, tmp_path)
    body = _settler_doc(_parked_evidence(ws))
    out = wire.write_sealed_verdict(ws, CLAIM, body)
    assert out["sealed"] is False
    want = json.dumps({k: v for k, v in body.items() if k != "seal"},
                      ensure_ascii=False, sort_keys=True) + "\n"
    got = (ws / "runs" / f"settlement-verdict-{CLAIM}.json") \
        .read_text(encoding="utf-8")
    assert got == want                      # byte-identical legacy file


# --------------------------------------------- 3. oracle-status.json

def _status_report() -> dict:
    return {
        "schema": "oracle-status/1",
        "cases": {"OC-1": {"status": "pass", "pending_entries": 0,
                           "instrumented": True}},
        "counts": {"red": 0, "green": 1, "pending": 0},
    }


def test_armed_writer_seals_oracle_status_and_phi_accepts(armed, tmp_path):
    from rlvr.incremental_reward import _oracle_progress_sealed
    from oracle_runner import write_status
    ws = _ws(tmp_path)
    write_status(ws, _status_report())
    doc = json.loads((ws / "runs" / "oracle-status.json")
                     .read_text(encoding="utf-8"))
    assert isinstance(doc.get("seal"), dict)
    ok, why = seal.verify_row(doc)
    assert ok, why
    assert _oracle_progress_sealed(ws) == (1, 1)


def test_armed_unsealed_oracle_status_is_refused(armed, tmp_path):
    from rlvr.incremental_reward import _oracle_progress_sealed
    ws = _ws(tmp_path)
    (ws / "runs" / "oracle-status.json").write_text(
        json.dumps(_status_report(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    assert _oracle_progress_sealed(ws) is None   # the oracle dim drops


def test_unarmed_oracle_status_is_byte_identical(key, tmp_path):
    from oracle_runner import write_status
    ws = _ws(tmp_path)
    write_status(ws, _status_report())
    doc = _status_report()
    want_doc = {"schema": doc["schema"], "cases": doc["cases"],
                "low_discriminativity": [],  # the writer's additive default
                "counts": doc["counts"]}
    want = json.dumps(want_doc, ensure_ascii=False, indent=2) + "\n"
    got = (ws / "runs" / "oracle-status.json").read_text(encoding="utf-8")
    assert got == want                      # the legacy file, byte for byte


# --------------------------------------------- 4a. l1-value-log.jsonl

def test_armed_l1_log_seals_at_the_writer_and_folds(armed, tmp_path):
    from rlvr import l1_value as l1
    ws = _ws(tmp_path)
    out = l1.record_observation(ws, "a" * 12, "dispatch", 0.8,
                                claim=CLAIM, source="terminal")
    assert out["appended"] is True
    line = json.loads(
        (ws / "runs" / "l1-value-log.jsonl").read_text(
            encoding="utf-8").splitlines()[-1])
    assert isinstance(line.get("seal"), dict)
    fold = l1.fold(l1.default_store(ws))
    assert sum(c.success for c in fold.cells.values()) == pytest.approx(0.8)

    # a worker-forged raw row never folds
    p = ws / "runs" / "l1-value-log.jsonl"
    forged = {"schema": l1.OBS_SCHEMA, "ts": T0.strftime(
        "%Y-%m-%dT%H:%M:%SZ"), "source": "terminal", "claim": CLAIM,
        "state_signature": "b" * 12, "action_kind": "dispatch",
        "return": 100.0}
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(forged, ensure_ascii=False) + "\n")
    fold2 = l1.fold(l1.default_store(ws))
    assert sum(c.success for c in fold2.cells.values()) == pytest.approx(
        0.8)                                # the forged 100.0 never lands


def test_unarmed_l1_log_is_byte_identical(key, tmp_path):
    from rlvr import l1_value as l1
    ws = _ws(tmp_path)
    out = l1.record_observation(ws, "a" * 12, "dispatch", 0.8,
                                claim=CLAIM, source="terminal")
    row = out["row"]
    assert "seal" not in row
    want = json.dumps(row, ensure_ascii=False) + "\n"
    got = (ws / "runs" / "l1-value-log.jsonl").read_text(encoding="utf-8")
    assert got == want
    # legacy fold counts a raw unsealed row too
    fold = l1.fold(l1.default_store(ws))
    assert sum(c.success for c in fold.cells.values()) == pytest.approx(0.8)


# --------------------------------------------- 4b. recipe_arms rows

def test_armed_arm_fold_refuses_forged_rows(armed, tmp_path):
    from rlvr import recipe_arms as ra
    ws = _ws(tmp_path)
    from rlvr import q_cells as qc
    qc.append_observation(ws, "a" * 12, FAM, 0.9, source="settlement",
                          claim=CLAIM, recipe_id="disasm:ghidra-headless",
                          recipe_propensity=0.5, recipe_source="sampled")
    fold = ra.arm_fold(ws)
    assert fold["disasm:ghidra-headless"]["success"] == pytest.approx(0.9)
    assert fold["disasm:radare2"]["success"] == 0.0

    # the forgery: a raw unsealed settlement row carrying 1.0
    from rlvr import consolidated_ledger as cl
    forged = {"schema": qc.OBS_SCHEMA, "ts": "2026-11-16T09:00:00Z",
              "source": "settlement", "claim": CLAIM, "agent": "w-forge",
              "signature_hash": "b" * 12, "method_family": FAM,
              "credit": 1.0, "recipe_id": "disasm:radare2"}
    p = cl.family_path(ws, "experience")
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(forged, ensure_ascii=False) + "\n")
    fold2 = ra.arm_fold(ws)
    assert fold2["disasm:radare2"]["success"] == 0.0   # never folds
    assert fold2["disasm:ghidra-headless"]["success"] == pytest.approx(0.9)


def test_unarmed_arm_fold_rides_legacy(key, tmp_path):
    from rlvr import recipe_arms as ra
    from rlvr import consolidated_ledger as cl
    ws = _ws(tmp_path)
    forged = {"schema": "q-cell-obs/1", "ts": "2026-11-16T09:00:00Z",
              "source": "settlement", "claim": CLAIM, "agent": "w-forge",
              "signature_hash": "b" * 12, "method_family": FAM,
              "credit": 1.0, "recipe_id": "disasm:radare2"}
    p = cl.family_path(ws, "experience")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(forged, ensure_ascii=False) + "\n")
    fold = ra.arm_fold(ws)
    assert fold["disasm:radare2"]["success"] == pytest.approx(1.0)  # legacy


# --------------------------------------------- 4c. posteriors.yaml

def test_armed_posteriors_seal_round_trips(armed, tmp_path):
    from posteriors_case import CasePosterior, PosteriorLedger
    ws = _ws(tmp_path)
    led = PosteriorLedger()
    led.cases["OC-1"] = CasePosterior("OC-1", alpha=2.0, beta=1.0)
    led.save(ws)
    doc = yaml.safe_load(
        (ws / "runs" / "posteriors.yaml").read_text(encoding="utf-8"))
    assert isinstance(doc.get("seal"), dict)
    loaded = PosteriorLedger.load(ws)
    assert loaded.degraded is False, loaded.warnings
    assert loaded.cases["OC-1"].alpha == 2.0
    assert loaded.cases["OC-1"].beta == 1.0


def test_armed_forged_posteriors_are_refused(armed, tmp_path):
    from posteriors_case import PosteriorLedger
    ws = _ws(tmp_path)
    forged = {"schema": "posteriors-schema/1",
              "cases": {"OC-1": {"alpha": 99.0, "beta": 0.0}},
              "pqs": {}}
    (ws / "runs" / "posteriors.yaml").write_text(
        yaml.safe_dump(forged, allow_unicode=True, sort_keys=True),
        encoding="utf-8")
    loaded = PosteriorLedger.load(ws)
    assert loaded.degraded is True
    assert loaded.cases == {}               # the forged mass never loads
    assert any("seal" in w for w in loaded.warnings)


def test_unarmed_posteriors_are_byte_identical(key, tmp_path):
    from posteriors_case import CasePosterior, PosteriorLedger
    ws = _ws(tmp_path)
    led = PosteriorLedger()
    led.cases["OC-1"] = CasePosterior("OC-1", alpha=2.0, beta=1.0)
    led.save(ws)
    want = yaml.safe_dump(led.to_doc(), allow_unicode=True, sort_keys=True)
    got = (ws / "runs" / "posteriors.yaml").read_text(encoding="utf-8")
    assert got == want                      # the legacy file, byte for byte
    loaded = PosteriorLedger.load(ws)
    assert loaded.degraded is False


# --------------------------------------------- 4d. hypotheses store

def _hyp(tmp_path: Path) -> Path:
    from hypothesis_store import Hypothesis, HypothesisStore
    ws = _ws(tmp_path)
    store = HypothesisStore(ws / "hypotheses")
    h = Hypothesis(id="H-001", claim_id=CLAIM,
                   competitor_group="prng-vs-cipher",
                   candidates=["AES", "ChaCha20"], status="open",
                   body="motivation body")
    store.create(h)
    return ws


def test_armed_hypothesis_seal_round_trips(armed, tmp_path):
    from hypothesis_store import HypothesisStore
    ws = _hyp(tmp_path)
    p = ws / "hypotheses" / "H-001.md"
    text = p.read_text(encoding="utf-8")
    assert "\nseal: " in text
    got = HypothesisStore(ws / "hypotheses").get("H-001")
    assert got.status == "open" and got.body == "motivation body"
    assert [h.id for h in
            HypothesisStore(ws / "hypotheses").list_all()] == ["H-001"]

    # post-seal tamper is refused
    p.write_text(text.replace("motivation body", "MOTIVATION EDITED"),
                 encoding="utf-8")
    with pytest.raises(ValueError):
        HypothesisStore(ws / "hypotheses").get("H-001")
    assert [h.id for h in
            HypothesisStore(ws / "hypotheses").list_all()] == []


def test_armed_unsealed_hypothesis_is_refused(armed, tmp_path):
    from hypothesis_store import Hypothesis, HypothesisStore
    ws = _ws(tmp_path)
    p = ws / "hypotheses" / "H-002.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    h = Hypothesis(id="H-002", claim_id=CLAIM,
                   competitor_group="g", candidates=["A"],
                   body="hand-written")
    p.write_text(h.to_frontmatter() + "\n" + h.body + "\n",
                 encoding="utf-8")
    with pytest.raises(ValueError):
        HypothesisStore(ws / "hypotheses").get("H-002")


def test_unarmed_hypothesis_is_byte_identical(key, tmp_path):
    from hypothesis_store import Hypothesis, HypothesisStore
    ws = _ws(tmp_path)
    store = HypothesisStore(ws / "hypotheses")
    h = Hypothesis(id="H-001", claim_id=CLAIM,
                   competitor_group="g", candidates=["A"],
                   body="motivation body")
    store.create(h)
    want = h.to_frontmatter() + "\n" + h.body + "\n"
    got = (ws / "hypotheses" / "H-001.md").read_text(encoding="utf-8")
    assert got == want                      # the legacy file, byte for byte
    assert store.get("H-001").status == "open"


# --------------------------------------------- 5. write_guard face

_WS_GUARD = str(ROOT / "hooks" / "write_guard.py")


def _guard_payload(ws: Path, target: Path) -> str:
    return json.dumps({
        "tool_name": "Write", "cwd": str(ws),
        "tool_input": {"file_path": str(target),
                       "content": '{"schema": "settlement-verdict/1"}'},
    }, ensure_ascii=False)


def _run_guard(ws: Path, payload: str, home: Path) -> subprocess:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(ROOT / "hooks"), str(ROOT / "scripts")])
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    return subprocess.run(
        [sys.executable, _WS_GUARD], input=payload, capture_output=True,
        text=True, timeout=60, env=env, errors="replace")


def _mk_guard_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "guard-ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs").mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-001\n  status: OPEN\n", encoding="utf-8")
    return ws


def _provision_in_home(home: Path) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(ROOT / "scripts")])
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'scripts'); "
         "from rlvr import learning_seal; learning_seal.provision()"],
        capture_output=True, text=True, timeout=60, env=env,
        cwd=str(ROOT), check=True)


def test_write_guard_refuses_armed_verdict_write(tmp_path):
    ws = _mk_guard_ws(tmp_path)
    home = tmp_path / "guard-home"
    home.mkdir()
    _provision_in_home(home)
    target = ws / "runs" / f"settlement-verdict-{CLAIM}.json"
    proc = _run_guard(ws, _guard_payload(ws, target), home)
    assert proc.returncode == 2, (proc.returncode, proc.stderr[-500:])
    assert "harness-written" in proc.stderr
    assert not target.exists()


def test_write_guard_refuses_armed_oracle_status_write(tmp_path):
    ws = _mk_guard_ws(tmp_path)
    home = tmp_path / "guard-home"
    home.mkdir()
    _provision_in_home(home)
    target = ws / "runs" / "oracle-status.json"
    proc = _run_guard(ws, _guard_payload(ws, target), home)
    assert proc.returncode == 2, (proc.returncode, proc.stderr[-500:])


def test_write_guard_allows_unarmed_verdict_write(tmp_path):
    ws = _mk_guard_ws(tmp_path)
    home = tmp_path / "guard-home-empty"
    home.mkdir()
    target = ws / "runs" / f"settlement-verdict-{CLAIM}.json"
    proc = _run_guard(ws, _guard_payload(ws, target), home)
    assert proc.returncode == 0, (proc.returncode, proc.stderr[-500:])


def test_write_guard_allows_unrelated_paths_armed(tmp_path):
    ws = _mk_guard_ws(tmp_path)
    home = tmp_path / "guard-home"
    home.mkdir()
    _provision_in_home(home)
    target = ws / "runs" / "notes-draft.md"
    proc = _run_guard(ws, _guard_payload(ws, target), home)
    assert proc.returncode == 0, (proc.returncode, proc.stderr[-500:])


# --------------------------------------------- 6. init provisioning

_INIT_FLAGS = ["--type", "linux", "--lane", "algorithm",
               "--skip-toolchain", "--host-exec-protection", "enabled",
               "--assume-yes"]


def _init_run(ws: Path, home: Path) -> subprocess.CompletedProcess:
    from _factories import seed_bins, seed_oracle_anchors
    (ws / "bins").mkdir(parents=True, exist_ok=True)
    seed_bins(ws)
    seed_oracle_anchors(ws)
    env = dict(os.environ)
    env.pop("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "kunglao-init.py"),
         str(ws), *_INIT_FLAGS, "--profile-root",
         str(ws.parent / "profile-root")],
        capture_output=True, text=True, timeout=180, env=env,
        errors="replace")


def test_init_provisions_the_seal(tmp_path):
    ws = tmp_path / "ws-init"
    home = tmp_path / "home-init"
    home.mkdir()
    proc = _init_run(ws, home)
    assert proc.returncode == 0, (
        proc.returncode, proc.stdout[-800:], proc.stderr[-800:])
    keyp = home / ".claude" / ("kunglao-learning" + ".key")
    assert keyp.is_file()
    assert (keyp.stat().st_mode & 0o777) == 0o600
    first = keyp.read_bytes()
    assert "ARMED" in proc.stderr          # the receipt rides stderr
    # the key material never prints
    assert first.decode("ascii", errors="ignore") not in proc.stdout
    assert first.decode("ascii", errors="ignore") not in proc.stderr

    # idempotent: a re-run keeps the key verbatim (never rotated)
    proc2 = _init_run(ws, home)
    assert proc2.returncode == 0, proc2.stderr[-500:]
    assert keyp.read_bytes() == first


def test_init_keeps_a_pre_existing_key(tmp_path):
    ws = tmp_path / "ws-init2"
    home = tmp_path / "home-init2"
    (home / ".claude").mkdir(parents=True)
    keyp = home / ".claude" / ("kunglao-learning" + ".key")
    keyp.write_bytes(b"f" * 64)
    keyp.chmod(0o600)                       # already tight: kept untouched
    proc = _init_run(ws, home)
    assert proc.returncode == 0, proc.stderr[-800:]
    assert keyp.read_bytes() == b"f" * 64   # never rotated
    assert "left untouched" in (proc.stdout + proc.stderr)


def test_init_refuses_loudly_when_provisioning_fails(tmp_path):
    ws = tmp_path / "ws-init3"
    home = tmp_path / "home-init3"
    home.mkdir()
    # a regular file blocking the key directory: ENOTDIR for ANY user —
    # a chmod-based unwritable directory is bypassed by a root runner
    (home / ".claude").write_text("not a directory")
    proc = _init_run(ws, home)
    assert proc.returncode != 0
    assert "provisioning failed" in proc.stderr
    # nothing scaffolded: the refusal precedes the workspace writes
    assert not (ws / "claim-register.yaml").exists()


# --------------------------------------------- the verdict CLI face

def test_verdict_cli_lands_sealed_bytes_unarmed(tmp_path):
    ws = _ws(tmp_path)
    _park(ws, tmp_path)
    home = tmp_path / "cli-home"
    home.mkdir()
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "scripts")])
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["PYTHONIOENCODING"] = "utf-8"
    body = json.dumps(_settler_doc(_parked_evidence(ws)),
                        ensure_ascii=False)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "kunglao.py"), "seal",
         "verdict-write", str(ws), CLAIM],
        input=body, capture_output=True, text=True, timeout=60, env=env,
        errors="replace")
    assert proc.returncode == 0, (proc.stdout[-400:], proc.stderr[-400:])
    assert "unsealed" in proc.stdout
    doc = json.loads(
        (ws / "runs" / f"settlement-verdict-{CLAIM}.json")
        .read_text(encoding="utf-8"))
    assert "seal" not in doc


def test_verdict_cli_refuses_a_wall_miss(tmp_path):
    ws = _ws(tmp_path)
    home = tmp_path / "cli-home2"
    home.mkdir()
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "scripts")])
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "kunglao.py"), "seal",
         "verdict-write", str(ws), CLAIM],
        input="not json", capture_output=True, text=True, timeout=60,
        env=env, errors="replace")
    assert proc.returncode == 1
    assert "not JSON" in proc.stderr

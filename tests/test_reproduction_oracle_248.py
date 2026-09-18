# -*- coding: utf-8 -*-
"""Algorithm claims settle on reproduction, not endpoint
observations. Three pieces, owner-ruled folk-in design:

  1. intake maps generation-language to the reproduction oracle
     (scripts/oracle_anchors.py)
  2. admission executes closed-book with verifier-sampled novel inputs
     (scripts/replay_equivalence.py)
  3. evidence settles by need (scripts/settle_by_need.py)
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import oracle_anchors  # noqa: E402
import replay_equivalence as req  # noqa: E402
import settle_by_need  # noqa: E402


# --------------------------------------------------- mock web-signer fixture

def _true_sign(inputs: dict) -> str:
    """The toy signing algorithm only the SOURCE knows."""
    return hashlib.sha256(
        f"{inputs['appkey']}|{inputs['ts']}|{inputs['nonce']}"
        .encode()).hexdigest()


APPKEY = "k1"
CAPTURED = [
    {"appkey": APPKEY, "ts": "1700000000", "nonce": "aaa"},
    {"appkey": APPKEY, "ts": "1700000001", "nonce": "bbb"},
    {"appkey": APPKEY, "ts": "1700000002", "nonce": "ccc"},
]
VARIABLES = {"ts": ["1700000000", "1700000001", "1700000002", "1700000003"],
             "nonce": ["aaa", "bbb", "ccc", "ddd"]}


def _reference_source(inputs: dict) -> str:
    """Adapter stub: the verifier obtains the reference output FROM THE
    SOURCE (server submit / browser debug-anchoring in production)."""
    return _true_sign(inputs)


def _closed_book_client_source() -> str:
    """A reproduction client derived from the reversed algorithm."""
    return (
        "import hashlib\n"
        "def compute(params):\n"
        "    return hashlib.sha256(\n"
        "        f\"{params['appkey']}|{params['ts']}|{params['nonce']}\""
        ".encode()).hexdigest()\n"
    )


def _echo_client_source() -> str:
    """A replay-only 'client': it can only echo captured signatures
    (the field-evidence pathology, made executable)."""
    table = {
        json.dumps({k: p[k] for k in ("appkey", "ts", "nonce")},
                   sort_keys=True): _true_sign(p)
        for p in CAPTURED}
    return (
        "import json\n"
        f"_TABLE = {json.dumps(table, sort_keys=True)}\n"
        "def compute(params):\n"
        "    return _TABLE.get(json.dumps(params, sort_keys=True))\n"
    )


def _echo_plus_novel_miss_client_source(novel_inputs: dict) -> str:
    """A replay-only client whose table ALSO maps the novel inputs to the
    recorded 'miss' output — the schema-honest fabrication shape the
    recorded-novel-row face must catch (recompute == recorded repro_output,
    but the recorded reference and flag tell a different story)."""
    table = {
        json.dumps({k: p[k] for k in ("appkey", "ts", "nonce")},
                   sort_keys=True): _true_sign(p)
        for p in CAPTURED}
    table[json.dumps(novel_inputs, sort_keys=True)] = "garbage"
    return (
        "import json\n"
        f"_TABLE = {json.dumps(table, sort_keys=True)}\n"
        "def compute(params):\n"
        "    return _TABLE.get(json.dumps(params, sort_keys=True))\n"
    )


def _ws_with_artifact(tmp_path: Path, *, client_source: str | None,
                      repro_override: str | None = None,
                      include_novel: bool = False,
                      rng_seed: int = 248) -> tuple[Path, Path]:
    """Workspace with a replay artifact over the mock-signer captures,
    optionally a reproduction_client module on disk."""
    ws = tmp_path / "ws"
    (ws / "evidence").mkdir(parents=True)
    pairs = []
    for i, p in enumerate(CAPTURED):
        sig = _true_sign(p)
        pairs.append({
            "input_id": f"cap-{i:02d}",
            "inputs": dict(p),
            "ref_output": sig,
            "repro_output": repro_override if repro_override is not None
            else sig,
            "byte_equal": True,
        })
    doc = {
        "schema": req.SCHEMA_ID,
        "claim_id": "C-1",
        "captured_inputs": [f"cap-{i:02d}" for i in range(len(CAPTURED))],
        "variables": VARIABLES,
        "pairs": pairs,
    }
    if client_source is not None:
        client = ws / "reproduction_client.py"
        client.write_text(client_source, encoding="utf-8")
        doc["reproduction_client"] = "reproduction_client.py"
    if include_novel:
        novel = req.sample_novel_input(VARIABLES, CAPTURED,
                                       random.Random(rng_seed))
        base = dict(CAPTURED[0])
        base.update({k: v for k, v in novel.items() if k in VARIABLES})
        novel_inputs = {k: v for k, v in base.items()
                        if k in list(VARIABLES) + ["appkey"]}
        doc["pairs"].append({
            "input_id": "novel-01",
            "inputs": novel_inputs,
            "ref_output": _reference_source(novel_inputs),
            "repro_output": _true_sign(novel_inputs),
            "byte_equal": True,
            "novel_input": True,
        })
    path = ws / "evidence" / "replay-C-1.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return ws, path


# ------------------------------------------- 1. intake: generation-language

@pytest.mark.parametrize("goal", [
    "签名参数是怎么生成的",
    "这个签名字段是怎么算出来的",
    "签名算法的什么原理",
    "请求是如何构造的",
    "how is the signature computed",
    "what algorithm generates the token",
])
def test_generation_language_is_detected(goal):
    assert oracle_anchors.is_generation_language(goal)


@pytest.mark.parametrize("goal", [
    "登录接口能返回 200",
    "replay the captured request successfully",
    "接口是否可访问",
])
def test_acceptance_language_is_not_generation(goal):
    assert not oracle_anchors.is_generation_language(goal)


def test_intake_pins_reproduction_for_algorithm_class():
    spec = {"goal_verbatim": "签名参数是怎么生成的",
            "success_criterion": "closed-book reproduction matches",
            "verification_method": "replay-evidence"}
    assert oracle_anchors.derive_verification_method(spec) == "reproduction"


def test_intake_refuses_weak_selection_for_algorithm_class():
    spec = {"goal_verbatim": "签名参数是怎么生成的",
            "success_criterion": "x",
            "verification_method": "replay-evidence"}
    ok, reason = oracle_anchors.intake_method_gate(spec)
    assert not ok
    assert "replay-evidence" in reason


def test_intake_gate_allows_replay_for_acceptance_class():
    spec = {"goal_verbatim": "登录接口能返回 200",
            "success_criterion": "x",
            "verification_method": "replay-evidence"}
    ok, reason = oracle_anchors.intake_method_gate(spec)
    assert ok, reason


# ------------------------------- 2. admission: closed-book + novel inputs

def test_admission_refuses_artifact_without_runnable_client(tmp_path):
    """The copy-both-sides artifact (ref == repro == captured signature,
    no client) that passed admission before is now refused."""
    ws, path = _ws_with_artifact(tmp_path, client_source=None)
    errs = req.admission_errors(ws, json.loads(path.read_text()))
    assert errs and "reproduction_client" in errs[0]


def test_admission_refuses_fabricated_repro_output(tmp_path):
    """Client exists, but recomputed != recorded repro_output -> fabrication."""
    ws, path = _ws_with_artifact(
        tmp_path, client_source=_closed_book_client_source(),
        repro_override="deadbeef")
    errs = req.admission_errors(ws, json.loads(path.read_text()))
    assert errs and "fabrication" in errs[0].lower()


def test_admission_passes_honest_closed_book_artifact(tmp_path):
    """Corrected contract: an honest closed-book artifact satisfies
    admission only WITH the required recorded novel-input row."""
    ws, path = _ws_with_artifact(
        tmp_path, client_source=_closed_book_client_source(),
        include_novel=True)
    assert req.admission_errors(ws, json.loads(path.read_text())) == []


NOVEL_INPUTS = {"appkey": APPKEY, "ts": "1700000003", "nonce": "ddd"}


def _miss_artifact_ws(tmp_path: Path) -> Path:
    """Workspace whose artifact records a schema-honest novel MISS:
    ref_output is the real source signature, repro_output is garbage,
    byte_equal is false — and the declared client (an echo table that
    also maps the novel inputs to 'garbage') recomputes exactly the
    recorded repro_output, so the recorded-repro face alone stays silent."""
    ws = tmp_path / "ws"
    (ws / "evidence").mkdir(parents=True)
    doc = {
        "schema": req.SCHEMA_ID,
        "claim_id": "C-1",
        "captured_inputs": [f"cap-{i:02d}" for i in range(len(CAPTURED))],
        "variables": VARIABLES,
        "reproduction_client": "reproduction_client.py",
        "pairs": [{
            "input_id": f"cap-{i:02d}",
            "inputs": dict(p),
            "ref_output": _true_sign(p),
            "repro_output": _true_sign(p),
            "byte_equal": True,
        } for i, p in enumerate(CAPTURED)] + [{
            "input_id": "novel-01",
            "inputs": dict(NOVEL_INPUTS),
            "ref_output": _true_sign(NOVEL_INPUTS),
            "repro_output": "garbage",
            "byte_equal": False,
            "novel_input": True,
        }],
    }
    (ws / "reproduction_client.py").write_text(
        _echo_plus_novel_miss_client_source(NOVEL_INPUTS), encoding="utf-8")
    (ws / "evidence" / "replay-C-1.json").write_text(json.dumps(doc),
                                                     encoding="utf-8")
    return ws


def test_admission_requires_a_recorded_novel_input_row(tmp_path):
    """The novel-input discriminating bit is a REQUIRED floor at the
    wired admission faces, not an optional extra: an artifact whose pairs
    are all captured-parameter rows is refused even with a runnable
    client — replaying the captured rows alone cannot witness the
    algorithm, so a replay-only echo-table submission cannot reach
    admission green with zero novel rows."""
    ws, path = _ws_with_artifact(
        tmp_path, client_source=_closed_book_client_source())
    doc = json.loads(path.read_text())
    assert not any(p.get("novel_input") for p in doc["pairs"])
    errs = req.admission_errors(ws, doc)
    assert errs, "zero recorded novel-input rows must be refused"
    assert "novel" in " ".join(errs).lower()


def test_admission_refuses_recorded_novel_miss(tmp_path):
    """A recorded novel-input pair that MISSES is a refusal, never
    evidence: the recomputed output must equal BOTH the recorded
    repro_output AND the recorded ref_output, and the recorded
    byte_equal flag must be True."""
    ws = _miss_artifact_ws(tmp_path)
    doc = json.loads(
        (ws / "evidence" / "replay-C-1.json").read_text(encoding="utf-8"))
    errs = req.admission_errors(ws, doc)
    joined = " ".join(errs).lower()
    assert errs, "a recorded novel MISS must not be admitted"
    assert "byte_equal" in joined or "miss" in joined, joined
    assert "ref_output" in joined or "fabrication" in joined, joined


def test_admission_refuses_novel_row_with_false_flag_despite_matching_outputs(
        tmp_path):
    """Even when the client reproduces the novel output byte-for-byte, a
    row recorded with byte_equal=false is a recorded MISS — refused, not
    silently re-derived into a pass."""
    ws, path = _ws_with_artifact(
        tmp_path, client_source=_closed_book_client_source(),
        include_novel=True)
    doc = json.loads(path.read_text())
    novel = next(p for p in doc["pairs"] if p.get("novel_input"))
    novel["byte_equal"] = False
    client = req.load_ws_client(ws, doc)
    errs = req.admission_errors(ws, doc, client=client)
    assert errs, "a novel row with byte_equal=false must be refused"
    assert "byte_equal" in " ".join(errs).lower()


# ------------------- D1: the recorded-novel floor is not forgeable ------

FORGED_ROWS = [{"ts": t, "nonce": n} for t in ("t0", "t1")
               for n in (0, 1, 2)]  # full coverage, zero computation


def _echo_table_client_source(rows, repro_of) -> str:
    table = {json.dumps(dict(p), sort_keys=True): repro_of(p)
             for p in rows}
    return (
        "import json\n"
        f"_TABLE = {json.dumps(table, sort_keys=True)}\n"
        "def compute(params):\n"
        "    return _TABLE.get(json.dumps(params, sort_keys=True))\n")


def _forged_novel_ws(ws: Path) -> Path:
    """The re-review forgery: an echo-table client over 6 captured rows
    (covering array complete on ts x nonce), with ONE captured row
    relabeled novel_input — a submitter-controlled boolean the old floor
    took at face value."""
    (ws / "evidence").mkdir(parents=True, exist_ok=True)
    pairs = [{
        "input_id": f"cap-{i:02d}",
        "inputs": dict(p),
        "ref_output": _sig(p),
        "repro_output": _sig(p),
        "byte_equal": True,
    } for i, p in enumerate(FORGED_ROWS)]
    pairs[4]["novel_input"] = True  # cap-04: captured row, relabeled
    doc = {
        "schema": req.SCHEMA_ID,
        "claim_id": "C-1",
        "captured_inputs": [p["input_id"] for p in pairs],
        "variables": {"ts": ["t0", "t1"], "nonce": [0, 1, 2]},
        "reproduction_client": "reproduction_client.py",
        "pairs": pairs,
    }
    (ws / "reproduction_client.py").write_text(
        _echo_table_client_source(FORGED_ROWS, _sig), encoding="utf-8")
    (ws / "evidence" / "replay-C-1.json").write_text(json.dumps(doc),
                                                     encoding="utf-8")
    return ws


def test_admission_refuses_relabelled_captured_row_as_novel(tmp_path):
    """A recorded novel row that is actually a captured row is not fresh:
    its id sits inside captured_inputs, so the recorded-row floor must
    refuse it instead of taking the flag at face value."""
    ws = _forged_novel_ws(tmp_path / "ws")
    doc = json.loads(
        (ws / "evidence" / "replay-C-1.json").read_text(encoding="utf-8"))
    errs = req.admission_errors(ws, doc)
    joined = " ".join(errs).lower()
    assert errs, "a relabelled captured row must not satisfy the floor"
    assert "not fresh" in joined, joined
    assert "captured_inputs" in joined, joined


def test_equivalence_verdict_refuses_relabelled_captured_row_as_novel(
        tmp_path):
    """The same forgery at the wired verdict face: a replay-only
    echo-table submission that relabels a captured row cannot reach
    admission green (and PROVEN)."""
    ws = _armed_ws(tmp_path / "ws")
    _forged_novel_ws(ws)
    ok, reason = req.equivalence_verdict(ws, CLAIM)
    assert not ok
    assert "not fresh" in reason.lower(), reason


def test_admission_refuses_novel_row_whose_core_duplicates_a_captured_row(
        tmp_path):
    """Freshness is over the declared-variable core: a flagged row whose
    core assignment re-runs a captured row's combination is a
    captured-parameter replay, even when its id sits outside the
    inventory and the client honestly recomputes the recorded bytes."""
    ws, path = _ws_with_artifact(
        tmp_path, client_source=_closed_book_client_source())
    doc = json.loads(path.read_text())
    doc["pairs"].append({
        "input_id": "novel-01",
        "inputs": dict(CAPTURED[0]),  # exactly a captured row's inputs
        "ref_output": _true_sign(CAPTURED[0]),
        "repro_output": _true_sign(CAPTURED[0]),
        "byte_equal": True,
        "novel_input": True,
    })
    client = req.load_ws_client(ws, doc)
    errs = req.admission_errors(ws, doc, client=client)
    joined = " ".join(errs).lower()
    assert errs, "a core-duplicating novel row must be refused"
    assert "not fresh" in joined, joined
    assert any("cap-00" in e for e in errs), errs


def test_schema_lint_allows_novel_row_outside_captured_inputs():
    """Novelty must be EXPRESSIBLE: a novel_input pair's id lives outside
    the capture inventory by definition, so the membership rule cannot
    force it back inside (that forcing is what made the floor forgeable
    by relabeling)."""
    doc = {
        "schema": req.SCHEMA_ID,
        "claim_id": "C-1",
        "captured_inputs": ["cap-01"],
        "variables": {"nonce": [0, 1]},
        "strength": 1,
        "pairs": [
            {"input_id": "cap-01", "inputs": {"nonce": 0},
             "ref_output": "out-0", "repro_output": "out-0",
             "byte_equal": True},
            {"input_id": "novel-01", "inputs": {"nonce": 1},
             "ref_output": "out-1", "repro_output": "out-1",
             "byte_equal": True, "novel_input": True},
        ],
    }
    errs = req.artifact_errors(doc)
    assert errs == [], errs


def test_schema_lint_refuses_novel_row_inside_captured_inputs():
    """And the lint agrees with admission: a flagged novel row whose id
    is a declared captured input is a self-contradiction — refused with
    the same not-fresh reason."""
    doc = {
        "schema": req.SCHEMA_ID,
        "claim_id": "C-1",
        "captured_inputs": ["cap-01", "cap-02"],
        "variables": {"nonce": [0, 1]},
        "strength": 1,
        "pairs": [
            {"input_id": "cap-01", "inputs": {"nonce": 0},
             "ref_output": "out-0", "repro_output": "out-0",
             "byte_equal": True},
            {"input_id": "cap-02", "inputs": {"nonce": 1},
             "ref_output": "out-1", "repro_output": "out-1",
             "byte_equal": True, "novel_input": True},
        ],
    }
    errs = req.artifact_errors(doc)
    joined = " ".join(errs).lower()
    assert "not fresh" in joined, errs


def test_sample_novel_input_is_fresh_and_in_domains():
    rng = random.Random(248)
    for _ in range(20):
        novel = req.sample_novel_input(VARIABLES, CAPTURED, rng)
        assert novel is not None
        core = {k: novel[k] for k in VARIABLES}
        for p in CAPTURED:
            assert core != {k: p[k] for k in VARIABLES}
        assert all(novel[k] in VARIABLES[k] for k in VARIABLES)
        assert novel["appkey"] == APPKEY  # fixed params carry over


def test_novel_input_pair_cannot_pass_replay_only(tmp_path):
    """Property (a): a replay-only submission structurally cannot produce a
    passing novel-input pair."""
    ws, path = _ws_with_artifact(tmp_path,
                                 client_source=_echo_client_source())
    doc = json.loads(path.read_text())
    client = req.load_ws_client(ws, doc)
    pair = req.novel_input_pair(doc, _reference_source, client)
    assert pair["ref_output"] == _reference_source(pair["inputs"])
    assert pair["byte_equal"] is False


def test_novel_input_pair_passes_closed_book(tmp_path):
    """Property (b): the closed-book client reproduces the source-derived
    reference on a verifier-sampled novel input."""
    ws, path = _ws_with_artifact(
        tmp_path, client_source=_closed_book_client_source())
    doc = json.loads(path.read_text())
    client = req.load_ws_client(ws, doc)
    pair = req.novel_input_pair(doc, _reference_source, client)
    assert pair["byte_equal"] is True


def test_novel_input_pair_rng_is_injectable_and_deterministic(tmp_path):
    """The verifier challenge is entropy-seeded, not a fixed constant:
    the rng is injectable (tests inject a fixed seed for determinism) and
    the production default draws verifier entropy (secrets-seeded), so a
    pre-captured challenge table cannot be built offline."""
    ws, path = _ws_with_artifact(
        tmp_path, client_source=_closed_book_client_source())
    doc = json.loads(path.read_text())
    client = req.load_ws_client(ws, doc)
    p1 = req.novel_input_pair(doc, _reference_source, client,
                              rng=random.Random(20260913))
    p2 = req.novel_input_pair(doc, _reference_source, client,
                              rng=random.Random(20260913))
    assert p1["inputs"] == p2["inputs"]
    assert p1["byte_equal"] is True
    # the default (no rng) still samples a novel pair the client passes
    pair = req.novel_input_pair(doc, _reference_source, client)
    assert pair["byte_equal"] is True


def test_admission_with_novel_pair_rejects_echo_client(tmp_path):
    ws, path = _ws_with_artifact(tmp_path,
                                 client_source=_echo_client_source(),
                                 include_novel=True)
    doc = json.loads(path.read_text())
    client = req.load_ws_client(ws, doc)
    errs = req.admission_errors(ws, doc, client=client)
    assert errs and "novel" in errs[0].lower()


def test_admission_with_novel_pair_accepts_closed_book(tmp_path):
    ws, path = _ws_with_artifact(
        tmp_path, client_source=_closed_book_client_source(),
        include_novel=True)
    doc = json.loads(path.read_text())
    client = req.load_ws_client(ws, doc)
    assert req.admission_errors(ws, doc, client=client) == []


# ------------------------------------------------- 3. settle by need

ALGO_CLAIM = {"id": "C-algo", "answers_question": "Q1"}
CONTRACT_CLAIM = {"id": "C-contract", "answers_question": "Q2"}
QUESTIONS = {"Q1": "model_selection", "Q2": "yes_no_with_evidence"}
REPLAY_OBS = {"class": "replay-observation",
              "detail": "replay succeeded; endpoint returned 200"}
REPRO_EVIDENCE = {"class": "reproduction", "artifact": "evidence/replay-C-1.json"}


def test_replay_observation_does_not_settle_algorithm_claim():
    outcome = settle_by_need.settle_attempt(
        ALGO_CLAIM, REPLAY_OBS, QUESTIONS)
    assert outcome["settled"] is False
    assert outcome["claim_stays_open"] is True


def test_replay_observation_is_rerouted_to_input_contract():
    outcome = settle_by_need.settle_attempt(
        ALGO_CLAIM, REPLAY_OBS, QUESTIONS)
    assert outcome["reroute_to"] == "input-contract"


def test_reproduction_evidence_settles_algorithm_claim():
    outcome = settle_by_need.settle_attempt(
        ALGO_CLAIM, REPRO_EVIDENCE, QUESTIONS)
    assert outcome["settled"] is True


def test_replay_observation_settles_input_contract_claim():
    outcome = settle_by_need.settle_attempt(
        CONTRACT_CLAIM, REPLAY_OBS, QUESTIONS)
    assert outcome["settled"] is True
    assert outcome["reroute_to"] is None


# --------------------------------- wiring: the gates live on the real faces

def test_validate_values_refuses_weak_method_for_algorithm_goal():
    """Piece 1 wiring: the intake pre-write contract refuses to LAND the
    weak selection for a generation-language goal (kunglao-init /
    kunglao-upgrade call validate_values before oracle_anchors.apply)."""
    values = {"goal_verbatim": "签名参数是怎么生成的",
              "success_criterion": "x",
              "verification_method": "replay-evidence"}
    with pytest.raises(ValueError) as exc:
        oracle_anchors.validate_values(values)
    assert "replay-evidence" in str(exc.value)
    # the pinned method and an acceptance-class goal land unchanged
    oracle_anchors.validate_values({**values,
                                    "verification_method": "reproduction"})
    oracle_anchors.validate_values({"goal_verbatim": "登录接口能返回 200",
                                    "verification_method": "replay-evidence"})


def _armed_ws(ws: Path) -> Path:
    """Stamp the workspace's task_spec with an algorithm-class goal armed
    for reproduction (intake-derived method; primary_questions carry the
    settle-by-need vocabulary)."""
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "task_spec.yaml").write_text(
        "goal_verbatim: 签名参数是怎么生成的\n"
        "success_criterion: closed-book reproduction matches\n"
        "verification_method: reproduction\n"
        "primary_questions:\n"
        "  - id: q1\n"
        "    q: how are the signing parameters generated?\n"
        "    need: model_selection\n", encoding="utf-8")
    return ws


def _sig(params: dict) -> str:
    return f"sig-{params['ts']}-{params['nonce']}"


_CLIENT_BODY = (
    "def compute(params):\n"
    "    return f\"sig-{params['ts']}-{params['nonce']}\"\n")


def _verdict_artifact(ws: Path, *, client_body: str | None,
                      repro_override: str | None = None,
                      include_novel: bool = False,
                      echo_client: bool = False,
                      novel_repro_override: str | None = None) -> Path:
    """A replay-schema-valid artifact over the verdict face: ts x nonce
    covered, optional runnable client, recorded repro rows. With
    include_novel the nonce domain grows to [0, 1, 2], one extra captured
    row (t0, nonce=2) keeps the covering array complete, and a recorded
    novel-input pair (t1, nonce=2) is appended — the structural floor the
    wired admission face requires. echo_client writes a table client that
    returns each row's recorded repro_output (the replay-only shape)."""
    nonce_domain = [0, 1, 2] if include_novel else [0, 1]
    rows = [{"ts": t, "nonce": n} for t in ("t0", "t1") for n in (0, 1)]
    if include_novel:
        rows.append({"ts": "t0", "nonce": 2})  # keeps coverage complete
    pairs = [{
        "input_id": f"cap-{i:02d}",
        "inputs": dict(p),
        "ref_output": _sig(p),
        "repro_output": repro_override if repro_override is not None
        else _sig(p),
        "byte_equal": req.byte_equal(_sig(p),
                                     repro_override or _sig(p)),
    } for i, p in enumerate(rows)]
    if include_novel:
        novel_inputs = {"ts": "t1", "nonce": 2}
        novel = {
            "input_id": "novel-01",  # outside captured_inputs: fresh
            "inputs": novel_inputs,
            "ref_output": _sig(novel_inputs),
            "repro_output": _sig(novel_inputs),
            "byte_equal": True,
            "novel_input": True,
        }
        if novel_repro_override is not None:
            novel["repro_output"] = novel_repro_override
            novel["byte_equal"] = req.byte_equal(novel["ref_output"],
                                                 novel_repro_override)
        pairs.append(novel)
    doc = {
        "schema": req.SCHEMA_ID,
        "claim_id": "C-1",
        "captured_inputs": [f"cap-{i:02d}" for i in range(len(rows))],
        "variables": {"ts": ["t0", "t1"], "nonce": nonce_domain},
        "pairs": pairs,
    }
    if echo_client:
        table = {json.dumps(p["inputs"], sort_keys=True): p["repro_output"]
                 for p in pairs}
        client_body = (
            "import json\n"
            f"_TABLE = {json.dumps(table, sort_keys=True)}\n"
            "def compute(params):\n"
            "    return _TABLE.get(json.dumps(params, sort_keys=True))\n")
    if client_body is not None:
        (ws / "oracle").mkdir(parents=True, exist_ok=True)
        (ws / "oracle" / "client.py").write_text(client_body,
                                                 encoding="utf-8")
        doc["reproduction_client"] = "oracle/client.py"
    (ws / "evidence").mkdir(parents=True, exist_ok=True)
    path = ws / "evidence" / "replay-C-1.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


CLAIM = {"id": "C-1", "answers_question": "q1"}


def test_equivalence_verdict_refuses_clientless_copy_both_sides(tmp_path):
    """Piece 2 wiring at the REAL admission face: the copy-both-sides
    artifact (ref == repro == captured signatures, no client) that passed
    admission before is now refused by equivalence_verdict."""
    ws = _armed_ws(tmp_path / "ws")
    _verdict_artifact(ws, client_body=None)
    ok, reason = req.equivalence_verdict(ws, CLAIM)
    assert not ok
    assert "reproduction_client" in reason
    # with the runnable client AND the required recorded novel-input row,
    # the same face passes (the corrected armed-face contract)
    ws2 = _armed_ws(tmp_path / "ok" / "ws")
    _verdict_artifact(ws2, client_body=_CLIENT_BODY, include_novel=True)
    ok2, reason2 = req.equivalence_verdict(ws2, CLAIM)
    assert ok2, reason2


def test_equivalence_verdict_requires_novel_input_row(tmp_path):
    """Wired-face floor: a runnable client over captured rows alone is
    replay — the verdict face requires at least one recorded novel-input
    row, so a replay-only echo-table submission with zero novel rows
    cannot reach admission green (and PROVEN)."""
    ws = _armed_ws(tmp_path / "ws")
    _verdict_artifact(ws, client_body=_CLIENT_BODY)  # zero novel rows
    ok, reason = req.equivalence_verdict(ws, CLAIM)
    assert not ok
    assert "novel" in reason.lower()


def test_equivalence_verdict_refuses_recorded_novel_miss(tmp_path):
    """Wired-face record check: a schema-honest novel row recording a
    MISS (source-derived ref, garbage repro, byte_equal=false) with a
    replay-only table client is refused — recorded novel rows are
    verified against BOTH recorded outputs and the recorded flag on
    every admission."""
    ws = _armed_ws(tmp_path / "ws")
    _verdict_artifact(ws, client_body=None, echo_client=True,
                      include_novel=True, novel_repro_override="deadbeef")
    ok, reason = req.equivalence_verdict(ws, CLAIM)
    assert not ok
    assert "novel" in reason.lower()


def test_equivalence_verdict_refuses_fabricated_rows(tmp_path):
    """Piece 2 wiring: a declared client whose re-execution disagrees with
    the recorded repro_output is refused at the real admission face."""
    ws = _armed_ws(tmp_path / "ws")
    _verdict_artifact(ws, client_body=_CLIENT_BODY,
                      repro_override="deadbeef")
    ok, reason = req.equivalence_verdict(ws, CLAIM)
    assert not ok
    assert "fabrication" in reason.lower()

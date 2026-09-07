# -*- coding: utf-8 -*-
"""tests/test_hypothesis_loop_integration_111.py — the v0.1.5 exit criterion.

Issue #111: "does round N+1's hypothesis quality actually rise from round
N's verification outcome?" One synthetic fixture task, three rounds, one
falsifiable inequality:

    dispatches_to_first_green(round1) > dispatches_to_first_green(round2)
                                        >= dispatches_to_first_green(round3)

The fixture task is an offline request-sign reproduction whose true
algorithm is a salted composite (``sign = md5(OUTER_SALT + md5(canon))``) —
deliberately trap-shaped: the naive hypothesis (``sign = md5(canon)``) is
WRONG but plausible from the 32-hex string shape. Round 1 cold-starts with
the #759 worth channel boosting the naive family (the "routing tables give
the string-shape -> family table" prior), so the loop burns wrong-family
dispatches before the first case green. Rounds 2/3 re-run the SAME task on
the SAME workspace: only the DESIGNED experience channels persist
(runs/posteriors.yaml #106, runs/case-bank.jsonl #110, terminal hypothesis
adjudications #528) while greens-closed claims reopen — every round's green
is re-earned through the oracle, never cached.

NO production code is touched. The mini-loop driver below is the loop:
rank (priority_ratio #107) -> declare intent (#105) -> run the oracle
(oracle_runner #108) -> record posteriors (#106) -> bank the outcome
(case_bank #110, attribution mandatory on NEGATIVE) -> settle
(promotion_attempts, DLQ at the #36 limit) -> refute/confirm hypotheses
(hypothesis_store state machine).

Mechanism attribution (E1, .claude/PRPs/reports/e1-111-feasibility.md):
the round-2 flip is produced by (1) the case-bank premise_correction
retrieval eliminating the refuted family BEFORE dispatch (the issue's own
"eliminated by a retrieved premise_correction" face) and (2) the
dispatch-frontier memory (promotion_attempts -> #36 DLQ) — partially.
It is NOT produced by case posteriors (they lower case_face for ALL
PQ-linked claims uniformly — variant G keeps the full speedup with
posteriors disabled), NOT by the flip-potential feeds decay (diagnostic
only, never enters the score), and novelty saturation does not exist
since #107. The brief-literal "reset claim attempts to 0" variant
provably FAILS the inequality (E1 variant F: r2 = r3 = 10): the round
reset below therefore refreshes the round budget (greens-closed claims
reopen) while terminal refutation adjudications persist.

Side contracts exercised end-to-end: #109 (open competing candidates
before the round-1 first dispatch), #105 (runs/roi-intents.jsonl rows via
the dispatch gate's own record path), #108 (mutation-must-fail teeth on
the fixture's case set + the naive client red on every case).
"""
from __future__ import annotations

import hashlib
import random
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import case_bank as cbank  # noqa: E402  (#110 bank + ruling-4 attribution)
import dead_letter  # noqa: E402  (#36 DLQ at the attempts limit)
import hypothesis_store as hstore  # noqa: E402  (#528/#109 hypothesis layer)
import oracle_runner as orun  # noqa: E402  (#108 oracle mechanical face)
import priority_ratio as pr  # noqa: E402  (#107 Thompson ranker)
from roi_settlement import ROI_POSITIVE  # noqa: E402  (#49 shared vocabulary)
from _factories import write_hook_state  # noqa: E402  (#105 harness shape)
from hypothesis_store import Hypothesis, HypothesisStore  # noqa: E402

# ---------------------------------------------------------------- constants
# Every synthetic value below is derived at build time with hashlib; the only
# protocol-given literals are the capture inputs and the outer salt itself.

PQ_ID = "PQ-SIGN"                 # the task's single primary question
FIXTURE_SEED = 111                # the issue number; any seed 0..59 passes
MAX_DISPATCHES = 12               # round budget (r1 worst case is bounded: 3
                                  # naive claims x 3 attempts + 1 green = 10)
ATTEMPT_LIMIT = 3                 # priority_ratio candidate filter + #36 DLQ
NAIVE_WORTH_OVERRIDE = 5.0        # #759 worth channel: string-shape prior
OUTER_SALT = "k1"                 # the true protocol's outer salt (fixture)

CLAIMS_NAIVE = ("C-101", "C-102", "C-104")
CLAIMS_SALTED = ("C-103", "C-105", "C-106")
ALL_CLAIMS = CLAIMS_NAIVE + CLAIMS_SALTED
CLAIM_FAMILY = {cid: ("naive" if cid in CLAIMS_NAIVE else "salted")
                for cid in ALL_CLAIMS}

CLIENT_NAIVE_REL = "oracle/client_naive.py"
CLIENT_SALTED_REL = "oracle/client_salted.py"
FAMILY_CLIENT = {"naive": CLIENT_NAIVE_REL, "salted": CLIENT_SALTED_REL}

HYP_NAIVE_ID = "H-01"
HYP_SALTED_ID = "H-02"
ROUND1_ANCHOR_FACT = "F001"       # refuting/confirming byte anchor (fixture)

# The three captures (F001..F003): params observed on the wire + the sign
# value they carried. params are the protocol data; signs are computed.
CAPTURES = [
    {"user": "alice", "action": "query", "nonce": "3117"},
    {"user": "bob", "action": "submit", "nonce": "4096"},
    {"user": "carol", "action": "sync", "nonce": "2048"},
]


def canonical_of(params: dict) -> str:
    """The captured canonical form: sorted key=value pairs joined with &."""
    return "&".join(f"{k}={params[k]}" for k in sorted(params))


def true_sign(params: dict) -> str:
    """The GROUND TRUTH (fixture-only): the salted composite."""
    inner = hashlib.md5(canonical_of(params).encode()).hexdigest()
    return hashlib.md5((OUTER_SALT + inner).encode()).hexdigest()


# The two candidate clients a dispatch can carry. load_client contract shape
# copied from tests/test_oracle_runner_108.py: compute(params) -> dict.
CLIENT_SALTED_SRC = (
    "import hashlib\n"
    "\n"
    "def _canon(params):\n"
    "    return '&'.join(f'{k}={params[k]}' for k in sorted(params))\n"
    "\n"
    "def compute(params):\n"
    "    canonical = _canon(params)\n"
    "    inner = hashlib.md5(canonical.encode()).hexdigest()\n"
    "    sign = hashlib.md5(('k1' + inner).encode()).hexdigest()\n"
    "    return {'sign': sign, 'canonical': canonical}\n"
)

# The naive hypothesis: plausible (same 32-hex shape) and WRONG — it drops
# the outer salt, so every oracle case goes red under this client.
CLIENT_NAIVE_SRC = (
    "import hashlib\n"
    "\n"
    "def _canon(params):\n"
    "    return '&'.join(f'{k}={params[k]}' for k in sorted(params))\n"
    "\n"
    "def compute(params):\n"
    "    canonical = _canon(params)\n"
    "    sign = hashlib.md5(canonical.encode()).hexdigest()\n"
    "    return {'sign': sign, 'canonical': canonical}\n"
)

# Dispatch prompt template: carries the #105 prose declaration faces. The
# declared uncertainty is round-scoped: a round-N re-verification genuinely
# declares a different intent than round 1 (it runs WITH round-1 evidence),
# so #105's declaration idempotency never collapses two rounds into one row.
_DISPATCH_PROMPT = (
    "[T1 tools=Read,Write] claim {claim_id} replay the captured request "
    "against the oracle case set\n"
    "uncertainty: round {round_no} verification — does the {family} "
    "composite reproduce every captured sign value\n"
    "preconditions: oracle-replay, {family}-composite\n"
    "expected_artifact: oracle-verdict"
)


# ------------------------------------------------------------------ fixture

def _make_loop_ws(tmp_path: Path) -> Path:
    """Build the synthetic workspace: register, deps, task_spec, #759 worth
    overrides, 3 byte-anchored oracle cases, the two candidate clients,
    F001..F003 + _INDEX, and the two competing hypotheses (#528 shape)."""
    ws = tmp_path / "ws"
    for rel in ("facts", "hypotheses", "runs", "oracle", "oracle/cases"):
        (ws / rel).mkdir(parents=True, exist_ok=True)

    claims = []
    for cid in ALL_CLAIMS:
        fam = CLAIM_FAMILY[cid]
        claims.append({
            "id": cid,
            "status": "OPEN",
            "statement": f"Request-sign reconstruction: the {fam} composite "
                         f"explains the {PQ_ID} sign field",
            "answers_question": PQ_ID,
            "competitor_group": PQ_ID,
            "promotion_attempts": 0,
            "evidence_tier_attempted": 0,
        })
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, sort_keys=False), encoding="utf-8")
    (ws / "claim_deps.yaml").write_text(
        yaml.safe_dump({"depends_on": {},
                        "competitor_groups": {PQ_ID: list(ALL_CLAIMS)}},
                       sort_keys=False), encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump({"primary_questions": [PQ_ID]}, sort_keys=False),
        encoding="utf-8")

    # Round-1 cold-start prior: the routing table favors the naive family
    # (the #759 per-claim worth overrides consumed by claim_value_weight).
    (ws / "runs" / "value-weights.yaml").write_text(
        yaml.safe_dump({"overrides": {cid: NAIVE_WORTH_OVERRIDE
                                      for cid in CLAIMS_NAIVE}},
                       sort_keys=False), encoding="utf-8")

    index_rows = ["# _INDEX"]
    for i, params in enumerate(CAPTURES, start=1):
        fid = f"F{i:03d}"
        sign = true_sign(params)
        (ws / "facts" / f"{fid}.md").write_text(
            f"---\nid: {fid}\nstatus: PROVEN\n---\n\n"
            f"capture {i}: params={params} sign={sign}\n", encoding="utf-8")
        index_rows.append(f"{fid} | PROVEN | C-101 | capture params={params} "
                          f"sign={sign}")
        case = {
            "id": f"CASE-S{i}",
            "target_pq": PQ_ID,
            "params": params,
            "expected": [
                {"field": "sign", "value": sign, "evidence_refs": [fid]},
                {"field": "canonical", "value": canonical_of(params),
                 "evidence_refs": [fid]},
            ],
            "mutations": [
                {"field": "sign", "kind": "swap"},
                {"field": "sign", "kind": "change"},
            ],
        }
        (ws / "oracle" / "cases" / f"case-s{i}.yaml").write_text(
            yaml.safe_dump(case, sort_keys=False), encoding="utf-8")
    (ws / "facts" / "_INDEX.md").write_text("\n".join(index_rows) + "\n",
                                            encoding="utf-8")

    (ws / CLIENT_SALTED_REL).write_text(CLIENT_SALTED_SRC, encoding="utf-8")
    (ws / CLIENT_NAIVE_REL).write_text(CLIENT_NAIVE_SRC, encoding="utf-8")

    store = HypothesisStore(ws / "hypotheses")
    store.create(Hypothesis(
        id=HYP_NAIVE_ID, claim_id="C-101", competitor_group=f"pq-{PQ_ID}",
        candidates=["naive-md5-composite"], status="open",
        predicted_observation="oracle cases go green under the naive client",
        body=f"pq:{PQ_ID}\n\nNaive hypothesis: sign = md5(canon(params)). "
             "Plausible from the 32-hex shape. Falsifier: any case red.\n"))
    store.create(Hypothesis(
        id=HYP_SALTED_ID, claim_id="C-105", competitor_group=f"pq-{PQ_ID}",
        candidates=["salted-outer-composite"], status="open",
        predicted_observation=("oracle cases go green under the salted "
                               "client"),
        body=f"pq:{PQ_ID}\n\nCompeting hypothesis: sign = md5(salt + "
             "md5(canon(params))). Falsifier: any case red.\n"))

    write_hook_state(ws, active_hooks=["dispatch_gate"])
    return ws


# -------------------------------------------------------------- mini driver

def _load_register(ws: Path) -> tuple[list[dict], dict]:
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text("utf-8"))
    deps = yaml.safe_load((ws / "claim_deps.yaml").read_text("utf-8"))
    return reg["claims"], deps


def _save_register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, sort_keys=False), encoding="utf-8")


def _eliminated_families(ws: Path) -> set[str]:
    """Families eliminated by a RETRIEVED premise_correction before dispatch
    (the issue's round-2 face): a case-bank NEGATIVE entry whose mandatory
    attribution names the family's client and whose observed outcome failed
    every case (a partially-green family must NOT be eliminated)."""
    # RED(#111): the retrieval channel is unwired in the RED state — round 2
    # must replay the naive-family burn and the strict inequality must FAIL
    # (E1 variant F). GREEN wires the cbank.retrieve body below.
    return set()
    out: set[str] = set()
    for entry in cbank.retrieve(ws, [PQ_ID], limit=50):
        if entry.get("roi_class") != cbank.ROI_NEGATIVE:
            continue
        observed = entry.get("outcome_observed") or {}
        if not observed.get("red") or observed.get("green"):
            continue
        attribution = str(entry.get("attribution") or "")
        for family, client_rel in FAMILY_CLIENT.items():
            if Path(client_rel).name in attribution:
                out.add(family)
    return out


def _settle_red(ws: Path, claims: list[dict], claim: dict,
                store: HypothesisStore) -> None:
    """A red settlement: promotion_attempts + 1; at the #36 limit the DLQ
    marks the claim DEAD. A naive-family red also refutes the family
    hypothesis (terminal — the state machine refuses reopening)."""
    claim["promotion_attempts"] = int(claim.get("promotion_attempts", 0)) + 1
    if claim["promotion_attempts"] >= ATTEMPT_LIMIT:
        dead_letter.mark_dead(ws, claim["id"],
                              "promotion_attempts exhausted (DLQ)")
        claim["status"] = "DEAD"
    _save_register(ws, claims)
    if CLAIM_FAMILY[claim["id"]] == "naive":
        hyp = store.get(HYP_NAIVE_ID)
        if hyp.status == "open":
            store.transition(HYP_NAIVE_ID, "refuted",
                             refuting_fact_id=ROUND1_ANCHOR_FACT)


def _settle_green(ws: Path, claims: list[dict], claim: dict,
                  store: HypothesisStore) -> None:
    claim["status"] = "PROVEN"
    _save_register(ws, claims)
    for hyp in store.list_all():
        if hyp.status == "open" and hyp.claim_id == claim["id"]:
            store.transition(hyp.id, "confirmed",
                             confirming_fact_id=ROUND1_ANCHOR_FACT)


def run_round(ws: Path, round_no: int) -> tuple[int | None, list[str]]:
    """One loop round: rank -> declare intent -> oracle run -> posteriors ->
    bank -> settle. Returns (dispatches_to_first_green, dispatch sequence);
    dispatches is None when the budget or the candidate pool ran out."""
    claims, deps = _load_register(ws)
    cases_dir = ws / "oracle" / "cases"
    store = HypothesisStore(ws / "hypotheses")
    eliminated = _eliminated_families(ws)
    sequence: list[str] = []

    for _tick in range(1, MAX_DISPATCHES + 1):
        pool = [c for c in claims
                if CLAIM_FAMILY[c["id"]] not in eliminated]
        evidence = pr.EvidenceView.from_workspace(ws)
        actions = pr.priority_ratio(pool, deps, evidence,
                                    rng=random.Random(FIXTURE_SEED))
        if not actions:
            return None, sequence
        top = actions[0]
        sequence.append(top.claim_id)

        # #105: the dispatch declares its intent through the gate's own
        # record path (the producer runs/roi-intents.jsonl).
        import dispatch_gate as dgate
        dgate._record_dispatch_intent(
            ws, top.claim_id,
            _DISPATCH_PROMPT.format(claim_id=top.claim_id, round_no=round_no,
                                    family=CLAIM_FAMILY[top.claim_id]),
            {"tool_input": {"subagent_type": "kunglao-worker"}})

        # #108: the oracle is the only judge — the claim's linked client
        # runs the whole case set; #106: real verdicts update the ledger.
        report = orun.run(cases_dir, ws / FAMILY_CLIENT[CLAIM_FAMILY[
            top.claim_id]])
        orun.write_status(ws, report)
        orun.record_posteriors(ws, report)

        red = report["counts"]["red"]
        green = report["counts"]["green"]
        claim = next(c for c in claims if c["id"] == top.claim_id)
        # #110: symmetric collection — failures banked WITH attribution
        # (ruling 4 makes the attribution mandatory on NEGATIVE).
        cbank.append_once(ws, {
            "claim_id": top.claim_id,
            "method": "oracle-replay",
            "context_tags": [PQ_ID, "sign-reconstruction"],
            "roi_class": cbank.ROI_NEGATIVE if red else ROI_POSITIVE,
            "attribution": (f"oracle red {red}/{red + green} cases under "
                            f"{FAMILY_CLIENT[CLAIM_FAMILY[top.claim_id]]}"
                            if red else ""),
            "premise_correction": (
                f"naive composite mismatched on all {red} cases: the sign "
                "field depends on more than the canonical params"
                if red else ""),
            "outcome_observed": {"red": red, "green": green},
            "intent_uncertainty": (
                f"does the {CLAIM_FAMILY[top.claim_id]} composite reproduce "
                "every captured sign value"),
        })

        if green:
            _settle_green(ws, claims, claim, store)
            return len(sequence), sequence
        _settle_red(ws, claims, claim, store)

    return None, sequence


def _round_reset(ws: Path) -> None:
    """Fresh attempt on the SAME task: claims closed BY a round's green
    reopen (the green must be re-earned through the oracle every round —
    no degenerate cached answer), while terminal refutation adjudications
    (DEAD claims, refuted/superseded hypotheses) persist."""
    claims, _ = _load_register(ws)
    for claim in claims:
        # RED(#111): the frontier-memory channel is unwired in the RED state
        # — DEAD adjudications are wiped too, so round 2 replays the whole
        # naive burn and the strict inequality must FAIL (E1 variant F).
        claim["status"] = "OPEN"
        claim["promotion_attempts"] = 0
    _save_register(ws, claims)


def _refile_hypotheses(ws: Path) -> None:
    """Hypotheses refiled: a refuted family is NOT resurrected (terminal
    states never reopen — hypothesis_store enforces it); the surviving
    competitor space gets a fresh open verification hypothesis."""
    store = HypothesisStore(ws / "hypotheses")
    if store.list_open():
        return
    existing = {h.id for h in store.list_all()}
    n = 1
    while f"H-{n:02d}" in existing:
        n += 1
    store.create(Hypothesis(
        id=f"H-{n:02d}", claim_id="C-105", competitor_group=f"pq-{PQ_ID}",
        candidates=["salted-outer-composite"], status="open",
        predicted_observation=("oracle cases go green under the salted "
                               "client"),
        body=f"pq:{PQ_ID}\n\nRefile of the surviving competitor space "
             "(case-bank premise_correction applied; the refuted naive "
             "family is history, not a live candidate).\n"))


def three_rounds(ws: Path) -> dict:
    """R1 on the cold-start fixture, then R2/R3 on the same workspace with
    only the designed experience channels persisted."""
    r1, seq1 = run_round(ws, 1)
    out = {"r1": r1, "seq1": seq1}
    for rnd in (2, 3):
        _round_reset(ws)
        _refile_hypotheses(ws)
        r, seq = run_round(ws, rnd)
        out[f"r{rnd}"] = r
        out[f"seq{rnd}"] = seq
    return out


# -------------------------------------------------------------------- tests

def test_round2_beats_round1_strictly(tmp_path: Path) -> None:
    """THE gate: r1 > r2 — round 2 must reach the first case green in
    STRICTLY fewer dispatches than round 1, on the same task, seeded."""
    ws = _make_loop_ws(tmp_path)
    rounds = three_rounds(ws)
    r1, r2 = rounds["r1"], rounds["r2"]
    # the round-1 trap must actually have burned wrong-family dispatches —
    # otherwise r1 is vacuous and the inequality proves nothing
    assert any(CLAIM_FAMILY[cid] == "naive" for cid in rounds["seq1"]), (
        f"round 1 never dispatched the naive family: {rounds['seq1']}")
    assert r1 is not None, f"round 1 exhausted the budget: {rounds}"
    assert r2 is not None, f"round 2 exhausted the budget: {rounds}"
    print(f"[#111] dispatches to first green: r1={r1} r2={r2} "
          f"r3={rounds['r3']}")
    assert r1 > r2, (
        f"round 2 failed to beat round 1: r1={r1} r2={r2} rounds={rounds}")


def test_round3_no_degradation(tmp_path: Path) -> None:
    """Regression guard: a third identical round does not degrade vs
    round 2 (guards degenerate cached-answer implementations that would
    make round 2 trivially good and round 3 unstable)."""
    ws = _make_loop_ws(tmp_path)
    rounds = three_rounds(ws)
    r2, r3 = rounds["r2"], rounds["r3"]
    assert r2 is not None and r3 is not None, rounds
    assert r2 >= r3, f"round 3 degraded vs round 2: r2={r2} r3={r3}"


def test_admission_gate_round1(tmp_path: Path) -> None:
    """#109 side contract: before the round-1 FIRST dispatch, the hypothesis
    layer holds non-adjudicated competing candidates for the PQ (the gate's
    admission read open_candidates_for_question, seeded shape)."""
    ws = _make_loop_ws(tmp_path)
    store = HypothesisStore(ws / "hypotheses")
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text("utf-8"))
    claim_question = {c["id"]: c.get("answers_question")
                      for c in reg["claims"]}
    candidates = hstore.open_candidates_for_question(
        store.list_all(), PQ_ID, claim_question)
    assert len(candidates) >= 2, (
        f"round 1 must open with >= 2 competing candidates, got "
        f"{candidates}")
    assert "naive-md5-composite" in candidates
    assert "salted-outer-composite" in candidates


def test_intent_rows_present(tmp_path: Path) -> None:
    """#105 side contract: every dispatch declares its intent through the
    dispatch gate's own record path, so runs/roi-intents.jsonl carries rows
    (claim_id + declared uncertainty + preconditions + ts)."""
    ws = _make_loop_ws(tmp_path)
    rounds = three_rounds(ws)
    assert rounds["r1"] is not None, rounds
    intents_path = ws / "runs" / "roi-intents.jsonl"
    assert intents_path.exists(), "the dispatch gate wrote no intent rows"
    rows = [yaml.safe_load(  # jsonl: yaml is a superset for these flat rows
        ln) for ln in intents_path.read_text("utf-8").splitlines()
        if ln.strip()]
    # #105 declares intents idempotently (a byte-identical re-declaration
    # appends nothing), so the row count is the DISTINCT (round, claim)
    # declaration count, not the raw dispatch count.
    expected_rows = sum(len({*rounds[f"seq{r}"]}) for r in (1, 2, 3))
    assert len(rows) == expected_rows, (
        f"expected {expected_rows} intent rows, got {len(rows)}")
    for row in rows:
        assert row["claim_id"] in ALL_CLAIMS
        assert row["uncertainty"], f"row lost its declared uncertainty: {row}"
        assert row["ts"], f"row lost its record timestamp: {row}"
        assert row["method"] == "kunglao-worker"


def test_oracle_has_teeth(tmp_path: Path) -> None:
    """#108 side contract on the fixture's case set: (a) the mutation pass
    reports must-fail hits — a deliberately perturbed client turns its case
    red, and no case is flagged low_discriminativity; (b) the naive client
    is red on every case (the trap's teeth: a wrong-but-plausible
    hypothesis is OBSERVED wrong, never guessed wrong)."""
    ws = _make_loop_ws(tmp_path)
    cases_dir = ws / "oracle" / "cases"
    report = orun.run(cases_dir, ws / CLIENT_SALTED_REL, mutation=True)
    mutation_rows = [row
                     for rows in report["mutation"]["mutations"].values()
                     for row in rows]
    assert sum(1 for row in mutation_rows if row["red"]) >= 1, (
        f"mutation pass found no must-fail hit: {report['mutation']}")
    assert report["mutation"]["low_discriminativity"] == [], (
        "a fixture case observes nothing its author claims distinguishes it")
    assert report["counts"]["green"] == len(CAPTURES)

    naive = orun.run(cases_dir, ws / CLIENT_NAIVE_REL)
    assert naive["counts"]["red"] == len(CAPTURES), (
        f"the naive client must fail every case, got {naive['counts']}")
    assert naive["counts"]["green"] == 0

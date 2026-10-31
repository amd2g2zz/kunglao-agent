# -*- coding: utf-8 -*-
"""tests/test_rl_v2_distill_action_938.py — DISTILL as ActionKind #11.

Owner framing: distillation is an ACTION in the action space, not a
side subsystem. Pins, written before the faces they pin (TDD order):

  SPEC      the #924 spec machinery governs ``distill``: REQUIRED
            ``formulation`` (the capability gap's problem statement);
            OPTIONAL ``max_depth`` (default 3, int 1..5), ``sources``
            (default ("references", "web"), allowed names only),
            ``budget_scale`` (default 1.0, positive finite); the row
            records the effective params.
  DRIVER    the deep-research round driver: round 1 queries =
            [formulation]; round k's queries are a DETERMINISTIC
            function of the prior round's cognition trio (open
            questions -> targeted; conflicts -> counter-queries;
            unknown motives/constraints -> focused); terminate at
            max_depth or convergence (no new open questions AND no
            unresolved conflicts); the cognition state + extraction
            records land as q_cells observation rows under the
            DISTILL family, driver clock only, credit-free (standard
            settlement — no special treatment).
  R3        the extraction contract keeps the six fields as structure
            guidance: approach / planning_pattern / success_markers /
            failure_markers REQUIRED (fail-closed, named); motives /
            constraints IDENTIFIED when the source states them — their
            absence is honest knowledge gap (focused queries), never a
            penalty: no copying_risk, no suspicion machinery anywhere.
  SOURCES   references_recall is the FIRST-CLASS source (the recall
            face is imported, hits are read, provenance = path); web
            is a SEAM (injected Callable; no network in production
            faces — a web source without an injected fetcher refuses).
  TRIGGER   the loop's shelf-miss wiring: a worker receipt's
            shelf-miss signal lands ONE distill action row (decision +
            row are production; the research execution is a separate
            injected Callable). EXECUTOR INDEPENDENCE: the research
            seam is never the worker and never receives it — it gets
            (ws, formulation, clock=...) only.

Mock sources/extractors live in THIS file only; the production faces
(distill.research wiring, references fetch, loop trigger) are
mock-free and deterministic.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop",
           ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import loop as loop913  # noqa: E402
import distill  # noqa: E402
from loop_worker import mock_worker  # noqa: E402
from rlvr import action_params  # noqa: E402
from rlvr import learning_seal as seal  # noqa: E402
from rlvr import q_cells  # noqa: E402
from core import ActionKind, parse_action  # noqa: E402

ActionParamError = action_params.ActionParamError
DistillError = distill.DistillError


@pytest.fixture(autouse=True)
def _unarmed_seal(monkeypatch, tmp_path):
    """The suite's default seal posture (rows pass through unsigned)."""
    monkeypatch.setattr(seal, "KEY_PATH", tmp_path / "absent.key")
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})


@pytest.fixture(autouse=True)
def _isolated_store_root(monkeypatch, tmp_path):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))


class _Clock:
    """A deterministic tick recorder — proves the driver clock stamps
    every landed row (no wall clock anywhere)."""

    def __init__(self) -> None:
        self.ticks: list[str] = []
        self._n = 0

    def tick(self) -> str:
        self._n += 1
        stamp = f"2026-10-31T00:{self._n // 60:02d}:{self._n % 60:02d}Z"
        self.ticks.append(stamp)
        return stamp


def _record(**over):
    """A COMPLETE R3 record (all six fields identified)."""
    rec = {"approach": "unpack then trace the dispatcher",
           "planning_pattern": "static triage before dynamic confirm",
           "success_markers": ["dispatcher resolved"],
           "failure_markers": ["vm deadlock"],
           "motives": ["why: the shelf has no unpack rung"],
           "constraints": ["offline only"]}
    rec.update(over)
    return {k: v for k, v in rec.items() if v is not None}


def _web_source(docs_per_round: list[list[dict]]):
    calls: list[list[str]] = []

    def fetch(queries: list[str]) -> list[dict]:
        calls.append(list(queries))
        docs = docs_per_round[len(calls) - 1]
        for d in docs:
            d.setdefault("query", queries[0])
        return docs

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def _web_doc(text: str, url: str = "https://example.test/a",
             query: str | None = None) -> dict:
    doc = {"origin": "web", "provenance": {"url": url, "date": "2026-10-31"},
           "text": text}
    if query is not None:
        doc["query"] = query
    return doc


def _distill_rows(ws) -> list[dict]:
    return [r for r in q_cells.trajectory_rows(ws)
            if r.get("method_family") == distill.DISTILL_FAMILY]


# ------------------------------------------------------------ the spec

def test_distill_joins_the_closed_action_space():
    assert ActionKind.DISTILL.value == "distill"
    # the drift pin's other direction: the spec key resolves through
    # ActionKind at the boundary
    assert "distill" in action_params.ACTION_PARAM_SPECS


def test_distill_spec_shape():
    spec = action_params.ACTION_PARAM_SPECS["distill"]
    assert frozenset(spec.required) == {"formulation"}
    assert frozenset(spec.optional) == {"max_depth", "sources",
                                        "budget_scale"}


def test_distill_spec_defaults():
    spec = action_params.ACTION_PARAM_SPECS["distill"]
    assert spec.optional["max_depth"][0] == 3
    assert spec.optional["sources"][0] == ("references", "web")
    assert spec.optional["budget_scale"][0] == 1.0


def test_distill_effective_params_in_the_row(tmp_path):
    ws = tmp_path / "ws"
    q_cells.append_action(ws, kind="distill", rollout_id="ro-1",
                          target="task", params={"formulation": "gap"},
                          ts="t0")
    (row,) = [r for r in q_cells.trajectory_rows(ws)
              if r.get("schema") == q_cells.SCHEMA_ACTION_V2]
    # the landed row's sources: the spec default (JSON lands the tuple
    # as a list — the row is the effective-values audit surface)
    assert row["params"] == {"formulation": "gap", "max_depth": 3,
                             "sources": ["references", "web"],
                             "budget_scale": 1.0}


def test_distill_formulation_required_and_named():
    with pytest.raises(ActionParamError) as exc:
        action_params.normalize_params("distill", {})
    assert "formulation" in str(exc.value)
    for bad in ("", "   ", None, 7):
        with pytest.raises(ActionParamError) as exc:
            action_params.normalize_params("distill", {"formulation": bad})
        assert "formulation" in str(exc.value)


@pytest.mark.parametrize("depth", [1, 5])
def test_distill_max_depth_rails_accept(depth):
    out = action_params.normalize_params(
        "distill", {"formulation": "gap", "max_depth": depth})
    assert out["max_depth"] == depth


@pytest.mark.parametrize("depth", [0, 6, -1, True, "3", 3.0, None])
def test_distill_max_depth_rails_refuse(depth):
    with pytest.raises(ActionParamError) as exc:
        action_params.normalize_params("distill",
                                       {"formulation": "gap",
                                        "max_depth": depth})
    assert "max_depth" in str(exc.value)


@pytest.mark.parametrize("sources", [("references",), ["web"],
                                     ["web", "references"]])
def test_distill_sources_rails_accept(sources):
    out = action_params.normalize_params("distill",
                                         {"formulation": "gap",
                                          "sources": sources})
    assert out["sources"] == tuple(sources)


@pytest.mark.parametrize("sources", [[], ("references", "reddit"),
                                     "references", None,
                                     ["references", ""]])
def test_distill_sources_rails_refuse(sources):
    with pytest.raises(ActionParamError) as exc:
        action_params.normalize_params("distill",
                                       {"formulation": "gap",
                                        "sources": sources})
    assert "sources" in str(exc.value)


@pytest.mark.parametrize("scale", [0.5, 2, 1.0])
def test_distill_budget_scale_rails_accept(scale):
    out = action_params.normalize_params("distill",
                                         {"formulation": "gap",
                                          "budget_scale": scale})
    assert out["budget_scale"] == float(scale)


@pytest.mark.parametrize("scale", [0, -1.0, float("inf"), True, "1",
                                   None])
def test_distill_budget_scale_rails_refuse(scale):
    with pytest.raises(ActionParamError) as exc:
        action_params.normalize_params("distill",
                                       {"formulation": "gap",
                                        "budget_scale": scale})
    assert "budget_scale" in str(exc.value)


def test_parse_action_builds_the_distill_action():
    doc = {"schema": "action/1", "kind": "distill", "target": "task",
           "params": {"formulation": "the unpack rung is missing"},
           "budget": {"wall_s": 600.0, "max_calls": None},
           "context": {"rollout_id": "ro-1", "step_id": "s-1",
                       "policy_version": "v2"}}
    parsed = parse_action(doc)
    assert parsed.kind is ActionKind.DISTILL
    assert parsed.params["max_depth"] == 3
    assert parsed.params["sources"] == ("references", "web")


# ------------------------------------------------- the query-generation

def test_generate_queries_is_a_pure_pinned_function():
    state = {"findings": ["f"], "open_questions": ["how to unpack x",
                                                    "motives: web/u"],
             "conflicts": ["tool A says yes, tool B says no"]}
    once = distill.generate_queries(state)
    twice = distill.generate_queries(dict(state))
    assert once == twice
    # the pinned mapping: targeted as-is, counter-queries prefixed
    assert once == ["how to unpack x", "motives: web/u",
                    "counter: tool A says yes, tool B says no"]


def test_generate_queries_of_an_empty_trio_is_empty():
    assert distill.generate_queries({"findings": ["f"],
                                     "open_questions": [],
                                     "conflicts": []}) == []


# ------------------------------------------------------- the R3 record

def test_r3_completeness_fail_closed_named():
    clock = _Clock()
    for field in ("approach", "planning_pattern", "success_markers",
                  "failure_markers"):
        rec = _record()
        rec.pop(field)
        web = _web_source([[_web_doc("doc text")]])  # fresh per case
        with pytest.raises(DistillError) as exc:
            distill.research(Path("."), "gap", max_depth=1,
                             sources=("web",), clock=clock,
                             web_fetch=web,
                             extract_fn=lambda doc, r=dict(rec): dict(r))
        assert field in str(exc.value)


def test_r3_motives_constraints_absence_is_honest_not_an_error():
    """The #938 correction: no copying_risk, no suspicion machinery —
    a source that cannot state motives/constraints still extracts; the
    gap becomes a FOCUSED question that drives round 2 (and honest
    convergence once the focused round surfaces nothing new)."""
    clock = _Clock()
    web = _web_source([[_web_doc("doc one")], [_web_doc("doc two")]])

    def extract(doc: dict) -> dict:
        return _record(motives=None, constraints=None)

    out = distill.research(Path("."), "gap", max_depth=3,
                           sources=("web",), clock=clock, web_fetch=web,
                           extract_fn=extract)
    assert out["rounds_run"] == 2 and out["converged"] is True
    first = out["rounds"][0]["cognition"]
    assert any(q.startswith("motives: web/") for q in
               first["open_questions"])
    assert any(q.startswith("constraints: web/") for q in
               first["open_questions"])
    # the focused gaps ARE round 2's queries (the focused arm)
    assert out["rounds"][1]["queries"] == first["open_questions"]


def test_r3_extension_channels_ride_the_record():
    clock = _Clock()
    web = _web_source([[_web_doc("doc one")], [_web_doc("doc one again")]])
    rec = _record(open_questions=["how does the licensing gate key"],
                  conflicts=["source says CTR, sample says CBC"])
    out = distill.research(Path("."), "gap", max_depth=2,
                           sources=("web",), clock=clock, web_fetch=web,
                           extract_fn=lambda doc: dict(rec))
    cog = out["rounds"][0]["cognition"]
    assert "how does the licensing gate key" in cog["open_questions"]
    assert "source says CTR, sample says CBC" in cog["conflicts"]


# ------------------------------------------------- the round driver

def test_round1_queries_are_the_formulation():
    seen: list[list[str]] = []

    def spy_fetch(queries: list[str], width: int) -> list[dict]:
        seen.append(list(queries))
        return []

    original = distill._references_fetch
    distill._references_fetch = spy_fetch  # type: ignore
    try:
        distill.research(Path("."), "how do I unpack the packed stub",
                         max_depth=1, sources=("references",),
                         clock=_Clock(),
                         extract_fn=lambda doc: _record())
    finally:
        distill._references_fetch = original  # type: ignore
    assert seen == [["how do I unpack the packed stub"]]


def test_round_k_queries_come_from_the_prior_cognition():
    """The recursion: round 1's record lacks motives -> round 2's query
    is the focused motive question; the round-2 doc identifies them ->
    converged at depth 2 (the mal-recon conditional-recursion shape)."""
    clock = _Clock()
    rec_r1 = _record(motives=None)
    rec_r2 = _record()
    rounds: list[list[dict]] = [[_web_doc("doc one")],
                                [_web_doc("doc two",
                                          url="https://example.test/b")]]

    def extract(doc: dict) -> dict:
        return dict(rec_r1 if doc["provenance"]["url"].endswith("/a")
                    else rec_r2)

    web = _web_source(rounds)
    out = distill.research(Path("."), "gap", max_depth=3,
                           sources=("web",), clock=clock, web_fetch=web,
                           extract_fn=extract)
    assert out["rounds_run"] == 2 and out["converged"] is True
    r2_queries = out["rounds"][1]["queries"]
    assert r2_queries == [f"motives: web/https://example.test/a"]


def test_conflicts_generate_counter_queries_until_depth_cap():
    clock = _Clock()
    rec = _record(conflicts=["CTR vs CBC disagreement"])

    def extract(doc: dict) -> dict:
        return dict(rec)

    web = _web_source([[_web_doc("d1")], [_web_doc("d2")],
                       [_web_doc("d3")]])
    out = distill.research(Path("."), "gap", max_depth=3,
                           sources=("web",), clock=clock, web_fetch=web,
                           extract_fn=extract)
    assert out["rounds_run"] == 3 and out["converged"] is False
    for rnd in out["rounds"][1:]:
        assert rnd["queries"] == ["counter: CTR vs CBC disagreement"]


def test_max_depth_caps_the_recursion():
    clock = _Clock()

    def extract(doc: dict) -> dict:
        # a NEW open question every round (derived from the round's own
        # query) — the recursion never converges, the cap decides
        return _record(open_questions=[f"open {doc['query']}"])

    web = _web_source([[_web_doc("d1")], [_web_doc("d2")],
                       [_web_doc("d3")], [_web_doc("d4")]])
    out = distill.research(Path("."), "gap", max_depth=3,
                           sources=("web",), clock=clock, web_fetch=web,
                           extract_fn=extract)
    assert out["rounds_run"] == 3
    assert out["converged"] is False
    assert out["rounds"][1]["queries"] == ["open gap"]
    assert out["rounds"][2]["queries"] == ["open open gap"]


def test_convergence_stops_before_depth():
    clock = _Clock()

    def extract(doc: dict) -> dict:
        return _record()

    web = _web_source([[_web_doc("d1")]])
    out = distill.research(Path("."), "gap", max_depth=3,
                           sources=("web",), clock=clock, web_fetch=web,
                           extract_fn=extract)
    assert out["rounds_run"] == 1 and out["converged"] is True


def test_driver_rejects_garbage_inputs():
    clock = _Clock()
    extract = lambda doc: _record()  # noqa: E731
    with pytest.raises(DistillError):
        distill.research(Path("."), "   ", clock=clock, sources=("web",),
                         web_fetch=_web_source([[]]), extract_fn=extract)
    for depth in (0, 6, True):
        with pytest.raises(DistillError):
            distill.research(Path("."), "gap", max_depth=depth,
                             clock=clock, sources=("web",),
                             web_fetch=_web_source([[]]),
                             extract_fn=extract)
    with pytest.raises(DistillError):
        distill.research(Path("."), "gap", clock=clock, sources=(),
                         extract_fn=extract)
    with pytest.raises(DistillError) as exc:
        distill.research(Path("."), "gap", clock=clock,
                         sources=("references", "fuzzlib"),
                         extract_fn=extract)
    assert "fuzzlib" in str(exc.value)
    with pytest.raises(DistillError):
        distill.research(Path("."), "gap", clock=clock,
                         sources=("web",), extract_fn=extract)
    with pytest.raises(DistillError) as exc:
        distill.research(Path("."), "gap", clock=clock,
                         sources=("references",))
    assert "extract_fn" in str(exc.value)


def test_web_source_without_seam_refuses_fail_closed():
    with pytest.raises(DistillError) as exc:
        distill.research(Path("."), "gap", sources=("references", "web"),
                         clock=_Clock(), extract_fn=lambda doc: _record())
    assert "web" in str(exc.value) and "seam" in str(exc.value)


# ------------------------------------------------ the ledger landing

def test_records_and_cognition_land_as_credit_free_rows():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        real = Path(td)
        clock = _Clock()

        def extract(doc: dict) -> dict:
            return _record()

        web = _web_source([[_web_doc("d1")]])
        out = distill.research(real, "gap", max_depth=2,
                               sources=("web",), clock=clock,
                               web_fetch=web, extract_fn=extract)
        rows = _distill_rows(real)
        # one extraction row + one cognition row per round
        assert len(rows) == 2 * out["rounds_run"]
        for row in rows:
            assert row["source"] == "distill"
            assert row["credit"] is None      # standard settlement: the
            # row observes; the standard gates price it — no special path
            assert row["ts"] in clock.ticks   # driver clock only
        kinds = [r["claim"].split()[2] for r in rows]
        assert kinds == ["extract", "cognition"]
        assert all(r["reason"] in (distill.REASON_EXTRACT,
                                   distill.REASON_COGNITION)
                   for r in rows)


def test_research_receipt_is_deterministic():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        real = Path(td)
        clock_a, clock_b = _Clock(), _Clock()

        def extract(doc: dict) -> dict:
            return _record()

        def run(clock):
            web = _web_source([[_web_doc("d1")], [_web_doc("d2")]])
            return distill.research(real, "gap x", max_depth=2,
                                    sources=("web",), clock=clock,
                                    web_fetch=web, extract_fn=extract)

        a, b = run(clock_a), run(clock_b)
        a["rounds"] = b["rounds"] = []   # the receipts agree modulo the
        assert a == b                    # clock-stamped rows


# ------------------------------------------- the references source face

def test_references_is_a_first_class_source_with_provenance():
    """The REAL recall face runs (no mock): hits carry catalog
    provenance paths that resolve on disk under references/ — the
    cited integration is the import of the recall face."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        real = Path(td)
        clock = _Clock()

        def extract(doc: dict) -> dict:
            # a pure extraction: identity of the hit file -> R3
            rel = doc["provenance"]["path"]
            return _record(approach=f"study {rel}",
                           planning_pattern="read then map",
                           success_markers=[rel],
                           failure_markers=["none observed"])

        out = distill.research(
            real, "distillation deviation ledger", max_depth=1,
            sources=("references",), clock=clock, extract_fn=extract)
        assert out["rounds_run"] == 1
        records = out["rounds"][0]["records"]
        assert records, "the references face matched nothing"
        refs_root = ROOT / "references"
        for rec in records:
            assert rec["origin"] == "references"
            rel = rec["provenance"]["path"]
            assert (refs_root / rel).exists(), rel
        # the first hit is the deviation ledger itself (name-exact)
        assert records[0]["provenance"]["path"] == \
            "contracts/external-distilled/distillation-deviation-ledger.md"


def test_references_catalog_escape_path_is_skipped(tmp_path, monkeypatch):
    """A catalog row carrying ../ must not escape references/ — the
    containment skips it (warn) and the legit path still lands
    (the #938 review follow-up regression pin)."""
    import types

    import references_recall as rr

    hit = tmp_path / "references" / "contracts" / "real.md"
    hit.parent.mkdir(parents=True)
    hit.write_text("# real hit\n", encoding="utf-8")

    fake_index = types.SimpleNamespace(
        entries=types.SimpleNamespace(entries=None),
        scenes=None)
    fake_index.entries = type("E", (), {})()
    fake_index.entries.entries = []
    calls = {"n": 0}

    def fake_recall(entries, scenes, query):
        calls["n"] += 1
        class R:
            files = ["../outside.md", "contracts/real.md"]
        return R()

    monkeypatch.setattr(rr, "default_index_path",
                        lambda: tmp_path / "references" / "_INDEX.yaml")
    monkeypatch.setattr(rr, "build_index",
                        lambda p: fake_index)
    monkeypatch.setattr(rr, "recall", fake_recall)
    docs = distill._references_fetch(["q"], width=5)
    paths = [d["provenance"]["path"] for d in docs]
    assert paths == ["contracts/real.md"], \
        "the escape path must be skipped; the legit path lands"


def test_research_never_references_the_worker_seam():
    """EXECUTOR INDEPENDENCE (#938 correction): the distillation
    execution never involves the worker — the module does not even
    know the worker seam, and the research face takes no worker
    argument."""
    source = inspect.getsource(distill)
    assert "loop_worker" not in source
    assert "mock_worker" not in source
    params = inspect.signature(distill.research).parameters
    assert "worker" not in params


# ------------------------------------------------- the loop trigger

def _shelf_worker(formulation: str):
    calls = {"n": 0}

    def worker(situation: str, family: str) -> dict:
        out = mock_worker(situation, family)
        if out["verified"] and calls["n"] == 0:
            calls["n"] += 1
            return {**out, "shelf_miss": formulation}
        return out

    return worker


def _action_rows(ws, kind: str) -> list[dict]:
    return [r for r in q_cells.trajectory_rows(ws)
            if r.get("schema") == q_cells.SCHEMA_ACTION_V2
            and r.get("kind") == kind]


def test_shelf_miss_lands_one_distill_row(tmp_path):
    ws = tmp_path / "ws"
    loop913.run_loop(ws, laps=1, seed=7, spawn_slots=1,
                     worker=_shelf_worker("formulate the unpack rung"))
    rows = _action_rows(ws, "distill")
    assert len(rows) == 1
    row = rows[0]
    assert row["params"] == {
        "formulation": "formulate the unpack rung", "max_depth": 3,
        "sources": ["references", "web"], "budget_scale": 1.0}
    assert row["policy_version"] == loop913.POLICY_VERSION
    assert row["budget"]["wall_s"] == loop913.PER_DISPATCH_BUDGET_S * 1.0


def test_shelf_miss_research_seam_receives_no_worker(tmp_path):
    """The research execution is a SEPARATE Callable: it receives the
    workspace, the formulation, and the driver clock — never the
    worker (the double-emission collapse stays structurally impossible)."""
    ws = tmp_path / "ws"
    seen: dict = {}

    def research_seam(a_ws, formulation, *, clock=None):
        seen["ws"] = a_ws
        seen["formulation"] = formulation
        seen["clock"] = clock
        seen["argv"] = (a_ws, formulation)
        return {"schema": "distill-research/1", "rounds_run": 0}

    loop913.run_loop(ws, laps=1, seed=7, spawn_slots=1,
                     worker=_shelf_worker("gap: no unpack rung"),
                     distill_research=research_seam)
    assert seen["formulation"] == "gap: no unpack rung"
    assert seen["ws"] == ws
    assert seen["clock"] is not None and callable(seen["clock"].tick)
    assert "worker" not in inspect.signature(research_seam).parameters


def test_shelf_miss_without_seam_is_decision_only(tmp_path):
    ws = tmp_path / "ws"
    run, _ = loop913.run_loop(ws, laps=1, seed=7, spawn_slots=1,
                              worker=_shelf_worker("gap"))
    steps = [s for lap in run["report"]["per_lap"]
             for ro in lap["rollouts"] for s in ro["steps"]]
    triggered = [s for s in steps if s.get("distill")]
    assert triggered
    for step in triggered:
        assert step["distill"]["research"] is None
        assert step["distill"]["trigger"] == "shelf_miss"


def test_plain_worker_never_lands_distill_rows(tmp_path):
    ws = tmp_path / "ws"
    loop913.run_loop(ws, laps=1, seed=7, spawn_slots=1,
                     worker=mock_worker)
    assert _action_rows(ws, "distill") == []


def test_malformed_shelf_miss_refused_fail_closed(tmp_path):
    ws = tmp_path / "ws"
    calls = {"n": 0}

    def worker(situation: str, family: str) -> dict:
        out = mock_worker(situation, family)
        if out["verified"] and calls["n"] == 0:
            calls["n"] += 1
            return {**out, "shelf_miss": 123}
        return out

    with pytest.raises(loop913.LoopError) as exc:
        loop913.run_loop(ws, laps=1, seed=7, spawn_slots=1, worker=worker)
    assert "shelf" in str(exc.value).lower()

# -*- coding: utf-8 -*-
"""tests/test_rlvr_termination_461.py — the option-death termination
estimator + sampler floor wiring (issue 461 Phase 2: Bayesian
option-death, obstacle-attributed, floor-not-delete).

Pins the learned-termination contract:
  - posterior form: Beta per (obstacle-kind, method-family); death
    observation = ONE obstacle/1 row (attributed failure); alive
    evidence = the family's γ-discounted success mass from the q-cell
    fold (family-level); cause-free failures contribute nothing;
  - decision: posterior mean >= 0.75 with kinds conditioned on the
    current signature's ob= segment (the foreign-snapshot guard);
    zero-registry verdicts = {} (no kwarg at all);
  - sampler: duck-typed death mapping floors a dead family's weight
    (never zeroes it — PARK revivability), additive receipt block,
    byte-identity for the DRAW absent verdicts, malformed multiplier
    fail-open, q_cells import wall (attribution-blind sampler), both
    production hosts threaded fail-open;
  - float pins use the float.hex idiom (the bit-exact suite's
    encoding); NEW pins live HERE — the frozen
    tests/test_rlvr_bitexact.py is untouched (16/16).

All fixtures are SYNTHETIC (privacy rule).
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from rlvr import obstacles, q_cells  # noqa: E402
from rlvr import termination as term  # noqa: E402

TS = "2026-09-30T00:00:00Z"

# registered trap vocabulary (EX-4; production Q-key tokens)
FAM = "dynamic-trace"
FAM2 = "crypto-core-identification"

_PROBE_TEXT = (
    "cmd: isolation-probe --variant=clean\nrc=1\n"
    "stdout: Process terminated 30s after attach (ptrace stop, 2/2)\n"
)


def _fhex(value) -> str:
    """The pinned encoding of one float: exact hex (never approx)."""
    return float(value).hex()


def _assert_hex(label: str, value, golden_hex: str) -> None:
    assert _fhex(value) == golden_hex, (
        f"PIN FAILED: {label}: got {float(value).hex()} ({value!r}), "
        f"golden {golden_hex} — option-death determinism wall "
        "(issue 461 P2): STOP, do not loosen; re-mint needs an owner "
        f"ruling"
    )


def _probe_file(ws: Path, name: str) -> str:
    d = ws / "runs" / "probes"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(_PROBE_TEXT, encoding="utf-8")
    return f"runs/probes/{name}"


def _record_deaths(ws: Path, kind: str, family: str, n: int) -> None:
    """n attributed failures via the REAL registry face (fixed ts)."""
    for i in range(n):
        rel = _probe_file(ws, f"p-{family}-{kind}-{i}.txt")
        out = obstacles.record(
            ws, kind=kind, cause=f"probe rc=1 ({i})", evidence_path=rel, method_family=family, ts=TS
        )
        assert out["appended"], out


def _settle(ws: Path, family: str, credit: float, sig: str = "aaaabbbbcccc", ts: str = TS) -> None:
    """One q-cell settlement observation (the real append face)."""
    out = q_cells.append_observation(ws, sig, family, credit, source="settlement", ts=ts)
    assert out["appended"], out


def _cells(report: dict) -> dict[tuple[str, str], dict]:
    return {(c["kind"], c["family"]): c for c in report["cells"]}


# ===========================================================================
# Requirement 1 — the option-death posterior over (kind, family)
# ===========================================================================


class TestPosteriorForm:
    def test_repeated_attributed_failures_cross_threshold(self, tmp_path):
        """One attributed failure: mean 2/3 (alive). Two: exactly 3/4 —
        dead at threshold. Pinned in float.hex (the a=0 crossing is
        the exactly-representable one)."""
        _record_deaths(tmp_path, "detection_trigger", FAM, 1)
        one = _cells(term.report(tmp_path))
        c = one[("detection_trigger", FAM)]
        assert c["deaths"] == 1
        _assert_hex("1-death alpha", c["alpha"], (1.0 + 1).hex())
        _assert_hex("1-death beta", c["beta"], (1.0 + 0).hex())
        # the DECISION mean is the unrounded α/(α+β) (the receipt's
        # p_dead is its 9-dp display rounding — 2/3 rounds off-pattern)
        _assert_hex("1-death mean", c["alpha"] / (c["alpha"] + c["beta"]), _fhex(2.0 / 3.0))
        assert c["dead"] is False

        _record_deaths(tmp_path, "detection_trigger", FAM, 1)
        two = _cells(term.report(tmp_path))
        c2 = two[("detection_trigger", FAM)]
        assert c2["deaths"] == 2
        _assert_hex("2-death alpha", c2["alpha"], (1.0 + 2).hex())
        _assert_hex("2-death beta", c2["beta"], (1.0 + 0).hex())
        _assert_hex("2-death mean", c2["p_dead"], _fhex(3.0 / 4.0))
        assert c2["dead"] is True  # 0.75 >= 0.75 — the pinned crossing

    def test_different_causes_different_posteriors(self, tmp_path):
        """Kind-keyed cells: the same family's failures under different
        causes stay in DISTINCT cells — unequal repetition under the
        two causes yields genuinely different posteriors (1 vs 2
        deaths: 2/3 vs 3/4), and neither cause's count pools into the
        other's cell (the kind is the cause resolution)."""
        _record_deaths(tmp_path, "detection_trigger", FAM, 1)
        _record_deaths(tmp_path, "encryption_layer", FAM, 2)
        cells = _cells(term.report(tmp_path))
        assert set(cells) == {("detection_trigger", FAM), ("encryption_layer", FAM)}
        dt = cells[("detection_trigger", FAM)]
        el = cells[("encryption_layer", FAM)]
        assert dt["deaths"] == 1 and el["deaths"] == 2  # no pooling
        assert dt["dead"] is False  # one attributed dt failure: alive
        assert el["dead"] is True  # two attributed el failures: dead
        assert dt["p_dead"] != el["p_dead"]  # genuinely distinct
        # decision means (unrounded α/(α+β); p_dead is the 9-dp display)
        _assert_hex("dt-cell mean", dt["alpha"] / (dt["alpha"] + dt["beta"]), _fhex(2.0 / 3.0))
        _assert_hex("el-cell mean", el["alpha"] / (el["alpha"] + el["beta"]), _fhex(3.0 / 4.0))

    def test_cause_free_failures_never_terminate(self, tmp_path):
        """Settlement failures (credit 0) with NO obstacle rows: zero
        cells, zero-registry verdicts, never dead — cause-free
        failures are the attribution protocol's feed, not death
        evidence (the owner's core ruling)."""
        for _ in range(10):
            _settle(tmp_path, FAM, 0.0)
        report = term.report(tmp_path)
        assert report["cells"] == []
        assert term.verdicts(tmp_path, [FAM]) == {}  # zero-registry rule
        v = term.option_dead(tmp_path, FAM)
        assert v["dead"] is False  # the decision face always answers

    def test_alive_mass_revives_a_dead_cell(self, tmp_path):
        """Two attributed deaths kill the cell; one settled success
        (alive mass 1.0 at stream end, weight 1.0) drops the mean to
        3/5 — revival with no dedicated code path (the fold runs both
        directions)."""
        _record_deaths(tmp_path, "detection_trigger", FAM, 2)
        assert _cells(term.report(tmp_path))[("detection_trigger", FAM)]["dead"] is True
        _settle(tmp_path, FAM, 1.0)
        c = _cells(term.report(tmp_path))[("detection_trigger", FAM)]
        _assert_hex("revived alpha", c["alpha"], (1.0 + 2).hex())
        _assert_hex("revived beta", c["beta"], (1.0 + 1.0).hex())
        _assert_hex("revived mean", c["p_dead"], _fhex(3.0 / 5.0))
        assert c["dead"] is False
        v = term.option_dead(tmp_path, FAM)
        assert v["dead"] is False and v["weight_multiplier"] == 1.0

    def test_alive_mass_delays_death(self, tmp_path):
        """With one success banked BEFORE the deaths, two attributed
        failures do not kill (3/(3+2) < 0.75): each alive unit costs
        ~3 further deaths."""
        _settle(tmp_path, FAM, 1.0)
        _record_deaths(tmp_path, "tool_limit", FAM, 2)
        c = _cells(term.report(tmp_path))[("tool_limit", FAM)]
        assert c["dead"] is False

    def test_report_is_deterministic_and_clock_free(self, tmp_path):
        _record_deaths(tmp_path, "detection_trigger", FAM, 2)
        _settle(tmp_path, FAM2, 1.0)
        r1 = term.report(tmp_path)
        r2 = term.report(tmp_path)
        assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)
        assert "ts" not in json.dumps(r1)  # no wall clock in receipts

    def test_fail_open_reads_never_raise(self, tmp_path):
        """Corrupt registry + unreadable everything: the empty report,
        never an exception (fail-open reads)."""
        d = tmp_path / "runs" / "obstacles"
        d.mkdir(parents=True)
        (d / "OBS-001.json").write_text("{not json", encoding="utf-8")
        report = term.report(tmp_path)
        assert report["cells"] == []
        assert term.option_dead(tmp_path, FAM)["dead"] is False


# ===========================================================================
# Requirement 2 — decision face + constants
# ===========================================================================


class TestDecisionFace:
    def test_policy_constants_pinned(self):
        assert term.DEATH_THRESHOLD == 0.75
        assert term.ARM_FLOOR == 0.1
        assert term.PRIOR_ALPHA == 1.0 and term.PRIOR_BETA == 1.0
        assert term.SCHEMA == "option-death/1"

    def test_state_conditioning_is_the_foreign_snapshot_guard(self, tmp_path):
        """A snapshot whose ob= pattern OMITS the cell's kind cannot
        trigger it (the state conditions the verdict)."""
        _record_deaths(tmp_path, "detection_trigger", FAM, 3)
        # the live snapshot: kinds present -> dead
        assert term.option_dead(tmp_path, FAM)["dead"] is True
        # a foreign snapshot carrying a different kind only: alive
        snap = {"obstacles": {"present": True, "count": 1, "kinds": "tool_limit=1"}}
        v = term.option_dead(tmp_path, FAM, snap=snap)
        assert v["dead"] is False
        # a foreign snapshot carrying nothing: alive
        snap0 = {"obstacles": {"present": False, "count": 0, "kinds": ""}}
        assert term.option_dead(tmp_path, FAM, snap=snap0)["dead"] is False

    def test_verdicts_zero_registry_returns_empty(self, tmp_path):
        assert term.verdicts(tmp_path, [FAM, FAM2]) == {}

    def test_no_cells_never_dead_any_alive_mass(self, tmp_path):
        _settle(tmp_path, FAM2, 1.0)  # breakthrough family, no rows
        _record_deaths(tmp_path, "detection_trigger", FAM, 2)
        v = term.verdicts(tmp_path, [FAM, FAM2])
        assert v[FAM2]["dead"] is False
        assert v[FAM2]["weight_multiplier"] == 1.0
        assert v[FAM2]["kind"] is None  # base cell, never dead
        assert v[FAM]["dead"] is True
        assert v[FAM]["weight_multiplier"] == term.ARM_FLOOR

    def test_verdict_pdead_is_max_over_present_kinds(self, tmp_path):
        _record_deaths(tmp_path, "detection_trigger", FAM, 2)
        _record_deaths(tmp_path, "encryption_layer", FAM, 1)
        v = term.verdicts(tmp_path, [FAM])
        assert v[FAM]["kind"] == "detection_trigger"  # the argmax cell
        assert v[FAM]["dead"] is True


# ===========================================================================
# Requirement 2 — the sampler floor (floor-not-delete)
# ===========================================================================


class TestSamplerFloor:
    STORE_ROWS = [
        {
            "schema": q_cells.OBS_SCHEMA,
            "ts": TS,
            "source": "settlement",
            "signature_hash": "aaaabbbbcccc",
            "method_family": FAM,
            "claim": None,
            "agent": None,
            "dispatch_id": None,
            "credit": 0.0,
        },
        {
            "schema": q_cells.OBS_SCHEMA,
            "ts": TS,
            "source": "settlement",
            "signature_hash": "aaaabbbbcccc",
            "method_family": FAM2,
            "claim": None,
            "agent": None,
            "dispatch_id": None,
            "credit": 1.0,
        },
    ]

    def _prior(self):
        return {FAM: 0.5, FAM2: 0.5}

    def _dead_map(self):
        return {
            FAM: {
                "family": FAM,
                "dead": True,
                "p_dead": 0.8,
                "kind": "detection_trigger",
                "alpha": 4.0,
                "beta": 1.0,
                "weight_multiplier": term.ARM_FLOOR,
                "threshold": term.DEATH_THRESHOLD,
            }
        }

    def test_floor_demotes_but_never_deletes(self):
        import random

        store = q_cells.InMemoryStore(self.STORE_ROWS)
        rng = random.Random("floor-pin")
        r = q_cells.sample_method_family(
            "aaaabbbbcccc", self._prior(), store, rng=rng, death=self._dead_map()
        )
        cand = r["candidates"][FAM]
        assert cand["death"]["dead"] is True
        assert cand["death"]["weight_multiplier"] == term.ARM_FLOOR
        # floored weight = p_llm * theta * floor — NONZERO (the PARK
        # posture: still samplable, revivable)
        assert cand["weight"] > 0.0
        expect = self._prior()[FAM] * cand["theta"] * term.ARM_FLOOR
        assert abs(cand["weight"] - expect) <= 1e-6
        # the alive competitor carries no death block
        assert "death" not in r["candidates"][FAM2]

    def test_draw_byte_identity_absent_and_empty_and_alive(self):
        import random

        store = q_cells.InMemoryStore(self.STORE_ROWS)
        args = ("aaaabbbbcccc", self._prior(), store)
        r_none = q_cells.sample_method_family(*args, rng=random.Random("s"))
        r_empty = q_cells.sample_method_family(*args, rng=random.Random("s"), death={})
        alive_map = {
            FAM: {
                "family": FAM,
                "dead": False,
                "p_dead": 0.4,
                "kind": None,
                "alpha": 1.0,
                "beta": 1.0,
                "weight_multiplier": 1.0,
                "threshold": term.DEATH_THRESHOLD,
            },
            FAM2: {
                "family": FAM2,
                "dead": False,
                "p_dead": 0.3,
                "kind": None,
                "alpha": 1.0,
                "beta": 1.0,
                "weight_multiplier": 1.0,
                "threshold": term.DEATH_THRESHOLD,
            },
        }
        r_alive = q_cells.sample_method_family(*args, rng=random.Random("s"), death=alive_map)
        assert json.dumps(r_none, sort_keys=True) == json.dumps(r_empty, sort_keys=True)
        assert r_alive["family"] == r_none["family"]
        for fam in (FAM, FAM2):
            # a SUPPLIED verdict always rides the receipt (alive too)
            assert "death" in r_alive["candidates"][fam]
            assert r_alive["candidates"][fam]["death"]["dead"] is False
            stripped = {k: v for k, v in r_alive["candidates"][fam].items() if k != "death"}
            assert stripped == r_none["candidates"][fam]

    def test_malformed_multiplier_fails_open_to_one(self):
        import random

        store = q_cells.InMemoryStore(self.STORE_ROWS)
        bad = {FAM: {"dead": True, "p_dead": 0.9, "weight_multiplier": "garbage"}}
        zero = {FAM: {"dead": True, "p_dead": 0.9, "weight_multiplier": 0.0}}  # would DELETE
        huge = {FAM: {"dead": True, "p_dead": 0.9, "weight_multiplier": 5.0}}
        for death_map in (bad, zero, huge):
            r = q_cells.sample_method_family(
                "aaaabbbbcccc", self._prior(), store, rng=random.Random("s"), death=death_map
            )
            cand = r["candidates"][FAM]
            assert cand["death"]["weight_multiplier"] == 1.0, (
                f"effective multiplier must degrade to 1.0: {death_map}"
            )
            base = q_cells.sample_method_family(
                "aaaabbbbcccc", self._prior(), store, rng=random.Random("s")
            )
            assert cand["weight"] == base["candidates"][FAM]["weight"]

    def test_q_cells_import_wall_attribution_blind(self):
        """The sampler NEVER imports termination/obstacles under any
        import form (full module strings — the freeze-test idiom)."""
        tree = ast.parse((SCRIPTS / "rlvr" / "q_cells.py").read_text(encoding="utf-8"))
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    mods.add(a.name)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    base = f"rlvr.{base}" if base else "rlvr"
                if base:
                    mods.add(base)
                for a in node.names:
                    mods.add(f"{base}.{a.name}" if base else a.name)
        bad = {
            m
            for m in mods
            if m.endswith(".termination")
            or m == "termination"
            or m.endswith(".obstacles")
            or m == "obstacles"
        }
        assert not bad, f"q_cells imports attribution faces: {bad}"


# ===========================================================================
# Requirement 2 — both production hosts threaded fail-open
# ===========================================================================


class TestHostWiring:
    def test_strategy_store_termination_kwargs_fail_open(self, tmp_path, monkeypatch):
        from rlvr import strategy_store

        _record_deaths(tmp_path, "detection_trigger", FAM, 1)
        store = strategy_store.PosteriorStrategyStore(tmp_path)
        # zero registry rows -> {} (no kwarg); >=1 row -> a mapping
        kw = store._termination_kwargs()
        assert isinstance(kw, dict)

        # any failure -> {} (fail-open, never breaks method_lead)
        def _boom(*a, **k):
            raise RuntimeError("verdicts exploded")

        monkeypatch.setattr(term, "verdicts", _boom)
        assert store._termination_kwargs() == {}

    def test_strategy_store_zero_registry_no_kwarg(self, tmp_path):
        from rlvr import strategy_store

        store = strategy_store.PosteriorStrategyStore(tmp_path)
        assert store._termination_kwargs() == {}

    def test_envelope_host_threads_verdicts_source_pin(self):
        """scripts/e2e/checkpoints._sample_envelope_family carries the
        termination threading beside the feature-prior kwargs (the
        action-selection site is wired, not just the advisory lead)."""
        src = (ROOT / "scripts" / "e2e" / "checkpoints.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_sample_envelope_family"
        )
        body = ast.get_source_segment(src, fn)
        assert "termination" in body, "envelope sampler host has no termination threading"
        assert "verdicts" in body
        assert "death" in body


# ===========================================================================
# CLI face
# ===========================================================================


class TestCli:
    def test_report_subcommand_prints_the_receipt(self, tmp_path, capsys):
        _record_deaths(tmp_path, "detection_trigger", FAM, 2)
        rc = term.main(["report", str(tmp_path)])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["schema"] == term.SCHEMA
        assert out["threshold"] == term.DEATH_THRESHOLD
        assert _cells(out)[("detection_trigger", FAM)]["dead"] is True

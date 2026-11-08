# -*- coding: utf-8 -*-
"""tests/test_knowledge_family_move_1004.py — the knowledge family move
(issue 1004 R2c).

The guarded-root posterior store (strategy_store), the DTS Bernoulli
store (posteriors), the degeneracy breaker's read face (signal_guard),
the feature-conditioned prior table (feature_prior + the feature_mining
CLI), and the MARL negative-knowledge store (marl) move their IO onto
the consolidated knowledge family (``consolidated_ledger.append/read``):
``knowledge-store.jsonl`` under the guarded cross-task root becomes the
single live file, the per-module IO silos retire (the consolidated
append's lock is the ONE guard), public APIs stay byte-compatible, and
the compat window stays (LEGACY entries remain until the
schema-cutover slice).

Pins defined here:
  1. API compatibility  store_root / store_path / append_row /
     append_store_row / append_workspace_credit_row / load_rows /
     warm_pools / record / read / fold / check_degeneracy /
     recent_credits / freeze_if_degenerate / default_table_path /
     load_table / table_rows / pools_for_candidates / mine_run / mine /
     neg_store_path / signature_class / read_negatives /
     record_negative / negative_pools / broadcast_solution signatures
     unchanged; rows land in the family file carrying their EXISTING
     registered stamps; the legacy rels are no longer written by
     production code.
  2. Lock pin           only the consolidated ``.knowledge-store.lock``
     (under the guarded root) appears on disk; the per-module lock rels
     (runs/.posterior-store.lock, .marl-negative.lock) never do.
  3. Cross-task pin     two DIFFERENT workspaces arming the same
     guarded root read the same knowledge rows (the ws-insensitivity
     the cross-task store is designed around), and the per-workspace
     degeneracy series stays isolated (a foreign workspace's credits
     never enter this workspace's breaker series).
  4. Seal pin           the guarded store seals rows BEFORE the family
     append (sign_row at write, unchanged); ``trusted_rows`` accepts
     the sealed rows read back from the family file — an armed
     workspace must not start refusing its own rows because the file
     name changed (R5's workspace migration depends on this).
  5. Chronology         legacy rows first, then live rows — the
     dual-read order the future migration must reproduce (list
     equality on every moved reader).
  6. Stamp coexistence  the multi-schema family file keeps its reads
     prefix-disciplined: a posterior-store-prefixed read admits only
     posterior-store history (the R2b-verified pre-stamp rule), never
     a marl-negative or feature-table row.
  7. Legacy resolution  knowledge rels resolve under the guarded root
     EXCEPT the ws-scoped runs/ rels (the historical ws-local
     posterior-store series and the mined feature table) — the
     documented exception legacy_path implements; store_root stays the
     ONLY root resolver (consolidated_ledger._knowledge_root delegates,
     no second resolver appears).
  8. Miner family face  the feature_mining CLI's default output is the
     family file with an idempotent dedupe-append (append-only — a
     re-run appends nothing and never touches other schemas' rows);
     an explicit --out keeps the deterministic single-file rebuild.
  9. Read faces ride    the degeneracy breaker, the rl-posterior-moved
     liveness fingerprint, and the eval_split_lint schema-aware
     firewall face all read the family file (a dependent face left on
     the legacy path would go permanently stale post-move — the R2b
     lesson).
 10. Writer tripwire    no production writer names a knowledge legacy
     rel LITERAL inside a write-method call (a literal tripwire, not a
     full data-flow wall: a variable-mediated writer would pass — the
     sanctioned faces define the legacy rels as documented
     compat-window constants and touch no write call with them).
 11. Population pins    the family file co-locates three
     formerly-isolated posterior-store/1 populations (bank rows =
     cross-task; credit series = ws-local; DTS rows = ws-local) — every
     consumer sees exactly its pre-move population (review round 2):
     load_rows excludes the credit-kind-marked credit series; DTS rows
     carry workspace_id and read per-workspace isolated; a foreign
     credit row cannot certify the l1_planner cross-task face, suppress
     the solution broadcast, or move warm anchor mass; revoke is
     workspace-scoped, stays out of the credit series, and its rewrites
     run inside the consolidated flock; migrate archives the two
     same-named posterior rels without collision; the breaker series
     rides trusted_rows.

All fixtures are SYNTHETIC (privacy rule). Every family-IO test arms an
ISOLATED guarded root via KUNGLAO_POSTERIOR_STORE — the repo's own
patterns dir is never touched.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rlvr.consolidated_ledger as cl  # noqa: E402
import rlvr.marl as marl  # noqa: E402
import rlvr.posteriors as dts  # noqa: E402
import rlvr.strategy_store as ss  # noqa: E402
import feature_mining as fm  # noqa: E402
import rlvr.feature_prior as fp  # noqa: E402
import rlvr.learning_seal as seal  # noqa: E402
import rlvr.signal_guard as sg  # noqa: E402
from rlvr import crystallize as crystallize_mod  # noqa: E402
from rlvr import l1_planner  # noqa: E402

POSTERIOR_STAMP = "posterior-store/1"
MARL_STAMP = "marl-negative/1"
FEATURE_STAMP = "feature-table/1"
STORE_ENV = "KUNGLAO_POSTERIOR_STORE"

#: the knowledge legacy rels this slice retires the writers of
KNOWLEDGE_LEGACY_RELS = (
    "posterior-store.jsonl",        # guarded root (cross-task store)
    "marl-negative.jsonl",          # guarded root (negative knowledge)
    "runs/posterior-store.jsonl",   # ws-local (DTS rows + credit series)
    "runs/feature-table.jsonl",     # ws-local (mined feature table)
)


def _armed_root(tmp_path: Path, monkeypatch, name: str = "root") -> Path:
    """An isolated guarded root for one test (the env override — the
    single root resolver reads it at call time)."""
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(STORE_ENV, str(root))
    return root


def _family_rows(root: Path) -> list[dict]:
    p = root / "knowledge-store.jsonl"
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _write_rows(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                         for r in rows), encoding="utf-8")


def _credit_row(ws_name: str, credit: float, claim: str) -> dict:
    """A synthetic ws-local credit-series row (the
    append_workspace_credit_row shape — one builder, two faces)."""
    return {"schema": POSTERIOR_STAMP, "ts": "2026-11-08T00:00:00Z",
            "workspace_id": ws_name, "arm_key": "graph",
            "method_family": "graph", "feature_key": "none",
            "fingerprint": None, "status": "ROUND_CREDIT",
            "credit": credit, "censored": False, "facts_citing": 0,
            "propensity": None, "phi_delta": None,
            "provenance": {"dispatch_id": claim},
            "claim": claim, "dispatch_id": claim,
            "credit_kind": "step"}


# ---------- 1. API compatibility ----------

class TestApiCompatibility:
    def test_public_signatures_unchanged(self):
        expect = {
            (ss.__name__, "store_root"): [],
            (ss.__name__, "store_path"): [],
            (ss.__name__, "append_row"): ["row"],
            (ss.__name__, "append_workspace_credit_row"): ["ws"],
            (ss.__name__, "load_rows"): ["ws"],
            (ss.__name__, "warm_pools"): ["ws", "families"],
            (dts.__name__, "record"):
                ["ws", "state", "arm", "outcome"],
            (dts.__name__, "read"): ["ws"],
            (dts.__name__, "fold"): ["ws"],
            (sg.__name__, "check_degeneracy"): ["credits"],
            (sg.__name__, "recent_credits"): ["ws"],
            (sg.__name__, "freeze_if_degenerate"): ["ws", "credits"],
            (fp.__name__, "default_table_path"): ["ws"],
            (fp.__name__, "load_table"): ["path"],
            (fp.__name__, "table_rows"): ["feature_table"],
            (fp.__name__, "pools_for_candidates"):
                ["feature_table", "features", "families"],
            (fm.__name__, "mine_run"): ["root", "run_dir"],
            (fm.__name__, "mine"): ["roots", "out"],
            (marl.__name__, "neg_store_path"): [],
            (marl.__name__, "signature_class"): ["ws"],
            (marl.__name__, "read_negatives"): [],
            (marl.__name__, "record_negative"): ["ws"],
            (marl.__name__, "negative_pools"): ["ws", "families"],
            (marl.__name__, "broadcast_solution"): ["ws"],
        }
        checked = 0
        for (mod, name), params in expect.items():
            func = getattr({ss.__name__: ss, dts.__name__: dts,
                            sg.__name__: sg, fp.__name__: fp,
                            fm.__name__: fm,
                            marl.__name__: marl}[mod], name)
            got = [p for p in inspect.signature(func).parameters]
            # positional prefix pinned (keyword-only extras allowed —
            # the API-compat contract is about the call faces, not
            # private keyword knobs)
            assert got[:len(params)] == params, \
                f"{mod}.{name}{got} != {params} prefix"
            checked += 1
        assert checked == len(expect)

    def test_append_store_row_keywords_unchanged(self):
        """append_store_row / record_negative / broadcast_solution keep
        their keyword faces byte-compatible (the settlement hook and
        the broadcast face are production callers)."""
        for func in (ss.append_store_row, ss.append_workspace_credit_row):
            kw = list(inspect.signature(func).parameters)
            for name in ("method_family", "status", "credit"):
                assert name in kw, (func.__name__, name)
        for name in ("method_family", "agent_type", "tool_chain",
                     "features", "claim_ref", "step_ref"):
            assert name in inspect.signature(
                marl.record_negative).parameters, name
        for name in ("method_family", "credit", "agent_type", "claim",
                     "answer"):
            assert name in inspect.signature(
                marl.broadcast_solution).parameters, name

    def test_cross_task_store_row_lands_in_family_file(
            self, tmp_path, monkeypatch):
        root = _armed_root(tmp_path, monkeypatch)
        out = ss.append_store_row(method_family="graph", status="ok",
                                  credit=1.0)
        assert out["appended"] is True
        rows = _family_rows(root)
        assert len(rows) == 1
        assert rows[0]["schema"] == POSTERIOR_STAMP == ss.STORE_SCHEMA
        assert rows[0]["method_family"] == "graph"
        # the legacy rel is NOT written by production code anymore
        assert not (root / "posterior-store.jsonl").exists()

    def test_ws_credit_row_lands_in_family_file(self, tmp_path,
                                                monkeypatch):
        root = _armed_root(tmp_path, monkeypatch)
        ws = tmp_path / "ws-a"
        ws.mkdir()
        out = ss.append_workspace_credit_row(
            ws, method_family="graph", status="ROUND_CREDIT",
            credit=1.0, claim="C-1", credit_kind="step")
        assert out["appended"] is True
        rows = _family_rows(root)
        assert len(rows) == 1
        assert rows[0]["schema"] == POSTERIOR_STAMP
        assert rows[0]["workspace_id"] == "ws-a"
        assert rows[0]["credit_kind"] == "step"
        # the ws-local legacy rel is NOT written by production anymore
        assert not (ws / "runs" / "posterior-store.jsonl").exists()

    def test_dts_row_lands_in_family_file(self, tmp_path, monkeypatch):
        root = _armed_root(tmp_path, monkeypatch)
        ws = tmp_path / "ws"
        ws.mkdir()
        out = dts.record(ws, "sig", "graph", 1)
        assert out["appended"] is True
        rows = _family_rows(root)
        assert len(rows) == 1
        assert rows[0]["schema"] == POSTERIOR_STAMP == dts.SCHEMA
        assert rows[0]["state"] == "sig"
        assert rows[0]["arm"] == "graph"
        assert rows[0]["outcome"] == 1
        assert not (ws / "runs" / "posterior-store.jsonl").exists()

    def test_marl_row_lands_in_family_file(self, tmp_path, monkeypatch):
        root = _armed_root(tmp_path, monkeypatch)
        ws = tmp_path / "ws"
        ws.mkdir()
        out = marl.record_negative(ws, method_family="frida",
                                   agent_type="worker",
                                   features={"lane": "apk"})
        assert out["appended"] is True
        rows = _family_rows(root)
        assert len(rows) == 1
        assert rows[0]["schema"] == MARL_STAMP == marl.NEG_SCHEMA
        assert rows[0]["method_family"] == "frida"
        assert not (root / "marl-negative.jsonl").exists()

    def test_neg_store_path_is_the_family_file(self, tmp_path,
                                               monkeypatch):
        root = _armed_root(tmp_path, monkeypatch)
        assert marl.neg_store_path() == cl.family_path(None, "knowledge")
        assert marl.neg_store_path() == root / "knowledge-store.jsonl"


# ---------- 2. the lock pin ----------

class TestSingleGuardLock:
    def test_family_lock_is_the_only_lock_rel_on_disk(
            self, tmp_path, monkeypatch):
        root = _armed_root(tmp_path, monkeypatch)
        ws = tmp_path / "ws"
        ws.mkdir()
        ss.append_store_row(method_family="graph", status="ok", credit=1.0)
        ss.append_workspace_credit_row(ws, method_family="graph",
                                       status="ROUND_CREDIT", credit=0.5)
        dts.record(ws, "sig", "graph", 0)
        marl.record_negative(ws, method_family="frida")
        # the consolidated append's lock is the ONE guard, under the
        # guarded root (NOT the workspace)
        assert (root / ".knowledge-store.lock").exists()
        assert not (ws / "runs" / ".knowledge-store.lock").exists()
        # no per-module lock rel ever appears
        for lock in ("runs/.posterior-store.lock", ".marl-negative.lock",
                     "runs/.marl-negative.lock"):
            assert not (root / lock).exists(), lock
            assert not (ws / lock).exists(), lock
        # the moved modules carry no lock machinery of their own
        assert not hasattr(dts, "_locked_append")
        assert not hasattr(dts, "_lock_path")


# ---------- 3. the cross-task pin ----------

class TestCrossTask:
    def test_two_workspaces_read_the_same_family_rows(
            self, tmp_path, monkeypatch):
        """The knowledge family ignores ws: two DIFFERENT workspaces
        arming the same guarded root see the same rows — and a
        workspace never warm-starts from its own rows (the
        leave-one-out shape rides the shared file)."""
        _armed_root(tmp_path, monkeypatch)
        ws_a = tmp_path / "ws-a"
        ws_b = tmp_path / "ws-b"
        ws_a.mkdir()
        ws_b.mkdir()
        ss.append_store_row(ws_a, method_family="graph", status="ok",
                            credit=1.0)
        rows_a = cl.read(ws_a, "knowledge", schema_prefix="posterior-store")
        rows_b = cl.read(ws_b, "knowledge", schema_prefix="posterior-store")
        assert rows_a == rows_b
        assert len(rows_a) == 1
        # leave-one-out: B sees A's row, A does not see its own
        assert ss.load_rows(ws_b)[0]["workspace_id"] == "ws-a"
        assert ss.load_rows(ws_a) == []
        # the sampler's warm pools see the other workspace's mass
        pools = ss.warm_pools(ws_b, ["graph"])
        assert pools["graph"].rows == 1

    def test_degeneracy_series_stays_workspace_isolated(
            self, tmp_path, monkeypatch):
        """A foreign workspace's credits never enter this workspace's
        breaker series (the five-identical trip is per workspace —
        cross-task contamination would freeze one workspace's learning
        on another's dead signal), and the cross-task settlement rows
        (the scalar bank face — no credit_kind marker) are warm-pool
        evidence, never the breaker's series."""
        _armed_root(tmp_path, monkeypatch)
        ws_a = tmp_path / "ws-a"
        ws_b = tmp_path / "ws-b"
        ws_a.mkdir()
        ws_b.mkdir()
        for _ in range(5):
            ss.append_workspace_credit_row(ws_b, method_family="graph",
                                           status="ROUND_CREDIT",
                                           credit=0.25, credit_kind="step")
        assert sg.recent_credits(ws_a) == []
        assert sg.recent_credits(ws_b) == [0.25] * 5
        # ws B's signal is dead; ws A's is not
        assert sg.freeze_if_degenerate(ws_b, sg.recent_credits(ws_b)) \
            is True
        assert sg.freeze_if_degenerate(ws_a, sg.recent_credits(ws_a)) \
            is False
        # the cross-task face's rows (same workspace, no credit_kind)
        # never enter the series
        ss.append_store_row(ws_b, method_family="graph", status="ok",
                            credit=0.25)
        assert sg.recent_credits(ws_b) == [0.25] * 5


# ---------- 4. the seal interplay ----------

class TestSealInterplay:
    def test_store_row_sealed_before_the_family_append(
            self, tmp_path, monkeypatch):
        """The guarded store seals at write TODAY — the move keeps the
        seal: sign_row happens BEFORE the family append, and the sealed
        row read back from the family file passes trusted_rows (an
        armed workspace must not start refusing its own rows because
        the file name changed)."""
        key = tmp_path / "learning.key"
        key.write_bytes(b"k" * 48)
        monkeypatch.setattr(seal, "KEY_PATH", key)
        monkeypatch.setattr(seal, "_ANCHOR", {"build": None})
        assert seal.armed() is True
        root = _armed_root(tmp_path, monkeypatch, name="store-root")
        out = ss.append_row({"schema": ss.STORE_SCHEMA,
                             "ts": "2026-11-08T00:00:00Z",
                             "workspace_id": "ws-a",
                             "arm_key": "graph",
                             "method_family": "graph",
                             "feature_key": "none",
                             "fingerprint": None, "status": "ok",
                             "credit": 1.0, "censored": False,
                             "facts_citing": 0, "propensity": None,
                             "phi_delta": None,
                             "provenance": {"dispatch_id": ""}})
        assert out["appended"] is True
        rows = _family_rows(root)
        assert len(rows) == 1 and "seal" in rows[0]
        ok, why = seal.verify_row(rows[0])
        assert ok is True, why
        kept = seal.trusted_rows(rows, op="test.knowledge-family-move")
        assert kept == rows
        # the load face (trusted_rows inside) keeps the sealed row
        assert len(ss.load_rows()) == 1

    def test_forged_family_row_dropped_by_the_read_face(
            self, tmp_path, monkeypatch):
        key = tmp_path / "learning.key"
        key.write_bytes(b"k" * 48)
        monkeypatch.setattr(seal, "KEY_PATH", key)
        monkeypatch.setattr(seal, "_ANCHOR", {"build": None})
        assert seal.armed() is True
        root = _armed_root(tmp_path, monkeypatch, name="store-root")
        assert ss.append_store_row(method_family="graph", status="ok",
                                   credit=1.0)["appended"]
        forged = {"schema": ss.STORE_SCHEMA, "ts": "2026-01-01T00:00:00Z",
                  "workspace_id": "evil", "arm_key": "graph",
                  "method_family": "graph", "feature_key": "none",
                  "fingerprint": None, "status": "ok", "credit": 0.0,
                  "censored": False, "facts_citing": 0,
                  "propensity": None, "phi_delta": None,
                  "provenance": {"dispatch_id": ""}}
        family = root / "knowledge-store.jsonl"
        with family.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(forged) + "\n")
        kept = ss.load_rows()
        assert len(kept) == 1 and kept[0]["workspace_id"] != "evil"


# ---------- 5. chronology (the dual-read order) ----------

class TestChronology:
    def test_posterior_store_legacy_first_then_live(
            self, tmp_path, monkeypatch):
        root = _armed_root(tmp_path, monkeypatch)
        ws = tmp_path / "ws"
        ws.mkdir()
        # guarded-root history (the cross-task store's pre-move file)
        _write_rows(root / "posterior-store.jsonl", [
            _credit_row("ws-old", 0.9, "C-0")])
        # ws-local history (the credit series' pre-move file)
        _write_rows(ws / "runs" / "posterior-store.jsonl", [
            _credit_row("ws", 0.5, "C-1")])
        ss.append_workspace_credit_row(ws, method_family="graph",
                                       status="ROUND_CREDIT", credit=0.5,
                                       claim="C-2", credit_kind="step")
        rows = cl.read(ws, "knowledge", schema_prefix="posterior-store")
        assert [r.get("claim") for r in rows] == ["C-0", "C-1", "C-2"]
        assert rows[-1]["schema"] == POSTERIOR_STAMP
        # the legacy files were not appended to — the new row rode the
        # family file
        assert len((root / "posterior-store.jsonl")
                   .read_text(encoding="utf-8").splitlines()) == 1
        assert len((ws / "runs" / "posterior-store.jsonl")
                   .read_text(encoding="utf-8").splitlines()) == 1

    def test_dts_fold_legacy_first_then_live(self, tmp_path, monkeypatch):
        root = _armed_root(tmp_path, monkeypatch)
        ws = tmp_path / "ws"
        ws.mkdir()
        legacy = {"schema": POSTERIOR_STAMP, "state": "sig", "arm": "old",
                  "ts": "2026-11-01T00:00:00Z", "gamma": 0.9,
                  "outcome": 1, "alpha_add": 1.0, "beta_add": 0.0}
        _write_rows(ws / "runs" / "posterior-store.jsonl", [legacy])
        dts.record(ws, "sig", "new", 0)
        rows = dts.read(ws)
        assert [r["arm"] for r in rows] == ["old", "new"]
        view = dts.fold(ws)
        assert ("sig", "old") in view.cells
        assert ("sig", "new") in view.cells

    def test_marl_legacy_first_then_live(self, tmp_path, monkeypatch):
        root = _armed_root(tmp_path, monkeypatch)
        ws = tmp_path / "ws"
        ws.mkdir()
        legacy = {"schema": MARL_STAMP, "ts": "2026-11-01T00:00:00Z",
                  "signature_class": "abc123def456",
                  "agent_type": "worker", "method_family": "old",
                  "tool_chain": None, "fails": 1}
        _write_rows(root / "marl-negative.jsonl", [legacy])
        marl.record_negative(ws, method_family="new",
                             features={"lane": "apk"})
        rows = marl.read_negatives()
        assert [r["method_family"] for r in rows] == ["old", "new"]
        assert len((root / "marl-negative.jsonl")
                   .read_text(encoding="utf-8").splitlines()) == 1

    def test_feature_table_legacy_first_then_live(
            self, tmp_path, monkeypatch):
        root = _armed_root(tmp_path, monkeypatch)
        ws = tmp_path / "ws"
        ws.mkdir()
        # two mining roots over the SAME ws: the pre-move table rode the
        # ws-local rel, the post-move table rides the family file
        legacy_src = _mine_root(tmp_path / "legacy-src")
        live_src = _mine_root(tmp_path / "live-src")
        legacy = fm.mine_run(legacy_src, legacy_src / "runs" / "e2e"
                             / "run-1")
        assert legacy is not None
        live = dict(legacy, run_id="run-2", task_id="t-2")
        _write_rows(ws / "runs" / "feature-table.jsonl", [legacy])
        fp.default_table_path(ws).parent.mkdir(parents=True,
                                               exist_ok=True)
        _write_rows(fp.default_table_path(ws), [live])
        rows = fp.family_table_rows(ws)
        assert [r["run_id"] for r in rows] == ["run-1", "run-2"]
        # the ws-local legacy rel was not appended to
        assert len((ws / "runs" / "feature-table.jsonl")
                   .read_text(encoding="utf-8").splitlines()) == 1

    def test_compat_window_stays_legacy_entries_registered(self):
        # the schema cutover slice removes these — not this one.
        for rel in KNOWLEDGE_LEGACY_RELS:
            assert rel in cl.LEGACY["knowledge"], rel
            assert cl.LEGACY["knowledge"][rel] == \
                ({"posterior-store.jsonl": POSTERIOR_STAMP,
                  "marl-negative.jsonl": MARL_STAMP,
                  "runs/posterior-store.jsonl": POSTERIOR_STAMP,
                  "runs/feature-table.jsonl": FEATURE_STAMP}[rel],)
        assert inspect.signature(cl.read).parameters[
            "include_legacy"].default is True


# ---------- 6. stamp coexistence + no cross-rel leak ----------

class TestPrefixDiscipline:
    def test_family_file_multi_schema_reads_stay_disciplined(
            self, tmp_path, monkeypatch):
        root = _armed_root(tmp_path, monkeypatch)
        ws = tmp_path / "ws"
        ws.mkdir()
        ss.append_store_row(method_family="graph", status="ok", credit=1.0)
        marl.record_negative(ws, method_family="frida")
        posteriors = cl.read(ws, "knowledge",
                             schema_prefix="posterior-store")
        negatives = cl.read(ws, "knowledge", schema_prefix="marl-negative")
        assert [r["schema"] for r in posteriors] == [POSTERIOR_STAMP]
        assert [r["schema"] for r in negatives] == [MARL_STAMP]

    def test_liveness_counts_the_knowledge_family(
            self, tmp_path, monkeypatch):
        _armed_root(tmp_path, monkeypatch)
        ws = tmp_path / "ws"
        ws.mkdir()
        ss.append_store_row(method_family="graph", status="ok", credit=1.0)
        marl.record_negative(ws, method_family="frida")
        counts = cl.liveness(ws)
        assert counts["knowledge:posterior-store/1"] == 1
        assert counts["knowledge:marl-negative/1"] == 1
        assert counts["knowledge:feature-table/1"] == 0


# ---------- 7. the guarded-root resolution ----------

class TestGuardedRootSingleSource:
    def test_knowledge_root_delegates_to_store_root(
            self, tmp_path, monkeypatch):
        """store_root is the ONLY root resolver: the consolidated
        ledger's knowledge face delegates to it, so one env flip moves
        both faces together."""
        for name in ("root-one", "root-two"):
            monkeypatch.setenv(STORE_ENV, str(tmp_path / name))
            assert cl._knowledge_root() == ss.store_root()
            assert cl.family_path(tmp_path / "ws", "knowledge") == \
                ss.store_root() / "knowledge-store.jsonl"

    def test_ws_scoped_legacy_rels_resolve_under_the_workspace(
            self, tmp_path, monkeypatch):
        """The documented exception: the knowledge family's ws-scoped
        runs/ rels (the historical ws-local posterior series + mined
        feature table) resolve under the WORKSPACE; the guarded-root
        rels stay under the guarded root."""
        root = _armed_root(tmp_path, monkeypatch)
        ws = tmp_path / "ws"
        assert cl.legacy_path(ws, "knowledge", "posterior-store.jsonl") \
            == root / "posterior-store.jsonl"
        assert cl.legacy_path(ws, "knowledge", "marl-negative.jsonl") \
            == root / "marl-negative.jsonl"
        assert cl.legacy_path(ws, "knowledge",
                              "runs/posterior-store.jsonl") \
            == ws / "runs" / "posterior-store.jsonl"
        assert cl.legacy_path(ws, "knowledge",
                              "runs/feature-table.jsonl") \
            == ws / "runs" / "feature-table.jsonl"


# ---------- 8. the miner family face ----------

def _mine_root(tmp: Path) -> Path:
    """A minimal mining root: one e2e run dir with a run-state.json and
    the task_spec the extractor reads (SYNTHETIC)."""
    run_dir = tmp / "runs" / "e2e" / "run-1"
    run_dir.mkdir(parents=True)
    ws = tmp / "ws"
    ws.mkdir()
    (run_dir / "run-state.json").write_text(json.dumps({
        "run_id": "run-1", "family": "apk", "unit": "t-1",
        "ws": str(ws), "task_dir": str(ws)}), encoding="utf-8")
    (ws / "task_spec.yaml").write_text("lane: apk\n", encoding="utf-8")
    return tmp


class TestMinerFamilyFace:
    def test_default_out_is_the_family_file(self, tmp_path, monkeypatch):
        root = _armed_root(tmp_path, monkeypatch)
        assert fm.default_out() == cl.family_path(None, "knowledge")
        assert fm.default_out() == root / "knowledge-store.jsonl"

    def test_mine_appends_to_the_family_file_idempotently(
            self, tmp_path, monkeypatch):
        root = _armed_root(tmp_path, monkeypatch)
        mining = _mine_root(tmp_path)
        out1 = fm.mine([mining], fm.default_out())
        assert out1["rows"] == 1
        rows = _family_rows(root)
        assert len(rows) == 1
        assert rows[0]["schema"] == FEATURE_STAMP
        assert rows[0]["run_id"] == "run-1"
        # a re-run appends NOTHING (idempotent — the append-only
        # contract, never a rewrite of a multi-schema file)
        out2 = fm.mine([mining], fm.default_out())
        assert out2["rows"] == 1
        assert _family_rows(root) == rows

    def test_family_mine_preserves_other_schemas_rows(
            self, tmp_path, monkeypatch):
        root = _armed_root(tmp_path, monkeypatch)
        ss.append_store_row(method_family="graph", status="ok", credit=1.0)
        mining = _mine_root(tmp_path)
        fm.mine([mining], fm.default_out())
        kinds = [r["schema"] for r in _family_rows(root)]
        assert kinds == [POSTERIOR_STAMP, FEATURE_STAMP]

    def test_explicit_out_keeps_the_deterministic_rebuild(
            self, tmp_path, monkeypatch):
        _armed_root(tmp_path, monkeypatch)
        mining = _mine_root(tmp_path)
        out_a = tmp_path / "table-a.jsonl"
        out_b = tmp_path / "table-b.jsonl"
        fm.mine([mining], out_a)
        fm.mine([mining], out_a)
        fm.mine([mining], out_b)
        # the operator face stays the deterministic single-file rebuild:
        # byte-identical across re-runs and across equal inputs
        assert out_a.read_bytes() == out_b.read_bytes()
        rows = [json.loads(ln) for ln in
                out_a.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 1  # rewritten, not duplicated


# ---------- 9. the read faces ride the family ----------

class TestReadFacesRide:
    def test_rl_posterior_moved_fingerprint_reads_the_family(
            self, tmp_path, monkeypatch):
        spec = importlib.util.spec_from_file_location(
            "liveness_gate_1004r2c", ROOT / "devkit" / "liveness_gate.py")
        lg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lg)
        root = _armed_root(tmp_path, monkeypatch)
        assert ss.append_store_row(method_family="graph", status="ok",
                                   credit=1.0)["appended"]
        fp_spec = next(f for f in lg.load_fingerprints()["fingerprints"]
                       if f["id"] == "rl-posterior-moved")
        ok, detail = lg.evaluate_fingerprint(tmp_path / "ws", fp_spec)
        assert ok, detail

    def test_eval_split_lint_schema_face_admits_the_family_file(self):
        import eval_split_lint as esl
        violation = esl._scan_posterior_store(
            [_synthetic_family_file()], ["unit-holdout-1"])
        assert violation, "the schema-aware face must scan the family file"
        assert "knowledge-store.jsonl" in violation[0]


def _synthetic_family_file() -> Path:
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="esl-r2c-"))
    p = d / "knowledge-store.jsonl"
    _write_rows(p, [{"schema": POSTERIOR_STAMP, "ts": "2026-11-08T00:00:00Z",
                     "workspace_id": "ws", "arm_key": "g",
                     "method_family": "g", "feature_key": "none",
                     "fingerprint": None, "status": "ok", "credit": 1.0,
                     "censored": False, "facts_citing": 0,
                     "propensity": None, "phi_delta": None,
                     "provenance": {"dispatch_id": "unit-holdout-1"}}])
    return p


# ---------- 10. production writers never touch the legacy rels ----------

_WRITE_METHODS = {"open", "write_text", "write_bytes", "unlink",
                  "replace", "rename", "touch", "mkdir"}
# sanctioned legacy-face machinery: the migration core reads/moves the
# legacy rels and the retire CLI extends it — both retire in the
# schema-cutover / retire-CLI slices.
_MIGRATION_FACES = ("rlvr/consolidated_ledger.py",
                    "consolidate_ledgers.py")


def _production_sources() -> list[Path]:
    out = [p for base in (SCRIPTS, ROOT / "hooks")
           for p in sorted(base.rglob("*.py"))]
    return [p for p in out
            if p.name != "conftest.py"
            and not any(face in p.as_posix() for face in _MIGRATION_FACES)]


class TestNoLegacyWrites:
    def test_no_production_call_writes_a_legacy_rel(self):
        """Literal tripwire (not a data-flow wall): a production write
        call whose source segment names a knowledge legacy rel fails;
        a variable-mediated writer (path built in steps) would pass —
        the sanctioned faces define the legacy rels as documented
        compat-window constants and never touch a write call with
        them."""
        offenders: list[str] = []
        for path in _production_sources():
            src = path.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = (func.attr if isinstance(func, ast.Attribute)
                        else getattr(func, "id", ""))
                if name not in _WRITE_METHODS:
                    continue
                seg = ast.get_source_segment(src, node) or ""
                if any(rel in seg for rel in KNOWLEDGE_LEGACY_RELS):
                    offenders.append(
                        f"{path.relative_to(ROOT)}: {seg[:80]}")
        assert not offenders, (
            "production writers must not name a knowledge legacy rel "
            "literal in a write call (literal tripwire — the writers "
            "ride the consolidated family; variable-mediated writers "
            "are out of this tripwire's reach):\n"
            + "\n".join(offenders))


# ---------- 11. the review-fix pins (population + isolation + revoke) ----------

class TestPopulationContract:
    """The family file co-locates three formerly-isolated posterior-store
    populations (bank rows = cross-task by design; credit series =
    ws-local; DTS rows = ws-local). BEHAVIOR PRESERVATION: every
    consumer sees exactly its pre-move population (the ``credit_kind``
    marker + the per-row workspace_id are the uniform mechanism)."""

    def test_load_rows_excludes_the_credit_series(self, tmp_path,
                                                  monkeypatch):
        """load_rows' pre-move population was the guarded-root file's
        BANK rows only — the ws credit series (the breaker's rows,
        ``credit_kind``-marked) never lived there, and it stays
        invisible to every load_rows consumer post-move."""
        _armed_root(tmp_path, monkeypatch)
        ws = tmp_path / "ws"
        ws.mkdir()
        ss.append_workspace_credit_row(ws, method_family="graph",
                                       status="ROUND_CREDIT", credit=1.0,
                                       claim="C-1", credit_kind="step")
        ss.append_store_row(ws, method_family="graph", status="ok",
                            credit=0.5)
        rows = ss.load_rows()
        assert [r.get("credit_kind") for r in rows] == [None]
        assert rows[0]["status"] == "ok"
        # the credit rows still ride the file for their own reader
        assert any(r.get("credit_kind") == "step"
                   for r in _family_rows(cl._knowledge_root()))

    def test_cross_task_face_cannot_be_certified_by_a_foreign_credit(
            self, tmp_path, monkeypatch):
        """HIGH review fix: a foreign workspace's round credit for ITS
        colliding claim id can never satisfy the l1_planner cross-task
        answer face (pre-move the credit series was ws-local, invisible;
        per-workspace claim-id collisions are systematic). The DESIGNED
        cross-certification face — a solution broadcast bank row — still
        fires."""
        _armed_root(tmp_path, monkeypatch)
        ws_a = tmp_path / "ws-a"
        ws_b = tmp_path / "ws-b"
        ws_a.mkdir()
        ws_b.mkdir()
        ss.append_workspace_credit_row(
            ws_b, method_family="frida", status="ROUND_CREDIT",
            credit=0.8, claim="C-9", credit_kind="step")
        assert l1_planner._cross_task_face(ws_a, "C-9") == []
        # the broadcast population (bank rows carrying claim) is the
        # face's designed evidence — untouched
        ss.append_store_row(ws_b, method_family="frida", status="ok",
                            credit=1.0, claim="C-9")
        face = l1_planner._cross_task_face(ws_a, "C-9")
        assert len(face) == 1 and face[0]["source"] == "cross_task"

    def test_bridged_credit_cannot_suppress_the_broadcast(
            self, tmp_path, monkeypatch):
        """HIGH review fix: the one-broadcast-per-(claim, family)
        contract's dedupe rides the BANK population only — a bridged
        round credit row (claim + method_family set) is not a broadcast
        and never suppresses one."""
        _armed_root(tmp_path, monkeypatch)
        ws = tmp_path / "ws"
        ws.mkdir()
        ss.append_workspace_credit_row(ws, method_family="frida",
                                       status="ROUND_CREDIT", credit=0.5,
                                       claim="C-3", credit_kind="step")
        from rlvr.crystallize import _broadcast_duplicate
        assert _broadcast_duplicate("C-3", "frida") is False

    def test_credit_series_changes_no_warm_anchor_mass(
            self, tmp_path, monkeypatch):
        """HIGH review fix: warm_pools' composition is the BANK
        population — a dense per-claim credit series from another
        workspace adds ZERO anchor mass (pre-move it was ws-local
        breaker telemetry, invisible to the pools)."""
        _armed_root(tmp_path, monkeypatch)
        ws_a = tmp_path / "ws-a"
        ws_b = tmp_path / "ws-b"
        ws_a.mkdir()
        ws_b.mkdir()
        for credit in (0.1, 0.2, 0.3, 0.4, 0.5):
            ss.append_workspace_credit_row(
                ws_b, method_family="graph", status="ROUND_CREDIT",
                credit=credit, claim=f"C-{credit}", credit_kind="step")
        assert ss.warm_pools(ws_a, ["graph"]) == {}
        # exactly one BANK row moves the pool — and only by its mass
        ss.append_store_row(ws_b, method_family="graph", status="ok",
                            credit=1.0)
        pools = ss.warm_pools(ws_a, ["graph"])
        assert pools["graph"].rows == 1

    def test_dts_rows_stay_workspace_isolated(self, tmp_path,
                                              monkeypatch):
        """HIGH review fix (the read face): DTS rows carry their owning
        workspace; two workspaces sharing one guarded root never fold
        each other's posteriors. (The bit-exact pins in
        test_rlvr_posteriors_428 pin the same property through values.)"""
        _armed_root(tmp_path, monkeypatch)
        ws_a = tmp_path / "ws-a"
        ws_b = tmp_path / "ws-b"
        ws_a.mkdir()
        ws_b.mkdir()
        dts.record(ws_a, "shared", "shared", 1, gamma=0.5, ts=TS_CONST)
        dts.record(ws_a, "shared", "shared", 1, gamma=0.5, ts=TS_CONST)
        dts.record(ws_b, "shared", "shared", 0, gamma=0.5, ts=TS_CONST)
        assert [r["outcome"] for r in dts.read(ws_a)] == [1, 1]
        assert [r["outcome"] for r in dts.read(ws_b)] == [0]
        view_a = dts.fold(ws_a)
        # γ=0.5, two passes: α = 0.5·1+1 = 1.5 → 0.5·1.5+1 = 1.75 —
        # ws B's failing obs must NOT be folded in here
        assert view_a.cell("shared", "shared")["alpha"] == 1.75


TS_CONST = "2026-11-09T00:00:00Z"


class TestRevokeScoping:
    def test_cross_ws_revoke_deletes_nothing_foreign(
            self, tmp_path, monkeypatch):
        """MED review fix: a revoke from workspace A never deletes
        workspace B's rows under a claim-id collision (per-workspace
        claim ids are systematic: C-1, C-2, ... in every workspace)."""
        _armed_root(tmp_path, monkeypatch)
        ws_a = tmp_path / "ws-a"
        ws_b = tmp_path / "ws-b"
        ws_a.mkdir()
        ws_b.mkdir()
        for ws in (ws_a, ws_b):
            ss.append_store_row(ws, method_family="frida", status="ok",
                                credit=1.0, claim="C-1")
            ss.append_workspace_credit_row(
                ws, method_family="frida", status="ROUND_CREDIT",
                credit=0.5, claim="C-1", credit_kind="step")
        out = crystallize_mod.revoke_claim(ws_a, "C-1")
        assert out["broadcasts_removed"] == 1
        rows = _family_rows(cl._knowledge_root())
        b_rows = [r for r in rows if r.get("workspace_id") == "ws-b"
                  and str(r.get("claim") or "") == "C-1"]
        assert len(b_rows) == 2, "ws B's rows must all survive"
        out = crystallize_mod.revoke_claim(ws_b, "C-1")
        assert out["broadcasts_removed"] == 1
        # both BANK rows revoked (each by its own workspace); the two
        # CREDIT rows survive — the credit series is outside revoke's
        # pre-move reach, and nothing foreign was ever touched
        rows = _family_rows(cl._knowledge_root())
        rest = [r for r in rows if str(r.get("claim") or "") == "C-1"]
        assert sorted(r.get("workspace_id") for r in rest) == \
            ["ws-a", "ws-b"]
        assert all(r.get("credit_kind") == "step" for r in rest)

    def test_credit_rows_are_never_revocable(self, tmp_path, monkeypatch):
        """Revoke's pre-move reach never touched the credit series — the
        workspace-scoped broadcast predicate stays in the BANK
        population (credit-kind rows survive every revoke)."""
        _armed_root(tmp_path, monkeypatch)
        ws = tmp_path / "ws"
        ws.mkdir()
        ss.append_workspace_credit_row(ws, method_family="frida",
                                       status="ROUND_CREDIT", credit=0.5,
                                       claim="C-1", credit_kind="step")
        out = crystallize_mod.revoke_claim(ws, "C-1")
        assert out["broadcasts_removed"] == 0
        assert [r for r in _family_rows(cl._knowledge_root())
                if r.get("credit_kind") == "step"]

    def test_revoke_rewrites_run_inside_the_family_lock(
            self, tmp_path, monkeypatch):
        """MED review fix: the revocation rewrites run INSIDE the
        consolidated flock (``consolidated_ledger.family_lock``) — a
        concurrent append between a rewrite's read and its atomic write
        can never be lost. Pinned deterministically through a lock spy
        (a timing race would make a thread-stress pin flaky, and a
        flaky pin is not a pin)."""
        from contextlib import contextmanager
        _armed_root(tmp_path, monkeypatch)
        ws = tmp_path / "ws"
        ws.mkdir()
        for i in range(3):
            ss.append_store_row(ws, method_family="frida", status="ok",
                                credit=1.0, claim="C-gone")
        for i in range(4):
            ss.append_store_row(ws, method_family="graph", status="ok",
                                credit=0.1, claim=f"C-keep-{i}")
        events: list[str] = []
        real_lock = cl.family_lock

        @contextmanager
        def _spy(ws_, family):
            events.append("enter")
            with real_lock(ws_, family):
                events.append("inside")
                yield
            events.append("exit")

        monkeypatch.setattr(cl, "family_lock", _spy)
        out = crystallize_mod.revoke_claim(ws, "C-gone")
        assert out["broadcasts_removed"] == 3
        assert events == ["enter", "inside", "exit"], (
            "the revocation rewrites must run inside the consolidated "
            "family lock")
        rows = _family_rows(cl._knowledge_root())
        kept = sorted(r.get("claim") or "" for r in rows
                      if str(r.get("claim") or "").startswith("C-keep"))
        assert kept == [f"C-keep-{i}" for i in range(4)]
        assert not [r for r in rows if r.get("claim") == "C-gone"]


class TestMigrateArchiveNaming:
    def test_knowledge_rels_archive_without_collision(
            self, tmp_path, monkeypatch):
        """LOW review fix: the knowledge family registers BOTH
        posterior-store rels (guarded root + ws-local) — the same file
        name. migrate() must archive them under DISTINCT names, never
        land ``copied-unarchived`` (rows in the family file AND the rel
        left on disk = a permanent double-count)."""
        root = _armed_root(tmp_path, monkeypatch)
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_rows(root / "posterior-store.jsonl", [
            {"schema": POSTERIOR_STAMP, "ts": "2026-11-01T00:00:00Z",
             "workspace_id": "old", "arm_key": "g", "method_family": "g",
             "feature_key": "none", "fingerprint": None, "status": "ok",
             "credit": 1.0, "censored": False, "facts_citing": 0,
             "propensity": None, "phi_delta": None,
             "provenance": {"dispatch_id": ""}},
            {"schema": POSTERIOR_STAMP, "ts": "2026-11-02T00:00:00Z",
             "workspace_id": "old", "arm_key": "g", "method_family": "g",
             "feature_key": "none", "fingerprint": None, "status": "ok",
             "credit": 0.5, "censored": False, "facts_citing": 0,
             "propensity": None, "phi_delta": None,
             "provenance": {"dispatch_id": ""}}])
        _write_rows(ws / "runs" / "posterior-store.jsonl", [
            _credit_row("ws", 0.9, "C-0")])
        report = cl.migrate(ws, ["knowledge"])
        statuses = {rel: entry["status"]
                    for rel, entry in report["knowledge"].items()}
        assert statuses == {
            "posterior-store.jsonl": "migrated",
            "marl-negative.jsonl": "absent",
            "runs/feature-table.jsonl": "absent",
            "runs/posterior-store.jsonl": "migrated"}
        # both rels gone from their pre-move locations
        assert not (root / "posterior-store.jsonl").exists()
        assert not (ws / "runs" / "posterior-store.jsonl").exists()
        # the family read returns each row EXACTLY once (no
        # double-count from a copied-unarchived rel)
        rows = cl.read(ws, "knowledge", schema_prefix="posterior-store")
        assert len(rows) == 3
        # distinct archive names, both under the archive dir — the two
        # same-named rels both take the family-qualified form (each sees
        # the other's flat name as taken), never one flat + one lost
        archived = sorted(p.name for p in
                          (ws / "runs" / "archive").iterdir())
        assert archived == ["knowledge__posterior-store.jsonl",
                            "knowledge__runs__posterior-store.jsonl"]


class TestBreakerSeriesSealed:
    def test_forged_credit_row_refused_from_the_series(
            self, tmp_path, monkeypatch):
        """LOW review fix: the breaker series rides trusted_rows — an
        armed workspace refuses a forged credit row naming it (the
        shared family file widened the forgery blast radius; the wall
        moves with it)."""
        key = tmp_path / "learning.key"
        key.write_bytes(b"k" * 48)
        monkeypatch.setattr(seal, "KEY_PATH", key)
        monkeypatch.setattr(seal, "_ANCHOR", {"build": None})
        assert seal.armed() is True
        root = _armed_root(tmp_path, monkeypatch)
        ws = tmp_path / "ws"
        ws.mkdir()
        forged = _credit_row("ws", 0.25, "C-1")
        forged.pop("seal", None)
        _write_rows(root / "knowledge-store.jsonl", [forged])
        assert sg.recent_credits(ws, 5) == []
        # the honest face: a SEALED credit row of the same shape passes
        sealed = seal.sign_row(dict(forged))
        _write_rows(root / "knowledge-store.jsonl", [sealed])
        assert sg.recent_credits(ws, 5) == [0.25]

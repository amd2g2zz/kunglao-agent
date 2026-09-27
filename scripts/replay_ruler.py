#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""replay_ruler.py — the replay ruler (#294): offline policy evaluation for
the DECIDE rank face.

The convergence loop had no feedback signal for ordering quality. This
harness closes it, READ-ONLY against the source workspace:

  1. load_history      — parse `.convergence_ledger.jsonl` (tolerating the
     mid-history schema drift: old rows carry no `dispatched_ids`/`decision`,
     event rows carry `type`, `rank_feeds` epochs are null on old events).
  2. build_universe    — the claim set ever open in the ledger + historical
     close ticks (open_ids semantics: RUNNING workers on new rows, open
     claims on old rows — both are "in flight", which is all the sim needs).
  3. simulate(config)  — serial-dispatch counterfactual: per tick, complete
     due completions, rank the dispatchable frontier with priority_ratio
     under the config (seed = case_face_seed(posteriors_at_tick, tick) —
     the #251 f(posterior_state, round) contract with the REPLAY tick as
     the round axis), dispatch the head, completion at tick + the claim's
     OBSERVED historical duration. TTC = first tick with nothing pending
     or running (the CONVERGED face: open_claims == 0), capped.
  4. D_t + relevance coupling — D_t = w_oracle*oracle_pass_norm +
     w_impl*checks_impl_norm + w_ev*pq_cov_mean over the PERSISTED factor
     vectors (mission_ledger history), pq_cov gated to OPEN primary
     questions. Activity (facts growth) with a flat D_t is reported as
     FLAT reward with a flagged window — high activity with zero mainline
     progress must never read as shaped progress (#294 annotation 2).

Configurations are dicts (w_downstream / d_weights) applied by
parameterizing the ranker's module constants per run and restoring them —
NO production default changes here. The three D_t weights and the two
downstream constants are FREE PARAMETERS: they must EARN their place on
real data (the ADR-001 governed procedure,
docs/adr-001-strategy-parameter-governance.md); this harness is what
makes that checkable. The former lambda_default/lambda_zero pair is
CONSUMED (#295): their λ=0.25 vs λ=0 comparison answered the
epistemology question — EXP-B found dh_pq identically zero in all real
rank events and the order digests were byte-identical at every tick —
so the ΔH face was REMOVED from the production ranker and the pair
collapsed away. The λ-check itself (lambda_check, below) stays: it
measures HISTORY, and old rank_feeds events legitimately carry dh_pq
strings the production face no longer emits.

SAFETY (hard, #137 doctrine):
  - the source workspace is opened READ-ONLY — every write (posteriors
    history stamping, rank_feeds emission) lands in a sandbox dir
    (tempfile.mkdtemp, or --sandbox-dir);
  - explicitly named paths only: no ambient workspace discovery;
  - the sandbox is isolated: rank_feeds from replayed ranks never enters
    the source's runs/logs;
  - the report carries NO wall clock (byte-identical double runs pin it).

Usage:
  python replay_ruler.py <workspace> [--sandbox-dir DIR] [--with-events]
                         [--configs-json FILE] [--max-ticks N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import priority_ratio as pr
import kunglao_log

SCHEMA = "kunglao-replay-ruler/1"

# replay-DERIVED D_t weights — FREE PARAMETERS (provisional equal thirds;
# they must earn their place on real data — report numbers, don't bake
# formulas: #294 plan supplement 2026-09-21).
D_W_ORACLE = 1.0 / 3.0
D_W_IMPL = 1.0 / 3.0
D_W_EV = 1.0 / 3.0

# serial-dispatch replay cap: a run that has not drained by then is
# reported unconverged (never a hang).
MAX_REPLAY_TICKS = 200

# the named configurations of the acceptance face, post-#295: the
# lambda_default/lambda_zero pair is CONSUMED — the λ epistemology check
# it served answered AGAINST the parameter (EXP-B: dh_pq ≡ 0 on all real
# events; #294: λ=0.25 vs λ=0 digests byte-identical) and the ΔH face is
# removed from the ranker, so a λ config axis no longer exists. The live
# TTC comparison axis is base (no downstream term) vs downstream (the
# #294 term at its pinned value). d_weights keeps its provisional thirds
# (they still owe their ADR-001 earn-in evidence).
DEFAULT_CONFIGS: dict[str, dict] = {
    "base": {
        "w_downstream": 0.0,
        "d_weights": {"w_oracle": D_W_ORACLE, "w_impl": D_W_IMPL,
                      "w_ev": D_W_EV},
    },
    "downstream": {
        "w_downstream": pr.W_DOWNSTREAM,
        "d_weights": {"w_oracle": D_W_ORACLE, "w_impl": D_W_IMPL,
                      "w_ev": D_W_EV},
    },
}


# ================================ history ================================

def load_history(ws: Path) -> list[dict]:
    """Every ledger row tagged: snapshots (no ``type``, has open_count)
    carry format=new|old (dispatched_ids presence); event rows carry
    is_snapshot=False. Unparseable rows are skipped (kunglao_log face)."""
    p = Path(ws) / ".convergence_ledger.jsonl"
    if not p.exists():
        return []
    out = []
    for e in kunglao_log.iter_jsonl(
            p.read_text(encoding="utf-8", errors="replace").splitlines()):
        if not isinstance(e, dict):
            continue
        if "type" not in e and "open_count" in e:
            out.append({"is_snapshot": True,
                        "format": "new" if "dispatched_ids" in e else "old",
                        "row": e})
        else:
            out.append({"is_snapshot": False, "format": "event", "row": e})
    return out


def round_of(ws: Path) -> int:
    """The #251 round axis: RAW snapshot-row count (single source)."""
    return pr.round_index(ws)


def _open_ids(row: dict) -> set[str]:
    return {str(x) for x in (row.get("open_ids") or [])}


@dataclass
class Universe:
    """Claims ever open in the ledger + historical timing faces.

    first_open / close_tick are SNAPSHOT INDICES (append order, machine-
    independent); a claim present in the trailing snapshot has
    closed=False and close_tick=len(snaps) (the sentinel the sim treats
    as "observed open forever" — its duration is the whole window)."""

    universe: set[str] = field(default_factory=set)
    first_open: dict[str, int] = field(default_factory=dict)
    close_tick: dict[str, int] = field(default_factory=dict)
    closed: dict[str, bool] = field(default_factory=dict)
    register: dict[str, dict] = field(default_factory=dict)
    deps: dict = field(default_factory=dict)
    n_snaps: int = 0
    facts_by_round: list[int] = field(default_factory=list)


def build_universe(history: list[dict], ws: Path) -> Universe:
    snaps = [h for h in history if h["is_snapshot"]]
    u = Universe(n_snaps=len(snaps))
    for i, s in enumerate(snaps):
        ids = _open_ids(s["row"])
        u.facts_by_round.append(int(s["row"].get("facts_total") or 0))
        for cid in ids:
            u.universe.add(cid)
            u.first_open.setdefault(cid, i)
    _close_ticks(u, snaps)
    # register + deps faces (needed for statuses/edges the ledger lacks)
    reg = _load_yaml(Path(ws) / "claim-register.yaml")
    for c in reg.get("claims") or []:
        if c.get("id"):
            u.register[str(c["id"])] = c
    u.deps = _load_yaml(Path(ws) / "claim_deps.yaml")
    return u


def _close_ticks(u: "Universe", snaps: list[dict]) -> None:
    """Close tick per claim: first snapshot index where an ever-open
    claim is absent AFTER having been present. Never-absent claims keep
    the sentinel len(snaps) with closed=False (observed open forever)."""
    for cid in u.universe:
        closed_at = None
        for i in range(u.first_open[cid] + 1, len(snaps)):
            if cid not in _open_ids(snaps[i]["row"]):
                closed_at = i
                break
        if closed_at is not None:
            u.close_tick[cid] = closed_at
            u.closed[cid] = True
        else:
            u.close_tick[cid] = len(snaps)
            u.closed[cid] = False


def duration_of(u: Universe, cid: str) -> int:
    """Observed historical duration in snapshot ticks (>= 1)."""
    span = u.close_tick.get(cid, u.n_snaps) - u.first_open.get(cid, 0)
    return max(1, int(span))


# ============================== posterior face ===========================

def _stamp_posteriors(sandbox: Path, tick: int) -> None:
    """Write the tick-indexed posterior state into the sandbox (the
    posterior-history surface runs/posterior-history/posteriors-<r>.yaml;
    latest r <= tick wins; absent surface leaves the base file)."""
    hdir = sandbox / "runs" / "posterior-history"
    if not hdir.is_dir():
        return
    best = None
    for p in sorted(hdir.glob("posteriors-*.yaml")):
        try:
            r = int(p.stem.split("-")[-1])
        except ValueError:
            continue
        if r <= tick:
            best = p
    if best is not None:
        shutil.copyfile(best, sandbox / "runs" / "posteriors.yaml")


_FACTOR_KEYS = ("oracle_pass", "checks_impl", "pq_cov")


def _load_factor_vectors(sandbox: Path) -> list[dict]:
    """Persisted per-round factor vectors (mission_ledger history). Two
    shapes tolerated (additive discipline): the vector INLINE in the
    history row (value_m appends ``**vector``), or nested under a
    ``factor`` key. Rows carrying none of the factor fields (repin and
    friends) are not vectors — skipped, never guessed."""
    p = sandbox / "runs" / "mission_ledger.yaml"
    doc = _load_yaml(p)
    hist = (doc.get("mission") or {}).get("history") or []
    out = []
    for h in hist:
        if not isinstance(h, dict):
            continue
        f = h.get("factor")
        if not isinstance(f, dict):
            f = h if any(k in h for k in _FACTOR_KEYS) else None
        if isinstance(f, dict) and "round" in f:
            out.append(f)
    return out


# ============================ D_t + coupling =============================

def _open_pqs(u: Universe, done: set[str]) -> set[str]:
    """PQs still answered by some non-DONE claim (the relevance gate)."""
    out = set()
    for cid in u.universe:
        if cid in done:
            continue
        pq = str((u.register.get(cid) or {}).get("answers_question") or "")
        if pq:
            out.add(pq)
    return out


def d_t_series(u: Universe, vectors: list[dict],
               d_weights: dict) -> tuple[list[float], bool]:
    """D_t per factor-vector round + availability flag.

    D_t = w_oracle*oracle_pass/max_op + w_impl*checks_impl/max_ci
          + w_ev*mean(pq_cov over OPEN PQs)
    each factor normalized by its own history max (deterministic,
    data-driven denominators); an all-zero factor contributes 0. The
    pq_cov face is RELEVANCE-GATED to open primary questions — coverage
    on answered PQs is bookkeeping, not mainline progress."""
    w = d_weights or {}
    w_or, w_im, w_ev = (float(w.get("w_oracle", D_W_ORACLE)),
                        float(w.get("w_impl", D_W_IMPL)),
                        float(w.get("w_ev", D_W_EV)))
    if not vectors:
        return [], False
    max_op = max((float(v.get("oracle_pass") or 0.0) for v in vectors),
                 default=0.0)
    max_ci = max((float(v.get("checks_impl") or 0.0) for v in vectors),
                 default=0.0)
    done_all: set[str] = set()
    series = []
    for v in vectors:
        # relevance gate: a vector round r maps to ledger snapshot r
        # (append order); claims closed by then are DONE
        done_all = {cid for cid in u.universe
                    if u.closed.get(cid)
                    and u.close_tick.get(cid, 10 ** 9) <= int(
                        float(v.get("round") or 0))}
        op = (float(v.get("oracle_pass") or 0.0) / max_op) if max_op > 0 else 0.0
        ci = (float(v.get("checks_impl") or 0.0) / max_ci) if max_ci > 0 else 0.0
        cov = v.get("pq_cov") or {}
        open_pqs = _open_pqs(u, done_all)
        vals = [float(cov[pq]) for pq in sorted(open_pqs)
                if str(pq) in cov] if open_pqs else []
        ev = (sum(vals) / len(vals)) if vals else 0.0
        series.append(w_or * op + w_im * ci + w_ev * ev)
    return series, True


def reward_windows(u: Universe, d_series: list[float], has_d: bool
                   ) -> tuple[bool, int]:
    """(reward_flat, flagged_windows) — the relevance coupling face.

    A window is one snapshot step with activity (facts_total growth) and
    zero ΔD_t. Flat reward = no D movement anywhere measurable. When no
    factor vectors exist, activity alone is FLAT by definition (nothing
    mainline was measured — never shape it into progress)."""
    if not has_d or len(d_series) < 2:
        moves = 0.0
    else:
        moves = max(d_series) - min(d_series)
    reward_flat = moves <= 1e-9
    flagged = 0
    if has_d and len(d_series) >= 2:
        for i in range(1, min(len(d_series),
                              max(len(u.facts_by_round), 0) + 1)):
            activity = (u.facts_by_round[i] - u.facts_by_round[i - 1]) \
                if i < len(u.facts_by_round) else 0
            moved = abs(d_series[i] - d_series[i - 1]) > 1e-9
            if activity > 0 and not moved:
                flagged += 1
    return reward_flat, flagged


# =============================== simulation ==============================

def cut_cycle_edges(deps: dict) -> set[tuple[str, str]]:
    """Edges inside a dependency cycle (Tarjan SCCs over the child->parent
    graph). A cycle is unsatisfiable by construction — no member can ever
    dispatch — yet history closed those claims: the live edges were
    written post-hoc by mint/record faces (the EXP-B gotcha list). The
    replay cuts exactly the intra-SCC edges, deterministically, and the
    rest of the graph keeps gating."""
    graph: dict[str, list[str]] = {}
    for child, parents in (deps or {}).items():
        graph[str(child)] = [str(p) for p in (parents or [])]
    cut: set[tuple[str, str]] = set()
    for comp in _tarjan_sccs(graph):
        if len(comp) < 2:
            continue
        members = set(comp)
        for child, parents in graph.items():
            for p in parents:
                if p in members and child in members:
                    cut.add((child, p))
    # self-loops are single-node SCCs the filter above skips — a claim
    # depending on itself is just as unsatisfiable, cut it too
    for child, parents in graph.items():
        if child in parents:
            cut.add((child, child))
    return cut


def _pop_component(v: str, stack: list[str], on: set[str]) -> list[str]:
    """Pop one SCC off the Tarjan stack (up to and including v)."""
    comp = []
    while True:
        w = stack.pop()
        on.discard(w)
        comp.append(w)
        if w == v:
            return comp


def _tarjan_sccs(graph: dict[str, list[str]]) -> list[list[str]]:
    """Iterative Tarjan strongly-connected components (deterministic
    order; single-node components returned as-is)."""
    index = 0
    stack: list[str] = []
    on: set[str] = set()
    idx: dict[str, int] = {}
    low: dict[str, int] = {}
    sccs: list[list[str]] = []
    for root in graph:
        if root in idx:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            v, pi = work[-1]
            if pi == 0:
                idx[v] = low[v] = index
                index += 1
                stack.append(v)
                on.add(v)
            advanced = False
            nbrs = graph.get(v, ())
            for i in range(pi, len(nbrs)):
                w = nbrs[i]
                if w not in idx:
                    work[-1] = (v, i + 1)
                    work.append((w, 0))
                    advanced = True
                    break
                if w in on:
                    low[v] = min(low[v], idx[w])
            if advanced:
                continue
            work.pop()
            if low[v] == idx[v]:
                sccs.append(_pop_component(v, stack, on))
            if work:
                pv = work[-1][0]
                low[pv] = min(low[pv], low[v])
    return sccs


def _reconstruct(u: Universe, done: set[str], running: dict[str, int],
                 ) -> list[dict]:
    """Register rows for the live frontier (pending + running), replay
    statuses (open claims PENDING; in-flight IN_PROGRESS), fresh attempt
    counts (history's per-tick attempts are unrecorded — the sim's own
    dispatch history is the counter that matters, and it is the run/done
    partition)."""
    rows = []
    for cid in sorted(u.universe):
        if cid in done:
            continue
        base = dict(u.register.get(cid) or {})
        base["id"] = cid
        base["status"] = "IN_PROGRESS" if cid in running else "PENDING"
        base["promotion_attempts"] = 0
        rows.append(base)
    return rows


def _rank_under_config(config: dict, claims: list[dict],
                       deps_face: dict, sandbox: Path, tick: int,
                       done: set[str]) -> list:
    """One rank face under a score configuration: parameterize the ranker
    constant, seed from the #251 contract at the replay tick, restore.
    This is the ONLY sanctioned runtime mutator of a ranker constant in
    the tree (ADR-001 §2.3: the harness may evaluate, never write back;
    pinned by tests/test_replay_ruler_294.py::TestNoRuntimeSelfTuning)."""
    ledger = pr.PosteriorLedger.load(sandbox)
    rng = random.Random(pr.case_face_seed(ledger, tick))
    # validate-then-assign: the conversion completes before the module
    # constant moves — a bad value ("abc") raises with nothing assigned.
    # (#295: the lambda_dh axis is consumed — see DEFAULT_CONFIGS.)
    wds = float(config.get("w_downstream", pr.W_DOWNSTREAM))
    saved = pr.W_DOWNSTREAM
    pr.W_DOWNSTREAM = wds
    try:
        evidence = pr.EvidenceView(
            terminal_fact_claims=frozenset(done), ws=sandbox)
        return pr.priority_ratio(claims, deps_face, evidence, rng=rng,
                                 round_no=tick)
    finally:
        pr.W_DOWNSTREAM = saved


def simulate(config: dict, u: Universe, sandbox: Path,
             max_ticks: int = MAX_REPLAY_TICKS) -> dict:
    """Serial-dispatch counterfactual replay (order-only: the sampler
    never influences the exit condition — it only chooses WHO is
    dispatched; the completion clock is the ledger's own history)."""
    dur = {cid: duration_of(u, cid) for cid in u.universe}
    superseded = {cid for cid, c in u.register.items()
                  if c.get("superseded_by")}
    pre_done = {cid for cid, c in u.register.items()
                if cid not in u.universe
                and (str(c.get("status") or "").upper() in pr.TERMINAL
                     or cid in superseded)}
    done: set[str] = set(pre_done)
    running: dict[str, int] = {}  # cid -> completion tick
    deps = (u.deps or {}).get("depends_on", {}) or {}
    if not deps:
        deps = {c.get("id"): list(c.get("depends_on") or [])
                for c in u.register.values()
                if c.get("id") and c.get("depends_on")}
    # post-hoc mint edges can form cycles history itself closed — cut the
    # intra-SCC edges (the replay gates on satisfiable structure only).
    # Local copy: the Universe stays unmutated across config runs
    # (immutability; the cut is recomputed per run, idempotent by
    # construction).
    cut = cut_cycle_edges(deps)
    if cut:
        deps = {c: [p for p in (ps or []) if (c, p) not in cut]
                for c, ps in deps.items()}
    deps_face = {"depends_on": deps}
    trajectory: list[dict] = []
    ttc = None
    converged = False
    for tick in range(1, max_ticks + 1):
        for cid in [c for c, due in running.items() if due <= tick]:
            done.add(cid)
            del running[cid]
        pending_left = [c for c in u.universe if c not in done
                        and c not in running]
        if not pending_left and not running:
            converged = True
            ttc = tick
            trajectory.append({"tick": tick, "open_ids": [],
                               "dispatched": [], "order": [],
                               "stall": False})
            break
        claims = _reconstruct(u, done, running)
        _stamp_posteriors(sandbox, tick)
        actions = _rank_under_config(config, claims, deps_face, sandbox,
                                     tick, done)
        order = [a.claim_id for a in actions]
        # dispatchability (the candidate filter re-derived here so a
        # no-candidate tick is a visible stall, not a silent skip)
        dispatchable = [cid for cid in order
                        if all(p in done or p in superseded
                               for p in (deps.get(cid) or []))]
        dispatched_now: list[str] = []
        if dispatchable:
            head = dispatchable[0]
            running[head] = tick + dur[head]
            dispatched_now = [head]
        trajectory.append({"tick": tick,
                           "open_ids": sorted(set(pending_left)
                                              | set(running)),
                           "dispatched": dispatched_now,
                           "order": order,
                           "stall": not dispatchable})
    if not converged:
        ttc = None
    order_digest = hashlib.sha256(json.dumps(
        [t["order"] for t in trajectory], sort_keys=True,
        ensure_ascii=False).encode("utf-8")).hexdigest()
    vectors = _load_factor_vectors(sandbox)
    d_series, has_d = d_t_series(u, vectors,
                                 config.get("d_weights") or {})
    reward_flat, flagged = reward_windows(u, d_series, has_d)
    return {
        "ttc": ttc,
        "converged": converged,
        "stall_ticks": sum(1 for t in trajectory if t["stall"]),
        "order_digest": order_digest,
        "d_t_series": [round(d, 6) for d in d_series],
        "reward_flat": reward_flat,
        "flagged_windows": flagged,
        "trajectory": trajectory,
    }


# ================================ lambda =================================

_DH_H_RE = re.compile(r"H=([0-9.]+)\s*bit")


def dh_pq_nonzero(dh_pq: str) -> bool:
    """Is this dh_pq feed string carrying a ΔH the λ term actually
    multiplies? The DECIDING VALUE is the parsed H number, never a
    sentinel grep: a settled single-candidate categorical prints
    "H=0.0 bit" with no "dH=0" marker and is λ-INERT exactly like the
    explicit "dH=0" face. No parsable H at all -> not signal (zero)."""
    m = _DH_H_RE.search(dh_pq or "")
    if m:
        try:
            return float(m.group(1)) > 0.0
        except ValueError:
            return False
    return False


def lambda_check(sandbox: Path) -> dict:
    """The λ epistemology check (annotation 1): scan HISTORICAL rank_feeds
    events (the sandbox's copy of runs/logs) for the dh_pq feed — was the
    ΔH term EVER nonzero in the wild? #295 answered this AGAINST the
    parameter and the production ranker no longer emits dh_pq at all
    (the ΔH face is removed, ADR-001); this face stays because it
    measures HISTORY — old events carry the strings, new ones carry no
    feed, which parses as inert. The TTC comparison half is the base vs
    downstream axis now; any NEW history-sensitive parameter change goes
    through the ADR-001 governed procedure."""
    scanned = 0
    nonzero = 0
    ldir = sandbox / "runs" / "logs"
    if ldir.is_dir():
        for p in sorted(ldir.glob("kunglao-*.jsonl")):
            for e in kunglao_log.iter_jsonl(
                    p.read_text(encoding="utf-8",
                                errors="replace").splitlines()):
                if not isinstance(e, dict) or e.get("action") != "rank_feeds":
                    continue
                try:
                    detail = json.loads(e.get("detail") or "{}")
                except (json.JSONDecodeError, TypeError):
                    continue
                feeds = detail.get("feeds") or {}
                if not isinstance(feeds, dict) or not feeds:
                    continue
                scanned += 1
                for f in feeds.values():
                    if dh_pq_nonzero(str((f or {}).get("dh_pq", ""))):
                        nonzero += 1
                        break
    rate = (nonzero / scanned) if scanned else 0.0
    return {"rank_events_scanned": scanned, "dh_nonzero": nonzero,
            "dh_nonzero_rate": round(rate, 6)}


def frozen_check(sandbox: Path) -> dict:
    """#266: run the rank face's frozen-sampling marker over the copied
    HISTORICAL rank_feeds tail (chronological: day-file name order, then
    line order — the kunglao_log._all_rows tolerance, inlined to keep the
    source read path single-faced)."""
    rows: list[dict] = []
    ldir = sandbox / "runs" / "logs"
    if ldir.is_dir():
        for p in sorted(ldir.glob("kunglao-*.jsonl")):
            rows.extend(e for e in kunglao_log.iter_jsonl(
                p.read_text(encoding="utf-8",
                            errors="replace").splitlines())
                if isinstance(e, dict))
    marks = pr.frozen_sampling_markers(rows)
    return {"windows": len(marks), "runs": marks}


# =============================== orchestration ===========================

_COPY_FACES = ("claim-register.yaml", "claim_deps.yaml")


def _copy_tree_glob(src_dir: Path, dst_dir: Path, pattern: str) -> None:
    """mkdir + copy every match of one glob, filename order."""
    if not src_dir.is_dir():
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    for p in sorted(src_dir.glob(pattern)):
        shutil.copyfile(p, dst_dir / p.name)


def _make_sandbox(source: Path, sandbox: Path, with_events: bool) -> None:
    """Copy the MINIMAL read surface into the sandbox (explicit faces
    only; the source is never written)."""
    sandbox.mkdir(parents=True, exist_ok=True)
    for name in _COPY_FACES:
        if (source / name).exists():
            shutil.copyfile(source / name, sandbox / name)
    led = source / ".convergence_ledger.jsonl"
    if led.exists():
        shutil.copyfile(led, sandbox / ".convergence_ledger.jsonl")
    runs = source / "runs"
    for rel in ("posteriors.yaml", "mission_ledger.yaml"):
        if (runs / rel).exists():
            (sandbox / "runs").mkdir(exist_ok=True)
            shutil.copyfile(runs / rel, sandbox / "runs" / rel)
    _copy_tree_glob(runs / "posterior-history",
                    sandbox / "runs" / "posterior-history",
                    "posteriors-*.yaml")
    _copy_tree_glob(source / "oracle" / "cases",
                    sandbox / "oracle" / "cases", "*.yaml")
    if with_events:
        _copy_tree_glob(source / "runs" / "logs",
                        sandbox / "runs" / "logs", "kunglao-*.jsonl")


def run_replay(ws: Path, configs: dict | None = None,
               sandbox: Path | None = None, with_events: bool = False,
               max_ticks: int = MAX_REPLAY_TICKS) -> dict:
    """Full replay report: per-configuration TTC + D_t + coupling faces,
    the λ check, and the universe echo. Deterministic and machine-
    independent (no wall clock in the report)."""
    source = Path(ws)
    if not source.is_dir():
        raise NotADirectoryError(f"workspace not found: {source}")
    owned = sandbox is None
    sb = Path(sandbox) if sandbox is not None else Path(
        tempfile.mkdtemp(prefix="replay-ruler."))
    try:
        if not owned and (sb.resolve() == source.resolve()
                          or source.resolve() in sb.resolve().parents):
            raise ValueError(
                "sandbox must be outside the source workspace (read-only "
                "source, #137)")
        _make_sandbox(source, sb, with_events)
        history = load_history(source)
        u = build_universe(history, source)
        rep = {
            "schema": SCHEMA,
            "universe": sorted(u.universe),
            "n_snaps": u.n_snaps,
            "round": round_of(source),
            "configs": {},
            "lambda_check": lambda_check(sb) if with_events
            else {"rank_events_scanned": 0, "dh_nonzero": 0,
                  "dh_nonzero_rate": 0.0, "available": False},
            "frozen_check": frozen_check(sb) if with_events
            else {"windows": 0, "runs": []},
        }
        for name, cfg in (configs or DEFAULT_CONFIGS).items():
            rep["configs"][name] = simulate(cfg, u, sb,
                                            max_ticks=max_ticks)
        return rep
    finally:
        if owned and sb.exists():
            shutil.rmtree(sb, ignore_errors=True)


def _load_yaml(path: Path) -> dict:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return doc if isinstance(doc, dict) else {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="replay_ruler.py",
        description="#294 replay ruler — offline TTC evaluation of the "
                    "rank face (read-only source, sandboxed writes)")
    ap.add_argument("workspace", help="source workspace (READ-ONLY)")
    ap.add_argument("--sandbox-dir", default=None,
                    help="explicit sandbox dir (default: fresh temp dir)")
    ap.add_argument("--with-events", action="store_true",
                    help="also copy runs/logs and run the λ epistemology "
                         "check over historical rank_feeds events")
    ap.add_argument("--configs-json", default=None,
                    help="JSON file of {name: config} score configurations")
    ap.add_argument("--max-ticks", type=int, default=MAX_REPLAY_TICKS)
    args = ap.parse_args(argv)
    configs = DEFAULT_CONFIGS
    if args.configs_json:
        configs = json.loads(
            Path(args.configs_json).read_text(encoding="utf-8"))
    rep = run_replay(args.workspace, configs=configs,
                     sandbox=Path(args.sandbox_dir)
                     if args.sandbox_dir else None,
                     with_events=args.with_events,
                     max_ticks=args.max_ticks)
    print(json.dumps(rep, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())

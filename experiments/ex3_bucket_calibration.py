# -*- coding: utf-8 -*-
"""ex3_bucket_calibration.py — EX-3: FACT_BUCKET_EDGES fill-distribution
replay over dispatch history (issue #429 W3-T3.2).

The W3 plan clause: "对 dispatch 历史重放签名，测格子填充分布；边界不当→
调 FACT_BUCKET_EDGES（声明+钉）". This harness replays the RECORDED
fact-count trajectories of a campaign's workspaces over the live
discretization (scripts/state_signature.FACT_BUCKET_EDGES, read — never
edited here) and reports the fill distribution:

  - workspaces = the #240 marker set (claim-register.yaml present),
    discovered by sorted rglob (scan order is data, so it is pinned
    deterministic);
  - trajectory face = the workspace's .convergence_ledger.jsonl
    ``facts_total`` history (one point per recorded snapshot — the
    recorded per-tick trajectory of the dispatch loop);
  - declared fallback = a workspace with NO convergence ledger
    contributes its terminal facts/F*.md count as a single point
    (state_signature.fact_face semantics — the same F*.md glob
    convergence_check._count_facts uses);
  - each point is bucketed by state_signature.fact_bucket — ONE
    discretization source, zero re-implementation;
  - verdict: "calibrate" requires, per the DECLARED_CRITERIA below, mass
    evidence that an edge cuts a dense region; otherwise
    "no-calibration" with the reason on the record. The live edges are
    NOT editable from this harness — a change is a separate declared
    diff (constants + re-mint) that CITES this file's results.

Output: experiments/ex3-results.json (+ this module's report doc).
Reproduce: uv run --project . python experiments/ex3_bucket_calibration.py <campaign-root>
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import state_signature as ssig  # noqa: E402

SCHEMA = "ex3-bucket-calibration/1"
RESULTS_REL = ROOT / "experiments" / "ex3-results.json"

# the declared decision rule (documented, not fitted): calibrating a
# discretization edge needs evidence the edge MISPLACES mass — counts
# within EDGE_ADJACENCY of an edge on BOTH sides, on a sample base
MIN_SAMPLES = 30       # below this the distribution is anecdote
EDGE_ADJACENCY = 2     # |count - edge| <= N counts as "at the edge"
MIN_EDGE_MASS = 5      # points needed on a side to call it mass


def workspaces(root: Path) -> list[Path]:
    """Every #240-marker workspace under root, sorted (scan order = data)."""
    return sorted(p.parent for p in root.rglob("claim-register.yaml"))


def trajectory(ws: Path) -> list[int]:
    """The recorded fact-count trajectory: convergence-ledger facts_total
    history; the terminal fact-face count when no ledger exists."""
    led = ws / ".convergence_ledger.jsonl"
    points: list[int] = []
    if led.is_file():
        try:
            lines = led.read_text(encoding="utf-8",
                                  errors="replace").splitlines()
        except OSError:
            lines = []
        from kunglao_log import iter_jsonl
        for row in iter_jsonl(lines):
            if isinstance(row, dict) and isinstance(
                    row.get("facts_total"), int):
                points.append(max(row["facts_total"], 0))
    if not points:
        points.append(int(ssig.fact_face(ws)["count"]))
    return points


def replay(root) -> dict:
    """Fill-distribution replay over one campaign root. Pure read —
    same root -> same document (determinism pin)."""
    root = Path(root)
    per_ws: list[dict] = []
    fills: Counter = Counter()
    samples = 0
    all_points: list[int] = []
    for ws in workspaces(root):
        pts = trajectory(ws)
        ws_fills: Counter = Counter()
        for n in pts:
            ws_fills[str(ssig.fact_bucket(n))] += 1
        for k, v in ws_fills.items():
            fills[k] += v
        samples += len(pts)
        all_points.extend(pts)
        per_ws.append({
            "workspace": ws.name,
            "points": len(pts),
            "trajectory_max": max(pts) if pts else 0,
            "buckets": {k: ws_fills[k] for k in sorted(ws_fills)},
        })
    n_buckets = len(ssig.FACT_BUCKET_EDGES) + 1
    edges = ssig.FACT_BUCKET_EDGES
    return {
        "schema": SCHEMA,
        "root": str(root),
        "fact_bucket_edges": list(edges),
        "workspaces_scanned": len(per_ws),
        "samples": samples,
        "fill_distribution": {str(b): fills.get(str(b), 0)
                              for b in range(n_buckets)},
        "edge_mass": edge_mass(all_points, edges),
        "per_workspace": per_ws,
    }


def edge_mass(points: list[int], edges: tuple) -> list[dict]:
    """Per interior edge: how many raw trajectory points sit within
    EDGE_ADJACENCY strictly below vs at-or-above it — mass on BOTH sides
    is the evidence that the edge cuts a dense region."""
    out = []
    for edge in edges[1:]:  # interior edges only (0 is the degenerate base)
        below = sum(1 for n in points
                    if edge - EDGE_ADJACENCY <= n < edge)
        above = sum(1 for n in points
                    if edge <= n <= edge + EDGE_ADJACENCY)
        out.append({"edge": edge, "below": below, "above": above})
    return out


def verdict(replay_doc: dict) -> dict:
    """The declared verdict over a replay document: "calibrate" only when
    an interior edge shows mass on both sides (evidence it cuts a dense
    region); otherwise "no-calibration" with the reason."""
    criteria = {
        "min_samples": MIN_SAMPLES,
        "edge_adjacency": EDGE_ADJACENCY,
        "min_edge_mass": MIN_EDGE_MASS,
        "rule": "calibrate iff some interior edge has >= MIN_EDGE_MASS "
                "points within EDGE_ADJACENCY on BOTH sides",
    }
    samples = int(replay_doc.get("samples") or 0)
    if samples == 0:
        return {"schema": SCHEMA, "verdict": "no-calibration",
                "reason": "no samples: no workspace carried a fact "
                          "trajectory",
                "declared_criteria": criteria}
    if samples < MIN_SAMPLES:
        return {"schema": SCHEMA, "verdict": "no-calibration",
                "reason": f"sample base {samples} < {MIN_SAMPLES}: the "
                          "distribution is anecdote, not calibration "
                          "evidence; re-run after the W3 E2E runs land",
                "declared_criteria": criteria}
    straddling = [{"edge": e["edge"], "below": e["below"],
                   "above": e["above"]}
                  for e in (replay_doc.get("edge_mass") or [])
                  if e["below"] >= MIN_EDGE_MASS
                  and e["above"] >= MIN_EDGE_MASS]
    if straddling:
        return {"schema": SCHEMA, "verdict": "calibrate",
                "reason": "interior edge(s) cut dense regions: "
                          f"{json.dumps(straddling)}",
                "straddling_edges": straddling,
                "declared_criteria": criteria}
    fills = {int(k): v for k, v in
             (replay_doc.get("fill_distribution") or {}).items()}
    top = max((b for b, v in fills.items() if v > 0), default=-1)
    return {"schema": SCHEMA, "verdict": "no-calibration",
            "reason": f"no interior edge shows mass on both sides "
                      f"(max filled bucket index {top} of "
                      f"{len(replay_doc.get('fact_bucket_edges') or [])}): "
                      f"the observed spread never reaches the upper "
                      f"edges, so their placement is untested — not "
                      f"misplacement",
            "declared_criteria": criteria}


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0]) if argv else Path(
        "/Users/mikenike/workprojects/kunglao-wt/eval-campaign-v016/"
        "runs/eval-campaign-v016")
    doc = replay(root)
    doc["verdict"] = verdict(doc)
    RESULTS_REL.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"workspaces_scanned={doc['workspaces_scanned']} "
          f"samples={doc['samples']}")
    print("fill_distribution=" + json.dumps(doc["fill_distribution"]))
    print(f"verdict={doc['verdict']['verdict']}: {doc['verdict']['reason']}")
    print(f"results={RESULTS_REL}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

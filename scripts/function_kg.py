# -*- coding: utf-8 -*-
"""function_kg.py — minimal function-level knowledge graph (issue #309).

Absorbed idea: Dryxio/auto-re-agent knowledge_graph.py:26-56 (JSON-persisted
graph + neighborhood injection for worker context), re-implemented for
kunglao. Honest discount per issue: kunglao is claim-driven, not
function-driven — this graph only pays off for "whole-function batch
analysis" claims, hence the minimal node/edge model.

Graph model:
    nodes: f:<name> (function), s:<text> (string), g:<name> (global)
    edges: call (f -> f), reference (f -> s), access (f -> g)
    schema: kunglao-function-kg/1

Input records (ghidra-recon style, one per decompiled function):
    [{"function": "main", "calls": [...], "strings": [...],
      "globals": [...], "decompiled_chars": 1200}, ...]

Calls to undeclared functions create synthetic function nodes so no edge is
dropped. Edges dedupe by (kind, src, dst).

Usage:
  python scripts/function_kg.py --input records.json --out kg.json --json
  python scripts/function_kg.py --input records.json --out kg.json \
      --neighborhood main --radius 1 --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

SCHEMA = "kunglao-function-kg/1"
SCRIPT_PATH = Path(__file__).resolve()


def node_id(kind: str, name: str) -> str:
    prefix = {"function": "f", "string": "s", "global": "g"}[kind]
    return f"{prefix}:{name}"


def _ensure_node(nodes: dict, kind: str, name: str, decompiled_chars=None) -> str:
    nid = node_id(kind, name)
    if nid not in nodes:
        node = {"kind": kind, "name": name}
        if decompiled_chars is not None and kind == "function":
            node["decompiled_chars"] = decompiled_chars
        nodes[nid] = node
    return nid


def _add_edge(edges: dict, kind: str, src: str, dst: str) -> None:
    eid = f"{kind}:{src}|{dst}"
    if eid not in edges:
        edges[eid] = {"kind": kind, "src": src, "dst": dst}


def build_graph(records: list[dict]) -> dict:
    """Build the graph from ghidra-recon style records (deterministic)."""
    nodes: dict = {}
    edges: dict = {}
    for rec in records or []:
        fname = str(rec.get("function", "") or "")
        if not fname:
            continue
        src = _ensure_node(nodes, "function", fname,
                           decompiled_chars=rec.get("decompiled_chars"))
        for callee in rec.get("calls", []) or []:
            dst = _ensure_node(nodes, "function", str(callee))
            _add_edge(edges, "call", src, dst)
        for s in rec.get("strings", []) or []:
            dst = _ensure_node(nodes, "string", str(s))
            _add_edge(edges, "reference", src, dst)
        for g in rec.get("globals", []) or []:
            dst = _ensure_node(nodes, "global", str(g))
            _add_edge(edges, "access", src, dst)
    return {"schema": SCHEMA, "nodes": nodes, "edges": edges}


def write_graph(graph: dict, out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return out_path


def load_graph(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _adjacency(graph: dict) -> dict:
    adj: dict = {}
    for e in graph.get("edges", {}).values():
        adj.setdefault(e["src"], set()).add(e["dst"])
        adj.setdefault(e["dst"], set()).add(e["src"])
    return adj


def neighborhood(graph: dict, func: str, radius: int = 1) -> dict:
    """Nodes and edges within `radius` hops of a function (undirected)."""
    center = node_id("function", func)
    nodes = graph.get("nodes", {})
    if center not in nodes:
        return {"center": center, "nodes": [], "edges": []}
    adj = _adjacency(graph)
    visited = {center}
    frontier = {center}
    for _ in range(max(0, radius)):
        nxt = set()
        for n in frontier:
            nxt |= {m for m in adj.get(n, set()) if m not in visited}
        visited |= nxt
        frontier = nxt
        if not frontier:
            break
    nb_nodes = [nodes[n] for n in sorted(visited) if n in nodes]
    nb_edges = [e for e in graph.get("edges", {}).values()
                if e["src"] in visited and e["dst"] in visited]
    return {"center": center, "radius": radius, "nodes": nb_nodes, "edges": nb_edges}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="function_kg.py",
        description="build/query a function-level KG from ghidra-recon records (#309)")
    ap.add_argument("--input", required=True, help="JSON records file")
    ap.add_argument("--out", required=True, help="graph JSON output path")
    ap.add_argument("--neighborhood", default=None, help="query: neighborhood of function")
    ap.add_argument("--radius", type=int, default=1)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--reproduce", action="store_true",
                    help="print field=value input lines (kunglao_verify parseable)")
    args = ap.parse_args(argv)

    inp = Path(args.input)
    out = Path(args.out)
    if args.reproduce:
        print(f"input={inp}")
        print(f"out={out}")
        print(f"neighborhood={args.neighborhood or '-'}")
        print(f"radius={args.radius}")
        return 0
    if not inp.exists():
        print(f"error: input not found: {inp}", file=sys.stderr)
        return 1

    if args.neighborhood is not None:
        if out.exists():
            graph = load_graph(out)
        else:
            graph = build_graph(json.loads(inp.read_text(encoding="utf-8")))
        nb = neighborhood(graph, args.neighborhood, radius=args.radius)
        print(json.dumps(nb, ensure_ascii=False, indent=2))
        return 0

    try:
        records = json.loads(inp.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    graph = build_graph(records)
    write_graph(graph, out)
    payload = {"out": str(out), "schema": SCHEMA,
               "n_nodes": len(graph["nodes"]), "n_edges": len(graph["edges"])}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"graph written: {out} ({payload['n_nodes']} nodes, "
              f"{payload['n_edges']} edges)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

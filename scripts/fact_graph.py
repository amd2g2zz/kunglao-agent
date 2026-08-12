#!/usr/bin/env python3
"""fact_graph.py -- fact-level reference graph (#140)."""
from __future__ import annotations
import argparse, sys
from pathlib import Path

def parse_frontmatter(text):
    fm = {}
    if text.startswith('---'):
        parts = text.split('---', 2)
        if len(parts) >= 3:
            for line in parts[1].strip().splitlines():
                if ':' in line:
                    k, v = line.split(':', 1)
                    fm[k.strip()] = v.strip()
    return fm

def build_graph(facts_dir):
    graph = {}
    for p in sorted(facts_dir.glob('F*.md')):
        fact_id = p.stem
        fm = parse_frontmatter(p.read_text(encoding='utf-8'))
        cites = [c.strip() for c in fm.get('cites', '').split(',') if c.strip()]
        supersedes = [s.strip() for s in fm.get('supersedes', '').split(',') if s.strip()]
        superseded_by = [s.strip() for s in fm.get('superseded_by', '').split(',') if s.strip()]
        graph[fact_id] = {'cites': cites, 'supersedes': supersedes, 'superseded_by': superseded_by}
    return graph

def neighborhood(graph, fact_id):
    result = {'outgoing': {}, 'incoming': {}}
    if fact_id not in graph: return result
    node = graph[fact_id]
    for et in ('cites', 'supersedes', 'superseded_by'):
        result['outgoing'][et] = node[et]
    for oid, onode in graph.items():
        if oid == fact_id: continue
        for et in ('cites', 'supersedes', 'superseded_by'):
            if fact_id in onode[et]:
                result['incoming'].setdefault(et, []).append(oid)
    return result

def impact_propagation(graph, fact_id):
    visited, queue = set(), [fact_id]
    while queue:
        cur = queue.pop(0)
        if cur in visited: continue
        visited.add(cur)
        if cur in graph:
            for c in graph[cur].get('cites', []):
                if c not in visited: queue.append(c)
    visited.discard(fact_id)
    return sorted(visited)

def main():
    parser = argparse.ArgumentParser(description='Fact reference graph')
    parser.add_argument('workspace')
    parser.add_argument('--neighbor')
    parser.add_argument('--impact')
    args = parser.parse_args()
    facts_dir = Path(args.workspace) / 'facts'
    if not facts_dir.exists():
        print('No facts/ directory'); return 1
    graph = build_graph(facts_dir)
    if args.neighbor:
        nb = neighborhood(graph, args.neighbor)
        print('Neighborhood of ' + args.neighbor)
        for d, edges in nb.items():
            for et, t in edges.items():
                if t: print('  ' + d + '.' + et + ': ' + str(t))
    elif args.impact:
        affected = impact_propagation(graph, args.impact)
        print('Impact: ' + str(affected))
    else:
        for fid, edges in sorted(graph.items()):
            ae = []
            for et, ts in edges.items():
                for t in ts: ae.append(et + '->' + t)
            label = str(ae) if ae else '(no edges)'
            print(fid + ': ' + label)
    return 0

if __name__ == '__main__': sys.exit(main())

"""test_fact_graph.py -- fact reference graph tests (#140)."""
from __future__ import annotations
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from fact_graph import build_graph, neighborhood, impact_propagation


def _make_fact(dirpath, fact_id, cites='', supersedes='', superseded_by=''):
    content = '---' + chr(10)
    content += 'fact_id: ' + fact_id + chr(10)
    content += 'cites: ' + cites + chr(10)
    content += 'supersedes: ' + supersedes + chr(10)
    content += 'superseded_by: ' + superseded_by + chr(10)
    content += '---' + chr(10) + 'Test.' + chr(10)
    (dirpath / (fact_id + '.md')).write_text(content, encoding='utf-8')


def test_build_graph_basic():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_fact(d, 'F001', cites='F002,F003')
        _make_fact(d, 'F002')
        _make_fact(d, 'F003')
        graph = build_graph(d)
        assert 'F001' in graph
        assert 'F002' in graph['F001']['cites']
        assert 'F003' in graph['F001']['cites']


def test_neighborhood_incoming():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_fact(d, 'F001', cites='F002')
        _make_fact(d, 'F002')
        graph = build_graph(d)
        nb = neighborhood(graph, 'F002')
        assert 'F001' in nb['incoming'].get('cites', [])


def test_impact_propagation():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        _make_fact(d, 'F001', cites='F002')
        _make_fact(d, 'F002', cites='F003')
        _make_fact(d, 'F003')
        graph = build_graph(d)
        affected = impact_propagation(graph, 'F001')
        assert 'F002' in affected
        assert 'F003' in affected


def test_empty_facts_dir():
    with tempfile.TemporaryDirectory() as tmp:
        graph = build_graph(Path(tmp))
        assert graph == {}

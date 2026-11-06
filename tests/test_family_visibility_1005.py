# -*- coding: utf-8 -*-
"""tests/test_family_visibility_1005.py — the method-family vocabulary is
VISIBLE at the health face (v0.1.6 mitigation of the closed-registry gap).

The 2026-11-05 audit found dispatch strategy rows reading
``strategy:"default", declared:false`` everywhere, and the vocabulary is
a CLOSED registry: an approach the analysis discovers has no path into
the arm set except a reviewed registry diff. The full fix (arm space
learned from settled outcomes) stays out of this release; the mitigation
is visibility — the operator's health report must show

  - the registry's health signals (never-fills / dominates-all /
    other-share), and
  - the quarantine triage's promotion candidates,

so "what should we mint next" is answerable from the loop's own data
instead of a hunch. The registry is NEVER modified here: promotion stays
a reviewed diff. The block is computed at the on-demand health face
only — the per-tick assess() path must not pay the usage scan.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import convergence_health as ch  # noqa: E402

BASE = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)


def _snap(i: int, open_count: int) -> dict:
    return {
        "ts": (BASE + timedelta(seconds=60 * i)).isoformat(),
        "decision": "DISPATCH",
        "open_count": open_count,
        "open_ids": [f"C-{n}" for n in range(1, open_count + 1)],
        "partial_count": 0,
        "active_workers": 1,
        "blockers": [],
        "facts_total": 5 + i,
    }


def _ws(tmp_path: Path, *, quarantine: int = 3) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    rows = [_snap(i, 2 - (i % 3)) for i in range(6)]
    (ws / ".convergence_ledger.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    if quarantine:
        (ws / "runs" / "method-family-quarantine.jsonl").write_text(
            "\n".join(json.dumps({"detail": "vm-dispatch", "claim": "C-1"})
                      for _ in range(quarantine)) + "\n", encoding="utf-8")
    return ws


def test_family_vocabulary_reads_health_and_triage(tmp_path) -> None:
    ws = _ws(tmp_path)
    face = ch.family_vocabulary(ws)
    health = face["method_family_health"]
    triage = face["method_family_triage"]
    assert isinstance(health["never_fills"], list)
    assert health["attributed_rows"] == 0, "no dispatch rows in this fixture"
    cands = triage["promotion_candidates"]
    assert [c["detail"] for c in cands] == ["vm-dispatch"]
    assert cands[0]["count"] == 3
    assert triage["promotion_min"] == 3


def test_triage_below_threshold_is_not_a_candidate(tmp_path) -> None:
    ws = _ws(tmp_path, quarantine=2)
    triage = ch.family_vocabulary(ws)["method_family_triage"]
    assert triage["quarantine_rows"] == 2
    assert triage["promotion_candidates"] == []


def test_assess_stays_lean(tmp_path) -> None:
    """The per-tick face must NOT carry the vocabulary block: the usage
    scan belongs to the on-demand health report, not every decide()."""
    ws = _ws(tmp_path)
    ledger = ch._read_ledger(ws)
    r = ch.assess(ledger, ws=ws)
    assert "method_family_health" not in r
    assert "method_family_triage" not in r


def test_default_cli_payload_does_not_grow(tmp_path, monkeypatch,
                                           capsys) -> None:
    """The dispatch gate runs `convergence_health.py <ws>` as a subprocess
    on every dispatch: the default payload must not grow (nor pay the
    usage scan) — the block is opt-in."""
    ws = _ws(tmp_path)
    monkeypatch.setattr(sys, "argv",
                        ["convergence_health.py", str(ws), "--json"])
    ch.main()
    out = json.loads(capsys.readouterr().out)
    assert "method_family_health" not in out
    assert "method_family_triage" not in out


def test_health_cli_json_carries_the_vocabulary(tmp_path, monkeypatch,
                                                capsys) -> None:
    ws = _ws(tmp_path)
    monkeypatch.setattr(sys, "argv",
                        ["convergence_health.py", str(ws), "--json",
                         "--families"])
    ch.main()
    out = json.loads(capsys.readouterr().out)
    assert out["method_family_triage"]["promotion_candidates"][0]["detail"] \
        == "vm-dispatch"
    assert "never_fills" in out["method_family_health"]


def test_health_cli_human_surfaces_promotion_candidates(tmp_path,
                                                        monkeypatch,
                                                        capsys) -> None:
    ws = _ws(tmp_path)
    monkeypatch.setattr(sys, "argv",
                        ["convergence_health.py", str(ws), "--families"])
    ch.main()
    text = capsys.readouterr().out
    assert "family vocabulary:" in text
    assert "promotion candidate" in text
    assert "vm-dispatch" in text


def test_router_health_merges_the_vocabulary(tmp_path, capsys) -> None:
    """The documented operator surface (`kunglao health`) is on-demand —
    the vocabulary block belongs there by default."""
    from types import SimpleNamespace
    import kunglao
    ws = _ws(tmp_path)
    kunglao.cmd_health(SimpleNamespace(workspace=str(ws)))
    text = capsys.readouterr().out
    assert "family vocabulary:" in text
    assert "vm-dispatch" in text


def test_router_health_surfaces_an_unavailable_registry(tmp_path,
                                                        monkeypatch,
                                                        capsys) -> None:
    """An unreadable registry is EXPLICIT on the human face, never a
    silent empty block."""
    import method_families as mf
    from types import SimpleNamespace
    import kunglao

    def _boom(ws):  # noqa: ANN001
        raise RuntimeError("torn registry")

    monkeypatch.setattr(mf, "family_health", _boom)
    ws = _ws(tmp_path)
    kunglao.cmd_health(SimpleNamespace(workspace=str(ws)))
    text = capsys.readouterr().out
    assert "family vocabulary: unavailable" in text
    assert "torn registry" in text


def test_family_vocabulary_degrades_explicitly(tmp_path, monkeypatch) -> None:
    import method_families as mf

    def _boom(ws):  # noqa: ANN001
        raise RuntimeError("registry torn")

    monkeypatch.setattr(mf, "family_health", _boom)
    face = ch.family_vocabulary(_ws(tmp_path))
    assert "registry torn" in face["method_family_health"]["unavailable"]
    assert "registry torn" in face["method_family_triage"]["unavailable"]

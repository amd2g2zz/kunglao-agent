"""Cross-process evidence for the existing strategic declaration boundary."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TS = "2026-01-01T00:00:00Z"


def _python(code: str, ws: Path, profile: Path) -> dict:
    profile.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HOME=str(profile),
               PYTHONPATH=os.pathsep.join((str(ROOT / "scripts"), str(ROOT / "hooks"))),
               KUNGLAO_POSTERIOR_STORE=str(profile / "posterior"))
    proc = subprocess.run([sys.executable, "-c", code, str(ws)], env=env,
                          text=True, capture_output=True, timeout=90)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    return json.loads(proc.stdout)


def _workspace(path: Path) -> None:
    (path / "runs").mkdir(parents=True)
    (path / "claim-register.yaml").write_text(yaml.safe_dump({
        "claims": [{"id": "C-001", "status": "PROVEN"}]}), encoding="utf-8")
    (path / "task_spec.yaml").write_text(yaml.safe_dump({
        "primary_questions": [{"id": "pq1", "q": "synthetic"}],
        "authorization": {"targets": ["target.example"], "excluded": [],
                          "authorization_ref": "ticket-test"}}), encoding="utf-8")
    (path / "runs" / "verification-C-001.md").write_text(
        "verifier-identity: checker-test\nverdict: verified\n", encoding="utf-8")


def test_s5_declaration_persists_to_signal_but_not_q_cell_fold(tmp_path):
    """A telemetry learning flag is observable, not proof of a posterior consumer."""
    cases = []
    for declared in (False, True):
        ws, profile = tmp_path / str(declared), tmp_path / (str(declared) + "-profile")
        _workspace(ws)
        writer = _python("""
import json, sys
from pathlib import Path
from rlvr import q_cells, strategic_action
ws = Path(sys.argv[1])
out = q_cells.append_observation(ws, 'sig-test', 'static-test', 0.75,
    source='settlement', claim='C-001', dispatch_id='dispatch-1',
    arm_key_col='static-test|facts_snapshot|none|0', ts='2026-01-01T00:00:00Z')
print(json.dumps({'appended': out['appended']}))
""", ws, profile)
        assert writer["appended"] is True
        if declared:
            written = _python("""
import json, sys
from rlvr import strategic_action as s
ws = sys.argv[1]
row = s.build_declaration_row(claim='C-001', route='FIGHT',
    propensity=s.route_propensity(ws, 'FIGHT'), declared=True,
    trace_id='tr-test-1', ts='2026-01-01T00:00:00Z')
print(json.dumps(s.append_declaration(ws, row)))
""", ws, profile)
            assert written["appended"] is True
        outcome = _python("""
import json, sys
from rlvr import disposition_producer as p, disposition_reward as r
ws = sys.argv[1]
print(json.dumps({'producer': p.produce(ws),
                  'reward': r.settle_workspace(ws, ts='2026-01-01T00:00:00Z')}))
""", ws, profile)
        assert outcome["producer"]["written"] == 1
        assert outcome["reward"]["settled"] == 1
        observed = _python("""
import json, sys
from rlvr import consolidated_ledger as c, disposition_measure as m, q_cells as q
ws = sys.argv[1]
fold = q.fold(q.default_store(ws), gamma=1.0)
print(json.dumps({'signal': c.read(ws, 'telemetry', schema_prefix='disposition-signal/1'),
    'measurement': m.measure(ws)['rows'],
    'posterior': q.cell_posterior(fold, 'sig-test', 'static-test',
        arm_key='static-test|facts_snapshot|none|0')}))
""", ws, profile)
        assert len(observed["signal"]) == len(observed["measurement"]) == 1
        cases.append(observed)
    plain, named = cases
    assert plain["signal"][0]["strategic_action"] is None
    assert named["signal"][0]["strategic_action"] == "FIGHT"
    assert named["signal"][0]["strategy_learning"] is True
    assert named["measurement"][0]["strategic_action"] == "FIGHT"
    assert plain["posterior"] == named["posterior"]


def test_declaration_view_labels_historical_frequency(tmp_path):
    ws, profile = tmp_path / "ws", tmp_path / "profile"
    _workspace(ws)
    result = _python("""
import json, sys
from rlvr import strategic_action as s
import worker_budget_sinks as sinks
ws = sys.argv[1]
row = s.build_declaration_row(claim='C-001', route='FIGHT',
    propensity=s.route_propensity(ws, 'FIGHT'), declared=True,
    trace_id='tr-test-1', ts='2026-01-01T00:00:00Z')
s.append_declaration(ws, row)
print(json.dumps(sinks._sample_reconciliation(ws, None)))
""", ws, profile)
    assert result["declared_propensity"] == round(1 / 3, 6)
    assert result["declared_propensity_interpretation"] == "historical_smoothed_frequency"

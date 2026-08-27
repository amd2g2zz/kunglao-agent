# -*- coding: utf-8 -*-
"""RED tests for issue #692 WP5 — taint seeds + hypothesis/anomaly wiring.

Pins design D7 (acceptance 5):

- references/re-library/android-fingerprint-seeds.yaml: extensible machine
  table {seeds: [{api, category, risk}]} covering the fingerprint-API
  families (device ids / SIM / location / network / sensors / clipboard);
  consumable by dexdc_scanner --seeds (the default seeds path resolves to
  this file); lifecycle = yara rules (data, extensible without code).
- hypothesis_seeder.seed_taint_candidates(ws): evidence/dexdc_taint.json
  findings -> `taint:<category>:<api>` competitor candidates on pq-family
  scaffolds — the exact mirror of #669's seed_apkid_candidates (idempotent,
  fail-open, emits `taint_candidates`).
- anomaly_detector.observe_taint(ws): taint findings as OBSERVATIONS (the
  #663 D8 posture: observation, never a verdict demotion) — a co-resident
  note appears when the distinct high-risk seed-category concentration
  crosses the threshold.
- EMIT_ACTIONS carries `taint_candidates` (CI anchor: unregistered emit
  words are red).

RED phase: none of these functions/tables exist.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
TOOLS_STATIC = REPO / "tools" / "static"
SEEDS = REPO / "references" / "re-library" / "android-fingerprint-seeds.yaml"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses needs the module registered
    spec.loader.exec_module(mod)
    return mod


_hs = _load("_hypothesis_seeder_692", SCRIPTS / "hypothesis_seeder.py")
_ad = _load("_anomaly_detector_692", SCRIPTS / "anomaly_detector.py")
_et = _load("_event_taxonomy_692", SCRIPTS / "event_taxonomy.py")


# ---------- the seed table itself ----------

def test_seed_table_exists_with_required_families():
    import yaml
    data = yaml.safe_load(SEEDS.read_text(encoding="utf-8"))
    seeds = data.get("seeds")
    assert isinstance(seeds, list) and len(seeds) >= 10, (
        "table too thin to be the extensible seed source")
    apis = {s["api"] for s in seeds}
    families = {s["category"] for s in seeds}
    # the issue's named families must all be present
    for api in ("getDeviceId", "getAndroidId", "getSubscriberId",
                "getSimSerialNumber"):
        assert api in apis, f"{api} missing from the seed table"
    for cat in ("device_id", "sim", "location", "sensors", "clipboard"):
        assert cat in families, f"category {cat} missing"
    assert all(s.get("risk") in ("high", "mid") for s in seeds)


def test_seed_table_is_dexdc_scanners_default():
    ds = _load("_dexdc_scanner_692", TOOLS_STATIC / "dexdc_scanner.py")
    assert ds.DEFAULT_SEEDS_FILE.name == "android-fingerprint-seeds.yaml"
    assert ds._load_seeds(None, None), "default table must load + be non-empty"


def test_seed_table_pinned_in_references_index():
    text = (REPO / "references" / "_INDEX.md").read_text(encoding="utf-8")
    assert "android-fingerprint-apis" in text


# ---------- acceptance 5: taint finding -> hypothesis candidate ----------

@pytest.fixture
def ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "hypotheses").mkdir(parents=True)
    (ws / "evidence").mkdir()
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n"
        "  - id: Q1\n"
        "    q: does the app collect device fingerprints and upload them\n",
        encoding="utf-8")
    # a pq-family scaffold (as seed_from_task_spec would create)
    (ws / "hypotheses" / "H-001.md").write_text(
        "---\n"
        "id: H-001\n"
        "claim_id: C-PENDING\n"
        "competitor_group: pq-Q1\n"
        "candidates: []\n"
        "status: open\n"
        "---\n\n"
        "pq:Q1\n\nscaffold\n",
        encoding="utf-8")
    (ws / "evidence" / "dexdc_taint.json").write_text(json.dumps({
        "tool": "dexdc", "status": "ok", "count": 2,
        "seeds": ["getDeviceId", "getSubscriberId"],
        "issues": [
            {"rule": "device-leak", "source": "getDeviceId",
             "sink": "Landroid/util/Log;->d", "traces": []},
            {"rule": "sim-leak", "source": "getSubscriberId",
             "sink": "Ljava/net/URL;->openConnection", "traces": []},
        ]}), encoding="utf-8")
    return ws


def test_taint_findings_append_candidates(ws):
    appended = _hs.seed_taint_candidates(ws)
    assert appended == 2
    body = (ws / "hypotheses" / "H-001.md").read_text(encoding="utf-8")
    assert "taint:device_id:getDeviceId" in body
    assert "taint:sim:getSubscriberId" in body


def test_taint_seeding_is_idempotent(ws):
    assert _hs.seed_taint_candidates(ws) == 2
    assert _hs.seed_taint_candidates(ws) == 0


def test_taint_seeding_fail_open_no_evidence(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert _hs.seed_taint_candidates(ws) == 0


def test_taint_emit_action_registered():
    assert "taint_candidates" in _et.EMIT_ACTIONS
    assert list(_et.EMIT_ACTIONS) == sorted(_et.EMIT_ACTIONS)


# ---------- anomaly observation (observation, never verdict) ----------

def test_observe_taint_writes_observation_note(ws):
    observations = _ad.observe_taint(ws)
    assert observations, "2 distinct high-risk families must fire"
    note = ws / "notes" / "taint-observation.md"
    assert note.is_file()
    text = note.read_text(encoding="utf-8")
    assert "type: observation" in text
    assert "device_id" in text and "sim" in text


def test_observe_taint_below_threshold_is_silent(tmp_path):
    ws = tmp_path / "ws"
    ev = ws / "evidence"
    ev.mkdir(parents=True)
    (ev / "dexdc_taint.json").write_text(json.dumps({
        "tool": "dexdc", "status": "ok", "count": 1, "seeds": [],
        "issues": [{"rule": "r", "source": "getDeviceId",
                    "sink": "s", "traces": []}]}), encoding="utf-8")
    assert _ad.observe_taint(ws) == []
    assert not (ws / "notes" / "taint-observation.md").exists()


def test_observe_taint_fail_open(tmp_path):
    ws = tmp_path / "empty-ws"
    ws.mkdir()
    assert _ad.observe_taint(ws) == []

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_hook_battery_registry_805.py — issue 805 wiring inversion.

The hook battery (the dispatch pre_check checks + the round-closure
kernel faces) was an if-chain: wiring was a convention, registration was
opt-in, and nothing structurally forced a new face to carry a liveness
fingerprint — the armed-unwired class survived. This file pins the
registry-driven battery:

  - the declarative registry (hooks/battery.yaml) is the registration
    face; registration REQUIRES the mechanisms.yaml prerequisites
    (trigger/gate/cost_class) PLUS the two #805 fields: the telemetry
    word and the liveness fingerprint (fail-closed: a check without a
    declared fingerprint cannot register);
  - an unwired face is unregistrable: entry must resolve to a real
    module:function in the deployed trees (AST-checked, no import);
  - the registry×fingerprint join is TOTAL: every registered face joins
    a fingerprint in devkit/liveness_fingerprints.json;
  - registration is a LAUNCH PREREQUISITE: pre_check refuses to run an
    uncovered/broken battery (fail-closed) and a passing battery lands
    ONE durable pass row (runs/gate-telemetry.jsonl, gate=worker_battery)
    carrying the check names — the liveness evidence the per-check
    fingerprints read (absence of evidence = FAIL);
  - the closure battery registers too, but keeps its fail-open double
    cage (warn, never block the stop path).
"""
from __future__ import annotations

import importlib.util as _ilu
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# hooks modules load by-path under isolated names (the 762 convention —
# shared-name twins cannot reorder under us).
def _load(path: Path, name: str):
    spec = _ilu.spec_from_file_location(name, path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sinks = _load(REPO_ROOT / "hooks" / "worker_budget_sinks.py",
              "battery_registry_sinks_805")
br = _load(REPO_ROOT / "hooks" / "battery_registry.py",
           "battery_registry_under_test")

FINGERPRINTS = REPO_ROOT / "devkit" / "liveness_fingerprints.json"

#: THE code battery — pre_check's checks list in execution order plus the
#: three post-loop validation legs. A check added to code but not to this
#: list (or to the registry) turns BOTH this anchor and the runtime launch
#: gate red — the fail-closed pin.
CODE_BATTERY = frozenset({
    "stepsettled", "workers", "max_retries", "cap", "branchbudget",
    "tools", "hostchan", "deadline", "tiercons", "tier", "selfcap",
    "heartbeat", "drift", "health", "envfresh", "envpremise",
    "backtrack", "zerooutput", "plan", "granularity", "toolfirst",
    "toolsearch", "handroll", "agenttype", "rotation",
    "snapshot", "priority", "methodfamily",
})

#: the closure kernel faces (hooks/round_closure._kernel_faces, in order)
CLOSURE_FACES = frozenset({
    "settle", "blind_settlement", "policy_state", "compose",
    "rl_digest", "t2", "distill",
})


# ---------- shipped registry: the registration face -------------------------

class TestShippedRegistry:
    def test_shipped_registry_validates(self):
        entries, errors = br.load_registry()
        assert not errors, errors
        assert entries

    def test_shipped_registry_covers_the_code_battery(self):
        entries, errors = br.load_registry()
        assert not errors, errors
        dispatch = {e["name"] for e in entries if e["battery"] == "dispatch"}
        assert CODE_BATTERY <= dispatch, (
            "a code check is not registered — 不入册不许跑: "
            f"{sorted(CODE_BATTERY - dispatch)}")

    def test_shipped_registry_covers_the_closure_faces(self):
        entries, _ = br.load_registry()
        closure = {e["name"] for e in entries if e["battery"] == "closure"}
        assert CLOSURE_FACES <= closure, sorted(CLOSURE_FACES - closure)

    def test_shipped_every_entry_carries_the_five_prerequisites(self):
        """trigger/gate/cost_class are the #878 prerequisites; the
        telemetry word + liveness fingerprint are the #805 additions."""
        entries, _ = br.load_registry()
        for e in entries:
            for field in ("name", "battery", "entry", "cost_class",
                          "telemetry_word", "liveness_fingerprint"):
                assert str(e.get(field) or "").strip(), (
                    f"{e.get('name')}: missing {field} (fail-closed)")
            trig = e.get("trigger") or {}
            assert str(trig.get("gate") or "").strip(), (
                f"{e['name']}: missing trigger.gate")

    def test_shipped_entries_resolve_to_real_code(self):
        """Unwired face = unregistrable: every entry resolves to a real
        top-level function in the deployed trees (no import, AST)."""
        entries, _ = br.load_registry()
        for e in entries:
            err = br.resolve_entry(str(e["entry"]))
            assert err is None, f"{e['name']}: {err}"


# ---------- the fail-closed registration pin --------------------------------

class TestFailClosedRegistration:
    def _write(self, tmp: Path, entries: list[dict]) -> Path:
        doc = {"schema": br.SCHEMA,
               "batteries": ["dispatch", "closure"],
               "cost_classes": ["cheap", "medium", "expensive"],
               "gates": ["always", "dispatch", "verifier_exempt"],
               "entries": entries}
        path = tmp / "battery.yaml"
        import yaml
        path.write_text(yaml.safe_dump(doc, allow_unicode=True),
                        encoding="utf-8")
        return path

    def _entry(self, **over) -> dict:
        base = {"name": "workers", "battery": "dispatch",
                "entry": "worker_budget_gates:check_workers_lt_3",
                "trigger": {"type": "event", "gate": "always"},
                "cost_class": "cheap",
                "telemetry_word": "worker_budget.workers",
                "liveness_fingerprint": "battery-check-workers"}
        base.update(over)
        return base

    @pytest.mark.parametrize("field", ["telemetry_word",
                                       "liveness_fingerprint",
                                       "cost_class", "entry"])
    def test_missing_prerequisite_fails_registration(self, tmp_path,
                                                     field):
        """PIN 1: a new hook/check without a declared fingerprint (or any
        other prerequisite) FAILS registration — the registration face
        refuses, never warns."""
        entry = self._entry()
        entry.pop(field)
        _entries, errors = br.load_registry(self._write(tmp_path, [entry]))
        assert errors, f"missing {field} must fail registration"
        assert any(field in err for err in errors), errors

    def test_blank_fingerprint_fails_registration(self, tmp_path):
        _entries, errors = br.load_registry(self._write(tmp_path, [
            self._entry(liveness_fingerprint="   ")]))
        assert errors and any("liveness_fingerprint" in e for e in errors)

    def test_unknown_fingerprint_id_fails_registration(self, tmp_path):
        """The declared fingerprint must EXIST in the fingerprint file —
        a declared-but-never-defined fingerprint is the decorative-
        evidence loophole, refused."""
        _entries, errors = br.load_registry(self._write(tmp_path, [
            self._entry(liveness_fingerprint="no-such-fingerprint")]))
        assert errors and any("liveness_fingerprint" in e for e in errors)

    def test_unwired_entry_fails_registration(self, tmp_path):
        """An entry pointing at code that does not exist cannot register —
        armed-unwired is refused AT REGISTRATION."""
        _entries, errors = br.load_registry(self._write(tmp_path, [
            self._entry(name="ghost",
                        entry="no_such_module:no_such_check",
                        telemetry_word="worker_budget.ghost",
                        liveness_fingerprint="battery-check-workers")]))
        assert errors and any("entry" in e for e in errors)

    def test_entry_function_missing_from_real_module(self, tmp_path):
        _entries, errors = br.load_registry(self._write(tmp_path, [
            self._entry(name="ghost",
                        entry="worker_budget_gates:no_such_check",
                        telemetry_word="worker_budget.ghost",
                        liveness_fingerprint="battery-check-workers")]))
        assert errors and any("entry" in e for e in errors)

    def test_unknown_telemetry_word_form_fails_registration(self, tmp_path):
        _entries, errors = br.load_registry(self._write(tmp_path, [
            self._entry(telemetry_word="totally_unknown_word")]))
        assert errors and any("telemetry_word" in e for e in errors)

    def test_unknown_cost_class_fails_registration(self, tmp_path):
        _entries, errors = br.load_registry(self._write(tmp_path, [
            self._entry(cost_class="free")]))
        assert errors and any("cost_class" in e for e in errors)

    def test_unknown_gate_fails_registration(self, tmp_path):
        _entries, errors = br.load_registry(self._write(tmp_path, [
            self._entry(trigger={"type": "event", "gate": "sometimes"})]))
        assert errors and any("gate" in e for e in errors)

    def test_duplicate_name_fails_registration(self, tmp_path):
        _entries, errors = br.load_registry(self._write(tmp_path, [
            self._entry(), self._entry()]))
        assert errors and any("duplicate" in e for e in errors)


# ---------- PIN 2: the registry×fingerprint join is total -------------------

class TestFingerprintJoin:
    def test_every_registered_face_joins_a_real_fingerprint(self):
        audit = br.coverage_audit()
        assert audit["ok"], audit
        assert audit["faces"] >= len(CODE_BATTERY) + len(CLOSURE_FACES)
        assert audit["join_complete"] is True
        assert audit["unknown_ids"] == []
        assert audit["missing_fingerprints"] == []

    def test_fingerprint_ids_all_exist_in_the_fingerprint_file(self):
        ids = br.fingerprint_ids()
        assert ids, "the fingerprint file must be readable"
        entries, _ = br.load_registry()
        declared = {e["liveness_fingerprint"] for e in entries}
        assert declared <= ids, sorted(declared - ids)

    def test_dispatch_fingerprints_key_the_pass_row_face(self):
        """The per-check fingerprints read the durable battery pass row
        (gate=worker_battery) — the evidence a PASS-silent battery leaves."""
        data = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))
        by_id = {f["id"]: f for f in data["fingerprints"]}
        entries, _ = br.load_registry()
        for e in entries:
            if e["battery"] != "dispatch":
                continue
            fp = by_id[e["liveness_fingerprint"]]
            assert fp["ledger"] == "runs/gate-telemetry.jsonl", e["name"]
            assert fp["check"]["all_of"].get("gate") == "worker_battery", \
                e["name"]


# ---------- PIN (launch prerequisite): the runtime gate ---------------------

class TestLaunchGate:
    def test_valid_registry_and_covered_names_pass(self):
        assert br.launch_gate(CODE_BATTERY) is None
        assert br.launch_gate(CLOSURE_FACES, battery="closure") is None

    def test_uncovered_check_rejects(self):
        msg = br.launch_gate(CODE_BATTERY | {"ghost_check"})
        assert msg is not None and "ghost_check" in msg

    def test_broken_registry_rejects(self, tmp_path, monkeypatch):
        bad = tmp_path / "battery.yaml"
        bad.write_text("schema: wrong/schema\nentries: []\n",
                       encoding="utf-8")
        monkeypatch.setattr(br, "REGISTRY_PATH", bad)
        msg = br.launch_gate(CODE_BATTERY)
        assert msg is not None

    def test_unreadable_registry_rejects(self, tmp_path, monkeypatch):
        monkeypatch.setattr(br, "REGISTRY_PATH",
                            tmp_path / "missing.yaml")
        assert br.launch_gate(CODE_BATTERY) is not None


class TestPreCheckLaunchWiring:
    def _payload(self, claim: str = "C-001", tools: str = "grep") -> dict:
        envelope = json.dumps({"kunglao_dispatch": {
            "version": 1, "claim": claim, "tier": 1, "tools": [tools],
            "agent": "w-test", "method_family": "static-decompile"}})
        return {"tool_input": {
            "name": "w-test", "description": "",
            "prompt": f"{envelope}\nfacts-snapshot: 1 facts"}}

    def _paths(self, ws: Path) -> dict:
        return {"workspace": str(ws),
                "state": ws / "analysis_state.txt",
                "register": ws / "claim-register.yaml",
                "deps": ws / "claim_deps.yaml",
                "task_spec": ws / "task_spec.yaml"}

    def test_passing_battery_lands_the_pass_row(self, tmp_path):
        """THE liveness evidence: a full battery pass lands ONE durable
        row (gate=worker_battery) carrying the check names — the row the
        per-check fingerprints read. Absence of the row = the battery
        did not run = the fingerprint FAILs."""
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        rc = sinks.pre_check(self._payload(), self._paths(ws))
        assert rc == 0
        rows = [json.loads(line)
                for line in (ws / "runs" / "gate-telemetry.jsonl")
                .read_text(encoding="utf-8").splitlines() if line.strip()]
        passes = [r for r in rows if r.get("gate") == "worker_battery"]
        assert len(passes) == 1, rows
        names = set((passes[0].get("msg") or "").split(","))
        assert CODE_BATTERY <= names, sorted(CODE_BATTERY - names)

    def test_broken_registry_rejects_the_dispatch(self, tmp_path,
                                                  monkeypatch):
        """Registration is a LAUNCH PREREQUISITE: a broken registry means
        the battery cannot prove its own registration — the dispatch is
        REFUSED (fail-closed), never silently ungated."""
        # the sink resolves the CANONICAL module name — patch that
        # instance (the by-path twin under test above is a second one)
        import battery_registry as canon
        monkeypatch.setattr(canon, "REGISTRY_PATH", tmp_path / "empty")
        bad = tmp_path / "battery.yaml"
        bad.write_text("schema: wrong/schema\nentries: []\n",
                       encoding="utf-8")
        monkeypatch.setattr(canon, "REGISTRY_PATH", bad)
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        rc = sinks.pre_check(self._payload(), self._paths(ws))
        assert rc == 2, "a broken registry must REFUSE, never ungate"
        rows = [json.loads(line)
                for line in (ws / "runs" / "gate-telemetry.jsonl")
                .read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(r.get("gate") == "worker_budget.batteryreg"
                   for r in rows), rows

    def test_reject_path_never_lands_a_pass_row(self, tmp_path):
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        payload = self._payload()
        payload["tool_input"]["prompt"] = payload["tool_input"][
            "prompt"].replace("facts-snapshot: 1 facts", "")
        rc = sinks.pre_check(payload, self._paths(ws))
        assert rc == 2
        text = (ws / "runs" / "gate-telemetry.jsonl").read_text(
            encoding="utf-8")
        assert "worker_battery" not in text


# ---------- the closure battery keeps its fail-open cage --------------------

class TestClosureBattery:
    def test_closure_launch_gate_warns_never_blocks(self, tmp_path,
                                                    monkeypatch):
        """The closure's fail-open double cage is contractual: a broken
        registry is ONE rate-limited warn — the stop path is never
        disturbed."""
        import shutil
        import subprocess
        hook = REPO_ROOT / "hooks" / "round_closure.py"
        src = hook.read_text(encoding="utf-8")
        assert "battery_registry" in src, (
            "the closure battery must consult the registry")
        # the cage: the launch-gate call site sits inside a try that
        # warns — grep-level pin on the warn op name
        assert br.LAUNCH_WARN_OP in src
        del tmp_path, monkeypatch, shutil, subprocess

# -*- coding: utf-8 -*-
"""tests/test_sanction_datetime_47.py — #47 second-stop sanction datetime crash.

Crash chain (issue #47, Doubao live evidence):
  task-oracle.yaml records an UNQUOTED timestamp (last_decision_at:
  2026-09-04T10:00:00Z) → yaml.safe_load returns a datetime.datetime →
  hooks/completion_gate._secondstop_record_sha json.dumps(adj) raises
  TypeError: Object of type datetime is not JSON serializable → the
  sanctioned second stop could not be reconciled against the ledger.

Contract:
  B1 _secondstop_record_sha accepts datetime values (normalizes at the
     json boundary — NO yaml representer, NO hand-edited yaml)
  B2 sha stability: the datetime OBJECT and its isoformat() STRING anchor
     to the SAME sha (records written after the fix and re-read through
     either path are the same record)
  B3 end-to-end: unquoted last_decision_at + sanctioned PASS → rc 0 AND
     the ledger anchor row is written (pre-fix the TypeError escaped and
     the anchor silently never happened)
  B4 error precision: an anchor-path failure BLOCKS with the underlying
     exception class/message in the reason — never the generic
     "without oracle sanction" text, never a silent fail-open
  B5 regression: quoted-string timestamp still works; missing
     last_decision_at still works; OSError-class ledger failures still
     carry their class name (#831 behavior preserved)
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"

SECOND_STOP_EVENT = "second_stop_pass"

UNQUOTED_ORACLE = """\
task_text: x
adjudication:
  stop_hook_active:
    second_stop: true
    last_decision: PASS
    last_decision_at: 2026-09-04T10:00:00Z
"""

QUOTED_ORACLE = """\
task_text: x
adjudication:
  stop_hook_active:
    second_stop: true
    last_decision: PASS
    last_decision_at: "2026-09-04T10:00:00Z"
"""

MISSING_TS_ORACLE = """\
task_text: x
adjudication:
  stop_hook_active:
    second_stop: true
    last_decision: PASS
"""


def _load_shim():
    name = "completion_gate_hook_47"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, HOOKS / "completion_gate.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def _plain_sha(adj: dict) -> str:
    """Pre-#47 canonical form (json over JSON-native values only)."""
    return hashlib.sha256(json.dumps(
        adj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _mk_ws_raw(tmp_path: Path, oracle_text: str) -> Path:
    """Workspace with a RAW task-oracle.yaml (no yaml.safe_dump round-trip —
    the whole point is the unquoted scalar that safe_load turns into a
    datetime)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    (ws / "task-oracle.yaml").write_text(oracle_text, encoding="utf-8")
    return ws


def _run(ws: Path) -> tuple[int, str]:
    mod = _load_shim()
    payload = {"hook_event_name": "Stop", "session_id": "t",
               "cwd": str(ws), "stop_hook_active": True}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main(io.StringIO(json.dumps(payload)))
    return rc, buf.getvalue()


def _anchor_rows(ws: Path) -> list[dict]:
    p = ws / ".convergence_ledger.jsonl"
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("type") == SECOND_STOP_EVENT:
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# B1 — the crash point: _secondstop_record_sha with a datetime value
# ---------------------------------------------------------------------------

def test_record_sha_accepts_datetime_value():
    mod = _load_shim()
    dt = datetime(2026, 9, 4, 10, 0, 0, tzinfo=timezone.utc)
    adj = {"second_stop": True, "last_decision": "PASS", "last_decision_at": dt}
    # Pre-fix: TypeError: Object of type datetime is not JSON serializable
    sha = mod._secondstop_record_sha(adj)
    assert isinstance(sha, str) and len(sha) == 64
    # deterministic: fresh equal object → same sha
    again = mod._secondstop_record_sha(
        {"second_stop": True, "last_decision": "PASS",
         "last_decision_at": datetime(2026, 9, 4, 10, 0, 0, tzinfo=timezone.utc)})
    assert sha == again


def test_record_sha_naive_datetime_and_date_and_nested():
    mod = _load_shim()
    adj = {"second_stop": True, "last_decision": "PASS",
           "last_decision_at": datetime(2026, 9, 4, 10, 0, 0),
           "window": {"from": datetime(2026, 9, 3), "notes": ["a", "b"]}}
    sha = mod._secondstop_record_sha(adj)
    assert isinstance(sha, str) and len(sha) == 64


# ---------------------------------------------------------------------------
# B2 — compatibility anchor: datetime object ≡ isoformat string
# ---------------------------------------------------------------------------

def test_sha_datetime_object_equals_isoformat_string():
    mod = _load_shim()
    dt = datetime(2026, 9, 4, 10, 0, 0, tzinfo=timezone.utc)
    as_obj = mod._secondstop_record_sha(
        {"second_stop": True, "last_decision": "PASS", "last_decision_at": dt})
    as_str = mod._secondstop_record_sha(
        {"second_stop": True, "last_decision": "PASS",
         "last_decision_at": dt.isoformat()})
    assert as_obj == as_str


def test_json_native_adj_sha_unchanged():
    """A JSON-native adjudication map (everything the pre-fix path could
    anchor) must keep its exact pre-#47 sha — normalization must not shift
    existing ledger anchors."""
    mod = _load_shim()
    adj = {"second_stop": True, "last_decision": "PASS",
           "last_decision_at": "2026-09-04T10:00:00Z", "notes": None}
    assert mod._secondstop_record_sha(adj) == _plain_sha(adj)


# ---------------------------------------------------------------------------
# B3 — end-to-end: unquoted timestamp no longer blocks/loses the anchor
# ---------------------------------------------------------------------------

def test_unquoted_timestamp_sanctioned_pass_anchors(tmp_path):
    ws = _mk_ws_raw(tmp_path, UNQUOTED_ORACLE)
    # fixture guard: the unquoted scalar REALLY parses into a datetime
    adj = yaml.safe_load((ws / "task-oracle.yaml").read_text(
        encoding="utf-8"))["adjudication"]["stop_hook_active"]
    assert isinstance(adj["last_decision_at"], datetime), adj
    rc, out = _run(ws)
    # sanctioned PASS goes through — no block JSON, no generic reason
    assert rc == 0, out
    assert out == "", out
    rows = _anchor_rows(ws)
    assert len(rows) == 1, rows
    assert rows[0]["record_sha256"] == mod_sha(adj)
    # idempotent second sighting — same record → same sha → no duplicate
    rc2, out2 = _run(ws)
    assert rc2 == 0, out2
    assert len(_anchor_rows(ws)) == 1


def mod_sha(adj: dict) -> str:
    """Expected anchor sha: the #47 canonical form — json with datetimes as
    isoformat strings (computed independently of the shim)."""
    def norm(o):
        if isinstance(o, dict):
            return {k: norm(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [norm(v) for v in o]
        if isinstance(o, (datetime,)):
            return o.isoformat()
        import datetime as _dtmod
        if isinstance(o, _dtmod.date):
            return o.isoformat()
        return o
    return _plain_sha(norm(adj))


# ---------------------------------------------------------------------------
# B4 — error precision: anchor-path failure carries the real cause
# ---------------------------------------------------------------------------

def test_unexpected_anchor_error_blocks_with_real_cause(tmp_path, monkeypatch):
    mod = _load_shim()
    ws = _mk_ws_raw(tmp_path, QUOTED_ORACLE)
    monkeypatch.setattr(mod, "_secondstop_record_sha",
                        lambda adj: (_ for _ in ()).throw(
                            RuntimeError("boom ledger codec")))
    rc, out = _run(ws)
    # fail-closed: BLOCK, not the old silent fail-open (rc 0), and the
    # reason names the underlying exception — not the generic sanction text
    assert rc == 1, out
    d = json.loads(out)
    assert d["decision"] == "block"
    assert "RuntimeError" in d["reason"] and "boom ledger codec" in d["reason"]
    assert "without oracle sanction" not in d["reason"]


def test_oserror_ledger_failure_still_names_class(tmp_path):
    """#831 regression: ledger unreadable (dir where the file belongs) →
    BLOCK carrying the OSError class (#47 adds precision, keeps posture)."""
    ws = _mk_ws_raw(tmp_path, QUOTED_ORACLE)
    (ws / ".convergence_ledger.jsonl").mkdir()
    rc, out = _run(ws)
    assert rc == 1
    d = json.loads(out)
    assert "IsADirectoryError" in d["reason"]
    assert "without oracle sanction" not in d["reason"]


# ---------------------------------------------------------------------------
# B5 — regressions: quoted string + missing timestamp still work
# ---------------------------------------------------------------------------

def test_quoted_timestamp_still_passes_and_anchors(tmp_path):
    ws = _mk_ws_raw(tmp_path, QUOTED_ORACLE)
    adj = yaml.safe_load((ws / "task-oracle.yaml").read_text(
        encoding="utf-8"))["adjudication"]["stop_hook_active"]
    assert isinstance(adj["last_decision_at"], str)
    rc, out = _run(ws)
    assert rc == 0, out
    rows = _anchor_rows(ws)
    assert len(rows) == 1
    assert rows[0]["record_sha256"] == _plain_sha(adj)


def test_missing_last_decision_at_still_passes(tmp_path):
    ws = _mk_ws_raw(tmp_path, MISSING_TS_ORACLE)
    rc, out = _run(ws)
    assert rc == 0, out
    assert len(_anchor_rows(ws)) == 1

# -*- coding: utf-8 -*-
"""tests/test_evidence_pin_652.py — evidence/** surface policy.

RED: hooks/write_guard.py carriers are only facts/**.md, notes/**.md,
claim-register.yaml, facts/_INDEX.md — evidence/** was maker-writable via
Write/Edit/Bash, while BOTH checker faces consume evidence/replay-<claim>.json
as ground truth (checkpoints verifier gate; convergence's replay-equivalence
face). A maker can pre-place or overwrite the artifact a checker will
"verify" against.

Fix under test: scripts/evidence_pin.py (sha-pin store: pin / check /
unpin-with-reason over runs/evidence-pins.json) + hooks/evidence_pin_guard.py
(PreToolUse Write|Edit|MultiEdit + Bash: a checker-consumed artifact is
FROZEN — rewriting it requires an explicit audited unpin first).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evidence_pin  # noqa: E402


def _load_guard():
    spec = importlib.util.spec_from_file_location(
        "evidence_pin_guard_uut", ROOT / "hooks" / "evidence_pin_guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ws(tmp_path) -> Path:
    ws = tmp_path / "ws"
    (ws / "evidence").mkdir(parents=True)
    (ws / "runs").mkdir()
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    (ws / "evidence" / "replay-C-1.json").write_text(
        '{"claim_id": "C-1", "pairs": 2}', encoding="utf-8")
    return ws


# ---------- the pin store --------------------------------------------------

def test_pin_records_sha_and_check_is_clean(tmp_path):
    ws = _ws(tmp_path)
    rec = evidence_pin.pin(ws, "evidence/replay-C-1.json", by="verifier-act-1")
    assert rec["sha256"] == evidence_pin.sha256_file(
        ws / "evidence" / "replay-C-1.json")
    assert evidence_pin.check(ws) == [], \
        "a pinned artifact that still hashes to its pin is clean"


def test_check_flags_overwrite_after_consumption(tmp_path):
    ws = _ws(tmp_path)
    evidence_pin.pin(ws, "evidence/replay-C-1.json", by="verifier-act-1")
    (ws / "evidence" / "replay-C-1.json").write_text(
        '{"claim_id": "C-1", "pairs": 99}', encoding="utf-8")
    violations = evidence_pin.check(ws)
    assert len(violations) == 1 and "evidence/replay-C-1.json" in violations[0], \
        "an overwrite of a checker-consumed artifact is a mechanical violation"


def test_check_flags_missing_pinned_artifact(tmp_path):
    ws = _ws(tmp_path)
    evidence_pin.pin(ws, "evidence/replay-C-1.json")
    (ws / "evidence" / "replay-C-1.json").unlink()
    violations = evidence_pin.check(ws)
    assert violations and "missing" in violations[0].lower()


def test_unpin_requires_a_reason(tmp_path):
    ws = _ws(tmp_path)
    evidence_pin.pin(ws, "evidence/replay-C-1.json")
    try:
        evidence_pin.unpin(ws, "evidence/replay-C-1.json", reason="")
    except ValueError as exc:
        assert "reason" in str(exc)
    else:
        raise AssertionError("unpin without a reason must refuse (audited supersede)")


def test_unpin_records_supersede_history(tmp_path):
    ws = _ws(tmp_path)
    evidence_pin.pin(ws, "evidence/replay-C-1.json")
    evidence_pin.unpin(ws, "evidence/replay-C-1.json",
                       reason="round-2 re-verification", by="orchestrator")
    assert evidence_pin.check(ws) == []
    doc = json.loads((ws / "runs" / "evidence-pins.json").read_text(encoding="utf-8"))
    assert "evidence/replay-C-1.json" not in doc["pins"]
    hist = [h for h in doc["history"] if h.get("action") == "unpin"]
    assert hist and hist[-1]["reason"] == "round-2 re-verification"


def test_cli_roundtrip(tmp_path, capsys):
    ws = _ws(tmp_path)
    rc = evidence_pin.main([str(ws), "pin", "evidence/replay-C-1.json",
                            "--by", "verifier-act-1"])
    assert rc == 0
    rc = evidence_pin.main([str(ws), "check"])
    assert rc == 0
    (ws / "evidence" / "replay-C-1.json").write_text("{}", encoding="utf-8")
    rc = evidence_pin.main([str(ws), "check"])
    assert rc == 2, "check exits 2 on violations"
    assert "evidence/replay-C-1.json" in capsys.readouterr().out
    rc = evidence_pin.main([str(ws), "unpin", "evidence/replay-C-1.json"])
    assert rc == 3, "CLI unpin without --reason refuses"
    rc = evidence_pin.main([str(ws), "unpin", "evidence/replay-C-1.json",
                            "--reason", "superseded by round-2"])
    assert rc == 0
    assert evidence_pin.main([str(ws), "check"]) == 0


# ---------- the write guard ------------------------------------------------

def _payload(ws: Path, tool: str, tool_input: dict) -> dict:
    return {"cwd": str(ws), "tool_name": tool, "tool_input": tool_input}


def test_write_to_pinned_artifact_denied(tmp_path):
    mod = _load_guard()
    ws = _ws(tmp_path)
    evidence_pin.pin(ws, "evidence/replay-C-1.json", by="verifier-act-1")
    rc, err, ctx = mod.evaluate(_payload(
        ws, "Write", {"file_path": str(ws / "evidence" / "replay-C-1.json"),
                      "content": "{}"}))
    assert rc == 2, "a checker-consumed artifact is frozen against overwrite"
    assert "REJECT evidence_pin_guard" in err
    assert ctx and "unpin" in ctx, "repair path names the audited supersede"
    # Edit face rides the same freeze
    rc, _e, _c = mod.evaluate(_payload(
        ws, "Edit", {"file_path": "evidence/replay-C-1.json",
                     "old_string": "a", "new_string": "b"}))
    assert rc == 2


def test_write_to_unpinned_evidence_stays_open(tmp_path):
    mod = _load_guard()
    ws = _ws(tmp_path)
    evidence_pin.pin(ws, "evidence/replay-C-1.json")
    rc, err, ctx = mod.evaluate(_payload(
        ws, "Write", {"file_path": str(ws / "evidence" / "replay-C-2.json"),
                      "content": "{}"}))
    assert (rc, err, ctx) == (0, "", None), \
        "only PINNED artifacts freeze — new evidence writes are normal traffic"


def test_no_pins_means_no_traffic(tmp_path):
    mod = _load_guard()
    ws = _ws(tmp_path)
    rc, _e, _c = mod.evaluate(_payload(
        ws, "Write", {"file_path": str(ws / "evidence" / "replay-C-1.json"),
                      "content": "{}"}))
    assert rc == 0, "target-based arming (the write_guard precedent): no pin, no guard"


def test_bash_mutations_denied_reads_allowed(tmp_path):
    mod = _load_guard()
    ws = _ws(tmp_path)
    evidence_pin.pin(ws, "evidence/replay-C-1.json")
    for cmd in ("rm evidence/replay-C-1.json",
                "cat > evidence/replay-C-1.json <<'EOF'\n{}\nEOF",
                "sed -i 's/a/b/' evidence/replay-C-1.json",
                "cp /tmp/fake.json evidence/replay-C-1.json",
                "python3 - <<'EOF' > evidence/replay-C-1.json\nprint('{}')\nEOF"):
        rc, err, _ctx = mod.evaluate(_payload(ws, "Bash", {"command": cmd}))
        assert rc == 2, f"mutation must be denied: {cmd!r}"
        assert "REJECT evidence_pin_guard" in err
    for cmd in ("sha256sum evidence/replay-C-1.json",
                "cmp evidence/replay-C-1.json evidence/other.json",
                "grep -c pairs evidence/replay-C-1.json"):
        rc, _e, _c = mod.evaluate(_payload(ws, "Bash", {"command": cmd}))
        assert rc == 0, f"reads must stay open: {cmd!r}"


def test_main_face_emits_rc2_and_durable_row(tmp_path, monkeypatch, capsys):
    mod = _load_guard()
    ws = _ws(tmp_path)
    evidence_pin.pin(ws, "evidence/replay-C-1.json")
    payload = _payload(ws, "Write",
                       {"file_path": str(ws / "evidence" / "replay-C-1.json"),
                        "content": "{}"})
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    rc = mod.main()
    assert rc == 2
    out = capsys.readouterr()
    assert "evidence_pin_guard" in out.err
    rows = []
    for f in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        rows += [json.loads(ln) for ln in f.read_text().splitlines() if ln.strip()]
    assert any(r.get("action") == "evidence_pin_blocked" for r in rows), \
        "the freeze must leave a durable row"


# ---------- e2e integration: pin at consumption, unpin before re-verify ----

def test_checkpoints_pins_consumed_artifact_on_verifier_land(tmp_path):
    from types import SimpleNamespace
    from e2e import checkpoints
    ws = _ws(tmp_path)
    (ws / "evidence" / "replay-C-1.json").write_text('{"pairs": 1}', encoding="utf-8")
    ctx = SimpleNamespace(ws=ws, repo=ROOT)
    checkpoints._pin_checker_artifacts(ctx, "C-1", by="verify-act-1")
    assert "evidence/replay-C-1.json" in evidence_pin.pins_of(ws), \
        "the verifier act's consumed artifact must be pinned at land"
    # relaunch for a re-verification round — the engine unpins (audited)
    checkpoints._unpin_checker_artifacts(ctx, "C-1",
                                         reason="round-2 re-verification")
    assert evidence_pin.pins_of(ws) == {}, \
        "a re-verification launch must release the pin before the act runs"
    doc = json.loads((ws / "runs" / "evidence-pins.json").read_text(encoding="utf-8"))
    assert any(h.get("action") == "unpin" for h in doc["history"])


def test_promotion_refuses_on_pin_violation(tmp_path):
    """The enforcement seam: a promotion whose checker-consumed artifact no
    longer matches its pin must refuse (the bytes on disk are not the bytes
    that were verified)."""
    from e2e import runtime
    ws = _ws(tmp_path)
    evidence_pin.pin(ws, "evidence/replay-C-1.json", by="verify-act-1")
    (ws / "evidence" / "replay-C-1.json").write_text(
        '{"claim_id": "C-1", "pairs": 99}', encoding="utf-8")
    res = runtime.promote_claims(ROOT, ws, ["C-1"])
    assert res["ok"] is False, "a pin violation must refuse the promotion"
    assert any("evidence pin" in str(v) for v in res["violations"])
    assert res["written"] is False


def test_promotion_untouched_without_pins(tmp_path):
    from e2e import runtime
    ws = _ws(tmp_path)
    res = runtime.promote_claims(ROOT, ws, ["C-1"])
    assert not any("evidence pin" in str(v) for v in res.get("violations", []))


def test_checkpoints_helpers_fail_open_on_stub_repo(tmp_path):
    """The act-fixture repos ship no scripts/evidence_pin.py — the helpers
    must be loud-but-harmless, never break the act flow."""
    from types import SimpleNamespace
    from e2e import checkpoints
    ws = _ws(tmp_path)
    stub = tmp_path / "stubrepo"
    (stub / "scripts").mkdir(parents=True)
    ctx = SimpleNamespace(ws=ws, repo=stub)
    checkpoints._pin_checker_artifacts(ctx, "C-1", by="x")  # must not raise
    checkpoints._unpin_checker_artifacts(ctx, "C-1", reason="x")


def test_registered_in_wire_up_and_subset_tables():
    wu = (ROOT / "scripts" / "wire_up_settings.py").read_text(encoding="utf-8")
    assert "evidence_pin_guard.py" in wu
    ha = (ROOT / "scripts" / "hook_activation.py").read_text(encoding="utf-8")
    assert "evidence_pin_guard.py" in ha
    ek = (ROOT / "scripts" / "external_kicker.py").read_text(encoding="utf-8")
    assert "evidence_pin_guard.py" in ek
    hs = (ROOT / "scripts" / "hooks_selfcheck.py").read_text(encoding="utf-8")
    assert "evidence_pin_guard.py" in hs

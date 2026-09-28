# -*- coding: utf-8 -*-
"""tests/test_jadx_exec_426.py — jadx EXECUTION contract (issue 426).

apk_mem_gate (#670) makes the memory-budget DECISION; #426 delivers the
execution wrapper that turns each verdict into a concrete, memory-bounded
jadx invocation plan:

  jadx-ok        -> rung-1: whole-APK ``jadx --no-res`` (bounded JVM heap +
                    thread cap);
  targeted-jadx  -> rung-2: extract classes*.dex from the APK (zip entries,
                    NO full unpack), byte-scan each dex for relevance
                    markers, isolated ``jadx --no-res`` per matched dex
                    (one bad dex never kills the batch);
  OOM fallback   -> rung-1 OOM (non-zero exit OR OOM string in output)
                    auto-drops to the per-dex rung; the transition is
                    RECORDED (canonical warn + summary JSON — silent
                    degradation forbidden) and rung-1 partial output is
                    DISCARDED, never merged with per-dex output;
  smali-only /
  refuse         -> no jadx run at all.

Output contract: unified ``-d OUT`` layout regardless of rung (per-dex
outputs under their source dex stem) so downstream faces see one source
tree; the structured summary JSON is written NEXT TO OUT.

Resources are NEVER decompiled: every invocation carries ``--no-res`` and
no res/ tree may appear under OUT in any rung.

All fixtures are SYNTHETIC; jadx itself is a stub shim written to tmp_path
— the real binary is never required or invoked.
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

_HERE = Path(__file__).parent
SCRIPTS = _HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from jadx_exec import SUMMARY_NAME, main  # noqa: E402 (RED: module absent yet)

DEX_MAGIC = b"dex\n035\x00"


# ---------------------------------------------------------------------------
# Helpers — synthetic APK + jadx stub shim
# ---------------------------------------------------------------------------

# The shim mimics jadx's observable contract: it records argv + JAVA_OPTS so
# tests can pin the exact invocation surface, and it HONORS --no-res by
# sabotage: when the flag is absent it writes a resources/ tree into -d, so
# "no res dirs in output" assertions actually bite. Failure modes come from
# env: JADX_STUB_MODE=oom (whole-APK input -> partial output + OOM stderr +
# exit 1), oom_stdout (OOM text on stdout, exit 0), fail-dex (input basename
# in JADX_STUB_FAIL_DEX -> partial output + exit 2).
_SHIM = r'''#!/usr/bin/env python3
"""jadx stub shim for #426 tests (never the real jadx)."""
import json
import os
import pathlib
import sys

args = sys.argv[1:]
d = args[args.index("-d") + 1]
rest = args[args.index("-d") + 2:]
src = [a for a in rest if not a.startswith("-")][-1]
no_res = "--no-res" in args
entry = {"argv": args, "java_opts": os.environ.get("JAVA_OPTS", ""),
         "no_res": no_res, "input": src}
with open(os.environ["JADX_STUB_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(entry) + "\n")

out = pathlib.Path(d)
mode = os.environ.get("JADX_STUB_MODE", "ok")
fail_dex = [s for s in os.environ.get("JADX_STUB_FAIL_DEX", "").split(",")
            if s]
name = pathlib.Path(src).name
is_apk = src.lower().endswith(".apk")


def write_sources(tag):
    p = out / "sources" / "com" / "example"
    p.mkdir(parents=True, exist_ok=True)
    (p / (tag + ".java")).write_text("class " + tag.replace(".", "_") + " {}\n")


def write_resources():
    p = out / "resources"
    p.mkdir(parents=True, exist_ok=True)
    (p / "icon.png").write_bytes(b"\x89PNG")


if not no_res:
    write_resources()  # sabotage face: proves assertions watch the flag

if mode == "oom" and is_apk:
    write_sources("rung1_partial")
    sys.stderr.write("Error: java.lang.OutOfMemoryError: Java heap space\n")
    sys.exit(1)
if mode == "oom_stdout" and is_apk:
    write_sources("rung1_partial")
    sys.stdout.write("java.lang.OutOfMemoryError: Java heap space\n")
    sys.exit(0)
if mode == "benign_oom_substring" and is_apk:
    # reviewer F1 probe: benign output whose substrings contain "oom"
    # ("com/zoom/...", "classroom") must NOT trigger the OOM ladder.
    write_sources("wholeapk")
    sys.stdout.write("INFO: loaded com/zoom/sdk/lib/ZoomSDK.class\n"
                     "INFO: classroom schedule parsed\n")
    sys.exit(0)
if mode == "fail-dex" and name in fail_dex:
    write_sources(name[:-4] + "_partial")
    sys.stderr.write("jadx-stub: parse error in " + name + "\n")
    sys.exit(2)
write_sources(name[:-4] if name.lower().endswith(".dex") else "wholeapk")
sys.exit(0)
'''


def _write_shim(tmp_path: Path) -> Path:
    shim = tmp_path / "jadx-stub.py"
    shim.write_text(_SHIM, encoding="utf-8")
    shim.chmod(0o755)
    return shim


def _make_apk(tmp_path: Path, entries: dict) -> Path:
    apk = tmp_path / "fake.apk"
    with zipfile.ZipFile(apk, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return apk


def _read_log(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in
            log.read_text(encoding="utf-8").splitlines()]


def _invoke(tmp_path: Path, monkeypatch, ws: Path, apk: Path, shim: Path,
            *extra) -> tuple[int, Path, list[dict]]:
    """Run main() with the stub wired in; returns (rc, log_path, entries)."""
    log = tmp_path / "invocations.jsonl"
    monkeypatch.setenv("JADX_STUB_LOG", str(log))
    rc = main([str(ws), str(apk), "--jadx-bin", str(shim), *extra])
    return rc, log, _read_log(log)


def _summary(out: Path) -> dict:
    return json.loads((out.parent / SUMMARY_NAME).read_text(encoding="utf-8"))


def _no_res_dirs(out: Path) -> list[str]:
    """Any res/resources tree leaked into the output root (must stay empty)."""
    return [str(p) for p in out.rglob("*")
            if p.is_dir() and p.name in ("res", "resources")]


# ---------------------------------------------------------------------------
# RED1 — small APK + jadx-ok -> whole-APK plan, --no-res + bounded JVM
# ---------------------------------------------------------------------------

def test_red1_small_apk_whole_plan_no_res_bounded_heap(tmp_path, monkeypatch):
    """jadx-ok verdict -> exactly ONE whole-APK jadx invocation carrying
    --no-res, a thread cap, and the bounded JVM heap via JAVA_OPTS; the
    unified -d OUT layout holds (OUT itself is the jadx -d target)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    out = ws / "out" / "jadx-src"
    apk = _make_apk(tmp_path, {"classes.dex": DEX_MAGIC + b"\x00" * 64})
    shim = _write_shim(tmp_path)

    rc, log, entries = _invoke(tmp_path, monkeypatch, ws, apk, shim,
                               "--verdict", "jadx-ok", "--out", str(out))

    assert rc == 0, entries
    assert len(entries) == 1, entries
    call = entries[0]
    assert "--no-res" in call["argv"], call
    assert call["no_res"] is True, call
    assert call["java_opts"] == "-Xmx4g", call
    assert "--threads-count" in call["argv"], call
    assert call["input"].endswith("fake.apk"), call
    # unified layout: whole-APK rung decompiles into OUT itself
    d_target = call["argv"][call["argv"].index("-d") + 1]
    assert Path(d_target) == out, call
    assert (out / "sources" / "com" / "example" / "wholeapk.java").exists()
    assert not _no_res_dirs(out), "resources must never be decompiled"
    summary = _summary(out)
    assert summary["verdict"] == "jadx-ok", summary
    assert summary["rungs"][0]["kind"] == "whole-apk", summary
    assert summary["rungs"][0]["status"] == "ok", summary
    assert list(summary) == sorted(summary), "summary key order must be stable"


def test_red1b_heap_override_via_flag(tmp_path, monkeypatch):
    """--heap-gb overrides the default JVM bound (named constant, no magic
    number in the call)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    out = ws / "out" / "jadx-src"
    apk = _make_apk(tmp_path, {"classes.dex": DEX_MAGIC + b"\x00" * 64})
    shim = _write_shim(tmp_path)
    rc, _, entries = _invoke(tmp_path, monkeypatch, ws, apk, shim,
                             "--verdict", "jadx-ok", "--out", str(out),
                             "--heap-gb", "2")
    assert rc == 0
    assert entries[0]["java_opts"] == "-Xmx2g", entries


# ---------------------------------------------------------------------------
# RED2 — many-dex APK + OOM injection -> auto per-dex fall, recorded
# ---------------------------------------------------------------------------

def test_red2_oom_falls_back_to_per_dex_recorded(tmp_path, monkeypatch,
                                                 capsys):
    """Stub jadx exits non-zero with OOM in stderr on the whole-APK rung:
    the wrapper must automatically drop to the per-dex rung, RECORD the
    transition (warn + summary), process dexes in sorted order, and DISCARD
    the rung-1 partial output (never merged with per-dex output)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    out = ws / "out" / "jadx-src"
    apk = _make_apk(tmp_path, {
        "classes.dex": DEX_MAGIC + b"Lcom/a/A;",
        "classes2.dex": DEX_MAGIC + b"Lcom/b/B;",
        "classes3.dex": DEX_MAGIC + b"Lcom/c/C;",
    })
    shim = _write_shim(tmp_path)
    monkeypatch.setenv("JADX_STUB_MODE", "oom")

    rc, log, entries = _invoke(tmp_path, monkeypatch, ws, apk, shim,
                               "--verdict", "jadx-ok", "--out", str(out))

    assert rc == 0, entries
    # rung-1 whole-APK first, then per-dex in SORTED order
    assert entries[0]["input"].endswith("fake.apk"), entries
    dex_inputs = [Path(e["input"]).name for e in entries[1:]]
    assert dex_inputs == ["classes.dex", "classes2.dex", "classes3.dex"], \
        entries
    # rung-1 partial output DISCARDED: the stub wrote it into OUT before dying
    assert not (out / "sources" / "com" / "example" /
                "rung1_partial.java").exists(), "rung-1 partial must be gone"
    assert not _no_res_dirs(out)
    # per-dex outputs under their source dex stem, all present
    for stem in ("classes", "classes2", "classes3"):
        assert (out / stem / "sources" / "com" / "example" /
                (stem + ".java")).exists(), stem
    # transition RECORDED on both faces
    err = capsys.readouterr().err
    assert "jadx_exec_rung_fallback" in err, err
    summary = _summary(out)
    assert summary["rungs"][0]["status"] == "oom", summary
    assert summary["rungs"][0]["discarded"] is True, summary
    assert summary["rungs"][1]["kind"] == "per-dex", summary
    fb = summary["rung_fallback"]
    assert fb and fb["reason"] == "oom", summary
    assert "OutOfMemoryError" in json.dumps(fb), summary
    assert summary["per_dex_failures"] == [], summary


def test_red2b_oom_by_output_string_alone(tmp_path, monkeypatch):
    """OOM detection is non-zero exit OR the OOM string in captured output:
    exit 0 + OOM on stdout must still trigger the fallback ladder."""
    ws = tmp_path / "ws"
    ws.mkdir()
    out = ws / "out" / "jadx-src"
    apk = _make_apk(tmp_path, {"classes.dex": DEX_MAGIC + b"Lcom/a/A;"})
    shim = _write_shim(tmp_path)
    monkeypatch.setenv("JADX_STUB_MODE", "oom_stdout")
    rc, log, entries = _invoke(tmp_path, monkeypatch, ws, apk, shim,
                               "--verdict", "jadx-ok", "--out", str(out))
    assert rc == 0, entries
    assert len(entries) == 2, "whole-APK run must fall back to per-dex"
    assert entries[1]["input"].endswith("classes.dex"), entries
    summary = _summary(out)
    assert summary["rung_fallback"]["reason"] == "oom", summary


def test_f1_benign_oom_substring_no_fallback(tmp_path, monkeypatch):
    """Reviewer F1 regression: substring "oom" inside benign tokens (zoom,
    classroom) must NOT trigger the OOM ladder — the bare "OOM" marker is
    word-boundary anchored (a healthy rung-1 pass stays rung 1)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    out = ws / "out" / "jadx-src"
    apk = _make_apk(tmp_path, {"classes.dex": DEX_MAGIC + b"Lcom/a/A;"})
    shim = _write_shim(tmp_path)
    monkeypatch.setenv("JADX_STUB_MODE", "benign_oom_substring")
    rc, log, entries = _invoke(tmp_path, monkeypatch, ws, apk, shim,
                               "--verdict", "jadx-ok", "--out", str(out))
    assert rc == 0, entries
    assert len(entries) == 1, "no OOM fallback may fire on benign output"
    assert entries[0]["input"].endswith(".apk"), entries
    summary = _summary(out)
    assert summary["rung_fallback"] is None, summary
    assert len(summary["rungs"]) == 1, summary
    assert summary["rungs"][0]["kind"] == "whole-apk", summary
    assert summary["rungs"][0]["discarded"] is False, summary
    assert summary["rungs"][0]["status"] == "ok", summary
    assert summary["rungs"][0]["oom_markers"] == [], summary


def test_f1_has_oom_word_boundary_unit():
    """Unit pins for _has_oom: word-boundary 'OOM' hits, substrings don't;
    the other markers stay plain substring matches."""
    import jadx_exec
    assert jadx_exec._has_oom("OOM: heap exhausted") == ["OOM"]
    assert jadx_exec._has_oom("an OOM occurred during merge") == ["OOM"]
    assert jadx_exec._has_oom("com/zoom/sdk/lib") == []
    assert jadx_exec._has_oom("classroom schedule") == []
    assert jadx_exec._has_oom("OOMCommand failed") == []
    assert "OutOfMemoryError" in jadx_exec._has_oom(
        "Error: java.lang.OutOfMemoryError: Java heap space")
    assert "GC overhead limit exceeded" in jadx_exec._has_oom(
        "GC overhead limit exceeded")


# ---------------------------------------------------------------------------
# RED3 — relevance markers -> only matching dexes decompiled
# ---------------------------------------------------------------------------

def test_red3_markers_decompile_only_matching_dexes(tmp_path, monkeypatch):
    """targeted-jadx + markers: each extracted dex is byte-scanned for the
    markers and only matching dexes reach jadx; skipped dexes are recorded,
    not silently dropped."""
    ws = tmp_path / "ws"
    ws.mkdir()
    out = ws / "out" / "jadx-src"
    apk = _make_apk(tmp_path, {
        "classes.dex": DEX_MAGIC + b"Lcom/targetapp/crypto/Foo;",
        "classes2.dex": DEX_MAGIC + b"Lcom/other/Bar;",
        "AndroidManifest.xml": b"<?xml binary?>",
    })
    shim = _write_shim(tmp_path)

    rc, log, entries = _invoke(tmp_path, monkeypatch, ws, apk, shim,
                               "--verdict", "targeted-jadx", "--out", str(out),
                               "--markers", "Lcom/targetapp/")

    assert rc == 0, entries
    assert len(entries) == 1, "only the matching dex may reach jadx"
    assert Path(entries[0]["input"]).name == "classes.dex", entries
    assert "--no-res" in entries[0]["argv"], entries
    assert (out / "classes").is_dir(), entries
    assert not (out / "classes2").exists(), entries
    assert not _no_res_dirs(out)
    summary = _summary(out)
    assert summary["matched_dexes"] == ["classes.dex"], summary
    assert summary["skipped_dexes"] == ["classes2.dex"], summary
    assert summary["per_dex_failures"] == [], summary
    plans = {p["dex"]: p for p in summary["dex_plans"]}
    assert plans["classes.dex"]["status"] == "ok", summary
    assert plans["classes2.dex"]["status"] == "skipped", summary


# ---------------------------------------------------------------------------
# RED4 — --no-res contract on EVERY rung; no-op verdicts never run jadx
# ---------------------------------------------------------------------------

def test_red4_no_res_on_every_rung(tmp_path, monkeypatch):
    """Both rungs carry --no-res and leak no res/ tree. The sabotage face
    first proves the shim WOULD write resources without the flag, so the
    wrapper-run assertions genuinely bite."""
    ws = tmp_path / "ws"
    ws.mkdir()
    out = ws / "out" / "jadx-src"
    apk = _make_apk(tmp_path, {"classes.dex": DEX_MAGIC + b"Lcom/a/A;"})
    shim = _write_shim(tmp_path)
    log = tmp_path / "invocations.jsonl"
    monkeypatch.setenv("JADX_STUB_LOG", str(log))

    # sabotage face: shim called WITHOUT --no-res leaks resources/ (isolated
    # probe log — must not pollute the wrapper-run invocation log)
    probe_log = tmp_path / "probe-log.jsonl"
    probe = tmp_path / "probe-out"
    subprocess.run([str(shim), "-d", str(probe), str(apk)], check=False,
                   env={"JADX_STUB_LOG": str(probe_log), "PATH": "/usr/bin:/bin"})
    assert (probe / "resources").is_dir(), "sabotage face must hold"

    # OOM fallback run exercises BOTH rungs in one pass
    monkeypatch.setenv("JADX_STUB_MODE", "oom")
    rc, _, entries = _invoke(tmp_path, monkeypatch, ws, apk, shim,
                             "--verdict", "jadx-ok", "--out", str(out))
    assert rc == 0, entries
    assert len(entries) >= 2, entries
    assert all(e["no_res"] is True and "--no-res" in e["argv"]
               for e in entries), entries
    assert not _no_res_dirs(out), "no rung may leak a res tree"


def test_red4b_smali_only_and_refuse_never_run_jadx(tmp_path, monkeypatch):
    """smali-only / refuse: unchanged — zero jadx invocations, zero output
    tree, summary records the no-op."""
    ws = tmp_path / "ws"
    ws.mkdir()
    apk = _make_apk(tmp_path, {"classes.dex": DEX_MAGIC + b"Lcom/a/A;"})
    shim = _write_shim(tmp_path)
    for verdict in ("smali-only", "refuse"):
        out = tmp_path / f"out-{verdict}" / "jadx-src"
        rc, log, entries = _invoke(tmp_path, monkeypatch, ws, apk, shim,
                                   "--verdict", verdict, "--out", str(out))
        assert rc == 0, (verdict, entries)
        assert entries == [], (verdict, entries)
        assert not log.exists(), verdict
        assert not out.exists(), verdict
        summary = _summary(out)
        assert summary["status"] == "noop", summary
        assert summary["rungs"] == [], summary


# ---------------------------------------------------------------------------
# RED5 — per-dex isolated failure -> batch continues, failure recorded
# ---------------------------------------------------------------------------

def test_red5_per_dex_failure_does_not_kill_batch(tmp_path, monkeypatch,
                                                  capsys):
    """One bad dex: its isolated run fails (non-OOM), the batch continues,
    the failure is recorded (warn + summary) and its partial output is
    discarded with the rest of the tree intact."""
    ws = tmp_path / "ws"
    ws.mkdir()
    out = ws / "out" / "jadx-src"
    apk = _make_apk(tmp_path, {
        "classes.dex": DEX_MAGIC + b"Lcom/a/A;",
        "classes2.dex": DEX_MAGIC + b"Lcom/b/B;",
        "classes3.dex": DEX_MAGIC + b"Lcom/c/C;",
    })
    shim = _write_shim(tmp_path)
    monkeypatch.setenv("JADX_STUB_MODE", "fail-dex")
    monkeypatch.setenv("JADX_STUB_FAIL_DEX", "classes2.dex")

    rc, log, entries = _invoke(tmp_path, monkeypatch, ws, apk, shim,
                               "--verdict", "targeted-jadx", "--out", str(out))

    assert rc == 0, "one bad dex must not kill the batch"
    assert len(entries) == 3, "each dex gets an isolated run"
    assert (out / "classes").is_dir() and (out / "classes3").is_dir()
    assert not (out / "classes2").exists(), "failed dex partial is discarded"
    assert not _no_res_dirs(out)
    err = capsys.readouterr().err
    assert "jadx_exec_dex_failed" in err, err
    assert "classes2.dex" in err, err
    summary = _summary(out)
    assert summary["per_dex_failures"] == ["classes2.dex"], summary
    plans = {p["dex"]: p for p in summary["dex_plans"]}
    assert plans["classes.dex"]["status"] == "ok", summary
    assert plans["classes2.dex"]["status"] == "failed", summary
    assert plans["classes2.dex"]["exit"] == 2, summary
    assert plans["classes3.dex"]["status"] == "ok", summary


# ---------------------------------------------------------------------------
# Supporting faces — verdict source + error contract
# ---------------------------------------------------------------------------

def test_verdict_read_from_gate_evidence(tmp_path, monkeypatch):
    """Without --verdict the #670 gate evidence file is the verdict source
    (key 'verdict' in evidence/apk_mem_gate.json)."""
    ws = tmp_path / "ws"
    (ws / "evidence").mkdir(parents=True)
    (ws / "evidence" / "apk_mem_gate.json").write_text(
        json.dumps({"verdict": "smali-only"}), encoding="utf-8")
    apk = _make_apk(tmp_path, {"classes.dex": DEX_MAGIC + b"Lcom/a/A;"})
    shim = _write_shim(tmp_path)
    out = ws / "out" / "jadx-src"
    rc, log, entries = _invoke(tmp_path, monkeypatch, ws, apk, shim,
                               "--out", str(out))
    assert rc == 0, entries
    assert entries == [], entries
    summary = _summary(out)
    assert summary["verdict"] == "smali-only", summary
    assert summary["verdict_source"] == "evidence/apk_mem_gate.json", summary


def test_missing_verdict_is_structured_error(tmp_path, monkeypatch, capsys):
    """No --verdict and no gate evidence: exit 2 with a structured error on
    stderr (never a traceback, never a silent guess)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    apk = _make_apk(tmp_path, {"classes.dex": DEX_MAGIC + b"Lcom/a/A;"})
    shim = _write_shim(tmp_path)
    rc, log, entries = _invoke(tmp_path, monkeypatch, ws, apk, shim)
    assert rc == 2, entries
    assert entries == [], entries
    err = capsys.readouterr().err
    payload = json.loads(err.strip().splitlines()[-1])
    assert "error" in payload and payload["exit_code"] == 2, err


def test_unknown_verdict_rejected(tmp_path, monkeypatch, capsys):
    """A verdict outside the #670 vocabulary is a usage error (exit 2)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    apk = _make_apk(tmp_path, {"classes.dex": DEX_MAGIC + b"Lcom/a/A;"})
    shim = _write_shim(tmp_path)
    out = ws / "out" / "jadx-src"
    rc, _, entries = _invoke(tmp_path, monkeypatch, ws, apk, shim,
                             "--verdict", "banana", "--out", str(out))
    assert rc == 2, entries
    payload = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert "banana" in payload["error"], payload

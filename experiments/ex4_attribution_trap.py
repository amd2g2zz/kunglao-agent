#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ex4_attribution_trap.py — EX-4: attribution trap trajectory replay
(issue 461 Phase 1: attribution-in-state data production).

The launcher plan's "E2 data-production" experiment — the repo
experiment sequence EX-2 (gamma calibration) / EX-3 (bucket
calibration) is taken, so this ships as EX-4.

**DECLARED SYNTHETIC** — the five-step trap trajectory is the issue's
owner-authored scenario, replayed through the REAL obstacle record +
state signature faces on a throwaway workspace; nothing here is
campaign data. It produces the training shape the Phase-2 Bayesian
option-death termination estimator will consume: one obstacle row per
failing step, over REGISTERED method-family tokens (the production
Q-key vocabulary, scripts/method_families.yaml), plus the per-step
signature evolution showing cause-bearing states accumulating.

Reproduce:
  uv run --project . python experiments/ex4_attribution_trap.py
(raw numbers: experiments/ex4-results.json, same commit).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import state_signature as ssig  # noqa: E402
from rlvr import obstacles  # noqa: E402

RESULTS_REL = Path("experiments") / "ex4-results.json"

# The five-step trap (issue 461): frida-detected -> unidbg-env-error ->
# static-tool-limit -> encrypted-layer -> breakthrough-at-decryptor.
# Families are the registered Q-key vocabulary; probe artifacts carry
# the command/rc/output shape the record face validates. Fixed ts per
# step — determinism is the pin.
TRAJECTORY = [
    {
        "step": 1,
        "family": "dynamic-trace",
        "outcome": "failure",
        "kind": "detection_trigger",
        "cause": "anti-frida ptrace guard kills process 30s after "
                 "attach (probe rc=1, two reruns identical)",
        "probe": ("cmd: frida -U -f app.nk.target -l probe.js "
                  "--no-pause\nrc=1\nstdout: Process terminated 30s "
                  "after attach (ptrace stop, 2/2 reruns)\n"),
        "ts": "2026-09-30T08:01:00Z",
    },
    {
        "step": 2,
        "family": "replay-harness-verification",
        "outcome": "failure",
        "kind": "missing_env_entry",
        "cause": "unidbg aborts: ANDROID_SDK_ROOT unset (differential "
                 "probe rc=1 unset / rc=0 set)",
        "probe": ("cmd: env -u ANDROID_SDK_ROOT unidbg run.apk\n"
                  "rc=1\nstderr: IllegalStateException: SDK dir not "
                  "set; rerun with entry set: rc=0\n"),
        "ts": "2026-09-30T08:04:00Z",
    },
    {
        "step": 3,
        "family": "static-decompile",
        "outcome": "failure",
        "kind": "tool_limit",
        "cause": "jadx 300s timeout on flattened switch (probe rc=124, "
                 "same on both reruns)",
        "probe": ("cmd: jadx -d out classes.dex --timeout 300\nrc=124\n"
                  "stdout: decompile incomplete at 41% (OLLVM flattened "
                  "switch, 2/2 reruns)\n"),
        "ts": "2026-09-30T08:11:00Z",
    },
    {
        "step": 4,
        "family": "obfuscation-peeling",
        "outcome": "failure",
        "kind": "encryption_layer",
        "cause": "assets/config.bin encrypted blob (entropy 7.98, "
                 "Salted__ header; key not in binary)",
        "probe": ("cmd: python tools/crypto-tool.py entropy "
                  "assets/config.bin\nrc=0\nstdout: entropy=7.98/8.0 "
                  "header=Salted__ size=4096\n"),
        "ts": "2026-09-30T08:19:00Z",
    },
    {
        "step": 5,
        "family": "crypto-core-identification",
        "outcome": "success",
        "kind": None,  # the breakthrough: no obstacle row
        "cause": None,
        "probe": None,
        "ts": "2026-09-30T08:40:00Z",
    },
]


def replay(ws) -> dict:
    """Replay the trap trajectory on ``ws`` through the REAL faces.

    Each failing step: write the synthetic probe artifact, record the
    obstacle row (rlvr.obstacles.record — the production validation
    path), then snapshot + signature. The breakthrough step records
    nothing and lands one synthetic fact — the evidence the whole
    chase was for (the state moves by evidence, not by attribution).
    Deterministic: fixed ts per step, sorted iteration, no clock reads.
    """
    ws = Path(ws)
    ws.mkdir(parents=True, exist_ok=True)
    steps = []
    obstacles_out = []
    for entry in TRAJECTORY:
        if entry["outcome"] == "failure":
            probe_rel = f"runs/probes/ex4-step{entry['step']}.txt"
            p = ws / probe_rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(entry["probe"], encoding="utf-8")
            out = obstacles.record(
                ws, kind=entry["kind"], cause=entry["cause"],
                evidence_path=probe_rel,
                method_family=entry["family"], ts=entry["ts"])
            if not out["appended"]:  # pragma: no cover — contract break
                raise RuntimeError(
                    f"ex4: obstacle record rejected at step "
                    f"{entry['step']}: {out['errors']}")
            row = out["row"]
            obstacles_out.append({
                "id": row["id"], "kind": row["kind"],
                "method_family": row["method_family"],
                "evidence_path": row["evidence_path"], "ts": row["ts"],
            })
        else:
            facts = ws / "facts"
            facts.mkdir(parents=True, exist_ok=True)
            (facts / "F001-decryptor.md").write_text(
                "---\nid: F001\nstatus: VERIFIED\nclaim_id: C-1\n"
                "verified: false\n---\n\n# decryptor located\n"
                "synthetic breakthrough fact\n", encoding="utf-8")
        snap = ssig.snapshot(ws)
        steps.append({
            "step": entry["step"], "family": entry["family"],
            "outcome": entry["outcome"],
            "signature": ssig.signature_str(snap),
            "signature_hash": ssig.signature_hash(snap),
        })
    return {
        "experiment": "ex4-attribution-trap",
        "declared_synthetic": True,
        "workspace": str(ws),
        "steps": steps,
        "obstacles": obstacles_out,
        "expected_sequence": [
            {"kind": s["kind"], "method_family": s["family"]}
            for s in TRAJECTORY if s["outcome"] == "failure"
        ],
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import tempfile
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / RESULTS_REL),
                    help="results JSON path (default: experiments/)")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="ex4-trap-") as td:
        doc = replay(Path(td))
    doc.pop("workspace", None)  # machine-local temp path: never shipped
    out_path = Path(args.out)
    out_path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"ex4: {len(doc['obstacles'])} obstacle rows over "
          f"{len(doc['steps'])} steps -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

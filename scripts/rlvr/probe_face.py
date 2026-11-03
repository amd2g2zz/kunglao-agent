#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_face.py — the mechanical V(s) probe-face contract.

The direction face prices per-step credit as ΔV of a mechanical probe
reading V(s) — a PARTIAL-PROGRESS scalar computable from the workspace
state at step boundaries. This module owns THE registered interface the
consumer reads through (single seam — the direction face wires here,
nowhere else):

  run_probe(unit_dir, ws) -> {"schema": "kunglao-probe-reading/1",
                              "task_id", "family", "entrypoint",
                              "scalar": float in [0, 1],
                              "vector": {...evidence...},
                              "reason": str}
  probe_delta(ws, t0_reading, t1_reading) -> float   # ΔV, clamped, monotone

Contract (the probe-face construction card, binding for every family):
  - MECHANICAL: V(s) is computable from the workspace state alone — no
    agent-writable input beyond the artifacts the loop legitimately
    holds (its own candidate/answer), no grading root, no gold answer
    beyond what the unit's own terminal checker reads;
  - ORACLE-LOCKED: each unit probe's input surface is stated in its
    docstring and is the checker's surface;
  - DETERMINISTIC: same workspace state -> byte-same reading (the ΔV
    arithmetic is only as honest as this; pinned in
    tests/test_rl_v3_probe_faces_956.py);
  - FAIL-CLOSED: any fault — missing unit/entrypoint/ws, crash, harness
    cap, non-JSON output, schema mismatch, scalar out of range — reads
    scalar 0.0 with a deterministic reason. NEVER a crash, never a guess,
    never a wall-clock-dependent field in the envelope.

Dispatch is by FAMILY CONTRACT: each unit declares the face in its
task.yaml ``probe: {entrypoint: probe.py, cadence: <class>}`` block and
ships the implementation as a unit-local ``probe.py <ws>`` shim that
mirrors ``checker.py``'s shape exactly (same trust boundary — operator-
side, never copied into the agent scaffold; same stdlib-only rule).
The shim prints ONE kunglao-probe-reading/1 JSON doc on stdout, exit 0.

Cadence (cost) classes: ``instant`` (artifact-only, milliseconds — the
answer-graded families), ``bounded`` (a short bounded run, seconds —
tf-snake), ``unit-defined`` (the family's own construction decides).

Per-family faces (ACTIVE corpus):
  tf-snake         bounded run -> the checker's 8-face partial vector
  (both trainer    (schema/seed/score/foods/frames/deaths/clean/proof) +
  variants)        score/frames/foods magnitudes; scalar = weighted mix
                   (SHIPPED: probe.py in both units).
  tf-novelvm       digest distance: per-line solved count + bit-hamming
                   of the workspace answer lines vs the four expected
                   digests; scalar = mean(1.0 solved, 0.5*(64-h)/64
                   near-miss) (SHIPPED: probe.py in the rust-VM unit;
                   its second variant is the identical derivation
                   against its own ground truth).
  tf-novelcipher   the checker is the same answer-graded template as
  tf-hardwall      tf-novelvm (answer.txt vs published_pairs) — the
  pair             digest-distance face IS these families' probe;
                   derivation = the shipped digest-distance shim with
                   the unit's own ground_truth.json (mint-on-need).
  mod-crypto /     replay hit-rate: fraction of published pairs the
  native           current candidate reproduces — the checker's own
                   matched/count arithmetic evaluated on the partial
                   candidate (no new shim needed until a family wants
                   per-step reads).
  chain            layers-peeled count — the LAYER_CHECKPOINTS face
                   already shipped IS this family's V(s) probe.

Harness cap: PROBE_EP_TIMEOUT_S bounds the shim from outside (the shim
bounds its own work from inside — tf-snake's bounded run is 90s inside
a 180s cap). Invocation mirrors the unit-entrypoint grading face in
scripts/eval_checker.py: start_new_session=True so a cap kill takes
the whole tree (a candidate may have spawned a GUI game).

Measured cost classes (unit scale, operator host): the answer-graded
shim reads in ~40 ms (instant); the tf-snake bounded attract run
completes in ~4 s wall (bounded; internal bound 90 s).

stdlib only.
"""
from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import sys
from pathlib import Path

import yaml

PROBE_SCHEMA = "kunglao-probe-reading/1"
# outside-the-shim harness cap; the shim bounds its own work inside this
PROBE_EP_TIMEOUT_S = 180.0
DEFAULT_ENTRYPOINT = "probe.py"


# ---- the ONE normalizer (the normalize-site house lesson) -----------------
def clamp01(x) -> float:
    """Fail-closed scalar normalization: non-numeric / NaN / ±inf -> 0.0,
    everything else clamped into [0, 1]."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(v) or math.isinf(v):
        return 0.0
    return min(1.0, max(0.0, v))


def reading(scalar, vector, reason) -> dict:
    """The one envelope builder: a valid kunglao-probe-reading/1 doc from
    parts, scalar clamped, vector dict-or-{}, reason str-or-described."""
    if not isinstance(vector, dict):
        vector = {}
    return {
        "schema": PROBE_SCHEMA,
        "scalar": clamp01(scalar),
        "vector": vector,
        "reason": reason if isinstance(reason, str) and reason else
        "unspecified",
    }


def _fault(reason: str, *, task_id: str = "", family: str = "",
           entrypoint: str = "") -> dict:
    doc = reading(0.0, {}, reason)
    doc.update({"task_id": task_id, "family": family,
                "entrypoint": entrypoint})
    return doc


# ---- the registered interface --------------------------------------------
def probe_decl(unit_dir: Path, task: dict | None = None) -> tuple[str, str]:
    """(entrypoint, cadence) from the unit's task.yaml probe block; the
    declared face wins, the checker-mirroring default fills a missing
    block (grandfathered corpus units still probe)."""
    if task is None:
        tp = Path(unit_dir) / "task.yaml"
        try:
            task = yaml.safe_load(tp.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            task = {}
    if not isinstance(task, dict):
        task = {}
    probe = task.get("probe")
    entrypoint = DEFAULT_ENTRYPOINT
    cadence = "unit-defined"
    if isinstance(probe, dict):
        ep = probe.get("entrypoint")
        if isinstance(ep, str) and ep.strip():
            entrypoint = ep.strip()
        cad = probe.get("cadence")
        if isinstance(cad, str) and cad.strip():
            cadence = cad.strip()
    return entrypoint, cadence


def _shim_reading(stdout: str) -> tuple[dict | None, str | None]:
    """Validate a shim's stdout as a kunglao-probe-reading/1 doc; returns
    (doc, None) or (None, fault-reason)."""
    try:
        raw = json.loads(stdout)
    except json.JSONDecodeError:
        return None, "non-json-output"
    if not isinstance(raw, dict) or raw.get("schema") != PROBE_SCHEMA:
        return None, "schema-mismatch"
    scalar = raw.get("scalar")
    if not isinstance(scalar, (int, float)) or isinstance(scalar, bool) \
            or math.isnan(float(scalar)) or math.isinf(float(scalar)) \
            or not 0.0 <= float(scalar) <= 1.0:
        return None, "scalar-out-of-range"
    return raw, None


def run_probe(unit_dir, ws, *, timeout_s: float = PROBE_EP_TIMEOUT_S,
              task: dict | None = None) -> dict:
    """THE seam: one mechanical V(s) reading of ``ws`` through the unit's
    declared probe shim. Fail-closed — every fault below returns a
    scalar-0.0 reading with a deterministic reason and this function
    itself NEVER raises."""
    unit_dir = Path(unit_dir)
    identity = {}
    if task is None:
        try:
            task = yaml.safe_load(
                (unit_dir / "task.yaml").read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            task = {}
    if isinstance(task, dict):
        identity = {"task_id": str(task.get("task_id") or unit_dir.name),
                    "family": str(task.get("family") or "")}
    else:
        identity = {"task_id": unit_dir.name, "family": ""}
    entrypoint, _cadence = probe_decl(unit_dir, task)
    doc = _fault("probe-entrypoint-missing", entrypoint=entrypoint, **identity)
    ep_path = unit_dir / entrypoint
    if not ep_path.is_file():
        return doc
    if not Path(ws).is_dir():
        return _fault("workspace-missing", entrypoint=entrypoint, **identity)
    # unit-entrypoint-face mirror: start_new_session so a cap kill takes
    # the whole tree —
    # the candidate shim may have spawned a GUI game as its own child
    try:
        proc = subprocess.Popen(
            [sys.executable, str(ep_path), str(ws)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True)
    except OSError:
        return _fault("probe-spawn-failed", entrypoint=entrypoint, **identity)
    try:
        stdout, _stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.communicate()
        return _fault("probe-timeout", entrypoint=entrypoint, **identity)
    if proc.returncode != 0:
        return _fault(f"probe-crash rc={proc.returncode}",
                      entrypoint=entrypoint, **identity)
    raw, fault = _shim_reading(stdout)
    if raw is None:
        return _fault(fault or "probe-fault", entrypoint=entrypoint,
                      **identity)
    doc = reading(raw.get("scalar"), raw.get("vector"),
                  raw.get("reason") or "ok")
    doc.update({"task_id": identity["task_id"],
                "family": identity["family"],
                "entrypoint": entrypoint})
    return doc


# ---- the ΔV seam (the direction face consumes THIS and nothing else) ------
def _scalar_of(reading_doc) -> float:
    """Fail-closed scalar extraction: anything that is not a reading with
    a usable scalar reads 0.0."""
    if not isinstance(reading_doc, dict):
        return 0.0
    return clamp01(reading_doc.get("scalar"))


def probe_delta(ws, t0_reading, t1_reading) -> float:
    """ΔV = V(s1) - V(s0), the potential-difference arithmetic the
    prices per-step credit with.

    - scalars are clamped into [0, 1] BEFORE the difference, so the
      result is monotone (t1 >= t0 reading-for-reading implies
      delta >= 0) and bounded in [-1.0, 1.0];
    - fail-closed: a missing/garbage/faulted reading contributes its
      fail-closed scalar 0.0 — a broken probe prices work at zero,
      never at a guess;
    - pure arithmetic over the two readings: ``ws`` anchors the
      provenance face of the seam (the consumer's state the readings
      describe) and is deliberately not part of the math.
    """
    return round(_scalar_of(t1_reading) - _scalar_of(t0_reading), 6)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""meta_arms.py — the #524 P0 learning structure: 12 families -> 3 meta-arms,
hierarchical pooling, fingerprint tempering, MC propensity (#523 contract).

Why: 900 state cells x 12 arms starves any budget (#523 simulator: flat
12-arm sampling needs more episodes than we will ever have). Pooling to 3
meta-arms with strong shrinkage makes 30-100 paired instances decisive.
Version fingerprints key the posteriors by environment identity (model,
CLI, worker prompt, checker); a fingerprint change tempers old rows by
LAMBDA (power-prior) — neither reset nor full trust.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from kunglao_log import warn  # canonical fail-open trace (#275)

#: family -> meta-arm. The three meta-arms name the APPROACH class
#: (expert-3 clustering, #523 contract): structural probing, constraint
#: derivation, hypothesis falsification.
META_ARMS: dict[str, str] = {
    "structural-anchoring": "structural-probing",
    "static-decompile": "structural-probing",
    "obfuscation-peeling": "structural-probing",
    "crypto-core-identification": "structural-probing",
    "kdf-chain-reconstruction": "constraint-derivation",
    "dynamic-trace": "constraint-derivation",
    "protocol-flow-reconstruction": "constraint-derivation",
    "anti-analysis-discrimination": "constraint-derivation",
    "hypothesis-falsification": "hypothesis-falsification",
    "replay-harness-verification": "hypothesis-falsification",
    "pair-match-verification": "hypothesis-falsification",
    "red-team-verification": "hypothesis-falsification",
}
META_NAMES: tuple[str, ...] = ("structural-probing",
                               "constraint-derivation",
                               "hypothesis-falsification")
#: power-prior tempering for cross-fingerprint rows (owner-directed range
#: 0.1-0.3; 0.25 is the midpoint — bridge tests can recalibrate)
LAMBDA = 0.25
_FINGERPRINT_CACHE: dict[str, str] = {}


def meta_of(family: str) -> str | None:
    return META_ARMS.get(str(family).strip())


def hierarchical_prior(rows: list[dict], families: list[str],
                       current_fp: str | None = None) -> dict[str, float]:
    """Proposal prior over `families`: meta-level pooling with strong
    shrinkage (#523: meta main effect + arm offset). Dispatch rows only
    (outcome rows never enter any prior). Rows whose fingerprint differs
    from `current_fp` count at LAMBDA weight (power-prior tempering).

    Returns family -> weight. Families of one meta share the pooled meta
    success signal; with no data the prior is uniform (1.0)."""
    meta_succ: dict[str, float] = {m: 0.0 for m in META_NAMES}
    meta_tot: dict[str, float] = {m: 0.0 for m in META_NAMES}
    arm_succ: dict[str, float] = {}
    arm_tot: dict[str, float] = {}
    for r in rows:
        if not isinstance(r, dict) or r.get("credit") is None:
            continue  # pending rows carry no outcome
        fam = str(r.get("method_family") or "")
        meta = meta_of(fam)
        if meta is None:
            continue
        w = 1.0
        row_fp = r.get("fingerprint")
        if current_fp and row_fp and str(row_fp) != current_fp:
            w = LAMBDA
        c = float(r.get("credit"))
        meta_succ[meta] += w * c
        meta_tot[meta] += w
        arm_succ[fam] = arm_succ.get(fam, 0.0) + w * c
        arm_tot[fam] = arm_tot.get(fam, 0.0) + w
    SHRINK = 6.0  # strong shrinkage: the meta effect dominates until an
    # arm has SHRINK effective settled observations of its own
    out: dict[str, float] = {}
    for fam in families:
        meta = meta_of(fam) or META_NAMES[0]
        m_mean = (meta_succ[meta] + 0.5 * 2) / (meta_tot[meta] + 2)
        a_n = arm_tot.get(fam, 0.0)
        a_mean = ((arm_succ.get(fam, 0.0) + 0.5 * 2) / (a_n + 2)
                  if a_n > 0 else m_mean)
        pooled = (SHRINK * m_mean + a_n * a_mean) / (SHRINK + a_n)
        out[fam] = max(0.05, pooled)  # ARM_FLOOR-style exploration floor
    return out


def mc_propensity(rows: list[dict], chosen: str, families: list[str],
                  draws: int = 128, seed: int = 7) -> float:
    """Monte-Carlo estimate of P(this family's posterior sample is the
    max) — the selection propensity logged per dispatch (#524 item 1):
    the doubly-robust OPE raw material. Beta(succ+1, tot-succ+1) per
    family over settled rows; uniform prior when a family has no data."""
    import random  # noqa: PLC0415

    rng = random.Random(seed)
    params: dict[str, tuple[float, float]] = {}
    for fam in families:
        s = t = 0
        for r in rows:
            if (isinstance(r, dict) and r.get("credit") is not None
                    and str(r.get("method_family")) == fam):
                s += float(r.get("credit"))
                t += 1
        params[fam] = (s + 1.0, t - s + 1.0)
    wins = 0
    for _ in range(draws):
        best_v, best_f = -1.0, None
        for fam in families:
            a, b = params[fam]
            v = rng.betavariate(a, b)
            if v > best_v:
                best_v, best_f = v, fam
        if best_f == chosen:
            wins += 1
    return wins / draws


def env_fingerprint(ws, repo: Path | None = None) -> str:
    """Stable environment identity: (model env, claude CLI version,
    worker-agent prompt sha, act-timeout policy). Cached per workspace
    in runs/env-fingerprint.json — the posterior key dimension and the
    tempering discriminator (#524 item 4)."""
    ws = Path(ws)
    cache_p = ws / "runs" / "env-fingerprint.json"
    model = os.environ.get("KUNGLAO_MODEL", "") or os.environ.get(
        "ANTHROPIC_MODEL", "") or "default-model"
    key = model
    if cache_p.is_file():
        try:
            import json  # noqa: PLC0415
            prev = json.loads(cache_p.read_text(encoding="utf-8"))
            if prev.get("key") == key:
                return str(prev["fingerprint"])
        except (OSError, ValueError, KeyError):
            warn("meta_arms.env_fingerprint_cache",
                 "cache unreadable; recomputing")
    cli = "unknown"
    try:
        r = subprocess.run(["claude", "--version"], capture_output=True,
                           text=True, timeout=10, errors="replace")
        if r.returncode == 0 and r.stdout.strip():
            cli = r.stdout.strip().splitlines()[0][:40]
    except (OSError, subprocess.TimeoutExpired) as exc:
        warn("meta_arms.cli_version", f"{type(exc).__name__}: {exc}")
    agent_sha = ""
    repo = repo or Path(__file__).resolve().parents[2]
    for cand in (repo / "agents" / "kunglao-worker.md",
                 repo / ".claude" / "agents" / "kunglao-worker.md"):
        if cand.is_file():
            agent_sha = hashlib.sha256(
                cand.read_bytes()).hexdigest()[:12]
            break
    timeout = os.environ.get("KUNGLAO_E2E_ACT_TIMEOUT_S", "1800")
    fp = hashlib.sha256(
        f"{model}|{cli}|{agent_sha}|{timeout}".encode()
    ).hexdigest()[:12]
    try:
        import json  # noqa: PLC0415
        cache_p.parent.mkdir(parents=True, exist_ok=True)
        cache_p.write_text(json.dumps({"key": key, "fingerprint": fp}),
                           encoding="utf-8")
    except OSError as exc:
        warn("meta_arms.fp_cache_write", f"{type(exc).__name__}: {exc}")
    return fp

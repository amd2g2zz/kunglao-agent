#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rho_verifier.py — #823-P2 rho_t dense progress signal (shadow).

Blueprint 7.2: rho = dense proxy, z = mechanical terminal anchor;
(rho, z_self) pairs accumulate in the ledger and feed Platt calibration.
Pluggable backend: deterministic proxy by default (no LLM, fully green
tests); LLM backend interface activates only via env config, else falls
back. Shadow: sample_and_pair records, nothing intercepts (the P3
"completion claims pass a rho gate" is explicitly out of scope here).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import yaml

import kunglao_log
from kunglao_log import iter_jsonl  # noqa: E402  (#863 Family K single source)

ENV_BACKEND = "KUNGLAO_RHO_BACKEND"
_LEDGER = "runs/logs"
_WORD = re.compile(r"[a-z0-9]+")
_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n?", re.DOTALL)


def _words(text):
    return set(_WORD.findall(text.lower()))


def _load_yaml(path):
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _pq_terms(pqs):
    terms = set()
    for q in pqs:
        if isinstance(q, dict):
            q = (q.get("question") or q.get("q") or str(q))
        terms |= _words(str(q))
    return terms


def _facts_corpus(ws):
    out = set()
    fdir = Path(ws) / "facts"
    if fdir.is_dir():
        for f in sorted(fdir.glob("*.md")):
            try:
                out |= _words(_FRONTMATTER.sub("", f.read_text(
                    encoding="utf-8", errors="replace"), count=1))
            except OSError:
                continue
    return out


def _mission_level(ws):
    """V_m normalised by total PQ weight: 0..1 mission level."""
    led_path = Path(ws) / "runs" / "mission_ledger.yaml"
    led = _load_yaml(led_path)
    pqs = led.get("mission", {}).get("pqs") or []
    if not pqs:
        return None
    total, got = 0.0, 0.0
    n_answered = 0
    n_pqs = len(pqs)
    for p in pqs:
        w = float(p.get("weight", 1.0))
        total += w
        st = p.get("state")
        if st == "answered":
            got += w * float(p.get("coverage", 1.0))
            n_answered += 1
        elif st == "blocked":
            got += 0.3 * w
    if total <= 0:
        return None
    return {"level": max(0.0, min(1.0, got / total)),
            "n_answered": n_answered, "n_pqs": n_pqs}


def get_backend(env=None):
    """Pluggable backend selection: deterministic by default; 'llm' only
    with explicit endpoint env; anything else falls back deterministically
    (tests stay green with zero API)."""
    env = os.environ if env is None else env
    if str(env.get(ENV_BACKEND, "")).strip().lower() == "llm" and \
            os.environ.get("KUNGLAO_RHO_ENDPOINT"):
        try:
            from rho_llm_backend import LlmBackend  # optional module
            return LlmBackend()
        except ImportError:
            pass
    return DeterministicBackend()


class DeterministicBackend:
    """Coverage-delta + lexical progress proxy. No LLM, no API."""

    name = "deterministic"

    def sample(self, ws):
        ws = Path(ws)
        level_info = _mission_level(ws)
        pqs = []
        led = _load_yaml(ws / "runs" / "mission_ledger.yaml")
        for p in led.get("mission", {}).get("pqs") or []:
            q = p.get("question")
            if isinstance(q, dict):
                q = (q.get("question") or q.get("q") or str(q))
            pqs.append(q)
        corpus = _facts_corpus(ws)
        terms = _pq_terms(pqs)
        lexical = (len(terms & corpus) / len(terms)) if terms else 0.0
        level = level_info["level"] if level_info else 0.0
        rho = max(0.0, min(1.0, 0.6 * level + 0.4 * lexical))
        return {"rho": round(rho, 4), "backend": self.name,
                "level": round(level, 4), "lexical": round(lexical, 4)}


class LlmBackend:
    """LLM-as-a-Verifier interface (arXiv:2607.05391). Prompt/response
    contract already mechanical (rho_checkpoint.parse_verifier_response).
    Enabled only when env selects it AND a runner is configured; otherwise
    get_backend() never constructs this class."""

    name = "llm"

    def sample(self, ws):
        raise NotImplementedError(
            "LlmBackend requires KUNGLAO_RHO_ENDPOINT + runner; configure "
            "or unset " + ENV_BACKEND)


def sample_and_pair(ws, z=None):
    """Checkpoint sampling: rho_t paired with the mechanical terminal
    anchor z (1.0 mission complete / 0.0 mission failed / None pending).
    Shadow: emits one ledger row (action=rho_pair, #818 schema), nothing
    else. Never-raises: any failure degrades to a silent no-signal row? No
    -- silent = dishonest; failures propagate to the caller's shadow cage."""
    out = get_backend().sample(ws)
    mission = _mission_level(ws)
    if z is None and mission and mission.get("n_pqs") and \
            mission["n_answered"] == mission["n_pqs"]:
        z = 1.0
    # #873: rho_pair 携带真实 cost——cost_events.jsonl 最新 amount
    # （会话累计口径，与 cost_gate 解析一致）。缺源时置 None 不阻断采样；
    # 学费曲线只认有 cost 的行（duration 代理已废）。
    try:
        from tuition_curve import cost_state
        cost = cost_state(ws)["latest"]
    except Exception:  # noqa: BLE001 — cost 缺源不阻断采样
        cost = None
    kunglao_log.emit(
        Path(ws), actor="rho_verifier", action="rho_pair",
        detail=json.dumps({"rho": out["rho"], "z": z,
                           "backend": out["backend"],
                           "level": out.get("level"),
                           "lexical": out.get("lexical"),
                           "cost": cost},
                          ensure_ascii=False))
    # #58 S2b: the SETTLED checkpoint face (z is not None = the mechanical
    # terminal anchor fired: mission complete/failed) is a transition, so it
    # earns a result digest; plain per-checkpoint sampling rows stay lean
    # (no per-heartbeat spam).
    if z is not None:
        kunglao_log.emit_result_digest(
            Path(ws), actor="rho_verifier",
            verdict="mission_complete" if float(z) >= 1.0 else "mission_failed",
            exit=0)
    # #873: per-checkpoint 座舱持久化 — V/D/ETA + burn 面与 rho_pair 同节奏
    # 落账，座舱渲染/学费重放可仅凭 ledger 离线重建趋势。shadow 持久化
    # 失败不阻塞采样面（fail-open），与 rho_pair 的传播语义分层。
    try:
        import cost_gate
        import tuition_curve
        cs = tuition_curve.cockpit_summary(Path(ws))
        events = cost_gate.load_events(Path(ws))
        kunglao_log.emit(
            Path(ws), actor="rho_verifier", action="cockpit_sample",
            detail=json.dumps({**cs, "cost_spent": cost,
                               "n_cost_events": len(events)},
                              ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001 — 持久化永不破坏采样
        pass
    out["z"] = z
    return out


def pairs_from_ledger(ws):
    """Replay settled (score, outcome) pairs from ledger rho_pair rows."""
    ws = Path(ws)
    pairs = []
    for p in sorted((ws / _LEDGER).glob("kunglao-*.jsonl")):
        for r in iter_jsonl(p.read_text(encoding="utf-8").splitlines()):
            if r.get("action") != "rho_pair":
                continue
            try:
                d = r.get("detail")
                if isinstance(d, str):
                    d = json.loads(d)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(d, dict) and d.get("z") is not None:
                pairs.append({"score": float(d["rho"]),
                              "outcome": float(d["z"])})
    return pairs


def fit_platt(pairs):
    """Single-source re-export (rho_checkpoint.fit_platt)."""
    from rho_checkpoint import fit_platt as _fit
    return _fit(pairs)


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)

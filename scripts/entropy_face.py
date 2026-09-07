# -*- coding: utf-8 -*-
"""entropy_face.py — THE entropy-honesty face, single-source (#142 follow-up).

Owner design principle (dual-use display): every displayed metric must be
consumed by agent decisions AND informative to humans — a display-only
metric is decoration. This module owns the frontier PQ categorical entropy
and its trend so the two faces read THE SAME computed values:

  - display face   — scripts/statusline_snapshot.py renders ``H1.3b`` from
    ``face(ws)`` inside the snapshot (the renderer stays a dumb view);
  - decision face  — scripts/heartbeat_tick.py carries ``h_bits``/``h_pq``/
    ``h_trend`` in the tick report (runs/.heartbeat-tick.json); the future
    policy/strategy arbiter reads the same module, never a re-computation.

The trend baseline is the PREVIOUS STORED snapshot value
(``runs/.kunglao-statusline.json`` → ``h_bits``): one stored history, no
second trend ledger. Frontier = the mission ledger's first non-answered
PQ; a frontier without a posterior falls back to the deterministic
max-entropy PQ. Fail-open everywhere: an empty/unreadable posterior ledger
is ``h_bits=None`` / ``trend="unknown"``, never an exception.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

SNAPSHOT_REL = Path("runs") / ".kunglao-statusline.json"

# |ΔH| below this is flat — entropy only moves on posterior updates, so
# float noise must never flip the gear-shift signal.
TREND_EPS = 1e-6

TREND_FALLING = "falling"   # learning (green face)
TREND_RISING = "rising"     # luck/fake-progress alert (red face)
TREND_FLAT = "flat"         # stall-suspect (amber face)
TREND_UNKNOWN = "unknown"


def prev_h_bits(ws: Path) -> float | None:
    """The trend baseline: h_bits from the previous stored snapshot. None on
    missing/corrupt file (first observation — nothing to compare yet)."""
    try:
        prev = json.loads((Path(ws) / SNAPSHOT_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    h = prev.get("h_bits") if isinstance(prev, dict) else None
    return float(h) if isinstance(h, (int, float)) else None


def frontier_pq_id(ws: Path) -> str | None:
    """任务前沿 = mission_ledger PQ 序里第一个未 answered 的 PQ id。
    读失败/全答 -> None（调用方回退 max-entropy 或缺省）。"""
    try:
        led = yaml.safe_load((Path(ws) / "runs" / "mission_ledger.yaml")
                             .read_text(encoding="utf-8")) or {}
        for p in (led.get("mission", {}) or {}).get("pqs") or []:
            if not isinstance(p, dict):
                continue
            if str(p.get("state") or "") != "answered":
                return str(p.get("id")) if p.get("id") is not None else None
    except (OSError, yaml.YAMLError, TypeError):
        pass
    return None


def frontier_entropy(ws: Path) -> tuple[float | None, str | None]:
    """Frontier PQ categorical entropy in bits (posteriors.PQCategorical).
    Frontier without a posterior -> deterministic max-entropy PQ fallback;
    empty/unreadable ledger -> (None, None)."""
    try:
        from posteriors import PosteriorLedger
        led = PosteriorLedger.load(ws)
        if not led.pqs:
            return None, None
        frontier_id = frontier_pq_id(ws)
        pq = led.pqs.get(frontier_id) if frontier_id is not None else None
        if pq is None:
            pq = max(led.pqs.values(), key=lambda p: p.entropy())
        return round(pq.entropy(), 4), pq.pq_id
    except Exception:  # noqa: BLE001 — a face never breaks its caller
        return None, None


def trend(h_bits: float | None, prev_h: float | None) -> str:
    """Entropy trend vs the previous stored value:
    falling / flat / rising / unknown."""
    if not isinstance(h_bits, (int, float)):
        return TREND_UNKNOWN
    if not isinstance(prev_h, (int, float)):
        return TREND_UNKNOWN
    delta = float(h_bits) - float(prev_h)
    if delta < -TREND_EPS:
        return TREND_FALLING
    if delta > TREND_EPS:
        return TREND_RISING
    return TREND_FLAT


def face(ws: Path, prev: dict | None = None) -> dict:
    """THE single-source face: ``{"h_bits", "h_pq", "h_trend"}``.

    ``prev`` is the previous snapshot dict when the caller already read it
    (the snapshot writer has); otherwise the stored snapshot is read here
    (the tick report face). Both routes share this one computation.
    """
    h_bits, h_pq = frontier_entropy(ws)
    if prev is None:
        prev_h = prev_h_bits(ws)
    else:
        prev_h = prev.get("h_bits") if isinstance(prev, dict) else None
        prev_h = float(prev_h) if isinstance(prev_h, (int, float)) else None
    return {"h_bits": h_bits, "h_pq": h_pq,
            "h_trend": trend(h_bits, prev_h)}

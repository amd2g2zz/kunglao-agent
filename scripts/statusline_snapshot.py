#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""statusline_snapshot.py — #883 statusline 健康段数据面（快照解耦）.

THE architectural decision (issue #883, refined #142): kunglao logic never
enters Node. This module pre-writes ONE snapshot file per SEMANTIC EVENT
(``runs/.kunglao-statusline.json`` — tool use via hooks/heartbeat_touch,
plus tick-hosted settlement/rollup: heartbeat_tick writes right after its
settlement block) and the repo's
statusline_render.mjs only reads it (O(1), zero spawn). EVENT-DRIVEN
WRITES: if nothing happened, nothing changed — a stale snapshot during
idle is TRUTHFUL, so there is no tick-cadence refresh (the 5-min tick
keeps monitoring/breaker duties but is not a display dependency).
Watchdog: the renderer judges idle-vs-dead from the liveness policy —
mtime within HEARTBEAT_STALE_MINUTES with no events = the state machine's
own dim-blue-gray idle face;
beyond policy, or this module's own probe-driven "down" verdict = DOWN.
Never self-reported; always disk-observed.

Three planes, all pure disk observation (看门狗原则：磁盘观测，永不
self-report):

  1. Probe registry (``PROBES``) — every entry carries
     {id, dimension, probe, threshold, unit, staleness_budget, severity,
     short_code}. 不入册不显示；无 staleness_budget 不许上线 (guard-tested);
     probes are read-only + fail-open. Two declared-but-inert slots
     (unattributed_rate / backtrack_lag) wait for #879/#882 data sources.
  2. Semantic state machine — analyzing / toss / idle / stall / down /
     flawless, precedence down > flawless > stall > toss > analyzing > idle,
     with probe short codes ([ledger]/[hook]/[stall]/[audit]) overlaying the
     triage line: 见红即知看哪个文件.
  3. Snapshot writer — atomic write (tmp + replace, heartbeat_touch F2
     discipline); flash triggers (milestone crossings / every-N-ticks /
     state change / claim completion) are DETECTED here and shipped as
     {seq, ts, text}; the 5s fade window itself is Node-side render-clock
     scheduling.

Data sources are all pre-existing pipes (零新管道): mission_ledger (PQ
coverage / V_m history), tuition_curve._slope (d_slope -> eta), claim
register (OPEN count), noop breaker (stall fingerprint, #634), heartbeat
file mtime (alive, #534/#754), ledger tail (activity rate + sparks,
#459), hooks_selfcheck's registry constants (deployed, #381/#258).

#142 (statusline v2, schema 2) — the snapshot becomes the SINGLE data
owner for the whole kunglao segment (producer-owned data): it gains
``v_hist`` (last ~8 v_norm points — the sparkline), ``h_bits``/``h_pq``/
``h_trend`` (frontier PQ categorical entropy from runs/posteriors.yaml
via scripts/posteriors.py PQCategorical.entropy; trend vs the previous
stored value — SINGLE-SOURCED in scripts/entropy_face.py so the heartbeat
tick report face and the future policy/strategy arbiter read the SAME
computed values this snapshot renders; dual-use display, no decoration),
``health{oracle,retro,dormant}`` (#473 oracle marker check /
retro lag < 8 / #127 no DORMANT detectors), ``now{claim,op}`` (active
worker from the lib_kunglao worker-status scan; op is a <=24-char task
phrase), ``pq_rows`` + ``difficulty`` (the fine-grained PQ collection
the external renderer used to read DIRECTLY from rl-signals.jsonl — a
zero-spawn contract violation; that read is gone), and named phase-2
placeholder slots (``v_oracle_gap`` #133, ``baseline_inv_k`` #129) so
the renderer never changes twice.

Usage: python statusline_snapshot.py <workspace>
(attached from the heartbeat_touch per-tool-use path and from
heartbeat_tick's post-settlement step — event-driven writes, #142
refinement. Fail-open everywhere.)
"""
from __future__ import annotations

import json
import os
import re
import sys
import datetime
from pathlib import Path

import yaml

# #863 Family C: workspace resolution is single-sourced in ws_layout
# (the #228 strict family: arg wins, probe, exit 2 — never guess).
from ws_layout import resolve_strict as _resolve_ws

# #597: staleness constants are single-sourced in liveness_policy.
from liveness_policy import HEARTBEAT_STALE_MINUTES, TICK_INTERVAL_DEFAULT_MIN

# #142 follow-up: the entropy-honesty face is single-sourced in
# entropy_face (display + decision faces share one computation).
from entropy_face import face as _entropy_face

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/ root
# #142 follow-up: the snapshot path is single-sourced in entropy_face (the
# trend-baseline reader owns the constant; the writer reuses it — no twin).
from entropy_face import SNAPSHOT_REL

# #142: snapshot schema version — 2 adds the producer-owned v2 fields
# (v_hist / h_bits / h_trend / health / now / pq_rows / difficulty and the
# phase-2 placeholder slots). No-backcompat policy: readers probe the field
# set, never a version ladder.
SCHEMA_VERSION = 2

TICK_MINUTES = TICK_INTERVAL_DEFAULT_MIN          # 5 — elapsed/eta wall bridge
LEDGER_STALE_MINUTES = 90                          # ledger tail alive budget
TOSS_WINDOW_S = 120                                # dispatch -> toss window
STALL_TICKS_DEFAULT = 6                            # mirrors noop breaker (#634)
ACTIVITY_WINDOW_S = 300                            # recent-events window (1 tick)
AUDIT_STALE_MINUTES = 60                           # audit age WARN line
D_SLOPE_NOMINAL = 0.05                             # healthy settle rate / tick
FLASH_EVERY_N_TICKS = 10                           # periodic flash cadence
MILESTONES = (0.25, 0.50, 0.75)
LEDGER_TAIL_BYTES = 65_536                         # bounded O(64KB) tail read
# #882 probe thresholds (the cockpit trio's WARN lines)
BACKTRACK_LAG_WARN = 8                             # settlements since retro
UNATTRIBUTED_RATE_WARN = 0.30                      # unattributed fraction
# #142 v2 fields
V_HIST_POINTS = 8                                  # sparkline window (~8 points)
NOW_OP_MAX_CHARS = 24                              # task-chip phrase budget
# Display-only worker-status field extraction (kunglao_status precedent:
# NOT liveness parsing — liveness stays in lib_kunglao's protocol owners).
_CLAIM_RE = re.compile(r"claim\s*:?\s+([A-Za-z0-9][\w.-]*)")
_STEP_RE = re.compile(r"step\s*:?\s+([^|\n]+)")

# Color semantics are COMPUTED Python-side (kunglao logic stays out of Node);
# Node only interpolates brightness on its render clock (breathing) and ramps
# hue over 200ms on state changes.
STATE_COLORS = {
    "analyzing": {"hue": 140, "sat": 72, "light": 55},   # green: 气
    "toss": {"hue": 190, "sat": 70, "light": 60},        # cyan: in-flight dispatch
    "idle": {"hue": 220, "sat": 30, "light": 40},        # dim blue-gray: 常暗
    "stall": {"hue": 45, "sat": 85, "light": 55},        # yellow: 滞
    "down": {"hue": 0, "sat": 80, "light": 50},          # red: 厥 — no animation
    "flawless": {"hue": 48, "sat": 90, "light": 58},     # gold
}

# open/terminal claim status vocabulary (claim-register.yaml); failed claims
# block flawless.
_OPEN_STATUSES = {"OPEN", "IN_PROGRESS", "PARTIALLY-VERIFIED"}
_FAILED_STATUSES = {"REFUTED", "FAILED", "FALSIFIED"}

# Deployed probe disk candidates for hook files (override seam for tests:
# tests monkeypatch this module global to a fixture hook dir).
_hook_candidates: list | None = None

try:  # #381: the registry is the declaration source of truth for hooks
    from wire_up_settings import WIRE_UP_HOOK_FILES
except Exception:  # pragma: no cover — registry drift must not kill the writer
    WIRE_UP_HOOK_FILES = frozenset()

try:
    # Deployed probe checks the KONG liveness-chain subset (mirrors
    # hooks_selfcheck._KONG_CHAIN_FILES; import-time derive validates drift).
    from hooks_selfcheck import KONG_HOOK_FILES as _DEPLOYED_HOOK_FILES
except Exception:  # pragma: no cover
    _DEPLOYED_HOOK_FILES = ["heartbeat_touch.py", "worker_budget.py",
                            "dispatch_gate.py", "worker_pulse.py"]


# ---------------------------------------------------------------------------
# probe registry (v1)
# ---------------------------------------------------------------------------

PROBES: list[dict] = [
    {"id": "heartbeat_mtime", "dimension": "alive",
     "probe": "probe_heartbeat_mtime", "threshold": HEARTBEAT_STALE_MINUTES,
     "unit": "wall", "staleness_budget": f"{HEARTBEAT_STALE_MINUTES}m",
     "severity": "HARD", "short_code": "[ledger]", "enabled": True,
     "detail": "runs/.heartbeat.json mtime (heartbeat_touch producer)"},
    {"id": "ledger_tail", "dimension": "alive",
     "probe": "probe_ledger_tail", "threshold": LEDGER_STALE_MINUTES,
     "unit": "wall", "staleness_budget": f"{LEDGER_STALE_MINUTES}m",
     "severity": "HARD", "short_code": "[ledger]", "enabled": True,
     "detail": "runs/logs/kunglao-*.jsonl tail mtime; absent file fails open"},
    {"id": "hooks_declared_vs_disk", "dimension": "deployed",
     "probe": "probe_hooks_declared", "threshold": None,
     "unit": "tick", "staleness_budget": "1 tick",
     "severity": "WARN", "short_code": "[hook]", "enabled": True,
     "detail": "WIRE_UP_HOOK_FILES declared in project settings vs on disk"},
    {"id": "stall_fingerprint", "dimension": "moving",
     "probe": "probe_stall", "threshold": STALL_TICKS_DEFAULT,
     "unit": "tick", "staleness_budget": "1 tick",
     "severity": "WARN", "short_code": "[stall]", "enabled": True,
     "detail": "noop breaker consecutive_noop >= K with OPEN claims"},
    {"id": "audit_age", "dimension": "audit",
     "probe": "probe_audit_age", "threshold": AUDIT_STALE_MINUTES,
     "unit": "wall", "staleness_budget": "-",
     "severity": "WARN", "short_code": "[audit]", "enabled": True,
     "detail": "audit-grade artifact age (runs/.hooks-selfcheck.json) — "
               "displayed as age, never presented as real-time"},
    # ---- #882: the two slots go live (data sources landed #879/#882) ----
    {"id": "unattributed_rate", "dimension": "moving",
     "probe": "probe_unattributed_rate", "threshold": UNATTRIBUTED_RATE_WARN,
     "unit": "tick", "staleness_budget": "1 tick",
     "severity": "WARN", "short_code": "[stall]", "enabled": True,
     "detail": "#879 trace identity: ledger rows with null trace_id "
               "(kunglao_log.unattributed_rate)"},
    {"id": "backtrack_lag", "dimension": "moving",
     "probe": "probe_backtrack_lag", "threshold": BACKTRACK_LAG_WARN,
     "unit": "tick", "staleness_budget": "1 tick",
     "severity": "WARN", "short_code": "[stall]", "enabled": True,
     "detail": "#882 backtrack loop: settlements since the last policy "
               "retro (runs/.retro-state.json)"},
    # ---- #878: the scheduler registry's own health line ------------------
    {"id": "mechanism_health", "dimension": "moving",
     "probe": "probe_mechanism_health", "threshold": None,
     "unit": "tick", "staleness_budget": "1 tick",
     "severity": "WARN", "short_code": "[mech]", "enabled": True,
     "detail": "#878 scheduler registry: any mechanism whose last run "
               "failed (last_rc not in {0, null}) — runs/.mechanisms-state.json"},
]


from harness_common import utc_now_z as utc_now  # #863 Family F: single source (was a local def)


def _parse_ts(value: str) -> float | None:
    """ISO8601 Z -> epoch seconds; None on anything unparseable (fail-open)."""
    try:
        return datetime.datetime.fromisoformat(
            str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OSError):
        return None


# ---------------------------------------------------------------------------
# probes (read-only, fail-open)
# ---------------------------------------------------------------------------

def _detail(probe_entry: dict, ok: bool, text: str,
            severity: str | None = None) -> dict:
    return {"id": probe_entry["id"], "dimension": probe_entry["dimension"],
            "severity": severity or probe_entry["severity"],
            "short_code": probe_entry["short_code"],
            "ok": ok, "detail": text}


def probe_heartbeat_mtime(ws: Path, entry: dict) -> dict:
    """alive 主探针：runs/.heartbeat.json mtime（heartbeat_touch 生产者）。"""
    hb = ws / "runs" / ".heartbeat.json"
    try:
        age_s = max(0.0, datetime.datetime.now(
            datetime.timezone.utc).timestamp() - hb.stat().st_mtime)
    except OSError:
        return _detail(entry, False, "heartbeat file missing (never touched)")
    budget = (entry["threshold"] or 0) * 60
    if age_s > budget:
        return _detail(entry, False,
                       f"heartbeat stale {int(age_s // 60)}min "
                       f"> budget {entry['threshold']}min")
    return _detail(entry, True, f"heartbeat fresh ({int(age_s // 60)}min)")


def probe_ledger_tail(ws: Path, entry: dict) -> dict:
    """账本尾部追加探针：最新 kunglao-*.jsonl mtime。缺文件 fail-open（无
    事件可观测 ≠ 死亡——idle workspace 合法安静）。"""
    logs = ws / "runs" / "logs"
    try:
        latest = max((p for p in logs.glob("kunglao-*.jsonl")
                      if p.is_file()), key=lambda p: p.stat().st_mtime,
                     default=None)
    except OSError:
        return _detail(entry, True, "ledger unreadable (fail-open)")
    if latest is None:
        return _detail(entry, True, "no ledger yet (fail-open)")
    age_min = (datetime.datetime.now(datetime.timezone.utc).timestamp()
               - latest.stat().st_mtime) / 60
    if age_min > (entry["threshold"] or 0):
        return _detail(entry, False,
                       f"ledger tail quiet {int(age_min)}min "
                       f"> {entry['threshold']}min")
    return _detail(entry, True, f"ledger tail fresh ({int(age_min)}min)")


def _declared_path(cmds: list[str], hf: str) -> str | None:
    """The path the DECLARED command actually points at (build_hook_entry
    shape: `... uv run --project <root> <dir>/<hf>` -> last whitespace token
    ending in /hf). None when the path carries spaces the tokenizer cannot
    split (fail-open to the candidate dirs below)."""
    for c in cmds:
        if hf not in c:
            continue
        for tok in c.split():
            if tok.endswith("/" + hf) or tok.endswith("\\" + hf) or tok == hf:
                return tok
    return None


def probe_hooks_declared(ws: Path, entry: dict) -> dict:
    """deployed 探针（只读自算——hooks_selfcheck 会 auto-rebuild，其报告永远
    看不到故障窗口，不能作为本探针数据源）：
      - registry 文件未声明进 project settings → WARN（可自愈）
      - 声明了但声明路径/部署目录无文件 → HARD
    (#258 deployment contract: <ws>/.claude/hooks is THE deployment target;
    the repo hooks/ dir is the source, not a deployed copy.)
    """
    settings = ws / ".claude" / "settings.json"
    cmds: list[str] = []
    try:
        s = json.loads(settings.read_text(encoding="utf-8"))
        for entries in (s.get("hooks") or {}).values():
            if not isinstance(entries, list):
                continue
            for e in entries:
                for h in (e.get("hooks") or []):
                    c = h.get("command", "")
                    if isinstance(c, str):
                        cmds.append(c)
    except (OSError, ValueError):
        pass  # unreadable settings == nothing declared
    # test seam: module global overrides the deployment-dir candidates
    candidates = [Path(d) for d in (_hook_candidates
                                    or [ws / ".claude" / "hooks"])]
    undeclared, missing_file = [], []
    for hf in sorted(_DEPLOYED_HOOK_FILES):
        declared = any(hf in c for c in cmds)
        if not declared:
            undeclared.append(hf)
            continue
        declared_path = _declared_path(cmds, hf)
        on_disk = (bool(declared_path) and Path(declared_path).exists()) or any(
            (d / hf).exists() for d in candidates)
        if not on_disk:
            missing_file.append(hf)
    if missing_file:
        return _detail(entry, False,
                       f"HARD declared-but-missing-file: "
                       f"{', '.join(missing_file[:4])}", severity="HARD")
    if undeclared:
        return _detail(entry, False,
                       f"WARN undeclared in project settings: "
                       f"{', '.join(undeclared[:4])}")
    return _detail(entry, True,
                   f"all {len(_DEPLOYED_HOOK_FILES)} chain hooks declared+on disk")


def probe_stall(ws: Path, entry: dict, *, open_claims: int = 0) -> dict:
    """moving 探针：#634 noop breaker 的 consecutive_noop ≥ K 且有 OPEN claim
    （状态指纹 K tick 不动 = 没进展）。无 OPEN claim 的静止是诚实 idle。"""
    try:
        prev = json.loads((ws / "runs" / ".heartbeat-noop.json")
                          .read_text(encoding="utf-8"))
        noop = int(prev.get("count", 0))
    except (OSError, ValueError):
        noop = 0
    if noop >= (entry["threshold"] or STALL_TICKS_DEFAULT) and open_claims > 0:
        return _detail(entry, False,
                       f"stall fingerprint: {noop} consecutive no-op ticks, "
                       f"{open_claims} OPEN claim(s)")
    return _detail(entry, True, f"moving (noop={noop}, open={open_claims})")


def probe_audit_age(ws: Path, entry: dict) -> dict:
    """audit 维度：审计级工件年龄——显示年龄，不冒充实时。缺工件 fail-open。"""
    p = ws / "runs" / ".hooks-selfcheck.json"
    try:
        age_min = (datetime.datetime.now(datetime.timezone.utc).timestamp()
                   - p.stat().st_mtime) / 60
    except OSError:
        return _detail(entry, True, "no audit artifact yet (fail-open)")
    if age_min > (entry["threshold"] or AUDIT_STALE_MINUTES):
        return _detail(entry, False,
                       f"audit stale {int(age_min)}min > "
                       f"{entry['threshold']}min")
    return _detail(entry, True, f"audit age {int(age_min)}min")


def probe_unattributed_rate(ws: Path, entry: dict) -> dict:
    """#882 moving 探针（#879 数据源上线）：未归因率 = 无 trace_id 行占比。
    数据源 kunglao_log.unattributed_rate；读失败 fail-open（ok）。"""
    rate = None
    try:
        import kunglao_log
        rate = float(kunglao_log.unattributed_rate(ws).get("rate") or 0.0)
    except Exception:  # noqa: BLE001 — a probe never kills the tick
        return _detail(entry, True, "unattributed rate unavailable (fail-open)")
    threshold = entry["threshold"] or UNATTRIBUTED_RATE_WARN
    if rate > threshold:
        return _detail(entry, False,
                       f"unattributed_rate {rate:.2f} > {threshold:.2f} "
                       "(legacy rows outrun the trace chain)")
    return _detail(entry, True, f"unattributed_rate {rate:.2f} ok")


def probe_backtrack_lag(ws: Path, entry: dict) -> dict:
    """#882 moving 探针：回溯滞后 = 自上次策略回溯以来的结算数
    (runs/.retro-state.json，backtrack_loop 维护)。读失败 fail-open。"""
    try:
        from backtrack_loop import lag
        l = lag(ws)
    except Exception:  # noqa: BLE001 — a probe never kills the tick
        return _detail(entry, True, "backtrack lag unavailable (fail-open)")
    threshold = entry["threshold"] or BACKTRACK_LAG_WARN
    if l > threshold:
        return _detail(entry, False,
                       f"backtrack lag {l} > {threshold} settlements "
                       "since the last policy retro")
    return _detail(entry, True, f"backtrack lag {l} ok")


def probe_mechanism_health(ws: Path, entry: dict) -> dict:
    """#878 moving probe: scheduler-registered mechanisms must run clean —
    any last_rc outside {0, null} flags the failing mechanism by name
    (见红即知看哪个文件: runs/.mechanisms-state.json). Fail-open like every
    probe: a missing/unreadable state file is "no fault evidence", not down."""
    try:
        from mechanism_scheduler import mechanisms_health
        bad = mechanisms_health(ws)
    except Exception as exc:  # noqa: BLE001 — a probe never kills the tick
        return _detail(entry, True,
                       f"mechanism health unavailable (fail-open): {exc}")
    if bad:
        return _detail(entry, False,
                       "mechanism failure(s): " + ", ".join(bad[:4]))
    return _detail(entry, True, "all scheduler mechanisms clean")


def _make_run_probe(registry: list[dict]):
    """Registry-driven executor factory: a newly DECLARED probe wires itself
    in with zero writer-code change (acceptance: 新探针声明即接入)."""
    def run(ws: Path, ctx: dict) -> list[dict]:
        out = []
        for entry in registry:
            if not entry.get("enabled", True):
                continue  # slots are inert until their data source lands
            fn_name = entry.get("probe")
            fn = globals().get(fn_name) if fn_name else None
            if fn is None:
                # Declaration wires the probe into the snapshot pipeline even
                # before its fn lands (acceptance: 新探针声明即接入); it
                # reports no fault (fail-open) until implemented.
                out.append(_detail(entry, True,
                                   "declared (probe fn not implemented — "
                                   "fail-open)"))
                continue
            try:
                if fn is probe_stall:
                    out.append(fn(ws, entry,
                                  open_claims=ctx.get("open_claims", 0)))
                else:
                    out.append(fn(ws, entry))
            except Exception as exc:  # fail-open: a probe never kills the tick
                out.append(_detail(entry, True, f"probe error (fail-open): {exc}"))
        return out
    return run


def run_probe(ws: Path, ctx: dict) -> list[dict]:
    return _make_run_probe(PROBES)(ws, ctx)


# ---------------------------------------------------------------------------
# data plane (all pre-existing pipes)
# ---------------------------------------------------------------------------

def _claims_state(ws: Path) -> tuple[int, int]:
    """claim-register.yaml -> (open_count, failed_count). Fail-open -> (0,0)."""
    try:
        reg = yaml.safe_load((ws / "claim-register.yaml")
                             .read_text(encoding="utf-8")) or {}
        claims = reg.get("claims") or []
        open_n = sum(1 for c in claims
                     if str(c.get("status") or "").upper() in _OPEN_STATUSES)
        failed_n = sum(1 for c in claims
                       if str(c.get("status") or "").upper() in _FAILED_STATUSES)
        return open_n, failed_n
    except (OSError, yaml.YAMLError):
        return 0, 0


def _mission_state(ws: Path) -> dict:
    """mission_ledger.yaml -> PQ coverage + V_m/d_slope/eta + elapsed ticks.

    #10: v_norm / d_slope_norm ride alongside the raw fields — normalized
    value in [0,1] (v_m / total PQ weight) and the per-settlement-round
    rate on the normalized history (one history point == one round; no
    wall-clock in the density). eta_ticks extrapolates from the normalized
    series (same numbers under stable weights; scale-free after repin).
    """
    from tuition_curve import _norm_series, _slope
    out = {"answered": 0, "blocked": 0, "unattempted": 0, "total": 0,
           "coverage": 0.0, "v_m": 0.0, "v_norm": 0.0,
           "d_slope": 0.0, "d_slope_norm": 0.0, "eta_ticks": None,
           "elapsed_ticks": 0, "started_ts": None, "v_hist": []}
    try:
        led = yaml.safe_load((ws / "runs" / "mission_ledger.yaml")
                             .read_text(encoding="utf-8")) or {}
        pqs = led.get("mission", {}).get("pqs") or []
        hist = led.get("mission", {}).get("history") or []
        vm_hist = [float(h.get("v_m", 0.0)) for h in hist
                   if isinstance(h, dict) and "v_m" in h]
        total_w = sum(float(p.get("weight", 1.0)) for p in pqs)
        norm = _norm_series(hist, total_w)
        out["answered"] = sum(1 for p in pqs if p.get("state") == "answered")
        out["blocked"] = sum(1 for p in pqs if p.get("state") == "blocked")
        out["unattempted"] = sum(1 for p in pqs
                                 if p.get("state") == "unattempted")
        out["total"] = len(pqs)
        if out["total"]:
            out["coverage"] = round(out["answered"] / out["total"], 4)
        if vm_hist:
            out["v_m"] = round(vm_hist[-1], 6)
            slope = _slope(vm_hist[-5:])
            out["d_slope"] = round(slope, 6)
            if norm:
                out["v_norm"] = round(norm[-1], 6)
                out["v_hist"] = [round(x, 6) for x in norm[-V_HIST_POINTS:]]
                norm_slope = _slope(norm[-5:])
                out["d_slope_norm"] = round(norm_slope, 6)
                out["eta_ticks"] = (round((1.0 - norm[-1]) / norm_slope, 2)
                                    if norm_slope > 0 else None)
            out["elapsed_ticks"] = len(vm_hist)
            first_ts = hist[0].get("ts") if isinstance(hist[0], dict) else None
            out["started_ts"] = first_ts
    except (OSError, yaml.YAMLError, TypeError, ValueError):
        pass  # no/old ledger -> zeros (idle-dim workspace)
    return out


def _ledger_rows(ws: Path) -> list[dict]:
    """账本尾部（末 64KB 有界读）-> 已解析行。首行可能残缺，丢弃。"""
    logs = ws / "runs" / "logs"
    try:
        latest = max((p for p in logs.glob("kunglao-*.jsonl") if p.is_file()),
                     key=lambda p: p.stat().st_mtime, default=None)
        if latest is None:
            return []
        with latest.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - LEDGER_TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = tail.splitlines()
    if len(lines) > 1:
        lines = lines[1:]  # drop possibly-partial first line
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _ledger_activity(ws: Path, now_s: float) -> dict:
    """账本尾部 -> 近窗事件数 + 最近 dispatch 是否在 toss 窗口。"""
    rows = _ledger_rows(ws)
    recent = 0
    toss = False
    for row in rows:
        ts = _parse_ts(row.get("ts"))
        if ts is not None and now_s - ts <= ACTIVITY_WINDOW_S:
            recent += 1
        if (row.get("action") == "dispatch" and ts is not None
                and now_s - ts <= TOSS_WINDOW_S):
            toss = True
    return {"events_recent": recent,
            "spark_count": min(3, recent),  # sparks: event density, capped
            "toss": toss}


# ---------------------------------------------------------------------------
# #142 v2 data plane (producer-owned: the renderer never reads raw logs)
# ---------------------------------------------------------------------------

# The entropy-honesty badge is SINGLE-SOURCED in scripts/entropy_face.py
# (#142 follow-up, dual-use display): the snapshot face and the heartbeat
# tick report face read the SAME computed {h_bits, h_pq, h_trend} — no
# second computation lives here anymore.


def _health_oracle(ws: Path) -> bool:
    """>#473 门电力面：task-oracle.yaml 已注册（init skeleton marker 不算）。
    Single-sourced on heartbeat_tick._oracle_registered（lazy import —
    heartbeat_tick 反向只在 main() 内 lazy import 本模块，无环）。"""
    try:
        from heartbeat_tick import _oracle_registered
        return bool(_oracle_registered(ws))
    except Exception:  # noqa: BLE001 — a probe never kills the tick
        return False


def _health_retro(ws: Path) -> bool:
    """retro 滞后健康 = settlements since retro < 8（runs/.retro-state.json）。
    读失败 fail-open（无故障证据 != 故障）。"""
    try:
        from backtrack_loop import lag
        return lag(ws) < BACKTRACK_LAG_WARN
    except Exception:  # noqa: BLE001 — a probe never kills the tick
        return True


def _health_dormant(ws: Path) -> bool:
    """>#127 liveness face：无 DORMANT 探测器（evaluated, never fired）。
    读失败 fail-open。"""
    try:
        from detector_liveness import liveness_report
        return not liveness_report(ws).get("dormant")
    except Exception:  # noqa: BLE001 — a probe never kills the tick
        return True


def _health(ws: Path) -> dict:
    """#142 三颗健康点：oracle 已注册 / retro 滞后 < 8 / 无 DORMANT。"""
    return {"oracle": _health_oracle(ws), "retro": _health_retro(ws),
            "dormant": _health_dormant(ws)}


def _last_dispatch_claim(ws: Path) -> str | None:
    """>parked 状态的 `last C-<id>`：账本尾部逆序第一条带 claim 的行。"""
    for row in reversed(_ledger_rows(ws)):
        claim = row.get("claim")
        if isinstance(claim, str) and claim.strip():
            return claim.strip()
    return None


def _now_chip(ws: Path) -> dict:
    """#142 当前任务 chip：活跃 worker 的 claim + 短任务短语（<=24 字符）。

    活跃 = lib_kunglao.iter_worker_states 里 LAST status 非 terminal 且非
    waiting 的 worker（liveness 协议归 lib_kunglao 所有；此处只取身份），
    多活跃取 mtime 最新。空闲时 claim 回退最近一次 dispatch（`last C-<id>`）。
    全程 fail-open -> {claim: None, op: None}。
    """
    claim: str | None = None
    op: str | None = None
    try:
        from _hooks_path import load_hooks_lib
        lib = load_hooks_lib()
        states = lib.iter_worker_states(ws)
        active = [s for s in states
                  if s.get("status") not in lib.TERMINAL_WORKER_STATUSES
                  and s.get("status") != lib.WAITING_WORKER_STATUS]
        if active:
            cur = max(active, key=lambda s: s.get("mtime"))
            text = cur["file"].read_text(encoding="utf-8", errors="replace")
            m = _CLAIM_RE.search(text)
            if m:
                claim = m.group(1)
            steps = _STEP_RE.findall(text)
            if steps:
                op = steps[-1].strip()[:NOW_OP_MAX_CHARS]
        if claim is None:
            claim = _last_dispatch_claim(ws)
    except Exception:  # noqa: BLE001 — 快照永不打断 tick
        pass
    return {"claim": claim, "op": op}


def _pq_detail(ws: Path) -> list[dict]:
    """细粒度 PQ 面（原 external renderer 直接读 rl-signals.jsonl 的那部分
    数据 — 合同违规，#142 收归 producer）：逐 PQ {id,state,coverage}。"""
    rows: list[dict] = []
    try:
        led = yaml.safe_load((ws / "runs" / "mission_ledger.yaml")
                             .read_text(encoding="utf-8")) or {}
        for p in (led.get("mission", {}) or {}).get("pqs") or []:
            if not isinstance(p, dict):
                continue
            try:
                cov = round(float(p.get("coverage") or 0.0), 4)
            except (TypeError, ValueError):
                cov = 0.0
            rows.append({"id": str(p.get("id")), "state": p.get("state"),
                         "coverage": cov})
    except (OSError, yaml.YAMLError, TypeError):
        pass
    return rows


def _difficulty(ws: Path) -> str | None:
    """难度档（mission_ledger.read_difficulty_tier — evidence/difficulty.json
    first, task_spec.yaml second）。缺/读失败 -> None（渲染端省略）。"""
    try:
        import mission_ledger
        return mission_ledger.read_difficulty_tier(ws)
    except Exception:  # noqa: BLE001 — 快照永不打断 tick
        return None


# Perf-face terminal vocabulary (claim-register status comment is the
# shape contract: terminal = {PROVEN, VERIFIED, NEGATIVE, REFUTED, DEFERRED}).
_PERF_TERMINAL_STATUSES = {"PROVEN", "VERIFIED", "NEGATIVE", "REFUTED",
                           "DEFERRED"}


def _difficulty_face(ws: Path) -> dict | None:
    """Issue 212 difficulty face: the calibrated tier first (the mounted
    calibration output, via mission_ledger.read_difficulty_tier), the raw
    calibration surface second — difficulty_calibration.calibrate_workspace
    consumes the apkid/die evidence directly and is REUSED here, never
    re-derived. Nothing usable -> None (renderer hides the badge)."""
    try:
        import mission_ledger
        tier = mission_ledger.read_difficulty_tier(ws)
    except Exception:  # noqa: BLE001 — a face never breaks the snapshot
        tier = None
    if tier:
        return {"tier": str(tier), "score": None, "source": "calibrated"}
    try:
        from difficulty_calibration import calibrate_workspace
        res = calibrate_workspace(ws) or {}
        cov = res.get("coverage") or {}
        if cov.get("die") or cov.get("apkid"):
            score = res.get("score")
            return {"tier": res.get("tier"),
                    "score": (round(float(score), 4)
                              if score is not None else None),
                    "source": "raw-signals"}
    except Exception:  # noqa: BLE001 — a face never breaks the snapshot
        pass
    return None


def _perf_claims(ws: Path) -> dict:
    """Issue 212 claims closed/total, recomputed from the LIVE ledger on every
    build (owner correction: the denominator is dynamic — claims registered
    during the loop grow N; the init baseline is a starting point, never a
    cap). Unreadable register -> zeros (fail-open)."""
    try:
        reg = yaml.safe_load((ws / "claim-register.yaml")
                             .read_text(encoding="utf-8")) or {}
        claims = reg.get("claims") or []
    except (OSError, yaml.YAMLError):
        claims = []
    closed = sum(1 for c in claims
                 if str(c.get("status") or "").upper()
                 in _PERF_TERMINAL_STATUSES)
    return {"closed": closed, "total": len(claims)}


def _perf_face(ws: Path) -> dict:
    """Issue 212 performance face — every metric from a pre-existing pipe, every
    read fail-open (missing source = the field stays None/0; the renderer
    hides absent segments, it never renders a placeholder)."""
    out: dict = {"claims": _perf_claims(ws), "win_rate": None,
                 "heartbeat_age_min": None,
                 "workers": {"total": 0, "active": 0,
                             "last_activity_age_s": None}}
    try:
        from winrate_curve import face as _wr_face
        f = _wr_face(ws) or {}
        if int(f.get("n_settlements") or 0) > 0:
            windowed = f.get("windowed") or []
            rate = (windowed[-1].get("rate") if windowed else None) \
                or (f.get("overall") or {}).get("rate")
            out["win_rate"] = (round(float(rate), 4)
                               if rate is not None else None)
    except Exception:  # noqa: BLE001 — a face never breaks the snapshot
        pass
    try:
        hb = ws / "runs" / ".heartbeat.json"
        out["heartbeat_age_min"] = round(max(
            0.0, (datetime.datetime.now(datetime.timezone.utc).timestamp()
                  - hb.stat().st_mtime) / 60), 2)
    except OSError:
        pass
    try:
        from _hooks_path import load_hooks_lib
        lib = load_hooks_lib()
        states = list(lib.iter_worker_states(ws))
        active = [s for s in states
                  if s.get("status") not in lib.TERMINAL_WORKER_STATUSES
                  and s.get("status") != lib.WAITING_WORKER_STATUS]
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        last = max((s.get("mtime") for s in states), default=None)
        out["workers"] = {"total": len(states), "active": len(active),
                          "last_activity_age_s": (round(
                              (now_dt - last).total_seconds(), 1)
                              if last is not None else None)}
    except Exception:  # noqa: BLE001 — a face never breaks the snapshot
        pass
    return out


def _eta_fade_cells(d_slope: float) -> int:
    """条尾渐隐段长 = ETA 不确定性：斜率越接近名义健康值渐隐越短。"""
    confidence = min(1.0, abs(d_slope or 0.0) / D_SLOPE_NOMINAL)
    return round((1.0 - confidence) * 4)


# ---------------------------------------------------------------------------
# state machine + flash
# ---------------------------------------------------------------------------

_STATE_PRECEDENCE = ("down", "flawless", "stall", "toss", "analyzing", "idle")


def _detect_state(ws: Path, *, alive_ok: bool, open_claims: int,
                  failed_claims: int, pq: dict, toss: bool,
                  stall_ok: bool) -> str:
    if not alive_ok:
        return "down"                       # 厥：心跳停（看门狗原则）
    if (pq["total"] > 0 and open_claims == 0 and failed_claims == 0
            and pq["coverage"] >= 1.0):
        return "flawless"                   # 0 失败 claim 全答
    if not stall_ok:
        return "stall"                      # 滞：指纹 K tick 不动
    if toss:
        return "toss"                       # dispatch 后窗口
    if open_claims > 0:
        return "analyzing"                  # 气：OPEN claim 在案
    return "idle"                           # 无 OPEN claim


def _format_flash_text(pq: dict, elapsed: dict, eta) -> str:
    base = f"已 {elapsed['ticks']}t"
    if isinstance(eta, (int, float)):
        return f"{base} · 剩 ~{int(round(eta))}t"
    return base


def _detect_flash(prev: dict | None, cur: dict, *, flash_seq: int,
                  text: str) -> dict:
    """闪现触发（数据面）：milestone / 每 N tick / 状态切换 / answered 变化 /
    stall 解除。命中 → seq+1 + ts（Node 用 now-ts<5s 判窗口，无跨渲染状态）。"""
    triggered = None
    if prev is not None:
        if cur["tick"] > 0 and cur["tick"] % FLASH_EVERY_N_TICKS == 0:
            triggered = "periodic"
        else:
            prev_cov = float(prev.get("pq", {}).get("coverage", 0.0))
            cur_cov = float(cur["pq"]["coverage"])
            for m in MILESTONES:
                if prev_cov < m <= cur_cov:
                    triggered = f"milestone_{int(m * 100)}"
                    break
            if triggered is None:
                if (cur["state"] != prev.get("state")
                        and prev.get("state") is not None):
                    triggered = "state_change"
                elif (cur["pq"]["answered"] != prev.get("pq", {}).get("answered")
                        and cur["state"] != "down"):
                    triggered = "claim_progress"
                elif (prev.get("state") == "stall" and cur["state"] != "stall"):
                    triggered = "stall_cleared"
    if triggered is None and prev is not None:
        return prev.get("flash") or {"seq": 0, "ts": utc_now(),
                                     "reason": None, "text": None}
    if triggered is None:
        return {"seq": 0, "ts": utc_now(), "reason": None, "text": None}
    return {"seq": flash_seq, "ts": utc_now(), "reason": triggered,
            "text": text}


# ---------------------------------------------------------------------------
# snapshot build/write
# ---------------------------------------------------------------------------

def _read_prev(ws: Path) -> dict | None:
    try:
        prev = json.loads((ws / SNAPSHOT_REL).read_text(encoding="utf-8"))
        return prev if isinstance(prev, dict) else None
    except (OSError, ValueError):
        return None


def build_snapshot(ws: Path, now: datetime.datetime | None = None) -> dict:
    """Pure builder: every field traced to a disk observation. Never raises
    on workspace anomalies (fail-open to zeros/idle)."""
    ws = Path(ws)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    now_s = now.timestamp()
    prev = _read_prev(ws)
    open_claims, failed_claims = _claims_state(ws)
    ctx = {"open_claims": open_claims, "now": now}
    probe_detail = run_probe(ws, ctx)

    by_id = {d["id"]: d for d in probe_detail}
    alive_ok = (by_id.get("heartbeat_mtime", {}).get("ok", False)
                and by_id.get("ledger_tail", {}).get("ok", True))
    stall_ok = by_id.get("stall_fingerprint", {}).get("ok", True)

    pq = _mission_state(ws)
    activity = _ledger_activity(ws, now_s)
    state = _detect_state(ws, alive_ok=alive_ok, open_claims=open_claims,
                          failed_claims=failed_claims, pq=pq, toss=activity["toss"],
                          stall_ok=stall_ok)

    # #882: the cockpit trio rides the snapshot (Node renders the section
    # verbatim — zero kunglao logic client-side). Fail-open to zeros.
    try:
        from backtrack_loop import cockpit_backtrack
        backtrack = cockpit_backtrack(ws)
    except Exception:  # noqa: BLE001 — 快照永不打断 tick
        backtrack = {"backtrack_lag": 0, "unattributed_rate": 0.0,
                     "pending_proposals": 0}

    # #878: mechanisms health section — per registered mechanism
    # {last_run, next_eligible, drops}. Fail-open like the trio above: the
    # registry face degrades to an empty section, never breaks the snapshot.
    try:
        from mechanism_scheduler import mechanisms_view
        mech_rows = mechanisms_view(ws)
    except Exception:  # noqa: BLE001 — 快照永不打断 tick
        mech_rows = []

    elapsed = {"ticks": pq["elapsed_ticks"], "started_ts": pq["started_ts"]}
    tick = int(prev.get("tick", 0)) + 1 if prev else max(1, pq["elapsed_ticks"])
    state_since = now_iso = utc_now()
    if prev and prev.get("state") == state and prev.get("state_since"):
        state_since = prev["state_since"]

    flash = _detect_flash(
        prev, {"tick": tick, "state": state, "pq": pq},
        flash_seq=int((prev or {}).get("flash", {}).get("seq", 0)) + 1,
        text=_format_flash_text(pq, elapsed, pq["eta_ticks"]))

    codes = sorted({d["short_code"] for d in probe_detail if not d["ok"]})
    by_id.get("audit_age", {})
    audit_age_min = None
    try:
        audit_age_min = int((now_s - (ws / "runs" / ".hooks-selfcheck.json")
                             .stat().st_mtime) / 60)
    except OSError:
        pass

    # #142 v2 producer-owned fields — each traced to its disk observation,
    # each fail-open (the snapshot never breaks the tick / the touch).
    h = _entropy_face(ws, prev)
    health = _health(ws)
    now_chip = _now_chip(ws)
    pq_rows = _pq_detail(ws)
    difficulty = _difficulty(ws)
    # Issue 212: difficulty face (calibrated tier / raw-signals reuse) + the
    # perf face (live-ledger claims, rolling win-rate, heartbeat age,
    # worker liveness) — conditional segments, absent = hidden.
    difficulty_face = _difficulty_face(ws)
    perf = _perf_face(ws)

    return {
        "schema": SCHEMA_VERSION,
        "ts": now_iso,
        "workspace": str(ws.resolve()),
        "tick": tick,
        "tick_minutes": TICK_MINUTES,
        "state": state,
        "state_since": state_since,
        "prev_state": (prev or {}).get("state"),
        "color": dict(STATE_COLORS[state]),
        "probe_codes": codes,
        "probe_detail": probe_detail,
        "pq": pq,
        "v_m": pq["v_m"],
        "v_norm": pq["v_norm"],
        # ---- #142 v2: producer-owned data (the renderer is a dumb view) ----
        "v_hist": pq.get("v_hist") or [],
        "h_bits": h["h_bits"],
        "h_pq": h["h_pq"],
        "h_trend": h["h_trend"],
        "health": health,
        "now": now_chip,
        "pq_rows": pq_rows,
        "difficulty": difficulty,
        # Issue 212: difficulty face (calibrated/raw-signals provenance) + perf
        # face (claims closed/total live ledger, rolling win-rate, heartbeat
        # age, worker liveness). Additive fields — readers probe the field
        # set, never a version ladder (no-backcompat policy).
        "difficulty_src": difficulty_face,
        "perf": perf,
        # #142 phase-2 slots: named now, populated later — no renderer change
        # twice (#133 v_norm-v_oracle gap, #129 1/k baseline).
        "v_oracle_gap": None,
        "baseline_inv_k": None,
        "d_slope": pq["d_slope"],
        "d_slope_norm": pq["d_slope_norm"],
        "eta_ticks": pq["eta_ticks"],
        "eta_fade_cells": _eta_fade_cells(pq["d_slope"]),
        "elapsed": elapsed,
        "activity": {"events_recent": activity["events_recent"],
                     "spark_count": activity["spark_count"]},
        "backtrack": backtrack,
        "mechanisms": mech_rows,
        "flash": flash,
        "audit": {"age_min": audit_age_min,
                  "source": "runs/.hooks-selfcheck.json"},
    }


def write_snapshot(ws: Path, now: datetime.datetime | None = None) -> Path:
    """Atomic pre-write (tmp + replace, heartbeat_touch F2 discipline) +
    one controlled-vocabulary event (#883 statusline_snapshot face)."""
    ws = Path(ws)
    snap = build_snapshot(ws, now=now)
    out = ws / SNAPSHOT_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snap, ensure_ascii=False, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(out)
    try:
        import kunglao_log
        kunglao_log.emit(ws, "statusline_snapshot", "statusline_snapshot",
                         detail=json.dumps(
                             {"state": snap["state"], "schema": snap["schema"],
                              "tick": snap["tick"], "codes": snap["probe_codes"]},
                             ensure_ascii=False))
    except Exception:  # noqa: BLE001 — logging never breaks the write
        pass
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    ws = _resolve_ws(args[0] if args else None)
    out = write_snapshot(ws)
    snap = json.loads(out.read_text(encoding="utf-8"))
    print(f"statusline_snapshot: {out}")
    print(json.dumps({"state": snap["state"], "tick": snap["tick"],
                      "codes": snap["probe_codes"],
                      "coverage": snap["pq"]["coverage"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())

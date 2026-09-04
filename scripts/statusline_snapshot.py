#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""statusline_snapshot.py — #883 statusline 健康段数据面（快照解耦）.

THE architectural decision (issue #883, 定案): kunglao logic never enters
Node. This module pre-writes ONE snapshot file per heartbeat tick
(``runs/.kunglao-statusline.json``) and the user's combined-statusline.mjs
only reads it (O(1), zero spawn) to interpolate animation frames on its own
render clock. Watchdog semantics fall out for free: kunglao dies -> tick
stops -> snapshot mtime stalls -> Node judges down (no self-report).

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

Usage: python statusline_snapshot.py <workspace>
(attached from heartbeat_tick after the #873 cockpit sample; fail-open).
"""
from __future__ import annotations

import json
import os
import sys
import datetime
from pathlib import Path

import yaml

# #863 Family C: workspace resolution is single-sourced in ws_layout
# (the #228 strict family: arg wins, probe, exit 2 — never guess).
from ws_layout import resolve_strict as _resolve_ws

# #597: staleness constants are single-sourced in liveness_policy.
from liveness_policy import HEARTBEAT_STALE_MINUTES, TICK_INTERVAL_DEFAULT_MIN

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/ root
SNAPSHOT_REL = Path("runs") / ".kunglao-statusline.json"

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
           "elapsed_ticks": 0, "started_ts": None}
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


def _ledger_activity(ws: Path, now_s: float) -> dict:
    """账本尾部（末 64KB 有界读）-> 近窗事件数 + 最近 dispatch 是否在 toss 窗口。"""
    logs = ws / "runs" / "logs"
    try:
        latest = max((p for p in logs.glob("kunglao-*.jsonl") if p.is_file()),
                     key=lambda p: p.stat().st_mtime, default=None)
        if latest is None:
            return {"events_recent": 0, "spark_count": 0, "toss": False}
        with latest.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - LEDGER_TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError:
        return {"events_recent": 0, "spark_count": 0, "toss": False}
    lines = tail.splitlines()
    if len(lines) > 1:
        lines = lines[1:]  # drop possibly-partial first line
    recent = 0
    toss = False
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = _parse_ts(row.get("ts"))
        if ts is not None and now_s - ts <= ACTIVITY_WINDOW_S:
            recent += 1
        if (row.get("action") == "dispatch" and ts is not None
                and now_s - ts <= TOSS_WINDOW_S):
            toss = True
    return {"events_recent": recent,
            "spark_count": min(3, recent),  # sparks: event density, capped
            "toss": toss}


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

    return {
        "schema": 1,
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
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())

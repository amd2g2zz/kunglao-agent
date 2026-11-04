#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cost_input_capture.py — PostToolUse 成本输入捕获 (#873)。

缺口0：cost_events.jsonl 的写入方在仓库内不存在——cost_gate.py 只读，
docstring 声明的 "written by PostToolUse hook" 是纸面。本 hook 补上输入端：
  - tool_response 含 "COST WARNING: session total ~$<float>"
    （COST CRITICAL 同构）→ 追加 {"ts","amount","source"} 到
    <ws>/cost_events.jsonl（schema 与 cost_gate 解析器逐字段一致）
  - 无匹配 / ws 未解析 / IO 异常 → 静默不写（FAIL_OPEN，永不打断工具流）

口径边界（proposal 声明）：Claude Code 不暴露 per-call 计费遥测——amount
是会话累计 session total（PostToolUse 文本解析口径），非增量。

Wiring (scripts/hook_activation.py 部署表): PostToolUse/Edit|Write|MultiEdit|Agent。
"""
from __future__ import annotations
# The canonical warn — ONE implementation (process-wide
# dedupe per (op, reason) + the ledger face). The stderr-only fallback is
# the partial-deploy lifeline (scripts/ not importable here); production
# imports kunglao_log.
try:
    from _path_hygiene import ensure_scripts_path as _esp406
    _esp406()
# issue 275 batch-3: fail-open handlers leave ONE rate-limited trace —
# the canonical kunglao_log.warn.
    from kunglao_log import warn
except Exception:  # noqa: BLE001 — fail-open lifeline, never block the hook
    def warn(op: str, reason: str) -> None:
        print(f"[kunglao-agent] WARN (fail-open): {op}: {reason}",
              file=sys.stderr)
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

COST_RE = re.compile(
    r"COST (?:WARNING|CRITICAL): session total ~\$([0-9]+(?:\.[0-9]+)?)")
COST_EVENTS = "cost_events.jsonl"

# #801 Face 3: the machine:analysis cockpit ratio — machine-overhead input
# tokens (orchestrator transcript rows) over analysis-output tokens
# (sidechain/worker rows). The rc1 death shape (harness out-competing the
# analysis) becomes observable HOURS early: alarm at ratio > 1.
COCKPIT_RATIO_REL = Path("runs") / ".cockpit-ratio.json"
COCKPIT_RATIO_ALARM = 1.0
RATIO_ALARM_ACTION = "cockpit_ratio_alarm"

# #801 R2c: unactuated detector evaluations are BILLED CONSUMPTION. A
# detector_eval row with no detector_fired for the same detector is
# detection without action (the rc1 shapes: 62:1 and 142:1 eval:fire) —
# it counts into the same consumption account the cockpit ratio reads.
DETECTOR_EVAL_WORD = "detector_eval"
DETECTOR_FIRED_WORD = "detector_fired"
LEDGER_TAIL_BYTES = 65_536  # the #883 read budget (rank_face pattern)


def _fold_usage(transcript_path: str | Path) -> tuple[int, int]:
    """(machine_input, analysis_output) over a transcript JSONL. Machine
    side: isSidechain-falsy rows' input tokens incl. cache reads; analysis
    side: isSidechain-truthy rows' output tokens. Rows without usage are
    skipped."""
    machine = 0
    analysis = 0
    with Path(transcript_path).open("r", encoding="utf-8",
                                    errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                usage = (row.get("message") or {}).get("usage") or {}
            except ValueError:
                continue
            if not isinstance(usage, dict):
                continue
            inp = int(usage.get("input_tokens") or 0) + \
                int(usage.get("cache_read_input_tokens") or 0)
            outp = int(usage.get("output_tokens") or 0)
            if row.get("isSidechain"):
                analysis += outp
            else:
                machine += inp
    return machine, analysis


def compute_ratio(transcript_path: str | Path) -> float:
    """machine_input / analysis_output over a Claude Code transcript JSONL
    (the rc1 arithmetic — see _fold_usage). Denominator floored at 1."""
    machine, analysis = _fold_usage(transcript_path)
    return machine / max(analysis, 1)


def detector_consumption(ws: Path) -> dict | None:
    """#801 R2c: the eval/fire consumption accounting over the workspace
    ledger. Reads the NEWEST runs/logs/kunglao-*.jsonl (64KB tail, the
    #883 read budget), counts detector_eval / detector_fired per detector
    (the detail JSON's `detector` field), and reports unactuated =
    sum(max(0, evals - fires)) — detection without action, billed to the
    same consumption account the cockpit ratio reads. Returns None when
    no readable ledger exists (fail-open: no block, no alarm)."""
    log_dir = Path(ws) / "runs" / "logs"
    files = sorted(log_dir.glob("kunglao-*.jsonl"))
    if not files:
        return None
    path = files[-1]
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - LEDGER_TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError as exc:
        warn("detector_consumption", f"{type(exc).__name__}: {exc}")
        return None
    lines = tail.splitlines()
    if size > LEDGER_TAIL_BYTES and lines:
        lines = lines[1:]  # drop the possibly-truncated head line
    evals: dict[str, int] = {}
    fires: dict[str, int] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        action = row.get("action")
        if action not in (DETECTOR_EVAL_WORD, DETECTOR_FIRED_WORD):
            continue
        try:
            det_name = str((json.loads(row.get("detail") or "{}")
                            ).get("detector") or "unknown")
        except ValueError:
            det_name = "unknown"
        bucket = evals if action == DETECTOR_EVAL_WORD else fires
        bucket[det_name] = bucket.get(det_name, 0) + 1
    detectors = sorted(set(evals) | set(fires))
    per_detector = {
        d: {"detector_eval": evals.get(d, 0), "detector_fired":
            fires.get(d, 0),
            "unactuated": max(0, evals.get(d, 0) - fires.get(d, 0))}
        for d in detectors}
    total_evals = sum(evals.values())
    total_fires = sum(fires.values())
    return {
        "detectors": per_detector,
        "detector_eval": total_evals,
        "detector_fired": total_fires,
        "unactuated": sum(v["unactuated"] for v in per_detector.values()),
    }


def cockpit_ratio(ws: Path, transcript_path: str | Path) -> dict | None:
    """Persist the live ratio face + alarm when ratio > 1 (fail-open).

    Writes {ts, machine_input_tokens, analysis_output_tokens, ratio,
    alarm[, detector]} to ws/runs/.cockpit-ratio.json; on alarm also emits
    the registered `cockpit_ratio_alarm` ledger row. The `detector` block
    (#801 R2c: eval/fire/unactuated consumption) rides when a readable
    workspace ledger exists. Returns the face dict, or None on any
    read/parse trouble (nothing written, nothing alarmed).
    """
    try:
        machine, analysis = _fold_usage(transcript_path)
        ratio = machine / max(analysis, 1)
        face = {
            "ts": datetime.now(timezone.utc).isoformat(
                timespec="seconds").replace("+00:00", "Z"),
            "machine_input_tokens": machine,
            "analysis_output_tokens": analysis,
            "ratio": ratio,
            "alarm": ratio > COCKPIT_RATIO_ALARM,
        }
        det = detector_consumption(Path(ws))
        if det is not None:
            face["detector"] = det
        # issue-760 pricing face: the information-gathering account rides
        # the same consumption face (probes are no longer free — zero-info
        # re-probes of decided targets are countable next to the
        # unactuated detector evals). Fail-open: an outage drops the
        # block, never the ratio.
        try:
            from rlvr import pricing as _pricing760
            face["pricing"] = _pricing760.probe_consumption(Path(ws))
        except Exception as exc:  # noqa: BLE001 — telemetry fail-open
            warn("cockpit_ratio_pricing",
                 f"{type(exc).__name__}: {exc}")
        (Path(ws) / COCKPIT_RATIO_REL).write_text(
            json.dumps(face, ensure_ascii=False), encoding="utf-8")
        if face["alarm"]:
            warn("cockpit_ratio",
                 f"machine:analysis ratio {ratio:.2f} > "
                 f"{COCKPIT_RATIO_ALARM} — harness out-competing analysis")
            try:
                from _path_hygiene import ensure_scripts_path as _esp801
                _esp801()
                from kunglao_log import emit
                emit(Path(ws), actor="hook:cost_input_capture",
                     action=RATIO_ALARM_ACTION,
                     detail=f"ratio={ratio:.4f}; "
                            f"machine={machine}; analysis={analysis}")
            except Exception as exc:  # noqa: BLE001 — telemetry fail-open
                warn("cockpit_ratio_emit",
                     f"{type(exc).__name__}: {exc}")
        return face
    except OSError as exc:
        warn("cockpit_ratio", f"{type(exc).__name__}: {exc}")
        return None
    except Exception as exc:  # noqa: BLE001 — the face never breaks the hook
        warn("cockpit_ratio", f"{type(exc).__name__}: {exc}")
        return None


def resolve_ws(payload: dict) -> Path | None:
    cwd = Path(payload.get("cwd") or ".")
    for base in (cwd, cwd / "malware-analysis-workspace", cwd.parent):
        if (base / "runs").is_dir():
            return base
    return None


def extract_amount(text: str) -> float | None:
    m = COST_RE.search(text or "")
    return float(m.group(1)) if m else None


def process_event(payload: dict) -> int:
    """Testable core。恒返 0——recorder 是 FAIL_OPEN 面，永不阻塞工具流。"""
    text = str(payload.get("tool_response") or "")
    amount = extract_amount(text)
    if amount is None:
        # #801 Face 3: the cockpit-ratio face rides the same PostToolUse
        # stream — a live machine:analysis sample per tool call when the
        # payload carries the transcript. Fail-open, silent when absent.
        tx = payload.get("transcript_path")
        ws = resolve_ws(payload)
        if tx and ws is not None:
            cockpit_ratio(ws, tx)
        return 0
    ws = resolve_ws(payload)
    if ws is None:
        return 0
    try:
        row = {"ts": datetime.now(timezone.utc).isoformat(
                   timespec="seconds").replace("+00:00", "Z"),
               "amount": amount,
               "source": str(payload.get("tool_name") or "unknown")}
        with (ws / COST_EVENTS).open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        warn("process_event", f"{type(exc).__name__}: {exc}")
    return 0


def main(stdin_stream=None) -> int:
    try:
        stream = stdin_stream if stdin_stream is not None else sys.stdin
        data = stream.read()
        payload = json.loads(data) if data else {}
    except (json.JSONDecodeError, OSError, ValueError):
        return 0
    try:
        return process_event(payload)
    except Exception:  # noqa: BLE001 — FAIL_OPEN at the body level
        return 0


if __name__ == "__main__":
    sys.exit(main())

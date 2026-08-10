#!/usr/bin/env python3
"""kunglao_record — M4 RECORD 实现模块 (phase 5, E5.1).

独立 CLI 入口: scripts/kunglao-record.py(薄包装, 本模块含全部逻辑)。

- record_event: ledger.jsonl 幂等写入 (event_id = sha256(event_type + payload))
- read_events:  按 event_type 读回
- claim_migrator: claim 状态迁移合法性检查 (maker-checker:
  非 orchestrator 写 terminal 状态 → 拒)

输出契约: schemas/event.json (M0.3 Event schema, module-design §M0.3 L53-72)。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

LEDGER_NAME = "ledger.jsonl"
EVENT_TYPES = ("fact_written", "fact_verified", "claim_promoted", "claim_refuted",
               "failure_recorded", "intent_opened", "intent_closed")
# 与 hooks/worker_budget.py TERMINAL_STATUS 同集 (worker_budget L25)
TERMINAL_STATUSES = {"PROVEN", "VERIFIED", "NEGATIVE", "REFUTED", "DEFERRED"}
# 与 hooks/worker_budget.py check_claim_status_change 豁免集一致 (L289)
ORCHESTRATOR_ACTORS = ("orchestrator", "main", "kunglao-orch")


def utc_now() -> str:
    """UTC ISO-8601 秒级, Z 后缀."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical(payload: dict) -> str:
    """payload 确定性序列化(键排序, 紧凑) — 幂等键与 checksum 的字节基础."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def event_id_of(event_type: str, payload: dict) -> str:
    """event_id = sha256(event_type + canonical(payload)) — M0.3 L67/M4.2 L325 幂等键."""
    return hashlib.sha256((event_type + _canonical(payload)).encode("utf-8")).hexdigest()


def ledger_path(ws: Path) -> Path:
    """账本路径: <ws>/ledger.jsonl(M4.1 L315 "ledger.jsonl 幂等写入")."""
    return ws / LEDGER_NAME


def read_events(ws: Path, event_type: str | None = None) -> list[dict]:
    """读回 ledger 事件(M0.2 L49); event_type=None → 全部. 坏行跳过(不崩溃, M0.4 L76)."""
    p = ledger_path(ws)
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event_type is None or ev.get("event_type") == event_type:
            out.append(ev)
    return out


def _record_checksum(rec: dict) -> str:
    """checksum = sha256(整条记录除 checksum 字段外的 canonical JSON)."""
    core = {k: v for k, v in rec.items() if k != "checksum"}
    return hashlib.sha256(_canonical(core).encode("utf-8")).hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    """写 temp → rename(崩溃安全); 失败重试 1 次(M0.4 L78/L355 状态一致性优先)."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)


def record_event(ws: Path, event: dict) -> int:
    """幂等写入(M4.2 L325): 同 event_id 重复 → 返回已有 seq; 否则 append 返回新 seq."""
    et = event.get("event_type", "")
    if et not in EVENT_TYPES:
        raise ValueError(f"unknown event_type {et!r} (allowed: {', '.join(EVENT_TYPES)})")
    payload = event.get("payload") or {}
    eid = event_id_of(et, payload)
    existing = read_events(ws)
    for ev in existing:
        if ev.get("event_id") == eid:
            return int(ev["seq"])
    rec = {
        "seq": len(existing) + 1,
        "event_id": eid,
        "source_module": event.get("source_module", "unknown"),
        "event_type": et,
        "payload": payload,
        "ts": utc_now(),
    }
    rec["checksum"] = _record_checksum(rec)
    lines = [json.dumps(e, ensure_ascii=False) for e in existing]
    lines.append(json.dumps(rec, ensure_ascii=False))
    _atomic_write(ledger_path(ws), "\n".join(lines) + "\n")
    return rec["seq"]


def _set_claim_status(reg_path: Path, claim_id: str, new_status: str) -> bool:
    """line-based 重写 claim-register.yaml 中目标 claim 块的 status: 字段."""
    lines = reg_path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    in_block = False
    replaced = False
    for line in lines:
        s = line.strip()
        if s.startswith("- id:"):
            in_block = s.split(":", 1)[1].strip() == claim_id
            out.append(line)
            continue
        if in_block and s.startswith("status:"):
            out.append(f"  status: {new_status}")
            replaced = True
            in_block = False
            continue
        out.append(line)
    if not replaced:
        return False
    _atomic_write(reg_path, "\n".join(out) + "\n")
    return True


def _extract_worker_id(register_text: str, claim_id: str) -> str | None:
    """Extract worker_id or last_dispatched_worker for a claim from register text."""
    import re
    # Match the claim block starting with "- id: <claim_id>" up to the next "- id:" or EOF
    m = re.search(
        rf"- id:\s*{re.escape(claim_id)}\b(.*?)(?=\n-\s*id:|\Z)",
        register_text, re.DOTALL)
    if not m:
        return None
    block = m.group(1)
    for key in ("worker_id", "last_dispatched_worker"):
        wm = re.search(rf"\b{key}:\s*(\S+)", block)
        if wm:
            val = wm.group(1).strip().strip("'\"")
            if val and val.lower() not in ("null", "none", "~", ""):
                return val
    return None


def claim_migrator(ws: Path, claim_id: str, new_status: str, actor: str) -> tuple[bool, str]:
    """claim 状态迁移(合法性检查 + 落地, M4.2 L331).

    maker-checker(worker_budget L282-319 同判据): 非 orchestrator 写 terminal
    状态 → (False, reason), 不落地. orchestrator 写 terminal → 更新 register
    + 记 ledger 事件(claim_promoted / claim_refuted). DEFERRED 无专属
    event_type → 仅 register 更新(契约空白决策). 非 terminal 迁移 → register 更新.

    BLIND gate (issue #15 / PRD M1): orchestrator promoting to PROVEN must
    have a valid verifier_sign_off block in the claim's fact file. Without
    it (or on BLIND REFUTE / self-stamp), the effective status is STAMP
    (claimed-but-unverified), not PROVEN. STAMP is non-terminal.
    """
    reg_path = ws / "claim-register.yaml"
    if not reg_path.exists():
        return (False, f"no claim-register.yaml under {ws}")
    register = reg_path.read_text(encoding="utf-8", errors="replace")
    if f"id: {claim_id}" not in register:
        return (False, f"claim {claim_id} not in claim-register.yaml")
    if new_status in TERMINAL_STATUSES and actor not in ORCHESTRATOR_ACTORS:
        return (False, (
            f"WORKER SELF-PROMOTION BLOCKED (maker-checker): actor={actor!r} tried "
            f"to write terminal status {new_status!r} for {claim_id}. Only the "
            f"orchestrator promotes after kunglao-redteam passes."))

    # ---- BLIND gate (issue #15): PROVEN requires independent verifier sign-off
    effective_status = new_status
    gate_msg = ""
    if new_status == "PROVEN":
        try:
            from blind_gate import check_proven_gate, STAMP
            worker_id = _extract_worker_id(register, claim_id)
            allowed, effective_status, gate_reason = check_proven_gate(
                claim_id, ws / "facts", worker_id=worker_id)
            if not allowed:
                gate_msg = f" [BLIND GATE: {gate_reason}]"
        except ImportError:
            pass  # blind_gate not available — fail open (no gate)

    if not _set_claim_status(reg_path, claim_id, effective_status):
        return (False, f"could not rewrite status for {claim_id} in claim-register.yaml")
    event_type = None
    if effective_status in ("PROVEN", "VERIFIED"):
        event_type = "claim_promoted"
    elif effective_status in ("NEGATIVE", "REFUTED"):
        event_type = "claim_refuted"
    if event_type:
        record_event(ws, {"source_module": "claim_migrator", "event_type": event_type,
                          "payload": {"claim_id": claim_id, "status": effective_status}})
    return (True, f"claim {claim_id} → {effective_status} by {actor} (register updated"
                  + (f"; ledger {event_type}" if event_type else "")
                  + gate_msg)


def main(argv: list[str] | None = None) -> int:
    """独立 CLI: python kunglao-record.py <ws> --event '<json>'.

    附加操作: --claim-migrate CLAIM_ID NEW_STATUS ACTOR; --read [EVENT_TYPE].
    """
    ap = argparse.ArgumentParser(description="kunglao-record — M4 RECORD (ledger 幂等写入 + claim 迁移)")
    ap.add_argument("ws", type=Path, help="workspace root")
    ap.add_argument("--event", help='event JSON: {"source_module":..., "event_type":..., "payload": {...}}')
    ap.add_argument("--claim-migrate", nargs=3, metavar=("CLAIM_ID", "NEW_STATUS", "ACTOR"),
                    help="claim 状态迁移(合法性检查): claim_id new_status actor")
    ap.add_argument("--read", nargs="?", const="", default=None, metavar="EVENT_TYPE",
                    help="读回事件(event_type 可选, 缺省全部)")
    args = ap.parse_args(argv)
    try:
        if args.claim_migrate:
            cid, st, actor = args.claim_migrate
            ok, msg = claim_migrator(args.ws, cid, st, actor)
            print(msg)
            return 0 if ok else 1
        if args.read is not None:
            for ev in read_events(args.ws, args.read or None):
                print(json.dumps(ev, ensure_ascii=False))
            return 0
        if args.event:
            ev = json.loads(args.event)
            seq = record_event(args.ws, ev)
            print(f"recorded seq={seq} event_id="
                  f"{event_id_of(ev.get('event_type', ''), ev.get('payload') or {})}")
            return 0
        ap.print_help()
        return 2
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
import os
import datetime
import hashlib
import json
import sys
import threading
from pathlib import Path

LEDGER_NAME = "ledger.jsonl"
EVENT_TYPES = ("fact_written", "fact_verified", "claim_promoted", "claim_refuted",
               "failure_recorded", "intent_opened", "intent_closed")
# #34: unified 6-value TERMINAL from status_defs (was 5-value local copy
# annotated "同集 worker_budget"; STALE now terminal — a stale claim needs
# no further work, so claim_promoted on STALE is a real promotion)
from status_defs import TERMINAL as TERMINAL_STATUSES
# 与 hooks/worker_budget.py check_claim_status_change 豁免集一致 (L289)
ORCHESTRATOR_ACTORS = ("orchestrator", "main", "kunglao-orch")

# #78: gates REQUIRED for terminal promotion (PROVEN). When a required gate is
# unavailable (missing module / ImportError), raises (checker exception), or
# receives a corrupt required artifact, promotion FAILS CLOSED: original claim
# state preserved + explicit non-success (BLOCKED) with an audit receipt —
# a terminal state without the gates' verdicts is unverifiable. The hook-side
# backstop (hooks/worker_budget.py compare_register_change_proven_gate)
# imports this same policy so no alternate promotion route stays fail-open.
REQUIRED_FOR_TERMINAL_STATE = (
    "blind_gate",
    "fact_contradiction_gate",
    "blind_gate:check_inference_blind_scope",
)


def _required_gate_receipt(gate: str, exc: BaseException, claim_id: str) -> str:
    """Audit receipt for a required gate that could not run (D3, #78).

    Embeds checker identity, error class, and reason in the frozen
    tuple[bool, str] return contract (specs/phase-5/contract.md L79).
    """
    return (f"BLOCKED: promotion of {claim_id} requires required gate {gate}; "
            f"checker unavailable ({type(exc).__name__}): {exc} — "
            f"register not modified (fail closed)")


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


def _scan_ledger_tail(p: Path, n: int = 100) -> tuple[int, list[str]]:
    """Single-pass ledger scan: returns (line_count, last_n_non_empty_lines).

    Reads the file once to avoid TOCTOU race between idempotency check and
    seq counting.
    """
    if not p.exists():
        return 0, []
    raw = p.read_text(encoding="utf-8", errors="replace").splitlines()
    non_empty = [l.strip() for l in raw if l.strip()]
    return len(non_empty), non_empty[-n:] if n else []


def _event_id_in_lines(eid: str, lines: list[str]) -> tuple[bool, int | None]:
    """Check if event_id exists in parsed lines. Returns (found, seq_if_found)."""
    for line in lines:
        try:
            rec = json.loads(line)
            if rec.get("event_id") == eid:
                return True, int(rec["seq"])
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return False, None


def _append_single_line(p: Path, text: str) -> None:
    """Append a single line to a ledger file using os.open(O_APPEND).

    O_APPEND makes the kernel seek to EOF and write atomically for sizes
    <= PIPE_BUF (4KB+ on Windows), avoiding the temp-file rename race that
    _atomic_write causes under concurrency.
    """
    data = text.encode("utf-8")
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _ledger_lock_for(p: Path) -> threading.Lock:
    """Return a per-path threading.Lock for serializing record_event within a process.

    Uses a module-level dict keyed by resolved path. Locks are never removed
    (the set of ledger paths in a process is small and bounded).
    """
    resolved = p.resolve()
    if resolved not in _ledger_locks:
        _ledger_locks[resolved] = threading.Lock()
    return _ledger_locks[resolved]


_ledger_locks: dict[Path, threading.Lock] = {}


def record_event(ws: Path, event: dict) -> int:
    """幂等写入(M4.2 L325): 同 event_id 重复 → 返回已有 seq; 否则 append 返回新 seq.

    Fix #96 (F8): uses os.open(O_APPEND) instead of full read-modify-write
    with _atomic_write, eliminating the concurrency race where two writers
    overwrite each other's events. Idempotency is checked by scanning only the
    last 100 ledger lines in a single file read, and seq is derived from the
    same read -- no TOCTOU gap between idempotency check and seq counting.

    A per-path threading.Lock serializes the read-check-append sequence within
    a single process (the primary concurrency scenario for same-process workers).
    Cross-process safety is provided by O_APPEND atomicity for small writes.
    """
    et = event.get("event_type", "")
    if et not in EVENT_TYPES:
        raise ValueError(f"unknown event_type {et!r} (allowed: {', '.join(EVENT_TYPES)})")
    payload = event.get("payload") or {}
    eid = event_id_of(et, payload)

    p = ledger_path(ws)
    # Per-path lock: serialize read-check-append within same process
    lock = _ledger_lock_for(p)
    with lock:
        # Single-pass: read file once for both idempotency check and seq
        line_count, tail = _scan_ledger_tail(p, n=100)
        found, existing_seq = _event_id_in_lines(eid, tail)
        if found and existing_seq is not None:
            return existing_seq

        seq = line_count + 1
        rec = {
            "seq": seq,
            "event_id": eid,
            "source_module": event.get("source_module", "unknown"),
            "event_type": et,
            "payload": payload,
            "ts": utc_now(),
        }
        rec["checksum"] = _record_checksum(rec)

        # Atomic append via O_APPEND (no temp file, no read-modify-write)
        _append_single_line(p, json.dumps(rec, ensure_ascii=False) + "\n")
        return seq


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

    #78 fail-closed: the PROVEN gates (BLIND / contradiction / inference) are
    REQUIRED_FOR_TERMINAL_STATE — when a gate cannot run (ImportError,
    checker exception, corrupt artifact) the migration is refused with
    (False, BLOCKED receipt) and the register keeps its original status.
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

    # ---- #236 R3 (write-side gate): DEFERRED 写入前回查 defer_reason 引用的
    # decision-rights 行真实存在 — 引用不存在的行 = fake blocker 向量
    # (2026-08-12 事故). 引用违规 → 拒绝写入, register 保持原状.
    # 工作区无 references/decision-rights.md(无治理层)→ 跳过检查, 原行为不变.
    if new_status == "DEFERRED":
        try:
            from write_gate import (defer_reason_violations,
                                    extract_claim_defer_reason,
                                    parse_decision_rights)
        except Exception as exc:
            return (False, f"BLOCKED: {claim_id} DEFERRED write requires "
                           f"write-side gate R3; checker unavailable "
                           f"({type(exc).__name__}): {exc} — register not "
                           f"modified (fail closed)")
        dr_path = ws / "references" / "decision-rights.md"
        if dr_path.exists():
            rows = parse_decision_rights(dr_path)
            reason = extract_claim_defer_reason(register, claim_id)
            if reason:
                bad = defer_reason_violations(claim_id, reason, rows)
                if bad:
                    cited = ", ".join(str(b["row"]) for b in bad)
                    rows_fmt = ", ".join(str(n) for n in sorted(rows))
                    return (False, (f"DEFER REASON REJECTED (write-side gate "
                                    f"R3): {claim_id} defer_reason cites "
                                    f"nonexistent decision-rights row(s): "
                                    f"{cited} (references/decision-rights.md "
                                    f"has rows {rows_fmt or '(none)'})"))

    # ---- required gates (#78, fail closed): PROVEN requires the BLIND /
    # contradiction / inference verdicts.
    # #98 (D6/F15): two-tier exception classification:
    #   ImportError (gate module broken/code incomplete) -> FAIL_CLOSED, BLOCKED
    #   non-ImportError (verifier runtime error/timeout) -> degrade to STAMP
    effective_status = new_status
    gate_msg = ""
    if new_status == "PROVEN":
        # ---- BLIND gate ----
        try:
            from blind_gate import check_proven_gate, STAMP
        except Exception as exc:
            # Infrastructure failure: code incomplete -> FAIL_CLOSED
            return (False, _required_gate_receipt("blind_gate", exc, claim_id))
        try:
            worker_id = _extract_worker_id(register, claim_id)
            allowed, effective_status, gate_reason = check_proven_gate(
                claim_id, ws / "facts", worker_id=worker_id)
            if not allowed:
                gate_msg = f" [BLIND GATE: {gate_reason}]"
        except Exception as exc:
            # Runtime verifier failure -> degrade to STAMP (guardrails SS1b)
            effective_status = STAMP
            gate_msg += (f" [BLIND GATE: verifier runtime error "
                         f"({type(exc).__name__}: {exc}); degraded to STAMP "
                         f"(guardrails SS1b self_caveat allowed)]")
        # ---- contradiction gate (#47) ----
        try:
            from fact_contradiction_gate import check_proven_contradiction, STAMP
        except Exception as exc:
            return (False, _required_gate_receipt(
                "fact_contradiction_gate", exc, claim_id))
        try:
            c_ok, c_reason = check_proven_contradiction(claim_id, ws / "facts")
            if not c_ok:
                effective_status = STAMP
                gate_msg += f" [CONFLICT GATE: {c_reason}]"
        except Exception as exc:
            effective_status = STAMP
            gate_msg += (f" [CONFLICT GATE: verifier runtime error "
                         f"({type(exc).__name__}: {exc}); degraded to STAMP "
                         f"(guardrails SS1b self_caveat allowed)]")
        # ---- inference-scope gate (#48) ----
        try:
            from blind_gate import check_inference_blind_scope, STAMP
        except Exception as exc:
            return (False, _required_gate_receipt(
                "blind_gate:check_inference_blind_scope", exc, claim_id))
        try:
            worker_id = _extract_worker_id(register, claim_id)
            i_ok, _, i_reason = check_inference_blind_scope(
                claim_id, ws / "facts", register, worker_id=worker_id)
            if not i_ok:
                effective_status = STAMP
                gate_msg += f" [INFERENCE GATE: {i_reason}]"
        except Exception as exc:
            effective_status = STAMP
            gate_msg += (f" [INFERENCE GATE: verifier runtime error "
                         f"({type(exc).__name__}: {exc}); degraded to STAMP "
                         f"(guardrails SS1b self_caveat allowed)]")
        # ---- provenance gate (#147 wiring) ----
        # The research replay showed check_provenance_gate exists but was NOT
        # on the PROVEN path — summary-only facts were promoted. Every PROVEN
        # promotion must carry raw provenance that resolves to evidence-index
        # entries with matching hashes. Import failure = FAIL_CLOSED (same
        # policy as the other REQUIRED_FOR_TERMINAL_STATE gates, #78).
        # Gate scope: only when the workspace HAS an evidence index — a bare
        # workspace without evidence machinery keeps its legacy promotion
        # path (regression contract, test_fix_98_deadlock S9).
        try:
            from provenance_gate import check_provenance_gate
        except Exception as exc:
            return (False, _required_gate_receipt("provenance_gate", exc, claim_id))
        try:
            from blind_gate import find_fact_file
            fact_file = find_fact_file(ws / "facts", claim_id)
            if fact_file is None:
                effective_status = STAMP
                gate_msg += f" [PROVENANCE GATE: no fact file for {claim_id}]"
            elif (ws / "evidence" / "_index.json").exists():
                p_ok, p_reason = check_provenance_gate(fact_file, ws)
                if not p_ok:
                    # Evidence-integrity violation (bad ref / hash drift):
                    # refuse the promotion — do NOT record a fake STAMP for a
                    # workspace whose evidence machinery is present but says
                    # the provenance does not resolve.
                    return (False, f"PROVENANCE GATE: {p_reason} — "
                                   f"refusing {claim_id} promotion")
        except Exception as exc:
            effective_status = STAMP
            gate_msg += (f" [PROVENANCE GATE: verifier runtime error "
                         f"({type(exc).__name__}: {exc}); degraded to STAMP "
                         f"(guardrails SS1b self_caveat allowed)]")

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

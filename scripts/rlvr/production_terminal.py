"""Evidence-gated production Stop settlement with durable, replayable intent.

The next eligible Stop is the recovery consumer. The intent is a checkpoint,
not a transaction across the existing settlement writers. Their own dedupe
keys own partial-write recovery; completion requires reading their results.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile

from rlvr import episode_pool, episode_settle, ledger
import verifier_identity
import verifier_integrity

SCHEMA = "production-terminal/1"


class SettlementIncomplete(RuntimeError):
    """A known postcondition failed; the real Stop must block and retry."""


def evidence(ws: Path) -> dict | None:
    """Require terminal statuses and anchored, distinct checker identities."""
    claims = episode_settle._read_register(ws)
    if not claims:
        return None
    records = []
    for claim in claims:
        cid = str(claim.get("id") or "")
        status = str(claim.get("status") or "").casefold()
        if not cid or status not in {"proven", "verified", "negative", "refuted"}:
            return None
        passed, word, _ = verifier_integrity.resolve_verification(ws, cid, "")
        if (status in {"proven", "verified"} and not passed) or (
                status in {"negative", "refuted"} and
                word not in verifier_integrity.FAIL_VERDICTS):
            return None
        maker = str(claim.get("maker_identity") or claim.get("creator") or "")
        if not maker:
            from register_proven_gate import latest_evidence  # noqa: PLC0415
            note = (latest_evidence(ws, cid).get("verify_note") or {}).get("source")
            if note:
                maker = verifier_identity.extract_from_md(
                    (ws / "runs" / note).read_text(encoding="utf-8")) or ""
        if not maker:
            return None
        matched = _checker_record(ws, cid, status, maker)
        if not matched:
            return None
        records.append(matched)
    fingerprint = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
    return {"mission": episode_settle._anchor(claims), "evidence": records,
            "fingerprint": fingerprint}


def _checker_record(ws: Path, cid: str, status: str, maker: str) -> dict | None:
    """Validate the decisive canonical checker against its byte anchor."""
    for rel in verifier_integrity.canonical_records(cid):
        path = verifier_integrity._safe_ws_path(ws, rel)
        if path is None:
            return None
        if not path.is_file():
            continue
        found, _ = verifier_integrity._record_verdict_word(path, cid)
        if not found:
            return None
        text = path.read_text(encoding="utf-8")
        identity = (verifier_identity.extract_from_json(json.loads(text))
                    if path.suffix == ".json" else
                    verifier_identity.extract_from_md(text))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if not identity or identity == maker:
            return None
        anchored = any(a.get("record_sha256") == digest and
                       a.get("source") == path.name and
                       a.get("verifier_identity") == identity
                       for a in verifier_identity.anchors_for(ws, cid))
        if not anchored:
            return None
        return {"claim": cid, "status": status, "record": rel,
                "sha256": digest, "maker": maker, "checker": identity}
    return None


def _checkpoint(path: Path, doc: dict) -> None:
    """Atomic durable checkpoint; a failed write never certifies completion."""
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".terminal-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(doc, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        if os.name == "posix":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def _exclusive(path: Path):
    """Real process lock on POSIX/Windows; unavailable locks fail closed."""
    with path.open("a+b") as guard:
        if os.name == "nt":
            import msvcrt  # noqa: PLC0415 — Windows runtime only
            if path.stat().st_size == 0:
                guard.write(b"\0")
                guard.flush()
            guard.seek(0)
            msvcrt.locking(guard.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                guard.seek(0)
                msvcrt.locking(guard.fileno(), msvcrt.LK_UNLCK, 1)
        elif os.name == "posix":
            import fcntl  # noqa: PLC0415 — POSIX runtime only
            fcntl.flock(guard, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(guard, fcntl.LOCK_UN)
        else:
            raise OSError("production terminal: unsupported process lock platform")


def settle_stop(ws) -> dict:
    """Called only after every Stop gate passed; replay any unfinished intent."""
    ws = Path(ws)
    runs = ws / "runs"
    runs.mkdir(exist_ok=True)
    with _exclusive(runs / ".production-terminal.lock"):
        bound = evidence(ws)
        if bound is None:
            return {"status": "ineligible"}
        path = runs / "production-terminal.json"
        prior = json.loads(path.read_text()) if path.exists() else None
        if prior and prior.get("fingerprint") != bound["fingerprint"]:
            raise ValueError("terminal evidence changed after settlement intent")
        doc = {"schema": SCHEMA, **bound, "status": "pending", "reason": None}
        _checkpoint(path, doc)
        _span(ws, bound, "mission_terminal", "start")
        _span(ws, bound, "settlement", "start")
        try:
            _require_notes_queue(ws)
            _require_learning_seals(ws, bound)
            result = episode_settle.settle_mission(ws)
            import settle_round_credit  # noqa: PLC0415 — existing production owner
            credit = settle_round_credit.run(ws)
            if any(value for key, value in credit.items()
                   if key == "error" or key.endswith("_error")):
                raise RuntimeError("round credit settlement failed")
            _require_learning_seals(ws, bound)
            _require_dispatch_credit(ws, bound)
            if ledger.pending_settlement(ws):
                raise RuntimeError("rollout settlement remains pending")
            episode = episode_pool.episode_path(ws, bound["mission"])
            if not episode.is_file():
                raise RuntimeError("mission episode is absent")
            episode_pool.es.read_episode_file(episode)
            episode_settle.derived_views(ws)
            doc.update(status="completed", episode=str(episode.relative_to(ws)))
            _checkpoint(path, doc)
            _span(ws, bound, "settlement", "completed")
            _span(ws, bound, "mission_terminal", "completed")
            return {"status": "completed", **result}
        except Exception as exc:
            doc.update(status="retry", reason=f"{type(exc).__name__}: {exc}")
            _checkpoint(path, doc)
            _span(ws, bound, "settlement", "failed")
            _span(ws, bound, "mission_terminal", "retry")
            if isinstance(exc, SettlementIncomplete):
                return {"status": "retry", "reason": str(exc)}
            raise


def _require_notes_queue(ws: Path) -> None:
    """Missing is legacy absence; present but unreadable is never empty."""
    import yaml  # noqa: PLC0415
    path = ws / "runs" / "notes-due.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except (OSError, yaml.YAMLError) as exc:
        raise SettlementIncomplete(f"notes queue unreadable: {type(exc).__name__}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("due", []), list):
        raise SettlementIncomplete("notes queue has invalid shape")
    if any(not isinstance(row, dict) or not isinstance(row.get("claim_id"), str)
           or not row["claim_id"].strip() for row in data.get("due", [])):
        raise SettlementIncomplete("notes queue entry has invalid shape")


def _learning_rows(ws: Path, family: str) -> list[dict]:
    """Unlike tolerant telemetry readers, certification cannot skip dirty rows."""
    path = ws / "runs" / f"{family}.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    try:
        rows = [json.loads(line) for line in lines if line.strip()]
    except (ValueError, TypeError) as exc:
        raise SettlementIncomplete(f"{family} learning facts unreadable") from exc
    if any(not isinstance(row, dict) for row in rows):
        raise SettlementIncomplete(f"{family} learning facts have invalid shape")
    return rows


def _dispatches(ws: Path, bound: dict) -> dict[str, str]:
    import claims_store  # noqa: PLC0415
    out = {}
    for record in bound["evidence"]:
        cid = record["claim"]
        dispatch = claims_store.latest_committed_dispatch(ws, cid)
        if dispatch is not None:
            did = str(dispatch.get("dispatch_id") or "")
            if not did:
                raise SettlementIncomplete(f"credit dispatch identity missing: {cid}")
            out[cid] = did
    return out


def _require_learning_seals(ws: Path, bound: dict) -> None:
    """Validate participating credit facts through their seal owner, never re-sign."""
    from rlvr import learning_seal  # noqa: PLC0415
    claims = {row["claim"] for row in bound["evidence"]}
    ids = set(_dispatches(ws, bound).values())
    reward_rows = [row for row in _learning_rows(ws, "settlement")
        if row.get("kind") == "round_credit" and row.get("anchor") in claims]
    reward_rows += [row for row in _learning_rows(ws, "experience")
        if str(row.get("schema", "")).startswith("q-cell-obs")
        and row.get("source") in {"settlement", "credit-amendment"}
        and row.get("dispatch_id") in ids]
    for row in reward_rows:
        if learning_seal.armed() or "seal" in row:
            ok, reason = learning_seal.verify_row(row)
            if not ok:
                raise SettlementIncomplete(f"learning seal invalid: {reason}")


def _require_dispatch_credit(ws: Path, bound: dict) -> None:
    """Read back the existing bank; no reward or amendment arithmetic here."""
    from rlvr import q_cells  # noqa: PLC0415
    for cid, did in _dispatches(ws, bound).items():
        row = ledger.fold(ws, f"round_credit/{cid}")
        if row is None or row.get("settlement") is None:
            raise SettlementIncomplete(f"credit settlement absent: {did}")
        mass = q_cells.banked_mass(ws, did)
        if mass is None or mass[2] == 0:
            raise SettlementIncomplete(f"credit bank incomplete: {did}")


def inspect(ws) -> dict:
    """Operator read face: ledger truth and spans are reported separately."""
    ws = Path(ws)
    checkpoint = ws / "runs" / "production-terminal.json"
    doc = json.loads(checkpoint.read_text()) if checkpoint.is_file() else None
    spans = []
    span_path = ws / "runs" / "face-spans.jsonl"
    if span_path.is_file():
        spans = [json.loads(line) for line in span_path.read_text().splitlines() if line]
    return {"checkpoint": doc, "episodes": len(episode_pool.list_episodes(ws)),
            "pending_rollouts": len(ledger.pending_settlement(ws)),
            "spans": spans}


def _span(ws: Path, bound: dict, operation: str, state: str) -> None:
    """Best-effort trace of an actual call; never certifies settlement."""
    import time  # noqa: PLC0415
    from kunglao_log import warn  # noqa: PLC0415

    span_id = hashlib.sha256((bound["fingerprint"] + operation).encode()).hexdigest()[:16]
    parent_id = hashlib.sha256(
        (bound["fingerprint"] + "mission_terminal").encode()).hexdigest()[:16]
    row = {"schema": "face-span/1", "trace_id": bound["fingerprint"],
           "span_id": span_id,
           "parent_span_id": (None if operation == "mission_terminal" else
               parent_id),
           "role": "orchestrator", "gen_ai.operation.name": operation,
           "event": state, "time_ns": time.time_ns(), "usage": "unknown"}
    try:
        with (ws / "runs" / "face-spans.jsonl").open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError as exc:
        warn("production_terminal.span", type(exc).__name__)


if __name__ == "__main__":
    import sys
    print(json.dumps(inspect(Path(sys.argv[1])), sort_keys=True))

# -*- coding: utf-8 -*-
"""rlvr/settlement_wire.py — the blind settlement WIRE (issue-802).

The blind-settlement card (issue-687) shipped the barrier family (the whitelist builder, the settlement
gate, the read barrier, the kunglao-settler face) and left it
armed-unwired: no production writer built a ``blind-settlement-input/1``
doc and the unblinded ``settle_step`` judgment is what ran. This module
is the wire — the production writer + consumer that route the
settlement event through the blind face:

THE WRITER — ``park_blind_input`` builds the blind input doc through
``settlement_scorer.settler_input`` (the whitelist builder: producer
narrative and the policy learning faces are refused BY CONSTRUCTION,
before any read) and parks it at ``runs/settlement-input-<claim>.json``
as canonical bytes. Deterministic: same arguments -> same bytes; a
re-park of identical bytes is a no-op, and once the settler has ruled
(a verdict doc exists) a CHANGED re-park refuses — the ruling window is
closed, a blindside re-blinding would invalidate the ruling in flight.

THE CONSUMER — ``settle_parked`` loads the parked doc + the settler's
verdict doc and settles over EXACTLY what was blinded: every artifact's
current bytes must still hash to the parked sha256 (drift refuses —
ruling over unseen bytes fabricates credit), the verdict's grader
identity must equal the parked input's identity, and the ruling then
rides ``settlement_scorer.settle_blind`` (the blind gate ->
``scalar.validate_verdict_doc`` stack -> the rollout ledger). The
canonical parked paths match the kunglao-settler face's output contract
(``runs/settlement-verdict-<claim>.json``).

THE CLAIM-STORE ALIGNMENT (issues 800/809) — the claim mint rides ``claims_store.apply``,
never around it: an oracle-pass blind settlement mints PROVEN only
through ``settle_proven`` WITH a verification reference, and the store's
verifier-integrity resolver refuses anything that does not resolve to a
PASSED record (fail-closed; the refusal lands a provenance row and the
register is untouched). An oracle-fail maps to ``settle_refuted``. The
mint's actor is ``settler:<identity>`` — production provenance carries
the blind grader's identity.

THE EVAL GATE — the unblinded ``settle_step`` judgment is eval-only.
``eval_settle_enabled()`` (env ``KUNGLAO_EVAL_SETTLE=1``) is the
explicit opt-in; the production stop face defaults to blind mode. The
liveness fingerprint rides the ``settlement-wire/1`` rows in the
consolidated settlement ledger: a blind settlement event always lands a
settler-identity row — production settlements show settler-identity
rows from the blind path.

Fail-closed on trust, fail-open on telemetry: a refused settlement
writes nothing and says why; the wire row is the loud receipt either
way. Zero judgment here: no sampling slot, no model call, no narrative
field passes through.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from kunglao_log import warn
from rlvr import consolidated_ledger as cl
from rlvr import settlement_scorer as bss

#: the explicit eval gate for the unblinded settle_step judgment —
#: production defaults to the blind face; this env is the opt-back-in
EVAL_SETTLE_ENV = "KUNGLAO_EVAL_SETTLE"

#: the parked blind input doc (the writer's face — matches the
#: kunglao-settler input contract) and the ruling doc (its output)
INPUT_REL = "runs/settlement-input-{claim}.json"
VERDICT_REL = "runs/settlement-verdict-{claim}.json"

#: the wire row stamp — the liveness fingerprint's ledger evidence
WIRE_SCHEMA = "settlement-wire/1"

#: the default settler identity the production writer parks for
DEFAULT_SETTLER_IDENTITY = "kunglao-settler"

#: the default rules table (the repo-side settlement contract), resolved
#: off the package root when present — the doc pins it path + sha256
_DEFAULT_RULES = (Path(__file__).resolve().parents[2]
                  / "references" / "contracts" / "reward-rules.yaml")


def eval_settle_enabled() -> bool:
    """True only when the UNBLINDED settle_step judgment was explicitly
    opted back into (eval runs). Anything else — unset, empty, any other
    value — is production blind mode."""
    return os.environ.get(EVAL_SETTLE_ENV) == "1"


def _safe_claim(claim) -> str:
    """A parked path component must be a single safe token (claims are
    worker-writable — the same traversal defense as the launch stash)."""
    from rlvr import incremental_reward as _ir  # noqa: PLC0415 — lazy
    claim = str(claim or "").strip()
    if not _ir._safe_stash_token(claim):
        raise ValueError(
            f"settlement wire: unsafe claim token {claim!r} — not a "
            f"parkable path component")
    return claim


def blind_input_rel(claim) -> str:
    return INPUT_REL.format(claim=_safe_claim(claim))


def verdict_rel(claim) -> str:
    return VERDICT_REL.format(claim=_safe_claim(claim))


def default_rules_path() -> str | None:
    """The repo-side settlement rules table when it exists (the doc may
    legally pin no rules — schema nullable)."""
    return str(_DEFAULT_RULES) if _DEFAULT_RULES.is_file() else None


# ------------------------------------------------------------ the writer

def _scan_window(ws: Path, since_ts: str, until: datetime) -> list[str]:
    """Raw candidate artifact paths for a step window: files under
    evidence/ whose mtime falls in (since_ts, until]. Mechanical and
    producer-blind by construction (names + bytes, never content).
    Read errors degrade to an empty window — the park is caged."""
    try:
        since = _epoch(since_ts)
        if since is None or not isinstance(until, datetime):
            return []
        until_epoch = until.timestamp()
        root = Path(ws) / "evidence"
        if not root.is_dir():
            return []
        out: list[str] = []
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if since < mtime <= until_epoch:
                out.append(p.relative_to(Path(ws)).as_posix())
        return out
    except Exception as exc:  # noqa: BLE001 — the window is telemetry
        warn("rlvr.settlement_wire._scan_window",
             f"{type(exc).__name__}: {exc}")
        return []


_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _epoch(ts: str) -> float | None:
    """The house identity-ts format; anything else is an undecidable
    window (None — the caller degrades to an empty scan, never guesses)."""
    try:
        return datetime.strptime(str(ts), _TS_FMT).replace(
            tzinfo=timezone.utc).timestamp()
    except (ValueError, TypeError):
        return None


def step_window_artifacts(ws, since_ts: str,
                          until: datetime | None = None) -> list[str]:
    """The step's LEGAL raw artifacts: the window scan filtered through
    the scorer's exclusion wall — the single filter point both the
    builder and the settlement gate use, so a forbidden face can never
    be listed even when the scan surfaced it. Sorted, workspace-relative
    posix paths."""
    until = until or datetime.now(timezone.utc)
    return [a for a in _scan_window(Path(ws), since_ts, until)
            if bss.excluded_face(a) is None]


def park_blind_input(ws, claim, artifact_paths, *,
                     identity: str = DEFAULT_SETTLER_IDENTITY,
                     question: str = "",
                     rules_path: str | None = ...) -> dict:
    """Build + park the blind input doc for one claim (THE production
    writer — the issue-709 docstring's open gap, closed).

    Raises ValueError exactly where the whitelist builder raises
    (excluded face, missing artifact, unsafe claim) — the caller cages.
    Idempotent: identical bytes never rewrite; a CHANGED re-park after
    the settler ruled refuses (the ruling window is closed). Returns
    ``{"claim", "path", "doc", "parked", "reason"}``."""
    ws = Path(ws)
    rel = blind_input_rel(claim)  # also the claim-safety gate
    if rules_path is ...:
        rules_path = default_rules_path()
    doc = bss.settler_input(ws, claim=str(claim), identity=identity,
                            artifact_paths=list(artifact_paths or ()),
                            question=str(question or ""),
                            rules_path=rules_path)
    p = ws / rel
    blob = json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n"
    if p.is_file():
        if p.read_text(encoding="utf-8") == blob:
            return {"claim": str(claim), "path": rel, "doc": doc,
                    "parked": False, "reason": "unchanged"}
        if (ws / verdict_rel(claim)).is_file():
            return {"claim": str(claim), "path": rel, "doc": doc,
                    "parked": False,
                    "reason": "verdict-present: the ruling window is "
                              "closed — a changed re-park would "
                              "invalidate the ruling in flight"}
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(blob, encoding="utf-8")
    tmp.replace(p)
    return {"claim": str(claim), "path": rel, "doc": doc,
            "parked": True, "reason": ""}


# ---------------------------------------------------------- the readers

def _load_json(p: Path) -> dict | None:
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def load_parked(ws, claim) -> dict | None:
    p = Path(ws) / blind_input_rel(claim)
    return _load_json(p) if p.is_file() else None


def load_verdict(ws, claim) -> dict | None:
    p = Path(ws) / verdict_rel(claim)
    return _load_json(p) if p.is_file() else None


def pending_settlements(ws) -> list[dict]:
    """Parked blind inputs the settler has NOT ruled on yet — the
    dispatch read face (the orchestrator dispatches kunglao-settler for
    these). ``{"claim", "path"}`` per entry; an unparseable parked doc
    is skipped loudly once, never guessed."""
    ws = Path(ws)
    runs = ws / "runs"
    if not runs.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(runs.glob("settlement-input-*.json")):
        claim = p.stem.removeprefix("settlement-input-")
        if load_parked(ws, claim) is None:
            warn("rlvr.settlement_wire.pending_settlements",
                 f"unparseable parked input {p.name} — skipped")
            continue
        if (runs / f"settlement-verdict-{claim}.json").is_file():
            continue
        out.append({"claim": claim, "path": p.relative_to(ws).as_posix()})
    return out


# ------------------------------------------------------- the consumer

def _sha_recheck(ws: Path, input_doc: dict) -> str | None:
    """Every listed artifact's CURRENT bytes must still hash to the
    parked sha256 — settle over exactly what was blinded. None = ok,
    else the drift reason."""
    from _common import sha256_file
    for a in (input_doc.get("artifacts") or []):
        rel = str((a or {}).get("path") or "")
        want = str((a or {}).get("sha256") or "")
        p = ws / rel
        if not want:
            return f"sha-drift: {rel} carries no pinned sha256"
        if not p.is_file():
            return f"sha-drift: {rel} vanished after the park"
        if sha256_file(p) != want:
            return (f"sha-drift: {rel} changed after the ruling was "
                    f"blinded — settling over unseen bytes would "
                    f"fabricate credit")
    return None


def _verification_ref(ws, claim: str, explicit: str | None) -> str:
    """The verification reference for the mint: the caller's explicit
    path, else the claim's first existing canonical record surface (the
    store resolves the same surfaces — the wire passes the concrete path
    so the store's non-empty-reference precondition is honestly met)."""
    if explicit:
        return str(explicit)
    try:
        import verifier_integrity as _vi  # noqa: PLC0415 — lazy sibling
    except Exception:  # noqa: BLE001 — resolver unavailable: empty ref
        return ""
    for rel in _vi.canonical_records(claim):
        if (Path(ws) / rel).is_file():
            return str(rel)
    return ""


def _claim_transition(ws, claim: str, identity: str, *, settled: bool,
                      oracle_verdict: str, verification: str | None,
                      now) -> dict:
    """The issue-800/issue-809-aligned claim mint — rides claims_store.apply,
    never around it. pass -> settle_proven (the store refuses without a
    PASSED verification record); fail -> settle_refuted; no decisive
    oracle verdict -> no mint (the credit still settles). Never raises;
    the result dict is the loud receipt either way."""
    event = {"pass": "settle_proven", "fail": "settle_refuted"}.get(
        str(oracle_verdict or "").strip().lower())
    if not settled or not event:
        return {"ok": False, "from": None, "to": None, "reason": ""
                if settled else "settlement refused — no mint",
                "event": event or ""}
    if event == "settle_proven":
        verification = _verification_ref(ws, claim, verification)
        if not verification:
            return {"ok": False, "from": None, "to": None,
                    "event": event,
                    "reason": "settlement-without-verification: no "
                              "canonical verification record exists — "
                              "the mint is refused (fail-closed)"}
    try:
        import claims_store as _cs  # noqa: PLC0415 — lazy sibling
        res = _cs.apply(ws, claim, event, actor=f"settler:{identity}",
                        evidence=f"blind-settlement {WIRE_SCHEMA}",
                        verification=str(verification or ""),
                        verification_ts=None)
    except Exception as exc:  # noqa: BLE001 — fail-closed, never a raise
        return {"ok": False, "from": None, "to": None, "event": event,
                "reason": f"claims_store fault {type(exc).__name__}: {exc}"}
    return {"ok": bool(res.ok), "from": res.from_status, "to": res.to_status,
            "event": event, "reason": res.reason}


def _wire_row(ws, *, claim: str, identity: str, input_path: str,
              verdict_path: str, res: dict, mint: dict,
              oracle_verdict: str, artifacts: int, now) -> None:
    """The liveness fingerprint row: ONE settlement-wire/1 row per
    settlement EVENT, carrying the settler identity (production
    settlements show settler-identity rows from the blind path).
    Fail-open telemetry: a ledger fault is ONE warn, never a raise."""
    ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = {"schema": WIRE_SCHEMA, "ts": ts, "claim": str(claim),
           "identity": str(identity), "input_path": input_path,
           "verdict_path": verdict_path, "artifacts": int(artifacts),
           "settled": bool(res.get("settled")),
           "reason": str(res.get("reason") or ""),
           "oracle_verdict": str(oracle_verdict or ""),
           "claim_event": str(mint.get("event") or ""),
           "claim_transition": {"ok": bool(mint.get("ok")),
                                "from": mint.get("from"),
                                "to": mint.get("to"),
                                "reason": str(mint.get("reason") or "")}}
    if _wire_row_seen(ws, str(claim), row):
        return
    if not cl.append(ws, "settlement", row):
        warn("rlvr.settlement_wire", "wire row not appended (loud)")


def _wire_row_seen(ws: Path, claim: str, row: dict) -> bool:
    """Deterministic dedupe: a stop face re-runs settle_face on an
    unchanged workspace every round — the SAME event (same docs, same
    outcome, same mint) appends once; a changed outcome is a new row.
    Content-hash dedupe, never a clock compare."""
    import hashlib
    digest = hashlib.sha256(json.dumps(
        row, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    row["digest"] = digest
    try:
        for prior in cl.read(ws, "settlement"):
            if (str(prior.get("schema") or "") != WIRE_SCHEMA
                    or str(prior.get("claim") or "") != claim):
                continue
            if str(prior.get("digest") or "") == digest:
                return True
        return False
    except Exception:  # noqa: BLE001 — an unreadable ledger appends
        return False


def _ensure_rollout(ws: Path, rollout_id: str, claim: str,
                    oracle_verdict: str, now) -> None:
    """The rollout identity row for the claim (unsettled), created once —
    the ledger settles only known rollout ids. Signals carry the oracle
    verdict face when decisive (the same machine-signal shape the reward
    adapters emit). Fail-loud result, never a raise into the settle."""
    try:
        from rlvr import ledger as rl  # noqa: PLC0415 — lazy sibling
        if rl.fold(ws, rollout_id) is not None:
            return
        signals = []
        if str(oracle_verdict or "").strip().lower() in ("pass", "fail"):
            ts = (now or datetime.now(timezone.utc)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            signals = [{"type": "oracle_verdict",
                        "source": "settlement_wire",
                        "value": str(oracle_verdict), "ts": ts}]
        rl.record(ws, kind="task", anchor=str(claim), signals=signals,
                  rollout_id=rollout_id,
                  ts=(now or datetime.now(timezone.utc)).strftime(
                      "%Y-%m-%dT%H:%M:%SZ"))
    except Exception as exc:  # noqa: BLE001 — the settle below says why
        warn("rlvr.settlement_wire._ensure_rollout",
             f"{rollout_id}: {type(exc).__name__}: {exc}")


def settle_parked(ws, claim, *, oracle_verdict: str | None = None,
                  has_reproducible_evidence: bool = False,
                  verification: str | None = None,
                  cost_tokens: float = 0.0, cost_seconds: float = 0.0,
                  attempt_id: str = "", now=None) -> dict:
    """Settle one claim through the blind face from the parked docs.

    Order: load (missing doc -> loud refusal, nothing settles), the sha
    re-check (drift refuses), the identity match (the ruling grader is
    the blinded grader), then ``settle_blind`` (the blind gate ->
    scalar.validate_verdict_doc stack -> the ledger), then the
    issue-800/issue-809-aligned claim mint, then the wire row (the fingerprint —
    written for refusals too: a settlement event that did not settle is
    LOUD). Never raises on contract violations; returns the receipt."""
    ws = Path(ws)
    now_dt = now or datetime.now(timezone.utc)
    input_path = blind_input_rel(claim)
    verdict_path = verdict_rel(claim)
    input_doc = load_parked(ws, claim)
    if input_doc is None:
        return {"settled": False, "reason": f"input: {input_path} is "
                f"missing or unparseable — nothing settles"}
    verdict_doc = load_verdict(ws, claim)
    if verdict_doc is None:
        return {"settled": False, "reason": f"verdict: {verdict_path} is "
                f"missing or unparseable — nothing settles"}
    def _refuse(reason: str) -> dict:
        res = {"settled": False, "reason": reason}
        mint = {"ok": False, "from": None, "to": None, "event": "",
                "reason": reason}
        _wire_row(ws, claim=str(claim),
                  identity=str(input_doc.get("identity") or ""),
                  input_path=input_path, verdict_path=verdict_path,
                  res=res, mint=mint,
                  oracle_verdict=str(oracle_verdict or ""),
                  artifacts=len(input_doc.get("artifacts") or []),
                  now=now_dt)
        return res

    # the TRUST wall first (path-only, no reads): a doc carrying a
    # forbidden face never settles — its sha256 field is irrelevant
    gate = bss.check_blind_input(input_doc)
    if not gate["ok"]:
        return _refuse(gate["reason"])
    identity = str(input_doc.get("identity") or "").strip()
    if str(verdict_doc.get("identity") or "").strip() != identity:
        return _refuse(
            f"identity: the ruling grader "
            f"{str(verdict_doc.get('identity') or '')!r} is not the "
            f"blinded grader {identity!r}")
    # then the BYTES wall: settle over exactly what was blinded
    drift = _sha_recheck(ws, input_doc)
    if drift:
        return _refuse(drift)
    verdict = str(oracle_verdict) if oracle_verdict is not None else None
    if verdict is None:
        try:
            from rlvr import reward as _rw  # noqa: PLC0415 — lazy sibling
            verdict = _rw._oracle_verdict(ws) or ""
        except Exception:  # noqa: BLE001 — unmeasured settles creditless
            verdict = ""
    # the claim-grained rollout anchor (issue-800: settlement rows are
    # claim-grained): ensure the identity row exists — the parked input
    # IS the production event (the step ran; its artifacts are pinned)
    rollout_id = f"task/{claim}"
    _ensure_rollout(ws, rollout_id, str(claim), verdict, now_dt)
    res = bss.settle_blind(
        ws, rollout_id, verdict_doc, input_doc=input_doc,
        oracle_verdict=verdict,
        has_reproducible_evidence=bool(has_reproducible_evidence),
        claim=str(claim), cost_tokens=float(cost_tokens),
        cost_seconds=float(cost_seconds), attempt_id=str(attempt_id),
        now=now_dt.strftime(_TS_FMT))  # the ledger's identity-ts string
    mint = _claim_transition(ws, str(claim), identity, settled=bool(
        res.get("settled")), oracle_verdict=verdict,
        verification=verification, now=now_dt)
    res["claim_transition"] = mint
    _wire_row(ws, claim=str(claim), identity=identity,
              input_path=input_path, verdict_path=verdict_path,
              res=res, mint=mint, oracle_verdict=verdict,
              artifacts=len(input_doc.get("artifacts") or []), now=now_dt)
    return res


def settle_face(ws, *, oracle_verdict: str | None = None,
                has_reproducible_evidence: bool = False,
                verification: str | None = None, now=None) -> list[dict]:
    """The production stop-face driver: settle every parked claim that
    has a ruling. Each claim rides its own cage — one bad doc is ONE
    warn, never a raise into the hook path."""
    receipts: list[dict] = []
    ws = Path(ws)
    runs = ws / "runs"
    if not runs.is_dir():
        return receipts
    for inp in sorted(runs.glob("settlement-input-*.json")):
        claim = inp.stem.removeprefix("settlement-input-")
        if not (runs / f"settlement-verdict-{claim}.json").is_file():
            continue  # not ruled yet — the dispatch face owns it
        try:
            receipts.append(settle_parked(
                ws, claim, oracle_verdict=oracle_verdict,
                has_reproducible_evidence=has_reproducible_evidence,
                verification=verification, now=now))
        except Exception as exc:  # noqa: BLE001 — one cage per claim
            warn("rlvr.settlement_wire.settle_face",
                 f"{claim}: {type(exc).__name__}: {exc}")
    return receipts

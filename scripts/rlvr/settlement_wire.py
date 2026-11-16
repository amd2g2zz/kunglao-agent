# -*- coding: utf-8 -*-
"""rlvr/settlement_wire.py — the blind settlement WIRE (issue-802).

The blind-settlement card (issue-687) shipped the barrier family (the
whitelist builder, the settlement gate, the read barrier, the
kunglao-settler face) and left it
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

THE STOP FACE IS BLIND-ONLY. The production stop face has no unblinded
mode: the unblinded ``settle_step`` judgment survives only as
``rlvr.step_grain.settle_step``'s library face for direct callers
(eval harnesses); no environment value can steer a production stop back
into it. The liveness fingerprint rides the ``settlement-wire/1`` rows
in the consolidated settlement ledger: a blind settlement event always
lands a settler-identity row — production settlements show
settler-identity rows from the blind path.

THE LEARNER FEED — a settled blind verdict BANKS into the q-cell fold
(``rlvr.q_cells``) on the producing dispatch's arm: the claim resolves
to the dispatch id the dispatch ledger recorded, and the censoring
routes (``rlvr.scalar.settlement_route``) gate the bank on the SAME
faces the round-credit close path books — the register status and the
ACT OUTCOME word the stop face persisted beside the input doc (a
quota/timeout/blocked act banks nothing, its ruling notwithstanding).
One bank per dispatch holds (a replayed settlement never double-banks;
refinements ride the credit-amendment face). Fail-open telemetry: a
bank failure is ONE warn, never a settlement break.

Fail-closed on trust, fail-open on telemetry: a refused settlement
writes nothing and says why; the wire row is the loud receipt either
way. Zero judgment here: no sampling slot, no model call, no narrative
field passes through.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from kunglao_log import warn
from rlvr import consolidated_ledger as cl
from rlvr import learning_seal as _seal
from rlvr import settlement_scorer as bss

#: the parked blind input doc (the writer's face — matches the
#: kunglao-settler input contract), the ruling doc (its output), and
#: the act-outcome sidecar (the stop face's outcome word — consumer
#: side only, never a settler input: the ruling stays artifact-blind)
INPUT_REL = "runs/settlement-input-{claim}.json"
VERDICT_REL = "runs/settlement-verdict-{claim}.json"
ACT_REL = "runs/settlement-act-{claim}.json"

#: the act-outcome sidecar's schema stamp
ACT_SCHEMA = "settlement-act/1"

#: the verdict doc's schema stamp (the writer's landing wall)
VERDICT_SCHEMA = "settlement-verdict/1"

#: the wire row stamp — the liveness fingerprint's ledger evidence
WIRE_SCHEMA = "settlement-wire/1"

#: the default settler identity the production writer parks for
DEFAULT_SETTLER_IDENTITY = "kunglao-settler"

#: the default rules table (the repo-side settlement contract), resolved
#: off the package root when present — the doc pins it path + sha256
_DEFAULT_RULES = (Path(__file__).resolve().parents[2]
                  / "references" / "contracts" / "reward-rules.yaml")


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


def act_outcome_rel(claim) -> str:
    return ACT_REL.format(claim=_safe_claim(claim))


def default_rules_path() -> str | None:
    """The repo-side settlement rules table when it exists (the doc may
    legally pin no rules — schema nullable)."""
    return str(_DEFAULT_RULES) if _DEFAULT_RULES.is_file() else None


# ------------------------------------------------- the question resolver

#: the two value-function sources the resolver joins: the register row
#: carries ``answers_question`` (the pq id), the task spec maps that id
#: to the question text.
REGISTER_REL = "claim-register.yaml"
TASK_SPEC_REL = "task_spec.yaml"


def _yaml_doc(path: Path) -> dict:
    """Load one YAML mapping; a missing or unreadable file is ``{}``
    (the question field is context for the settler, never a gate). The
    catch is the full unreadable family — io, syntax, a non-UTF-8
    payload (UnicodeDecodeError), and the recursion blow-up a deeply
    nested spec triggers."""
    import ws_yaml  # noqa: PLC0415 — leaf face, import-light
    try:
        doc = ws_yaml.yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError, ws_yaml.yaml.YAMLError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _claim_qid(ws: Path, claim: str) -> str:
    """The claim's ``answers_question`` pq id ("" when the row, the
    field, or the register file is absent)."""
    for row in (_yaml_doc(ws / REGISTER_REL).get("claims") or []):
        if isinstance(row, dict) and str(row.get("id") or "") == claim:
            return str(row.get("answers_question") or "").strip()
    return ""


def _question_text(item) -> tuple[str, str]:
    """(qid, text) for one raw ``primary_questions`` item.

    Three accepted shapes, mirroring the canonical parse: the template
    dict (``id`` plus ``q``/``question``), the legacy one-key mapping
    (qid -> free text), and a bare qid string (its own text)."""
    if isinstance(item, str):
        return item.strip(), item.strip()
    if not isinstance(item, dict) or not item:
        return "", ""
    if "id" in item:
        qid = str(item.get("id") or "").strip()
        text = str(item.get("q") or item.get("question") or "").strip()
        return qid, text or qid
    if len(item) == 1:
        qid, text = next(iter(item.items()))
        qid = str(qid or "").strip()
        return qid, str(text or "").strip() or qid
    return "", ""


def claim_question(ws, claim) -> str:
    """The value question the claim answers, resolved register ->
    task_spec (the production park passed nothing here, so every blind
    doc lost the question it was judging).

    ``claim-register`` rows carry ``answers_question`` (the pq id); the
    task spec maps that id to the question text. Any missing link
    degrades to "" — the settler judges artifacts, never a guessed
    question."""
    ws = Path(ws)
    qid = _claim_qid(ws, str(claim or ""))
    if not qid:
        return ""
    raw = _yaml_doc(ws / TASK_SPEC_REL).get("primary_questions")
    if isinstance(raw, dict):
        # a top-level mapping: keys are qids, values free text
        if qid not in raw:
            return ""
        text = raw[qid]
        return (str(text).strip() if isinstance(text, str) else "") or qid
    for item in (raw or []):
        iqid, text = _question_text(item)
        if iqid and iqid == qid:
            return text
    return ""


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
                     question: str = ...,
                     rules_path: str | None = ...,
                     act_outcome: str = "") -> dict:
    """Build + park the blind input doc for one claim (THE production
    writer — the issue-709 docstring's open gap, closed).

    ``question`` defaults to the claim's resolved value question
    (``claim_question``: register ``answers_question`` through the task
    spec), so an omitted argument can never re-open the empty-question
    hole; an explicit ``question=""`` stays empty.

    ``act_outcome`` (the stop face's own outcome word, the closed
    act-outcome vocabulary) persists to the consumer-side sidecar
    (``act_outcome_rel``) — the censoring route's outcome face at
    settle time; the ruling doc never carries it (the settler stays
    artifact-blind).

    Raises ValueError exactly where the whitelist builder raises
    (excluded face, missing artifact, an empty artifact list, unsafe
    claim) — the caller cages.
    Idempotent: identical bytes never rewrite; a CHANGED re-park after
    the settler ruled refuses (the ruling window is closed). Returns
    ``{"claim", "path", "doc", "parked", "reason"}``."""
    ws = Path(ws)
    rel = blind_input_rel(claim)  # also the claim-safety gate
    word = str(act_outcome or "").strip()
    if word:
        side = ws / act_outcome_rel(claim)
        blob = json.dumps({"schema": ACT_SCHEMA, "claim": str(claim),
                           "outcome": word},
                          ensure_ascii=False, sort_keys=True) + "\n"
        if not (side.is_file()
                and side.read_text(encoding="utf-8") == blob):
            tmp = side.with_suffix(".json.tmp")
            tmp.write_text(blob, encoding="utf-8")
            tmp.replace(side)
    if rules_path is ...:
        rules_path = default_rules_path()
    if question is ...:
        question = claim_question(ws, claim)
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
    """The verdict doc's read face. Armed, only a SEAL-VALID doc
    resolves: the sanctioned writer (``write_sealed_verdict``) signs at
    write, so a verdict file that carries no valid seal was written by
    someone else — a worker-forged ruling is refused (None + ONE loud
    warn) and the claim stays pending, never settled from a
    worker-writable file. Unarmed the doc passes unchanged (byte-
    identical legacy face)."""
    p = Path(ws) / verdict_rel(claim)
    doc = _load_json(p) if p.is_file() else None
    if doc is None:
        return None
    if not _seal.armed():
        return doc
    ok, why = _seal.verify_row(doc)
    if ok:
        return doc
    warn("rlvr.settlement_wire.load_verdict",
         f"{verdict_rel(claim)} refused: not a harness-written verdict "
         f"({why}) — nothing settles from a worker-writable file; the "
         f"ruling must land through the sanctioned writer")
    return None


def write_sealed_verdict(ws, claim, doc) -> dict:
    """THE SANCTIONED VERDICT WRITER — the face that turns a settler
    ruling into the canonical verdict file. The doc rides stdin-shaped
    caller input, so the landing wall is strict: a JSON mapping with the
    ``settlement-verdict/1`` stamp, a claim field matching the parked
    claim, and a non-empty grader identity (credit without a named
    grader does not settle). Any caller-supplied ``seal`` block is
    dropped — the harness seal is minted HERE, from the channel key
    (armed; unarmed the doc lands unsealed, byte-identical to the
    legacy file the channel rides). The write is atomic
    (tmp + replace) at ``verdict_rel(claim)``. Raises ValueError on any
    wall miss — the caller (settler face or CLI) refuses loudly."""
    ws = Path(ws)
    rel = verdict_rel(claim)  # also the claim-safety gate
    if not isinstance(doc, dict):
        raise ValueError("verdict doc must be a JSON mapping")
    if str(doc.get("schema") or "") != VERDICT_SCHEMA:
        raise ValueError(
            f"verdict doc schema must be {VERDICT_SCHEMA!r}, got "
            f"{str(doc.get('schema') or '')!r}")
    if str(doc.get("claim") or "") != str(claim):
        raise ValueError(
            f"verdict doc claim {str(doc.get('claim') or '')!r} does not "
            f"match the parked claim {str(claim)!r}")
    if not str(doc.get("identity") or "").strip():
        raise ValueError(
            "verdict doc carries no grader identity — nothing settles "
            "from an anonymous ruling")
    body = {k: v for k, v in doc.items() if k != "seal"}
    sealed = _seal.sign_row(body)
    blob = json.dumps(sealed, ensure_ascii=False, sort_keys=True) + "\n"
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(blob, encoding="utf-8")
    tmp.replace(p)
    return {"path": rel, "sealed": bool(sealed.get("seal")),
            "doc": sealed}


def load_act_outcome(ws, claim) -> str:
    """The producing act's settled outcome word ("" when the sidecar is
    absent or unreadable) — the censoring route's outcome face,
    persisted at park time from the stop face's own outcome resolution.
    A sidecar word that is not machine vocabulary censors nothing: the
    route classifies unknown words as strategy outcomes, exactly like
    the round-credit close path."""
    doc = _load_json(Path(ws) / act_outcome_rel(claim))
    return str((doc or {}).get("outcome") or "").strip()


def pending_settlements(ws) -> list[dict]:
    """Parked blind inputs the settler has NOT ruled on yet — the
    dispatch read face (the orchestrator dispatches kunglao-settler for
    these). ``{"claim", "path"}`` per entry.

    Per-file cage: ANY unreadable doc — syntax, nesting blow-up
    (RecursionError), unsafe claim token, io error — is ONE warn and is
    skipped; one bad file must never suppress the drain for the rest (a
    producer could otherwise switch off the very dispatch that polices
    it). A claim counts as ruled only when its verdict PARSES: a corrupt
    verdict keeps the claim pending, matching what ``settle_parked``
    requires (``is_file`` alone would strand it as "ruled but
    unsettleable")."""
    ws = Path(ws)
    runs = ws / "runs"
    if not runs.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(runs.glob("settlement-input-*.json")):
        claim = p.stem.removeprefix("settlement-input-")
        try:
            if load_parked(ws, claim) is None:
                warn("rlvr.settlement_wire.pending_settlements",
                     f"unparseable parked input {p.name} — skipped")
                continue
            ruled = load_verdict(ws, claim) is not None
        except Exception as exc:  # noqa: BLE001 — one bad doc is ONE warn
            warn("rlvr.settlement_wire.pending_settlements",
                 f"{p.name}: {type(exc).__name__}: {exc} — skipped")
            continue
        if ruled:
            continue
        out.append({"claim": claim, "path": p.relative_to(ws).as_posix()})
    return out


# ------------------------------------------------------- the learner feed

def _claim_status(ws: Path, claim: str) -> str:
    """The claim's CURRENT register status ("" when the row, the field,
    or the register file is absent) — the censoring route reads the
    lifecycle face at settle time, never a guessed word."""
    for row in (_yaml_doc(ws / REGISTER_REL).get("claims") or []):
        if isinstance(row, dict) and str(row.get("id") or "") == claim:
            return str(row.get("status") or "").strip()
    return ""


def _producing_dispatch(ws: Path, claim: str) -> str:
    """The dispatch id the dispatch ledger recorded for this claim's
    producing dispatch — the settled credit's q-cell key. Soft face: no
    committed row keeps the claim token (the q-cell match face accepts
    either identity); the ledger id is the one key when it exists."""
    try:
        import claims_store as _cs  # noqa: PLC0415 — lazy sibling
        led = _cs.latest_committed_dispatch(ws, claim)
        if led:
            return str(led.get("dispatch_id") or claim)
    except Exception as exc:  # noqa: BLE001 — telemetry, never the settle
        warn("rlvr.settlement_wire.bank",
             f"dispatch-ledger resolve failed: "
             f"{type(exc).__name__}: {exc}")
    return claim


def _bank_settled_verdict(ws: Path, claim: str, res: dict, *,
                          act_outcome: str) -> dict | None:
    """Bank one settled blind verdict into the q-cell fold — the learning
    feed's consumer face. Order: only a SETTLED verdict reaches here;
    the censoring routes (``rlvr.scalar.settlement_route`` — the same
    face the round-credit close path books, driven by the same act
    outcome word the stop face settled under) gate the bank: a censored
    or pending outcome records its route on the receipt (marker, class,
    reason) and banks NOTHING. One bank per dispatch: an identity that already carries
    banked mass is skipped (``already-banked``) — replays never
    double-bank and a credit-amendment refinement is never clobbered;
    a dispatch with banked STEP credit takes the calibration residual
    face (``observe_step_calibration``), the normal no-step shape takes
    ``observe_settlement``. The banked row carries the
    ``blind-settlement`` ownership marker and the bank's companion legs
    (the cross-task store row, the claim-terminal rollout return) ride
    this face — the round-credit bank's one-bank-per-dispatch guard
    hands their ownership over. Fail-open telemetry: a bank failure is
    ONE rate-limited warn, never a settlement break. None = the bank
    face did not run (unsettled)."""
    if not res.get("settled"):
        return None
    settlement = res.get("settlement") or {}
    try:
        from rlvr import q_cells as _qc  # noqa: PLC0415 — lazy sibling
        from rlvr import scalar as _sc  # noqa: PLC0415 — lazy sibling
        target = _producing_dispatch(ws, claim)
        route = _sc.settlement_route(
            _claim_status(ws, claim), str(act_outcome or ""),
            [a for a in _sc.fact_artifacts(ws)
             if str(a.get("claim_id") or "") == claim])
        if route is not None:
            return {"appended": False, "matched": False,
                    "route": route[0], "class": route[1].get("class"),
                    "reason": str(route[1].get("reason") or route[0]),
                    "dispatch_id": target, "beta_updated": False}
        mass = _qc.banked_mass(ws, target)
        if mass is None:
            warn("rlvr.settlement_wire.bank",
                 f"{target}: log unreadable — the bank pass skipped")
            return {"appended": False, "matched": False,
                    "route": None, "class": None, "reason": "log-unreadable",
                    "dispatch_id": target, "beta_updated": False}
        if mass[2] > 0:
            return {"appended": False, "matched": True, "route": None,
                    "class": None, "reason": "already-banked",
                    "dispatch_id": target, "beta_updated": False}
        reward = float(settlement.get("reward") or 0.0)
        value = _sc.clamp_credit(reward)
        step_sum, step_n = _qc.step_credit_totals(ws, target)
        if step_n > 0:
            d_s, d_f = _sc._calibration_delta(
                value, step_sum, step_n,
                band_ceil=_qc.OBSERVATION_BAND_CEIL)
            bank = _qc.observe_step_calibration(
                ws, target, d_s, failure_delta=d_f,
                reason="blind-settlement")
        else:
            bank = _qc.observe_settlement(
                ws, target, value, reward=reward,
                confidence_band=str(settlement.get("band") or "") or None,
                reason="blind-settlement")
        if not (bank.get("matched") and bank.get("appended")) \
                or 0.0 < value <= _qc.OBSERVATION_BAND_CEIL:
            # an unmatched/unappended bank, or the massless information
            # option: no mass landed, so the companion legs stay with
            # whichever face's bank eventually carries the mass
            return dict(bank, route=None)
        # the bank's companion legs follow the bank (the same satellites
        # the round-credit bank drives — its one-bank-per-dispatch guard
        # hands their ownership to this face): the cross-task store row
        # and the claim-terminal rollout return. Fail-open telemetry.
        try:
            from rlvr import strategy_store as _store  # noqa: PLC0415
            _store.append_store_row(
                ws, method_family=str(bank.get("method_family") or ""),
                status=str(settlement.get("band") or "TRAJECTORY"),
                credit=value, dispatch_id=target, claim=str(claim),
                arm_key=bank.get("arm_key"),
                fingerprint=bank.get("fingerprint"), facts_citing=0)
        except Exception as exc:  # noqa: BLE001 — telemetry, never settle
            warn("rlvr.settlement_wire.bank.store",
                 f"{target}: {type(exc).__name__}: {exc}")
        try:
            from rlvr import l1_value as _l1  # noqa: PLC0415
            _l1.record_terminal_return(ws, str(claim), reward,
                                       signature=bank.get("signature_hash"))
        except Exception as after_exc:  # noqa: BLE001 — telemetry
            warn("rlvr.settlement_wire.bank.l1",
                 f"{claim}: {type(after_exc).__name__}: {after_exc}")
        return dict(bank, route=None)
    except Exception as exc:  # noqa: BLE001 — telemetry, never settlement
        warn("rlvr.settlement_wire.bank",
             f"{claim}: {type(exc).__name__}: {exc}")
        return None


# ------------------------------------------------------------ the consumer

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
    LOUD). A settled verdict then banks into the q-cell fold (the
    learner feed), censored by the act outcome the stop face parked
    alongside the input doc. Never raises on contract violations;
    returns the receipt."""
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
    # the learner feed: the settled verdict banks on the producing
    # dispatch's arm, censored by the act outcome the stop face parked
    # (fail-open telemetry — never the settle receipt)
    bank = _bank_settled_verdict(ws, str(claim), res,
                                 act_outcome=load_act_outcome(ws, claim))
    if bank is not None:
        res["q_cell_bank"] = bank
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

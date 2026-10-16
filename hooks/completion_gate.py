#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hooks/completion_gate.py — Stop-hook shim for the code-owned completion gate (#55).

Thin wrapper around scripts/completion_gate.py::judge. Reads the Claude Code
Stop payload, resolves the workspace, strict-activates (mirrors
hooks/state_anchor.py #44), finds task-oracle.yaml, calls judge, and emits a
Stop-hook {"decision": "block", "reason": "..."} when judge returns non-zero.

Activation gating: current fail-open / fail-closed boundaries (post
#147/#199/#200):
  - no workspace markers (neither claim-register.yaml nor .hook_state.json
    under cwd or cwd/malware-analysis-workspace) → pass-through (D9:
    nothing kunglao-related is running)
  - workspace resolved but NOT activated (no .hook_state.json, gate not
    strict-active, or expired) → pass-through (the gate is opt-in via
    activation)
  - activated + NO task-oracle.yaml → BLOCK, exit 3 (#200: an activated
    workspace must be oracle-anchored at Phase 0 — a missing oracle means
    the run was never anchored, and refusing completion is fail-closed,
    NOT the pre-#200 oracle-presence pass-through)
  - activated + oracle present + empty task_text → block, exit 3 (D6:
    malformed oracle is the genuine self-anchor fingerprint)
  - activated + oracle present + unsatisfied → block, exit 1/2
  - activated + oracle would PASS items but task_text anchors are absent
    from task_spec.yaml primary_questions → block, exit 4 (#664
    INTENT_UNMATCHED — the gate refuses PASS until every user concern is
    owned by a PQ; precedence 3>2>1>4>0 means this fires only at the
    would-be-PASS point)
  - activated + oracle PASSes items + runs/notes-due.yaml still lists owed
    durable result notes → block, exit 5 NOTES_DUE (#762 K1b — same
    would-be-PASS interception pattern as exit 4; the queue names the
    claims, writing notes/<claim-id>.md clears it on the next Stop.
    Fail-open double-cage: missing/corrupt/malformed queue = pass-through)
  - stop_hook_active=true (second stop) → BLOCK unless the gate's OWN
    sealed sanction verifies. The oracle's adjudication block is
    agent-writable advisory evidence: its `second_stop` flag only ARMS the
    second-stop face, and its decision text is never read for release.
    The release key is an HMAC-sealed record in the shim-owned store
    outside the workspace, bound to a decision the GATE derived:
    minted by the gate ONLY at a first stop whose judge verdict is PASS
    (a judge-blocked stop mints nothing — a block written before or
    between stops can never carry a seal), or minted by the operator CLI
    — the HUMAN-ONLY trust-root face for closing with items open, whose
    use is logged loudly. Any mismatch/absence keeps blocking, with the
    repair path in the reason (#147/#199: an unsanctioned second stop
    must not silently pass; only that sanctioned-PASS record passes)
  - any exception → pass-through (FAIL_OPEN: a completion-gate failure must
    never deadlock the session — unreadable oracle / judge errors fail open)

Emits Claude Code Stop-hook JSON to block; empty stdout + exit 0 to pass. The
pure judge() function does NOT fail open (it returns exit 3 on bad input) —
only THIS shim does. Mirrors state_anchor's _resolve_workspace +
_kunglao_active + FAIL_OPEN structure (#44).
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
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from _path_hygiene import load_module_by_path, scripts_on_path  # #671 sys.path hygiene authority

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/
ORACLE_FILE = "task-oracle.yaml"
# #472: the shim's refusal codes DERIVE from the registry (scripts/
# hook_exit_codes.py — the single source of truth) in a SEPARATE
# fail-open block placed after the _path_hygiene one: a registry import
# failure must not drop the canonical kunglao_log.warn into its stderr
# fallback arm. The per-constant literal fallbacks preserve the
# partial-deploy lifeline AND the source-substring drift pin
# (test_notes_closure_762); the registry-vs-shim VALUE pin lives in
# tests/test_hook_exit_codes.py.
# Semantics (shim-face only — judge() stays workspace-pure; the
# scripts-side judge keeps its {0..4} table):
#   5 = #762 K1b owed durable-result notes; 6 = #834 notes structural
#   discrimination; 7 = #826 summary structural contract (uncertainty
#   must not evaporate in the user-facing transcription).
try:
    from hook_exit_codes import ExitCode as _ExitCode
    EXIT_NOTES_DUE = int(_ExitCode.NOTES_DUE)
    EXIT_NOTES_FAKE = int(_ExitCode.NOTES_FAKE)
    EXIT_SUMMARY_FAKE = int(_ExitCode.SUMMARY_FAKE)
except Exception:  # noqa: BLE001 — fail-open literal fallback (partial deploy)
    EXIT_NOTES_DUE = 5
    EXIT_NOTES_FAKE = 6
    EXIT_SUMMARY_FAKE = 7
# #831: ledger-anchored second-stop sanction event type (ledger CONTRACT line
# format identical to rollup._append_ledger: json.dumps ensure_ascii=False).
SECOND_STOP_EVENT = "second_stop_pass"
# The second-stop release key is the gate's OWN sealed sanction, never the
# agent-writable oracle block: the record is written OUTSIDE the workspace
# tree and HMAC-bound to the block bytes frozen at the first stop that saw
# it. Mirrors the review-gate seal posture: the key is pinned at a fixed
# path outside the workspace (no env override face), verification uses
# hmac.compare_digest, and the record carries a versioned schema stamp.
# Both paths resolve the key through ONE helper (_sanction_keyfile) so mint
# and verify can never split onto different keys.
SANCTION_SCHEMA = "stop-sanction/1"
SANCTION_KEY_PATH = Path(
    os.path.expanduser("~/.claude/kunglao-sanction.key"))
SANCTION_STORE_DIR = Path(os.path.expanduser("~/.claude/kunglao/sanctions"))
_SANCTION_KEY_MIN = 32


def _json_safe(obj):
    """#47: recursive normalization at the json serialization boundary.
    yaml.safe_load turns an UNQUOTED timestamp (last_decision_at:
    2026-09-04T10:00:00Z) into a datetime object, which json.dumps refuses.
    datetime/date → isoformat() string: deterministic and stable, so the
    canonical sha form is "json with datetimes as isoformat strings" and a
    record read as a datetime anchors to the SAME sha as the same record
    written as an isoformat string. No yaml representer is touched — this
    changes only what json.dumps sees, never what safe_load returns."""
    if obj is None or isinstance(obj, (str, bool, int, float)):
        return obj
    if isinstance(obj, dict):
        return {(k if isinstance(k, str) else _json_safe(k)): _json_safe(v)
                for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    return str(obj)


def _secondstop_record_sha(adj: dict) -> str:
    """Canonical sha256 of the oracle's stop_hook_active adjudication map.
    Canonical form: sort_keys json over the #47-normalized map — datetime/
    date values become isoformat strings (#47), so json-native maps keep
    their exact pre-#47 sha (existing ledger anchors stay valid)."""
    canonical = json.dumps(_json_safe(adj), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _append_anchor(ledger: Path, entry: dict) -> None:
    """Minimal append writer with the #584 line CONTRACT (json.dumps
    ensure_ascii=False + newline); the shim must not import the whole
    rollup machinery for one append."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _secondstop_anchor(ws: Path, adj: dict) -> tuple[bool, str | None]:
    """#831: reconcile the oracle's second-stop exemption against the
    append-only ledger. First sanctioned sighting anchors it (legacy
    back-anchor); later divergence (rewrite/backdate) fails closed.
    Ledger unreadable / anchor write failure → BLOCK (cannot prove the
    sanction). Returns (allow, block_reason)."""
    h = _secondstop_record_sha(adj)
    ledger = ws / ".convergence_ledger.jsonl"
    anchored: set = set()
    if ledger.exists():
        try:
            for line in ledger.read_text(
                    encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("type") == SECOND_STOP_EVENT:
                    anchored.add(row.get("record_sha256"))
        except OSError as exc:
            return False, (f"second-stop sanction unverifiable - ledger "
                           f"unreadable ({type(exc).__name__}) (#831)")
    if h in anchored:
        return True, None
    if anchored:
        return False, ("second-stop exemption record does not match the "
                       "ledger anchor - the oracle adjudication was "
                       f"rewritten or backdated after its first sanction "
                       f"(#831)")
    # first sighting → anchor it (legacy back-anchor, #831 item 3)
    entry = {"type": SECOND_STOP_EVENT, "action": SECOND_STOP_EVENT,
             "actor": "completion_gate", "record_sha256": h,
             "ts": datetime.now(tz=timezone.utc).strftime(
                 "%Y-%m-%dT%H:%M:%SZ"),
             "detail": "second-stop PASS sanction anchored (#831)"}
    try:
        _append_anchor(ledger, entry)
    except OSError as exc:
        return False, (f"second-stop sanction could not be anchored - "
                       f"ledger write failed ({type(exc).__name__}) (#831)")
    return True, None


# ---------- the gate-owned sealed sanction (the second-stop release key) ----------

def _sanction_keyfile() -> Path:
    """ONE key resolution point shared by mint and verify — a split
    resolution would let a record be minted under one key and checked
    under another. Resolved once at import from the invoking process's
    environment; the hook process is harness-spawned, the same trust
    posture as the review-gate key."""
    return SANCTION_KEY_PATH


def _ws_fingerprint(ws: Path) -> str:
    """Opaque workspace identity: sha256 over the resolved absolute path.
    Hashed so the store's file names never leak workspace locations; the
    resolved path also makes symlinked cwd spellings of one workspace
    fingerprint identically."""
    return hashlib.sha256(
        str(Path(ws).resolve()).encode("utf-8")).hexdigest()


def _sanction_sign(key: bytes, ws_fp: str, origin: str, decision: str,
                   record_sha: str, minted_ts: int) -> str:
    """HMAC over the full record identity (schema + workspace + sealing
    face + decision + frozen block sha + mint time), NUL-joined like the
    review-gate seal."""
    payload = "\0".join([SANCTION_SCHEMA, ws_fp, origin, decision,
                         record_sha, str(minted_ts)])
    return hmac.new(key, payload.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def _sanction_record_path(ws: Path) -> Path:
    return SANCTION_STORE_DIR / (_ws_fingerprint(ws) + ".json")


def _sanction_mint(ws: Path, adj: dict, decision: str = "PASS",
                   origin: str = "gate") -> bool:
    """Seal the adjudication state into the gate-owned store: a versioned
    record binding the workspace, the sealing face, the decision and the
    block's canonical sha at mint time. `decision` is asserted by the
    CALLER — the gate passes its own judge verdict, the operator CLI
    passes the human-asserted decision — and is never read out of the
    agent-authored block. Best-effort by design — a missing/short key or
    an unwritable store returns False (never raises); sealing never moves
    the first-stop verdict, and the second stop's verify is the
    fail-closed face that will then block with the operator repair path."""
    decision = str(decision or "").strip()
    if not decision:
        return False
    try:
        key = _sanction_keyfile().read_bytes().strip()
    except OSError:
        return False
    if len(key) < _SANCTION_KEY_MIN:
        return False
    fp = _ws_fingerprint(ws)
    record_sha = _secondstop_record_sha(adj)
    minted_ts = int(time.time())
    record = {
        "schema": SANCTION_SCHEMA,
        "ws_fingerprint": fp,
        "origin": origin,
        "decision": decision,
        "record_sha256": record_sha,
        "minted_ts": minted_ts,
    }
    record["hmac"] = _sanction_sign(key, fp, origin, decision, record_sha,
                                    minted_ts)
    try:
        SANCTION_STORE_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(SANCTION_STORE_DIR, 0o700)
        _sanction_record_path(ws).write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return False
    return True


def _sanction_verify(ws: Path, adj: dict) -> tuple[bool, str | None]:
    """The second-stop release pre-check. The gate's OWN seal must exist,
    verify under hmac.compare_digest, match the on-disk adjudication block
    exactly (a post-mint edit of task-oracle.yaml is detected as tamper),
    and carry the required PASS decision. Any absence or mismatch blocks —
    blocking is the safe direction for a completion gate — and the reason
    carries the operator repair path. Never raises."""
    fp = _ws_fingerprint(ws)
    try:
        raw = _sanction_record_path(ws).read_text(encoding="utf-8")
        record = json.loads(raw)
    except OSError:
        return False, ("second-stop sanction is not sealed by the gate - "
                       "the oracle's adjudication block is advisory only "
                       "and cannot release a stop; the operator must seal "
                       "it (python hooks/completion_gate.py mint-sanction "
                       "<workspace> PASS) or the gate seals it at the next "
                       "first stop that sees the block")
    except ValueError:
        return False, ("sealed sanction record is corrupt/unreadable - "
                       "refusing release")
    if not isinstance(record, dict) or record.get("schema") != SANCTION_SCHEMA:
        return False, ("sealed sanction record carries an unknown schema - "
                       "refusing release")
    if record.get("ws_fingerprint") != fp:
        return False, ("sealed sanction record belongs to a different "
                       "workspace - refusing release")
    try:
        key = _sanction_keyfile().read_bytes().strip()
    except OSError:
        return False, ("sanction key file is missing - the operator must "
                       "provision it (python hooks/completion_gate.py "
                       "sanction-key-init); blocking closed")
    if len(key) < _SANCTION_KEY_MIN:
        return False, ("sanction key is too short - refusing release")
    expect = _sanction_sign(key, fp, str(record.get("origin") or ""),
                            str(record.get("decision") or ""),
                            str(record.get("record_sha256") or ""),
                            record.get("minted_ts"))
    if not hmac.compare_digest(str(record.get("hmac") or ""), expect):
        return False, ("sealed sanction HMAC invalid (forged or altered "
                       "record) - refusing release")
    if str(record.get("record_sha256") or "") != _secondstop_record_sha(adj):
        return False, ("task-oracle.yaml's adjudication block was altered "
                       "after the sanction was sealed (record sha mismatch)"
                       " - tamper detected, refusing release")
    if str(record.get("decision") or "") != "PASS":
        return False, ("sealed sanction decision is not the required PASS "
                       "verdict - refusing release")
    return True, None


def _first_stop_seal(ws: Path, oracle: dict) -> None:
    """Seal the gate's OWN PASS verdict at a first stop. Called ONLY where
    the judge has already returned 0 — a judge-blocked stop mints nothing,
    so a block the agent wrote before or between the stops can never carry
    a gate seal. The block's `second_stop` flag arms the second-stop face;
    its decision text is advisory and never read here. Best-effort: called
    inside a guarded block; never moves the first-stop verdict."""
    if not isinstance(oracle, dict):
        return
    adj = (oracle.get("adjudication") or {}).get("stop_hook_active")
    if isinstance(adj, dict) and adj.get("second_stop"):
        _sanction_mint(ws, adj)


# ---------- workspace + activation (mirror hooks/state_anchor.py #44) ----------

def _resolve_workspace(payload: dict) -> Path | None:
    """First candidate with a workspace MARKER wins. Markers: claim-register.yaml
    or .hook_state.json — NOT the oracle file. (#200: an activated workspace
    without an oracle must still be RESOLVED so the gate can block it; keying
    on oracle presence silently passed it through.)"""
    cwd = Path(payload.get("cwd") or payload.get("workspace") or ".")
    for base in [cwd / "malware-analysis-workspace", cwd]:
        if (base / "claim-register.yaml").exists() or (base / ".hook_state.json").exists():
            return base
    return None


def _kunglao_active(ws: Path) -> bool:
    """Strict activation (default-inactive): the gate fires only if explicitly
    activated AND not expired. Mirrors worker_pulse / state_anchor (#44)."""
    if not (ws / ".hook_state.json").exists():
        return False
    try:
        # #671: scoped membership — the entry leaves sys.path with the block
        # (a leaked scripts/ entry flipped the ambiguous lib_kunglao name in
        # long pytest sessions; hooks/ before scripts/ is the load order).
        with scripts_on_path():
            import hook_activation as ha
        return ha.is_active_strict(ws, "completion_gate")
    except Exception:  # noqa: BLE001 — never block on an activation-check error
        return False


def _load_judge():
    """Load scripts/completion_gate.py under a unique module name (avoid clash
    with this shim's basename). Cached in sys.modules for prod+test sharing.
    #863 Family B: delegates to the canonical loader (load_module_by_path) —
    get-or-create semantics unchanged (tests preload the same name+file)."""
    return load_module_by_path(
        "completion_gate_scripts", SKILL_DIR / "scripts" / "completion_gate.py")


# ---------- the Stop-event core ----------

def process_event(payload: dict) -> int:
    """Testable core: second-stop adjudication → workspace resolve → strict
    activation → load oracle → judge → emit block decision or pass through.
    Returns rc."""
    # #147: second stop — persistent oracle adjudication. The shim no longer
    # makes this decision: it reads the oracle's stop_hook_active block and
    # only passes when the oracle records a sanctioned PASS. Anything else
    # (no sanction on record, unreadable oracle) blocks — an unsanctioned
    # second stop must not silently pass (#199). #831: the exemption record
    # is additionally reconciled against the append-only ledger anchor —
    # a record rewritten or backdated after its first sanction fails closed.
    if payload.get("stop_hook_active"):
        ws_early = _resolve_workspace(payload)
        if ws_early is not None:
            try:
                import yaml as _yaml
                oracle_early = _yaml.safe_load(
                    (ws_early / ORACLE_FILE).read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — unreadable oracle → generic block
                oracle_early = None
            if isinstance(oracle_early, dict):
                adj = (oracle_early.get("adjudication") or {}).get(
                    "stop_hook_active") or {}
                if isinstance(adj, dict) and adj.get("second_stop"):
                    try:
                        allow, why = _secondstop_anchor(ws_early, adj)
                    except Exception as exc:  # noqa: BLE001 — #47: an anchor
                        # failure is fail-closed WITH the real cause; letting
                        # it escape would hit main()'s silent fail-open (rc 0)
                        # and the sanction would neither pass nor be diagnosed.
                        allow = False
                        why = (f"second-stop sanction anchor failed - "
                               f"{type(exc).__name__}: {exc} (#47)")
                    # The block's `second_stop` flag is only the arming
                    # marker for this face; its decision text is advisory
                    # and never read for release. The oracle block alone is
                    # never the release key: the gate's OWN sealed sanction
                    # must verify too. A seal failure blocks even when the
                    # ledger anchor allows, and the seal reason
                    # (tamper/absence/forgery) is surfaced first — it names
                    # the release-blocking defect.
                    try:
                        sealed, seal_why = _sanction_verify(ws_early, adj)
                    except Exception as exc:  # noqa: BLE001 — a verify crash
                        # must never release; name the cause and block.
                        sealed, seal_why = False, (
                            f"sealed sanction verification failed - "
                            f"{type(exc).__name__}: {exc}")
                    if allow and sealed:
                        return 0
                    reason = why or seal_why
                    warn("second_stop_sanction_refused", reason)
                    print(json.dumps({"decision": "block", "reason": reason},
                                     ensure_ascii=False))
                    return 1
        # No sanctioned PASS on record → block. (The plan sketch said "fall
        # through to the normal judge path, which blocks while items remain
        # unresolved", but judge() PASSES an oracle with zero open_items — the
        # test fixture — so an explicit block is required to honor "second
        # stop only passes with sanction".)
        reason = ("second stop without oracle sanction - task-oracle.yaml "
                  "must record adjudication.stop_hook_active with "
                  "{second_stop: true, last_decision: PASS} to pass")
        print(json.dumps({"decision": "block", "reason": reason},
                         ensure_ascii=False))
        return 1
    ws = _resolve_workspace(payload)
    if ws is None:
        return 0  # no workspace markers → pass-through (D9)
    if not _kunglao_active(ws):
        return 0  # not activated → pass-through
    if not (ws / ORACLE_FILE).exists():
        # #200: activated + NO task oracle → block with exit 3 (D6 family: a
        # kunglao workspace must be pre-anchored at Phase 0; missing oracle
        # means the run was never anchored — refusing completion is the
        # fail-closed half of the no-oracle pass-through that replay #4
        # observed).
        reason = ("no task-oracle.yaml in an activated workspace - the "
                  "orchestrator must register the oracle at Phase 0 before "
                  "completion can be judged")
        print(json.dumps({"decision": "block", "reason": reason},
                         ensure_ascii=False))
        return 3
    try:
        import yaml
        oracle = yaml.safe_load((ws / ORACLE_FILE).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        # #717: an UNREADABLE oracle in an activated workspace BLOCKS (exit 3),
        # it does not pass through. The pre-#717 FAIL_OPEN here swallowed the
        # sample-incident-01 L7 failure (a bare scalar with an inner colon —
        # ScannerError "mapping values are not allowed here"), so the session
        # ended cleanly with items open. A corrupted oracle is a
        # fail-closed event in the D6 family, same as a missing one — the
        # operator must repair task-oracle.yaml before completion can be
        # judged. (OSError on read stays FAIL_OPEN per the module docstring:
        # a transient IO error must not deadlock the session.)
        reason = (f"task-oracle.yaml is unparseable YAML ({type(exc).__name__}: "
                  f"{str(exc).splitlines()[0] if str(exc) else exc}) — repair "
                  f"the oracle before completion can be judged (#717)")
        print(json.dumps({"decision": "block", "reason": reason},
                         ensure_ascii=False))
        return 3
    except OSError:
        return 0  # transient IO failure — FAIL_OPEN (never deadlock)
    try:
        cg = _load_judge()
        code, reason = cg.judge(oracle)
    except Exception as exc:  # noqa: BLE001 — FAIL_CLOSED (owner ruling 2026-09-28)
        # was FAIL_OPEN (judge crash -> session end). A gate that cannot
        # see must not wave the completion through: the judge error BLOCKS
        # with the cause, the same #717 shape as an unreadable oracle.
        warn("gate_error:completion_judge", f"{type(exc).__name__}: {exc}")
        reason = (f"completion judge crashed ({type(exc).__name__}: {exc}) "
                  f"— gate error is fail-closed; repair the judge before "
                  "completion can be judged (owner ruling 2026-09-28)")
        print(json.dumps({"decision": "block", "reason": reason},
                         ensure_ascii=False))
        return 3
    if code == 0:
        # Seal the gate's OWN PASS verdict — here and ONLY here: a stop the
        # judge blocked mints nothing, so an agent-authored block written
        # before or between the stops can never carry a seal (the seal's
        # provenance is the judge's verdict, not the block's presence).
        # Best-effort (never moves the first-stop verdict); the second
        # stop's verify is the fail-closed face.
        try:
            _first_stop_seal(ws, oracle)
        except Exception as exc:  # noqa: BLE001 — sealing never moves the verdict
            warn("sanction_seal", f"{type(exc).__name__}: {exc}")
        # #762 K1b: at the would-be-PASS point ONLY (#664 pattern — item-level
        # defects, unsigned defers, INTENT_UNMATCHED all strictly outrank this;
        # mid-run Blocks are never caused by notes), refuse closure while the
        # owed durable-note queue (#628 runs/notes-due.yaml) still lists
        # unwritten obligations. Double-caged fail-open: notes_due() itself
        # degrades to [] on every malformed shape, and ANY exception here is
        # swallowed — a telemetry file must never deadlock a session.
        try:
            owed = cg.notes_due(ws)
        except Exception:  # noqa: BLE001 — FAIL_OPEN: never deadlock on the queue
            owed = []
        if owed:
            reason = ("NOTES_DUE: durable result notes owed (#628/#762) - "
                      "write notes/<claim-id>.md per worker contract "
                      "(frontmatter id/claim_id/verify_status: pending; "
                      "supersedes when correcting) for: " + ", ".join(owed))
            print(json.dumps({"decision": "block", "reason": reason},
                             ensure_ascii=False))
            return EXIT_NOTES_DUE
        # #834: a note that survives NOTES_DUE must be a reference-style
        # narrative, NOT a copied fact body. Double-caged FAIL_OPEN like the
        # queue above — a discriminator error must never deadlock a session
        # (structural fail-closed semantics live inside the discriminator).
        try:
            with scripts_on_path():
                import notes_discriminator as nd
            verdict = nd.check(ws / "notes", ws / "facts")
        except Exception:  # noqa: BLE001 — FAIL_OPEN: never deadlock on notes
            verdict = None
        if verdict is not None and not verdict.get("ok", True):
            detail = "; ".join(verdict.get("violations", []))
            reason = ("NOTES_FAKE: notes fail structural discrimination "
                      "(#834) - copied fact bodies or missing/dangling "
                      f"fact-id references: {detail}")
            print(json.dumps({"decision": "block", "reason": reason},
                             ensure_ascii=False))
            return EXIT_NOTES_FAKE
        # #826: the user-facing summary must not evaporate uncertainty —
        # completion vocabulary without a provisional section, unconveyed
        # uncertain facts, and unanswered primary questions are refused.
        # Double-caged FAIL_OPEN exactly like NOTES_FAKE above.
        try:
            with scripts_on_path():
                import summary_discriminator as sd
            verdict = sd.check(ws / "summary.md", ws / "facts")
        except Exception:  # noqa: BLE001 — FAIL_OPEN: never deadlock on summary
            verdict = None
        if verdict is not None and not verdict.get("ok", True):
            detail = "; ".join(verdict.get("violations", []))
            reason = ("SUMMARY_FAKE: summary fails structural contract "
                      "(#826) - uncertainty evaporating in transcription: "
                      f"{detail}")
            print(json.dumps({"decision": "block", "reason": reason},
                             ensure_ascii=False))
            return EXIT_SUMMARY_FAKE
        # #250: settle-time epistemic coverage annotation. R4-class
        # anti-Goodhart: the signal SORTS (event log for the orchestrator to
        # re-rank), it NEVER blocks — a coverage gate that blocked settlement
        # would be gamed by cheap mint-and-settle epistemic claims. The
        # annotation only fires when a terminal claim's presupposition is
        # unresolved. Double-caged FAIL_OPEN like the discriminators above.
        try:
            with scripts_on_path():
                import plan_epistemics as _pep
            note = _pep.coverage_note(ws)
            if note:
                try:
                    import kunglao_log as _kl
                    _kl.emit(ws, actor="hook:completion_gate",
                             action="epistemic_coverage", detail=note)
                except Exception as exc:  # noqa: BLE001 — emit never blocks
                    warn("process_event", f"{type(exc).__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001 — coverage bookkeeping must never deadlock
            warn("process_event_2", f"{type(exc).__name__}: {exc}")
        return 0  # PASS — let the session end
    # non-zero → block termination with the unclosed-items reason
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return code


def _cli(args: list[str]) -> int:
    """Operator faces for the sealed sanction.

    HUMAN-ONLY: the operator (human) is the trust root of this face. It is
    the ONLY way to release a second stop while items remain open, and its
    every use is logged loudly (stderr warn + an operator-sanctioned
    deferral ledger event). Invoking it from agent flow is a violation of
    the review-gate posture — stated convention backed by deliberate key
    exfiltration being the only bypass (the seal key is user-readable, so
    same-user mechanical enforcement is impossible; the convention is the
    control). Provision the key, mint a sealed record for a workspace.
    Refuses loudly on anything it cannot verify; exit 0 = done, 2 =
    refused."""
    if args[0] == "sanction-key-init":
        path = _sanction_keyfile()
        if path.exists():
            print(f"key already present: {path}")
            return 0
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(secrets.token_bytes(32).hex(), encoding="utf-8")
            os.chmod(path, 0o600)
        except OSError as exc:
            print(f"key-init FAIL: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return 2
        print(f"key written: {path} (mode 0600)")
        return 0
    if args[0] == "mint-sanction":
        if len(args) < 3:
            print("usage: mint-sanction <workspace> <decision>\n"
                  "  HUMAN-ONLY operator face — the trust root for closing "
                  "a run with items open. Every use is logged as an "
                  "operator-sanctioned deferral. Agent flow must never "
                  "invoke it.", file=sys.stderr)
            return 2
        ws, decision = Path(args[1]), str(args[2]).strip()
        oracle_path = ws / ORACLE_FILE
        try:
            import yaml
            oracle = yaml.safe_load(
                oracle_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — refuse with the cause
            print(f"mint FAIL: cannot read {oracle_path} "
                  f"({type(exc).__name__}: {exc})", file=sys.stderr)
            return 2
        adj = {}
        if isinstance(oracle, dict):
            adj = (oracle.get("adjudication") or {}).get(
                "stop_hook_active") or {}
        if not (isinstance(adj, dict) and adj.get("second_stop")):
            print("mint FAIL: the oracle records no armed second-stop "
                  "adjudication block (adjudication.stop_hook_active with "
                  "second_stop: true) — the block text itself is advisory "
                  "and is not sealed as a decision",
                  file=sys.stderr)
            return 2
        block_text = str(adj.get("last_decision") or "").strip()
        if block_text and block_text != decision:
            print(f"mint FAIL: requested decision {decision!r} contradicts "
                  f"the oracle's recorded {block_text!r}",
                  file=sys.stderr)
            return 2
        if not _sanction_mint(ws, adj, decision=decision,
                              origin="operator"):
            print("mint FAIL: no usable sanction key (provision it with "
                  "sanction-key-init) or the sanction store is unwritable",
                  file=sys.stderr)
            return 2
        # The operator deferral is loud: one rate-limited stderr warn and a
        # distinct unified-log event naming the operator-sanctioned
        # deferral, so an agent-flow invocation is at least visible.
        warn("mint_sanction_operator",
             f"operator-sanctioned deferral sealed: decision={decision!r} "
             f"for {ws} (HUMAN-ONLY face)")
        try:
            import kunglao_log
            kunglao_log.emit(ws, actor="operator",
                             action="operator_sanction_deferral",
                             detail=(f"mint-sanction sealed decision="
                                     f"{decision!r} (HUMAN-ONLY face)"))
        except Exception as exc:  # noqa: BLE001 — logging never breaks mint
            warn("mint_sanction_event", f"{type(exc).__name__}: {exc}")
        print(f"mint OK: {_sanction_record_path(ws)}")
        return 0
    print(f"unknown command: {args[0]}", file=sys.stderr)
    return 1


def main(stdin_stream=None) -> int:
    """Stop entry. Reads JSON payload from stdin (or stdin_stream for tests).
    FAIL_OPEN: unparseable stdin or any processing error → exit 0, empty
    stdout (never deadlock the session)."""
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
    # Stop-hook face reads the payload on stdin with NO argv; the operator
    # faces are argv-dispatched so a wired hook command can never trip them.
    if len(sys.argv) > 1 and sys.argv[1] in ("mint-sanction",
                                             "sanction-key-init"):
        sys.exit(_cli(sys.argv[1:]))
    sys.exit(main())

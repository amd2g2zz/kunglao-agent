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
  - stop_hook_active=true (second stop) → BLOCK unless task-oracle.yaml
    records adjudication.stop_hook_active = {second_stop: true,
    last_decision: PASS} (#147/#199: an unsanctioned second stop must not
    silently pass; only that sanctioned-PASS record passes)
  - any exception → pass-through (FAIL_OPEN: a completion-gate failure must
    never deadlock the session — unreadable oracle / judge errors fail open)

Emits Claude Code Stop-hook JSON to block; empty stdout + exit 0 to pass. The
pure judge() function does NOT fail open (it returns exit 3 on bad input) —
only THIS shim does. Mirrors state_anchor's _resolve_workspace +
_kunglao_active + FAIL_OPEN structure (#44).
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from _path_hygiene import load_module_by_path, scripts_on_path  # #671 sys.path hygiene authority

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/
ORACLE_FILE = "task-oracle.yaml"
# #762 K1b: owed durable-result-note refusal code (shim-face only — judge()
# stays workspace-pure; the scripts-side judge keeps its {0..4} table).
EXIT_NOTES_DUE = 5
# #834: notes structural-discrimination refusal (same shim-face-only rule).
EXIT_NOTES_FAKE = 6
# #826: summary structural-contract refusal (uncertainty must not evaporate
# in the user-facing transcription).
EXIT_SUMMARY_FAKE = 7
# #831: ledger-anchored second-stop sanction event type (ledger CONTRACT line
# format identical to rollup._append_ledger: json.dumps ensure_ascii=False).
SECOND_STOP_EVENT = "second_stop_pass"


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
                if (isinstance(adj, dict) and adj.get("second_stop")
                        and adj.get("last_decision") == "PASS"):
                    try:
                        allow, why = _secondstop_anchor(ws_early, adj)
                    except Exception as exc:  # noqa: BLE001 — #47: an anchor
                        # failure is fail-closed WITH the real cause; letting
                        # it escape would hit main()'s silent fail-open (rc 0)
                        # and the sanction would neither pass nor be diagnosed.
                        allow = False
                        why = (f"second-stop sanction anchor failed - "
                               f"{type(exc).__name__}: {exc} (#47)")
                    if allow:
                        return 0
                    reason = why
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
    except Exception:  # noqa: BLE001 — FAIL_OPEN on judge
        return 0
    if code == 0:
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
        return 0  # PASS — let the session end
    # non-zero → block termination with the unclosed-items reason
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return code


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
    sys.exit(main())

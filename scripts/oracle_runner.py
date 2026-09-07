#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""oracle_runner.py — the oracle's mechanical face (issue #108, design card #97 part 3).

Runs the workspace's oracle case set (`<ws>/oracle/cases/*.yaml`) against a
client implementation (a Python module exposing ``compute(params: dict) ->
dict``), and writes the verdict file the convergence DRAIN probes consume:

    <ws>/runs/oracle-status.json
      {"schema": "oracle-status/1",
       "cases": {"<case_id>": {"status": "pass|fail|pending",
                               "pending_entries": N, "instrumented": bool}},
       "low_discriminativity": [...], "counts": {"red": N, "green": N, "pending": N}}

Half B — mutation must fail (the oracle's own red-team, no LLM). The oracle
is LLM-built: it catches a wrong client (wrong values -> red) but not its
own design errors (a mis-pinned case passes a wrong implementation too).
What is mechanical: a deliberately-mutated client — ONE declared field
swapped / omitted / changed per the case's ``mutations:`` block — MUST turn
the case red. A case that stays green under all its declared mutations
observes nothing its author claims distinguishes it: flagged
``low_discriminativity`` (the strengthening to-do; the convergence gate
blocks on red/pending — the flag is reported, not a verdict branch).

Half C — byte anchors, made mechanical (the doubao convention): every
expected entry carries ``evidence_refs`` to the fact that pins it, or an
explicit ``pending-observation: true`` marker. An entry with neither is
REFUSED with a lint-style OracleCaseError — no silent invented values. On
refusal the runner exits 2 and writes NO status file (a refusal must never
degenerate into a green status).

No client runnable -> every case reports ``pending`` with
``instrumented=false`` — pending is the honest unknown; it is never green.
A client that CRASHES is recorded as pending too, but with
``instrumented=true``: the wiring exists, the observation is still owed
(the DRAIN probe blocks pendings on live instrumentation — "unknown" is
not "pass", #108 A).

#106 reuse: a REAL verdict (pass/fail) is a Bernoulli observation — each run
updates the case's CasePosterior in the ``runs/posteriors.yaml`` ledger via
record_posteriors() ("runner red/green is the only reward signal"). Pending
is not an observation and never touches the posterior.

Case YAML shape::

    id: auth-fields            # required (file stem as fallback)
    channel: device-trace      # required (#126): declared observation channel
    hypothesis_ref: H-001      # required (#126): the live bet this case realizes
    update_map:                # required (#126): cross-candidate separation —
      green_up: [H-001]        #   who RISES on green / on red; ids must be
      red_up: [H-002]          #   OPEN hypotheses in hypothesis_ref's group
    params: {user: alice, nonce: 10}
    expected:                  # required, non-empty
      - field: auth_algo       # required per entry
        value: hmac-sha256     # required per entry
        evidence_refs: [F001]  # byte anchor — must RESOLVE (#126) …
        pending-observation: true   # …or this marker: scaffold entry, owed
    mutations:                 # REQUIRED non-empty (#126; was optional):
      - field: auth_algo       #   what distinguishes this case from
        kind: swap             #   near-miss implementations (half B)

#126 — admission-time integrity beyond the #108 half C presence lint (the
case set is blessed as a whole or not at all, before any IO):
  - every non-pending evidence_ref RESOLVES to an existing fact-pipeline
    artifact under the workspace — facts/F*.md or an evidence/ file
    (an invented fact id is refused: refs are declarations, not
    resolutions);
  - refs into the oracle's own output (runs/ | oracle/ — the status file,
    the case file itself) are refused: self-anchoring is circular
    verification, the machine channel for a 100% pass rate;
  - hypothesis_ref must name an existing <ws>/hypotheses/H*.md — a case
    that discriminates nothing in the live competitor field is
    indistinguishable from a real experiment at load time (the
    trivial-oracle class);
  - the action signature (declared channel, competitor_group of the linked
    hypothesis) is the dedup axis: a second case with an identical
    signature in one load is refused — marginal discriminative power, not
    text. A different channel (emulator vs device) is a different
    signature: cross-channel divergence is itself an observation;
  - mutations non-empty at load: the --mutation flag becomes an admission
    requirement — a case that cannot go red under a deliberately wrong
    implementation is a rubber stamp;
  - update_map is required and non-vacuous (cross-candidate separation):
    green_up non-empty, at least one direction populated, every id an OPEN
    hypothesis in the linked hypothesis's competitor_group. A case whose
    outcome is invariant across the hypothesis space cannot write a valid
    update_map — the HTTP-200 specimen: "HTTP 200 + body non-empty" is a
    property of the ENVIRONMENT (server liveness), not of the unknown
    being reversed; every candidate client greens it and
    mutation-can-redden does not catch it (a mutation perturbing that
    client reddens it too). Refused at admission;
  - the linked hypothesis's competitor_group must hold >=2 OPEN members —
    a live competition to discriminate; a self-filed singleton vacuous
    hypothesis fails admission.

Exit codes: 0 = no red case; 1 = at least one red case; 2 = lint refusal
(also the --retire refusal exit).
Usage:
  python scripts/oracle_runner.py <ws> [--client <path>] [--mutation] [--json]

#146 — outcome forensics (settlements record HOW they were won/lost):

Every case row in the report gains an ADDITIVE ``forensics`` block (all
pre-existing report/status fields keep their shape — the status file stays
narrowed to the three convergence-convention fields):

  forensics:
    params_used       the params handed to compute() (derivation input
                      record; {} before compute was invoked)
    meta              the client's OPTIONAL ``meta`` return key, verbatim
                      (optional client contract; absent/not-a-dict -> {})
    mismatches        RED only: the per-field mismatch vector — every
                      non-matching expected entry as
                      {field, expected, actual}
    stages            the client's OPTIONAL ``stages`` return dict
                      (intermediate derivation steps), verbatim
    divergence_point  first stage whose output differs from the case's
                      expected-stage value (``stages:`` case key) — or an
                      expected stage the client never produced; None when
                      nothing differs or no expected stages are pinned

#146 — case-abandonment protocol (retirement lives HERE, with the case
files and OracleCaseError): a case transitions to ``status: retired`` ONLY
with the structured justification {attribution_class in the closed taxonomy
{implementation-wrong, case-wrong, client-wrong, channel-wrong,
capture-obsolete}, disconfirmation, replacement} — anything less is a loud
OracleCaseError refusal. The transition is append-only (the case file keeps
its expected entries; status + retirement are ADDED). Retired cases leave
the acceptance net: load_cases skips them (a retired case must never refuse
the set because its hypothesis went terminal), run() reports them, and
retiring emits the coverage-drop WARN event
(``acceptance_coverage_decreased`` — a registered event word) because the
armed-case count shrank.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Callable

import yaml

from harness_common import utc_now_iso  # #863 Family F: single source

SCHEMA_ID = "oracle-status/1"
STATUS_REL = ("runs", "oracle-status.json")
CASES_REL = ("oracle", "cases")
DEFAULT_CLIENT_REL = ("oracle", "client.py")
MUTATION_KINDS = ("swap", "omit", "change")

# #146 case-abandonment protocol: the closed attribution taxonomy a
# retirement justification must draw from, and the retired marker.
RETIRED_CASE_STATUS = "retired"
RETIREMENT_ATTRIBUTION_CLASSES = ("implementation-wrong", "case-wrong",
                                  "client-wrong", "channel-wrong",
                                  "capture-obsolete")

Compute = Callable[[dict], dict]


class OracleCaseError(ValueError):
    """Case-set lint refusal (#108 half C) — loud, never silently blessed."""


# ------------------------------------------------- #126 admission lints

# E3 (issue #126 pre-experiment): the observation channel is DECLARED, not
# inferred from tool names — priority_ratio.py's tool-family vocabulary is
# per-TOOL (frida != ida) and carries no emulator tokens, so it cannot
# produce the canonical verdict table ("frida stalker trace" == "ida server
# trace" -> SAME device-trace channel; "unidbg codehook trace" != "frida
# hook trace"). The case doc therefore declares `channel:` outright. The
# case bank's entries carry only a free-text `method`, so the bank face
# reads the channel through this DECLARED token vocabulary (word-bounded,
# mechanical — the tool_families_from_text posture, channel semantics).
# An unrecognized method maps to `adhoc:<normalized text>`: unknown actions
# keep per-method keys and can never falsely dedup.
_ACTION_CHANNEL_BY_TOKEN: dict[str, str] = {
    "frida": "device-trace", "ida": "device-trace",
    "x64dbg": "device-trace", "gdb": "device-trace",
    "unidbg": "emulator-trace", "qiling": "emulator-trace",
    "ghidra": "static",
}


def action_channel(method: str) -> str:
    """Declared observation channel of an action's method text (pure).

    Word-bounded, case-insensitive token match ('ida-server' -> ida; a
    token inside a longer word never matches). Unrecognized text maps to
    an ``adhoc:`` per-method channel so unknown actions stay distinct."""
    text = str(method or "").lower()
    for token, channel in _ACTION_CHANNEL_BY_TOKEN.items():
        if re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])",
                     text):
            return channel
    return "adhoc:" + " ".join(text.split())


def action_signature(channel: str, competitor_group: str) -> tuple[str, str]:
    """The #126 dedup axis: (declared observation channel, competitor
    group served). Pure — same inputs, same signature, no hidden state."""
    return (str(channel or "").strip(), str(competitor_group or "").strip())


_EVIDENCE_ROOTS = ("facts", "evidence")


def _resolve_evidence_ref(ws: Path, case_path: Path, cid: str,
                          field: str, ref: str) -> Path:
    """#126: an evidence ref RESOLVES or the case is refused.

    Valid targets are fact-pipeline artifacts under the workspace:
    ``facts/F*.md`` or any file under ``evidence/``. Refs pointing into
    the oracle's own output (``runs/`` | ``oracle/`` — the status file,
    the case file itself) are refused outright: self-anchoring is
    circular verification. Path escapes are neutralized by containment —
    a ref that resolves outside facts/ | evidence/ is refused, never
    followed."""
    text = str(ref).strip()
    if not text:
        raise OracleCaseError(
            f"{case_path.name}: case {cid!r}: expected entry {field!r} "
            f"carries an empty evidence_ref")
    norm = text.replace("\\", "/").lower()
    if norm.startswith(("runs/", "oracle/")) or "oracle-status" in norm:
        raise OracleCaseError(
            f"{case_path.name}: case {cid!r}: expected entry {field!r}: "
            f"evidence ref {text!r} points into the oracle's own output "
            f"(runs/ | oracle/) — self-anchor refused (#126: circular "
            f"verification is the machine channel for a 100% pass rate)")
    if "/" in text:
        candidates = [ws / Path(text)]
    else:
        candidates = [ws / "facts" / f"{text}.md", ws / "facts" / text,
                      ws / "evidence" / text]
    for cand in candidates:
        if not cand.is_file():
            continue
        resolved = cand.resolve()
        for root in _EVIDENCE_ROOTS:
            try:
                resolved.relative_to((ws / root).resolve())
            except ValueError:
                continue
            if root == "evidence" or (resolved.suffix == ".md"
                                      and resolved.stem.startswith("F")):
                return resolved
            break  # under facts/ but not an F*.md — refused below
        break  # exists, but outside facts/ | evidence/ — refused below
    raise OracleCaseError(
        f"{case_path.name}: case {cid!r}: expected entry {field!r}: evidence "
        f"ref {text!r} does not resolve to an existing fact-pipeline "
        f"artifact (facts/F*.md or an evidence/ file) under the workspace — "
        f"refs are declarations, not resolutions (#126)")


# ------------------------------------------------------------ case loading

def _parse_expected(ws: Path, case_path: Path, cid: str, raw) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        raise OracleCaseError(
            f"{case_path.name}: case {cid!r} needs a non-empty `expected` list")
    out: list[dict] = []
    for i, e in enumerate(raw):
        if not isinstance(e, dict):
            raise OracleCaseError(
                f"{case_path.name}: expected entry #{i} is "
                f"{type(e).__name__}; expected a mapping")
        field = e.get("field")
        if not isinstance(field, str) or not field:
            raise OracleCaseError(
                f"{case_path.name}: expected entry #{i} lacks a `field` name")
        if "value" not in e:
            raise OracleCaseError(
                f"{case_path.name}: expected entry {field!r} lacks a `value`")
        refs = e.get("evidence_refs")
        pending = bool(e.get("pending-observation"))
        if pending:
            out.append({"field": field, "value": e["value"],
                        "evidence_refs": [str(r) for r in (refs or [])],
                        "pending": True})
            continue
        # #108 half C: no byte-anchored fact reference and no pending marker
        # -> the value is invented. Refuse (lint-style), never bless.
        if not isinstance(refs, list) or not refs:
            raise OracleCaseError(
                f"{case_path.name}: expected entry {field!r} lacks "
                f"evidence_refs and a pending-observation marker — refusing "
                f"to bless an invented value (#108 half C: every expected "
                f"entry carries a byte-anchored fact reference or an "
                f"explicit pending-observation marker)")
        str_refs = [str(r) for r in refs]
        # #126: presence is not resolution — every non-pending ref must
        # name an existing fact-pipeline artifact, or the case is refused.
        for r in str_refs:
            _resolve_evidence_ref(ws, case_path, cid, field, r)
        out.append({"field": field, "value": e["value"],
                    "evidence_refs": str_refs, "pending": False})
    return out


def _parse_mutations(case_path: Path, cid: str, raw) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise OracleCaseError(
            f"{case_path.name}: case {cid!r}: `mutations` must be a list")
    out: list[dict] = []
    for i, m in enumerate(raw):
        if isinstance(m, str):  # shorthand: - auth_algo  (kind defaults change)
            m = {"field": m}
        if not isinstance(m, dict) or not isinstance(m.get("field"), str) \
                or not m["field"]:
            raise OracleCaseError(
                f"{case_path.name}: case {cid!r}: mutation #{i} needs a "
                f"`field` name")
        kind = m.get("kind") or "change"
        if kind not in MUTATION_KINDS:
            raise OracleCaseError(
                f"{case_path.name}: case {cid!r}: mutation {m['field']!r} has "
                f"unknown kind {kind!r} (have {MUTATION_KINDS})")
        out.append({"field": m["field"], "kind": kind})
    return out


def _parse_update_map(case_path: Path, cid: str, group: str, raw,
                      open_groups: dict[str, str]) -> dict:
    """#126 amendment: cross-candidate separation, mechanical, fail-closed.

    A valid case's outcome must functionally depend on the referenced
    hypothesis's model: ``green_up`` names the OPEN hypotheses (same
    competitor group) whose probability RISES if the case greens, ``red_up``
    the ones that rise on red. ``green_up`` empty — or both directions
    empty — means nothing rises if green: the case discriminates nothing
    upward (the HTTP-200 class, refused at admission). Ids must be OPEN
    hypotheses inside ``hypothesis_ref``'s own competitor group — an update
    outside the discriminated competition moves nobody's posterior."""
    if not isinstance(raw, dict):
        raise OracleCaseError(
            f"{case_path.name}: case {cid!r}: `update_map` is required — a "
            f"mapping {repr({'green_up': ['H-xxx'], 'red_up': ['H-yyy']})} "
            f"of hypothesis ids (#126: cross-candidate separation — the "
            f"case's outcome must functionally depend on the referenced "
            f"hypothesis's model)")
    green = raw.get("green_up")
    red = raw.get("red_up") or []
    if not isinstance(green, list) or not green:
        raise OracleCaseError(
            f"{case_path.name}: case {cid!r}: update_map.green_up must be a "
            f"non-empty list of hypothesis ids — nothing rises if green "
            f"(#126: an outcome invariant across the hypothesis space — "
            f"the HTTP-200 'environment predicate' class — discriminates "
            f"nothing upward)")
    if not isinstance(red, list):
        raise OracleCaseError(
            f"{case_path.name}: case {cid!r}: update_map.red_up must be a "
            f"list of hypothesis ids")
    for direction, ids in (("green_up", green), ("red_up", red)):
        for h in ids:
            hid = str(h).strip()
            if hid not in open_groups:
                raise OracleCaseError(
                    f"{case_path.name}: case {cid!r}: update_map."
                    f"{direction}: {hid!r} is not an OPEN hypothesis in the "
                    f"store (missing, terminal, or malformed) — update_map "
                    f"moves live candidates only (#126)")
            if open_groups[hid] != group:
                raise OracleCaseError(
                    f"{case_path.name}: case {cid!r}: update_map."
                    f"{direction}: {hid!r} competes in "
                    f"{open_groups[hid]!r}, not the linked competitor group "
                    f"{group!r} — update_map ids must sit inside "
                    f"hypothesis_ref's own competitor group (#126)")
    return {"green_up": [str(h).strip() for h in green],
            "red_up": [str(h).strip() for h in red]}


def _retired_or_stages(p: Path, cid: str, doc: dict) -> tuple[bool, dict]:
    """#146 pre-admission doc face: (skip_retired, expected_stages).

    A retired case has left the acceptance net — it is skipped BEFORE the
    admission lints (a retired case must never refuse the set because its
    linked hypothesis went terminal or its competitor group thinned).
    ``stages`` is the optional case key pinning expected stage values; a
    non-mapping is a loud refusal."""
    if str(doc.get("status") or "").strip() == RETIRED_CASE_STATUS:
        return True, {}
    stages = doc.get("stages")
    if stages is not None and not isinstance(stages, dict):
        raise OracleCaseError(
            f"{p.name}: case {cid!r}: `stages` must be a mapping of stage "
            f"name -> expected value (the runner diffs the client's stages "
            f"dict stage-wise, #146)")
    return False, dict(stages or {})


def load_cases(cases_dir) -> list[dict]:
    """Load + lint every ``*.yaml`` case. Raises OracleCaseError on the
    first refusal (#108 half C presence lint + #126 admission integrity:
    refs resolve, hypothesis_ref linked and existing, action-signature
    dedup, mutations required, cross-candidate separation — a non-vacuous
    update_map over OPEN hypotheses inside a live >=2-OPEN competitor
    group) — the case set is blessed as a whole or not at all."""
    cases_dir = Path(cases_dir)
    ws = cases_dir.parent.parent  # <ws>/oracle/cases -> ws root (#126)
    from hypothesis_store import HypothesisStore
    hypotheses = HypothesisStore(ws / "hypotheses")
    # #126 amendment: OPEN-hypothesis faces for the update_map + live-group
    # lints (id -> competitor_group, and the per-group OPEN census).
    open_groups: dict[str, str] = {h.id: h.competitor_group
                                   for h in hypotheses.list_open()}
    open_in_group: dict[str, int] = {}
    for g in open_groups.values():
        open_in_group[g] = open_in_group.get(g, 0) + 1
    cases: list[dict] = []
    seen_signatures: dict[tuple[str, str], str] = {}
    for p in sorted(cases_dir.glob("*.yaml")):
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise OracleCaseError(f"{p.name}: case file is not a mapping")
        cid = str(doc.get("id") or p.stem).strip()
        if not cid:
            raise OracleCaseError(f"{p.name}: case id is empty")
        # #146: retired skips BEFORE the lints; stages pins expected
        # stage values for the stage-diff forensics.
        skip_retired, stages_expected = _retired_or_stages(p, cid, doc)
        if skip_retired:
            continue
        expected = _parse_expected(ws, p, cid, doc.get("expected"))
        mutations = _parse_mutations(p, cid, doc.get("mutations"))
        # #126: mutations are an admission requirement now — a case that
        # cannot go red under a deliberately wrong implementation is a
        # rubber stamp (the --mutation flag made mandatory at load).
        if not mutations:
            raise OracleCaseError(
                f"{p.name}: case {cid!r}: `mutations` is required non-empty "
                f"at admission (#126) — a case that cannot go red under a "
                f"deliberately wrong implementation is a rubber stamp")
        # #126: case -> hypothesis linkage. A case that discriminates
        # nothing in the live competitor field is indistinguishable from a
        # real experiment at load time (the trivial-oracle class).
        hyp_ref = str(doc.get("hypothesis_ref") or "").strip()
        if not hyp_ref or "/" in hyp_ref or "\\" in hyp_ref \
                or hyp_ref in (".", ".."):
            raise OracleCaseError(
                f"{p.name}: case {cid!r}: `hypothesis_ref` is required and "
                f"must name a hypothesis id in the store (#126: without the "
                f"linkage a case that discriminates nothing in the live "
                f"competitor field passes for a real experiment)")
        try:
            hyp = hypotheses.get(hyp_ref)
        except (KeyError, OSError, ValueError) as exc:  # InvalidTransition
            # is a ValueError; the store's fail-open parse never invents a
            # hypothesis, so ANY read failure is a refused link.
            raise OracleCaseError(
                f"{p.name}: case {cid!r}: hypothesis_ref {hyp_ref!r} does "
                f"not resolve to a readable hypothesis in "
                f"{hypotheses.root} ({exc}) — a link to nothing links "
                f"nothing (#126)") from None
        # #126 amendment: cross-candidate separation. The HTTP-200 specimen
        # ("success" = server liveness — a property of the ENVIRONMENT,
        # invariant across the hypothesis space) cannot write a valid
        # update_map and is refused here.
        update_map = _parse_update_map(p, cid, hyp.competitor_group,
                                       doc.get("update_map"), open_groups)
        # #126 amendment: a live competition to discriminate. A group with
        # <2 OPEN members is a self-filed singleton — vacuous by width.
        n_live = open_in_group.get(hyp.competitor_group, 0)
        if n_live < 2:
            raise OracleCaseError(
                f"{p.name}: case {cid!r}: competitor group "
                f"{hyp.competitor_group!r} holds {n_live} OPEN "
                f"hypotheses — a live competition needs >=2 candidates to "
                f"discriminate; a self-filed singleton vacuous hypothesis "
                f"is refused (#126)")
        # #126 (E3): the observation channel is declared, never inferred
        # from tool names — the tool-family vocabulary cannot classify
        # "frida stalker trace" and "ida server trace" as one channel.
        channel = str(doc.get("channel") or "").strip()
        if not channel:
            raise OracleCaseError(
                f"{p.name}: case {cid!r}: `channel` is required (#126: the "
                f"observation channel is declared, not inferred)")
        # #126: action-signature dedup. Same signature = one case; a second
        # case with an identical signature adds no marginal discriminative
        # power and is refused. Different channel or different
        # competitor_group = different signature (cross-channel divergence
        # is itself an observation).
        sig = action_signature(channel, hyp.competitor_group)
        if sig in seen_signatures:
            raise OracleCaseError(
                f"{p.name}: case {cid!r}: duplicate action signature "
                f"{sig} — already covered by case "
                f"{seen_signatures[sig]!r} (same declared channel + same "
                f"competitor_group); the dedup axis is marginal "
                f"discriminative power, not text (#126)")
        seen_signatures[sig] = cid
        cases.append({
            "id": cid,
            "channel": channel,
            "hypothesis_ref": hyp_ref,
            "competitor_group": hyp.competitor_group,
            "update_map": update_map,
            "params": doc.get("params") or {},
            "expected_stages": dict(stages_expected or {}),
            "expected": expected,
            "mutations": mutations,
        })
    return cases


def retired_case_ids(cases_dir) -> list[str]:
    """#146: ids of cases whose file marks ``status: retired`` — they left
    the acceptance net and are skipped by load_cases/run. Tolerant per
    file (an unreadable case doc is not a retirement signal)."""
    cases_dir = Path(cases_dir)
    out: list[str] = []
    for p in sorted(cases_dir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — unreadable is not signal
            continue
        if not isinstance(doc, dict):
            continue
        cid = str(doc.get("id") or p.stem).strip()
        if cid and str(doc.get("status") or "").strip() == \
                RETIRED_CASE_STATUS:
            out.append(cid)
    return out


# ------------------------------------------------------------ client loader

def load_client(client_path) -> Compute | None:
    """Load a client module (``compute(params) -> dict``). Missing path ->
    None (all cases pending, never green). A PRESENT but broken client is a
    hard error: silently treating broken instrumentation as "no client"
    would dress a red face in pending clothes.

    Imported through a content-hashed snapshot copy under a digest-bearing
    module name, NOT the file itself: the source-file bytecode cache
    validates on (mtime_seconds, size), so a rewritten SAME-LENGTH client
    re-served the stale module (observed: equal-length good/bad clients ->
    the bad run silently judged the good one). Different bytes -> different
    snapshot name -> different cache file; identical bytes reuse the
    identical module (same behavior). #863 Family B: the by-path load
    itself delegates to hooks/_path_hygiene.load_module_by_path (the ONE
    importlib by-path load site in the repo)."""
    if client_path is None or not Path(client_path).exists():
        return None
    path = Path(client_path)
    source = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    snap_dir = Path(tempfile.gettempdir()) / "kunglao-oracle-clients"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap = snap_dir / f"{path.stem}-{digest}.py"
    if not snap.exists():
        snap.write_text(source, encoding="utf-8")
    from _hooks_path import load_module_by_path  # (#863 Family B delegation)
    mod = load_module_by_path(
        "kunglao_oracle_client_" + snap.stem.replace("-", "_"), snap)
    compute = getattr(mod, "compute", None)
    if not callable(compute):
        raise OracleCaseError(
            f"client {path} exposes no callable compute(params) -> dict")
    return compute


# ---------------------------------------------------------------- checking

def _stage_divergence(observed: dict, expected_stages: dict) -> str | None:
    """#146: first stage whose output differs from the case's expected
    stage value — or an expected stage the client never produced (a
    missing stage output differs from its expected value). Pure."""
    for stage, value in observed.items():
        if stage in expected_stages and value != expected_stages[stage]:
            return str(stage)
    for stage in expected_stages:
        if stage not in observed:
            return str(stage)
    return None


def check_case(case: dict, compute: Compute | None) -> dict:
    """One case -> {"status", "pending_entries", "instrumented", "failures",
    "error", "forensics"}.

    status: fail (observed entry mismatched) > pending (no client / client
    crash / nothing observed / scaffold entries owed) > pass (every observed
    entry matches and nothing is owed). "Unknown" is never "pass" (#108 A).

    #146 forensics (additive): params_used / meta / mismatches / stages /
    divergence_point — the settlement records HOW it was won or lost; see
    the module docstring for the full contract."""
    expected = case["expected"]
    pending_entries = sum(1 for e in expected if e["pending"])
    observed = [e for e in expected if not e["pending"]]
    forensics: dict = {"params_used": {}, "meta": {}, "mismatches": [],
                       "stages": {}, "divergence_point": None}
    row = {"status": "pending", "pending_entries": pending_entries,
           "instrumented": False, "failures": [], "error": None,
           "forensics": forensics}
    if compute is None:
        return row
    row["instrumented"] = True
    params = dict(case["params"])
    try:
        out = compute(params)
    except Exception as exc:  # noqa: BLE001 — a crash is a verdict of "unknown"
        row["error"] = f"{type(exc).__name__}: {exc}"
        forensics["params_used"] = params
        return row
    forensics["params_used"] = params
    if not isinstance(out, dict):
        row["error"] = f"client returned {type(out).__name__}, expected dict"
        return row
    meta = out.get("meta")
    if isinstance(meta, dict):
        forensics["meta"] = meta
    stages = out.get("stages")
    if isinstance(stages, dict):
        forensics["stages"] = stages
        forensics["divergence_point"] = _stage_divergence(
            stages, case.get("expected_stages")
            if isinstance(case.get("expected_stages"), dict) else {})
    for e in observed:
        if out.get(e["field"]) != e["value"]:
            row["failures"].append(
                f"{e['field']}: expected {e['value']!r}, got "
                f"{out.get(e['field'])!r}")
            forensics["mismatches"].append(
                {"field": e["field"], "expected": e["value"],
                 "actual": out.get(e["field"])})
    if row["failures"]:
        row["status"] = "fail"
    elif not observed or pending_entries:
        row["status"] = "pending"  # observations still owed — not pass
    else:
        row["status"] = "pass"
    return row


# ---------------------------------------------------------------- mutation

def _perturb(value):
    """A value GUARANTEED different from the input (deterministic)."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 1.0
    if isinstance(value, str):
        return value + "#mutated"
    if isinstance(value, list):
        return list(reversed(value))
    if isinstance(value, dict):
        return dict(value, mutated=True)
    if value is None:
        return "mutated"
    return f"{value!r}#mutated"


def _mutated_client(compute: Compute, mut: dict,
                    swap_partner: str | None) -> Compute:
    """A reference-BAD client: compute(), then perturb ONE declared field of
    its output (swap = transpose with the partner field, falling back to a
    changed value when no partner is available; omit = drop the field;
    change = _perturb). Output-only mutation, fixed case params: any verdict
    change is attributable to the declared field (#108 half B)."""
    field, kind = mut["field"], mut["kind"]

    def bad(params: dict) -> dict:
        out = dict(compute(params))
        if field not in out:
            return out  # nothing to mutate -> the case judges as-is
        if kind == "omit":
            out.pop(field)
        elif kind == "swap" and swap_partner and swap_partner in out \
                and out[swap_partner] != out[field]:
            out[field], out[swap_partner] = out[swap_partner], out[field]
        else:
            out[field] = _perturb(out[field])
        return out
    return bad


def mutation_pass(cases: list[dict], compute: Compute | None) -> dict:
    """--mutation: every declared mutation MUST turn its case red. A case
    that stays green under ALL its declared mutations observes nothing its
    author claims distinguishes it -> ``low_discriminativity`` (#108 B)."""
    result: dict = {"mutations": {}, "low_discriminativity": []}
    if compute is None:
        return result  # no live instrumentation -> nothing to discriminate
    for case in cases:
        decls = case["mutations"]
        if not decls:
            continue
        observed = [e["field"] for e in case["expected"] if not e["pending"]]
        rows = []
        for m in decls:
            partner = next((f for f in observed if f != m["field"]), None)
            row = check_case(case, _mutated_client(compute, m, partner))
            rows.append({"field": m["field"], "kind": m["kind"],
                         "red": row["status"] == "fail"})
        result["mutations"][case["id"]] = rows
        if rows and all(not r["red"] for r in rows) \
                and check_case(case, compute)["status"] == "pass":
            result["low_discriminativity"].append(case["id"])
    return result


# ------------------------------------------------------------------ report

def run(cases_dir, client_path, *, mutation: bool = False) -> dict:
    """Run the whole case set. No client -> ALL pending (never green).

    #146: retired cases are reported, not run — they left the acceptance
    net (load_cases skips them), so counts cover ACTIVE cases only."""
    cases_dir = Path(cases_dir)
    cases = load_cases(cases_dir)
    compute = load_client(client_path)
    rows = {c["id"]: check_case(c, compute) for c in cases}
    counts = {"red": 0, "green": 0, "pending": 0}
    for row in rows.values():
        counts[{"fail": "red", "pass": "green",
                "pending": "pending"}[row["status"]]] += 1
    return {
        "schema": SCHEMA_ID,
        "cases_dir": str(cases_dir),
        "client": str(client_path) if compute is not None else None,
        "cases": rows,
        "counts": counts,
        "retired": retired_case_ids(cases_dir),
        "mutation": mutation_pass(cases, compute)
        if (compute is not None and mutation) else None,
    }


def write_status(ws, report: dict) -> Path:
    """Atomic write of the convergence-convention verdict file. `cases` rows
    are narrowed to the three fields the DRAIN probe reads."""
    path = Path(ws).joinpath(*STATUS_REL)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": SCHEMA_ID,
        "cases": {cid: {"status": r["status"],
                        "pending_entries": r["pending_entries"],
                        "instrumented": r["instrumented"]}
                  for cid, r in report["cases"].items()},
        "low_discriminativity": list(
            (report.get("mutation") or {}).get("low_discriminativity") or []),
        "counts": report["counts"],
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)
    return path


def record_posteriors(ws, report: dict) -> Path | None:
    """#106 reuse: a REAL verdict (pass/fail) is one Bernoulli observation on
    the case's CasePosterior (green -> alpha+1 / red -> beta+1). Pending is
    not an observation — no update, no ledger touch. Missing/unreadable
    ledger degrades per posteriors.py's fail-open load contract."""
    import posteriors as po
    updates = {cid: row["status"] == "pass"
               for cid, row in report["cases"].items()
               if row["status"] in ("pass", "fail")}
    if not updates:
        return None
    led = po.PosteriorLedger.load(ws)
    for cid, passed in updates.items():
        cp = led.cases.get(cid) or po.CasePosterior(cid)
        cp.update(passed)
        led.cases[cid] = cp
    return led.save(ws)


# ------------------------------------------------- #146 case abandonment

def _armed_case_count(cases_dir: Path) -> int:
    """Cases still in the acceptance net (not retired)."""
    cases_dir = Path(cases_dir)
    if not cases_dir.is_dir():
        return 0
    total = 0
    for p in sorted(cases_dir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — unreadable is not signal
            continue
        if isinstance(doc, dict) and str(doc.get("status") or "").strip() \
                != RETIRED_CASE_STATUS:
            total += 1
    return total


def _emit_coverage_decreased(ws, case_id: str, before: int, after: int) -> None:
    """#146 coverage-drop WARN: retiring shrank the acceptance net. The
    word is a registered EMIT_ACTIONS member (the #459 controlled
    vocabulary); fail-open — telemetry never breaks a retirement."""
    try:
        from kunglao_log import emit
        emit(ws, actor="oracle_runner",
             action="acceptance_coverage_decreased",
             detail=(f"case={case_id} armed_cases={after} (was {before}) — "
                     f"acceptance coverage decreased"))
    except Exception:  # noqa: BLE001 — observability never disturbs the run
        pass


def retire_case(ws, case_id: str, *, attribution_class: str,
                disconfirmation: str, replacement: str) -> dict:
    """#146 case-abandonment protocol: retire a case, append-only, with
    the structured justification — or loud refusal.

    REQUIRED justification (anything less -> OracleCaseError, nothing
    written):
      - attribution_class: one of RETIREMENT_ATTRIBUTION_CLASSES (closed
        taxonomy: implementation-wrong | case-wrong | client-wrong |
        channel-wrong | capture-obsolete);
      - disconfirmation: the alternatives were argued away (text);
      - replacement: re-capture / re-derive / successor plan (text).

    The case file keeps everything it had (append-only): ``status:
    retired`` and the ``retirement`` block are ADDED. Retiring an
    already-retired case is refused (one transition, append-only). The
    armed-case count drop fires the acceptance_coverage_decreased WARN.

    Returns the retirement record; raises OracleCaseError on refusal."""
    cases_dir = Path(ws).joinpath(*CASES_REL)
    if not cases_dir.is_dir():
        raise OracleCaseError(f"no case set under {cases_dir} — nothing to "
                              f"retire")
    wanted = str(case_id or "").strip()
    target: Path | None = None
    doc: dict | None = None
    for p in sorted(cases_dir.glob("*.yaml")):
        try:
            candidate = yaml.safe_load(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — skip unreadable candidates
            continue
        if not isinstance(candidate, dict):
            continue
        cid = str(candidate.get("id") or p.stem).strip()
        if cid == wanted:
            target, doc = p, candidate
            break
    if target is None or doc is None:
        raise OracleCaseError(f"no case {wanted!r} under {cases_dir} — "
                              f"nothing to retire")
    if str(doc.get("status") or "").strip() == RETIRED_CASE_STATUS:
        raise OracleCaseError(f"case {wanted!r} is already retired — "
                              f"retirement is a one-way append-only "
                              f"transition (#146)")
    attribution_class = str(attribution_class or "").strip()
    disconfirmation = str(disconfirmation or "").strip()
    replacement = str(replacement or "").strip()
    if attribution_class not in RETIREMENT_ATTRIBUTION_CLASSES:
        raise OracleCaseError(
            f"case {wanted!r}: attribution_class {attribution_class!r} is "
            f"not in the closed taxonomy "
            f"({', '.join(RETIREMENT_ATTRIBUTION_CLASSES)}) — a retirement "
            f"without attribution is a silent abandonment (#146)")
    if not disconfirmation:
        raise OracleCaseError(
            f"case {wanted!r}: retirement needs `disconfirmation` — the "
            f"alternatives must be argued away before the case is "
            f"abandoned (#146)")
    if not replacement:
        raise OracleCaseError(
            f"case {wanted!r}: retirement needs `replacement` — the "
            f"acceptance-net hole must have a re-capture / re-derive / "
            f"successor plan (#146)")
    armed_before = _armed_case_count(cases_dir)
    doc["status"] = RETIRED_CASE_STATUS
    doc["retirement"] = {
        "attribution_class": attribution_class,
        "disconfirmation": disconfirmation,
        "replacement": replacement,
        "retired_at": utc_now_iso(),
    }
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    os.replace(tmp, target)
    armed_after = _armed_case_count(cases_dir)
    if armed_after < armed_before:
        _emit_coverage_decreased(ws, wanted, armed_before, armed_after)
    return {"case_id": wanted, "status": RETIRED_CASE_STATUS,
            "retirement": dict(doc["retirement"]),
            "armed_cases_before": armed_before,
            "armed_cases_after": armed_after}


# --------------------------------------------------------------------- CLI

def _human(report: dict) -> str:
    lines = [f"=== ORACLE RUN: {report['counts']['green']} green / "
             f"{report['counts']['red']} red / "
             f"{report['counts']['pending']} pending "
             f"(client: {report['client'] or 'NONE — all pending'}) ==="]
    for cid, row in report["cases"].items():
        mark = {"pass": "PASS", "fail": "FAIL",
                "pending": "PEND"}[row["status"]]
        lines.append(f"  [{mark}] {cid} "
                     f"(pending_entries={row['pending_entries']})")
        for f in row["failures"]:
            lines.append(f"         {f}")
        if row["error"]:
            lines.append(f"         error: {row['error']}")
        fore = row.get("forensics") or {}
        if fore.get("divergence_point"):
            lines.append(f"         divergence@{fore['divergence_point']} "
                         f"(stages: {fore.get('stages')})")
        if fore.get("meta"):
            lines.append(f"         meta: {fore['meta']}")
    if report.get("retired"):
        lines.append(f"  [RETIRED, not run] {', '.join(report['retired'])}")
    mut = report.get("mutation") or {}
    for cid, rows in (mut.get("mutations") or {}).items():
        for r in rows:
            lines.append(f"  [MUT] {cid}: {r['field']} {r['kind']} -> "
                         f"{'RED (discriminates)' if r['red'] else 'STAYED GREEN'}")
    for cid in (mut.get("low_discriminativity") or []):
        lines.append(f"  [LOW-DISCRIMINATIVITY] {cid}: green under every "
                     f"declared mutation — the case observes nothing its "
                     f"author claims distinguishes it; strengthen the case "
                     f"or revise its mutation set")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="oracle_runner.py",
        description="kunglao-agent oracle runner — red/green verdicts + "
                    "mutation-must-fail self-test (#108)")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--client", default=None,
                    help="client module path (default: <ws>/oracle/client.py "
                         "when present; without a client every case is pending)")
    ap.add_argument("--mutation", action="store_true",
                    help="run the mutation-must-fail pass over each case's "
                         "declared mutations (flag low_discriminativity)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable report on stdout")
    # #146 case-abandonment face
    ap.add_argument("--retire", metavar="CASE_ID", default=None,
                    help="#146: retire a case (append-only status: retired "
                         "in its case file) — requires the structured "
                         "justification flags below")
    ap.add_argument("--attribution-class", default=None,
                    help="#146 retirement taxonomy: implementation-wrong | "
                         "case-wrong | client-wrong | channel-wrong | "
                         "capture-obsolete")
    ap.add_argument("--disconfirmation", default=None,
                    help="#146 retirement: how the alternative attributions "
                         "were argued away")
    ap.add_argument("--replacement", default=None,
                    help="#146 retirement: re-capture / re-derive / "
                         "successor-case plan for the coverage hole")
    args = ap.parse_args(argv)

    ws = Path(args.workspace)
    cases_dir = ws.joinpath(*CASES_REL)

    # #146 case-abandonment face: retire before any run face (a refusal
    # never touches the status file or the posteriors).
    if args.retire:
        try:
            rec = retire_case(
                ws, args.retire,
                attribution_class=args.attribution_class or "",
                disconfirmation=args.disconfirmation or "",
                replacement=args.replacement or "")
        except OracleCaseError as exc:
            print(f"oracle_runner: RETIRE REFUSED — {exc}", file=sys.stderr)
            return 2
        print(json.dumps(rec, ensure_ascii=False, indent=2, default=repr))
        return 0

    if not cases_dir.is_dir():
        print(f"oracle_runner: no {cases_dir} — nothing to bless "
              f"(no status written)", file=sys.stderr)
        return 0
    try:
        load_cases(cases_dir)  # lint refusal: loud, before any IO
    except OracleCaseError as exc:
        print(f"oracle_runner: REFUSED — {exc}", file=sys.stderr)
        return 2
    client = args.client
    if client is None:
        default_client = ws.joinpath(*DEFAULT_CLIENT_REL)
        client = str(default_client) if default_client.exists() else None
    report = run(cases_dir, client, mutation=args.mutation)
    write_status(ws, report)
    record_posteriors(ws, report)
    # default=repr (#146): forensics carry raw client values — a
    # non-JSON-serializable client output must never crash the report face
    print(json.dumps(report, ensure_ascii=False, indent=2, default=repr)
          if args.json else _human(report))
    return 1 if report["counts"]["red"] else 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())

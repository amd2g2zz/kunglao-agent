# -*- coding: utf-8 -*-
"""recipe_arms.py — issue #695: tool-chain recipe arms (the learned
tool-choice substrate).

Owner rulings: tool selection and tool-chain orchestration are
first-class actions of the controller, never a static table injected
into a dispatch prompt (2026-10-11, closed #667); tool value is
context-dependent with no silver bullet — a decompiler is low-value on
a heavily obfuscated target and high-value again once a deobfuscation
step produced clean input (2026-10-14). This module is the v0.1.6
SUBSTRATE: arms + propensity + trusted settlement attribution. The v0.2
loop that switches policies on it is #50/#13.

An ARM is a RECIPE: ``{recipe_id, tool_class, invocation, artifact}``
scoped to a method family (the Q-key action half — a token names the
APPROACH, #432; the tool chain is a RIDER and never enters the key).
A dispatch may carry a recommended recipe with a logged propensity —
recommendation, NEVER restriction: the worker (frozen LLM) stays free,
instrument availability is an annotation, and divergence from the
sampler is a recorded decision (``recipe_deviation`` event), never a
new REJECT surface.

NOTE the naming split, deliberately kept: the 4-dim ``arm_key``'s
``context_recipe`` dim (q_cells.arm_key — facts_snapshot etc., #539)
is the dispatch CONTEXT recipe; this module's ``recipe_id`` is the
TOOL-CHAIN arm. They never share a field or a fold.

## Cold start = static prior with gravity (never the policy)

The registry below is a hand-mined cold-start prior over each family's
arms (tier chains / tools/_INDEX capability faces), every ``prior``
strictly positive. Data overturns it: the sampling weight is
``prior * max(theta, THETA_FLOOR)`` where theta is the arm's Beta
posterior mean from SETTLED recipe-credited rounds. THETA_FLOOR (0.1,
the same PARK posture as termination.ARM_FLOOR, kept local so this
module never imports the termination face) guarantees an arm is
floored, never deleted — a beaten arm keeps positive mass and revives
on new success.

## Agent dimension (owner comment on #695, 2026-10-15, MARL #705)

Posteriors are keyed per (recipe, agent type): ``arm_weights(...,
agent=...)`` uses the agent-local solve counts, and a cold agent
inherits its peers through the LAMBDA-tempered pooled mass (a
warm-start prior — not forced pooling; ``meta_arms.LAMBDA``). Only
SOLVE credit updates the posterior: a settlement carrying
``credit_kind: verification`` (#705's decomposition) is recorded but
excluded from the fold (verification credit != solve credit).

## Recording + credit (the #691 / #678 shapes at the tool grain)

``record_dispatch_recipe`` is called from
``q_cells.record_dispatch_observation`` (the dispatch ALLOW tail): the
q-cell dispatch row carries ``{recipe_id, recipe_propensity,
recipe_source: sampled|declared|none}``. The envelope's declared
``recipe_id`` is reconciled against THIS module's own sampler draw at
dispatch time (anti-spoof — nothing the envelope says can move it;
propensity = the draw probability of the recorded recipe, 0.0 outside
the arm support, null when no sampler view exists). ``observe_settlement``
then carries the triple onto the settlement row — credit banks against
the DISPATCH-RECORDED recipe without ever reading a worker narrative
(the #881 tool_value ``steps:`` pattern stays dead).

``replay_report(ws)`` is the S2-shape offline face: rerun the sampler
over recorded history, report arm-level separation and the
disagreement rate — offline evidence before any online switch.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

from kunglao_log import emit as _klog_emit
from kunglao_log import warn

#: the posterior-mean floor — floored, never deleted (PARK posture;
#: same value as termination.ARM_FLOOR, never imported across faces).
THETA_FLOOR = 0.1

#: recipe sources recorded on observation rows (closed vocabulary).
SOURCES = ("sampled", "declared", "none")


@dataclass(frozen=True)
class RecipeArm:
    """One tool-chain arm of a method family — the cold-start prior
    (``prior`` > 0 always; data overturns, never deletes)."""

    recipe_id: str
    method_family: str
    tool_class: str
    invocation: str
    artifact: str
    prior: float


#: #695 T4 — >= 3 arms per registered family. The cold-start prior is
#: hand-mined gravity (tier chains / tools/_INDEX faces), never the
#: policy: weights move with settled credit, and the floor keeps every
#: arm samplable. One line per arm; ids are global and unique.
RECIPE_ARMS: tuple[RecipeArm, ...] = (
    # structural-anchoring
    RecipeArm("identity:hash-map", "structural-anchoring", "identity",
              "sha256 + byte-offset structural map", "evidence/sample-identity.json", 0.6),
    RecipeArm("prescan:die-apkid", "structural-anchoring", "prescan",
              "die --format json + apkid per family", "evidence/die.json", 0.5),
    RecipeArm("signature:pefile", "structural-anchoring", "signature",
              "pefile Authenticode parse", "evidence/signature.json", 0.4),
    # static-decompile
    RecipeArm("disasm:ghidra-headless", "static-decompile", "disasm",
              "analyzeHeadless import + postScript export", "evidence/static-ghidra.json", 0.6),
    RecipeArm("disasm:radare2", "static-decompile", "disasm",
              "r2 aaa + pdf/pddj function text", "evidence/r2-functions.json", 0.45),
    RecipeArm("strings:floss", "static-decompile", "strings",
              "flare-floss extract + two-layer filter", "evidence/floss-filtered.json", 0.45),
    # dynamic-trace
    RecipeArm("debugger:x64dbg", "dynamic-trace", "debugger",
              "x64dbg session + bp/bctx trace", "evidence/dynamic-trace.json", 0.55),
    RecipeArm("instrument:frida", "dynamic-trace", "instrument",
              "frida spawn/attach + hook script", "evidence/frida-hooks.json", 0.5),
    RecipeArm("trace:strace", "dynamic-trace", "trace",
              "strace -f syscall capture + diff", "evidence/strace.json", 0.4),
    # obfuscation-peeling
    RecipeArm("js:webcrack", "obfuscation-peeling", "js-unbundle",
              "webcrack unpack pass", "evidence/unpack_out/index.json", 0.55),
    RecipeArm("js:wakaru", "obfuscation-peeling", "js-interpret",
              "wakaru interpret + normalized tree", "evidence/unpack_out/wakaru.json", 0.45),
    RecipeArm("pack:upx-unpack", "obfuscation-peeling", "unpack",
              "upx -d + re-scan the recovered image", "evidence/unpacked.bin", 0.5),
    # crypto-core-identification
    RecipeArm("crypto:constant-diff", "crypto-core-identification", "crypto",
              "constant-set diff vs reference tables", "evidence/crypto-identify.json", 0.6),
    RecipeArm("crypto:cipher-shape", "crypto-core-identification", "crypto",
              "cipher shape classification (SBOX/RCON/round count)",
              "evidence/cipher-shape.json", 0.45),
    RecipeArm("crypto:tool-decode", "crypto-core-identification", "crypto",
              "crypto-tool.py decode against candidate primitives",
              "evidence/crypto-tool.json", 0.45),
    # kdf-chain-reconstruction
    RecipeArm("kdf:counter-replay", "kdf-chain-reconstruction", "kdf",
              "counter-mode rebuild + byte-exact replay",
              "evidence/kdf-chain.json", 0.55),
    RecipeArm("kdf:arx-trace", "kdf-chain-reconstruction", "kdf",
              "ARX op trace of the iterated core",
              "evidence/kdf-arx.json", 0.45),
    RecipeArm("kdf:unicorn-emulate", "kdf-chain-reconstruction", "kdf",
              "Unicorn emulate the core with PLT stubs", "evidence/kdf-unicorn.json", 0.45),
    # protocol-flow-reconstruction
    RecipeArm("net:pcap-replay", "protocol-flow-reconstruction", "net",
              "pcap round-trip capture + shape trace", "evidence/protocol-flow.json", 0.55),
    RecipeArm("net:camoufox", "protocol-flow-reconstruction", "net",
              "camoufox session + XHR/WS interception", "evidence/session-capture.json", 0.5),
    RecipeArm("net:api-shape", "protocol-flow-reconstruction", "net",
              "request/response JSON shape walk", "evidence/api-shapes.json", 0.4),
    # anti-analysis-discrimination
    RecipeArm("anti:canary-probe", "anti-analysis-discrimination", "anti-analysis",
              "trip the canary, prove the live branch", "evidence/canary-probe.json", 0.55),
    RecipeArm("anti:branch-flip", "anti-analysis-discrimination", "anti-analysis",
              "force each branch, diff outputs", "evidence/branch-flip.json", 0.45),
    RecipeArm("anti:timing-xor", "anti-analysis-discrimination", "anti-analysis",
              "timing/XOR-poison decay measurement", "evidence/timing-decay.json", 0.45),
    # replay-harness-verification
    RecipeArm("replay:python-reimpl", "replay-harness-verification", "replay",
              "python reimplementation + byte-equivalence", "evidence/replay-roundtrip.json", 0.6),
    RecipeArm("replay:go-port", "replay-harness-verification", "replay",
              "Go port + recorded-pair replay", "evidence/replay-go.json", 0.45),
    RecipeArm("replay:harness", "replay-harness-verification", "replay",
              "standalone harness over recorded pairs", "evidence/replay-harness.json", 0.45),
    # pair-match-verification
    RecipeArm("pair:field-diff", "pair-match-verification", "pair",
              "input/output pair ground + field diff", "evidence/pair-match.json", 0.55),
    RecipeArm("pair:golden-vectors", "pair-match-verification", "pair",
              "golden vector set through the candidate", "evidence/golden-vectors.json", 0.45),
    RecipeArm("pair:harness-replay", "pair-match-verification", "pair",
              "checker_kind=pair-match harness replay", "evidence/pair-replay.json", 0.45),
    # red-team-verification
    RecipeArm("adversarial:blind-redteam", "red-team-verification", "adversarial",
              "blind red-team attack from raw evidence", "evidence/verify-redteam.md", 0.6),
    RecipeArm("adversarial:rederive", "red-team-verification", "adversarial",
              "independent re-derivation of the claim", "evidence/rederive.json", 0.45),
    RecipeArm("adversarial:verdict-scorer", "red-team-verification", "adversarial",
              "verdict-scorer PQ coverage check", "evidence/verdict.json", 0.45),
    # hypothesis-falsification
    RecipeArm("falsify:kill-experiment", "hypothesis-falsification", "falsify",
              "run the named kill experiment", "evidence/falsifier-result.json", 0.6),
    RecipeArm("falsify:discriminator", "hypothesis-falsification", "falsify",
              "one discriminator separating the candidates", "evidence/discriminator.json", 0.45),
    RecipeArm("falsify:exclusion", "hypothesis-falsification", "falsify",
              "alternate-exclusion sweep", "evidence/exclusion.json", 0.4),
)

ARMS_BY_FAMILY: dict[str, tuple[RecipeArm, ...]] = {}
ARMS_BY_ID: dict[str, RecipeArm] = {}
for _arm in RECIPE_ARMS:
    ARMS_BY_FAMILY.setdefault(_arm.method_family, []).append(_arm)
    ARMS_BY_ID[_arm.recipe_id] = _arm
ARMS_BY_FAMILY = {f: tuple(v) for f, v in ARMS_BY_FAMILY.items()}


def arm_ids_for(family: str) -> tuple[str, ...]:
    """The registered arm ids of one family (())."""
    return tuple(a.recipe_id for a in ARMS_BY_FAMILY.get(family, ()))


def declared_recipe(envelope_meta, prompt_text: str | None = None) -> str | None:
    """The envelope-declared tool-chain recipe (v1 field only — v1 is
    the one dispatch protocol; no prose face, unlike #432's dual-face
    family marker)."""
    del prompt_text  # envelope-only contract; kept for face symmetry
    if isinstance(envelope_meta, dict):
        v = envelope_meta.get("recipe_id")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


# ---------------------------------------------------------------------------
# the fold (solve credit only) + posteriors with the floor
# ---------------------------------------------------------------------------

def _zero_counts() -> dict:
    return {"success": 0.0, "failure": 0.0, "rows": 0,
            "agent_success": 0.0, "agent_failure": 0.0}


def arm_fold(ws, agent: str | None = None) -> dict[str, dict]:
    """Per-recipe solve-credit counts from the settlement rows of
    ``runs/q-cell-log.jsonl`` (the #678 trusted chain — the fold reads
    MECHANICALLY recorded rows, never a worker narrative). A row
    carrying ``credit_kind: verification`` is recorded but never
    learned from (#705). Keys: every registered arm (zeros
    when unseen — arms are never absent from the table); with ``agent``
    the agent-local split rides along (``agent_success`` /
    ``agent_failure`` — a subset of the pooled mass)."""
    out = {rid: _zero_counts() for rid in ARMS_BY_ID}
    try:
        from rlvr import q_cells as _qc  # noqa: PLC0415 — lazy (cycle wall)
        for row in _qc.JSONLQStore(ws).observations():
            if not isinstance(row, dict) or row.get("source") != "settlement":
                continue
            rid = row.get("recipe_id")
            credit = row.get("credit")
            if not isinstance(rid, str) or rid not in out:
                continue
            if isinstance(credit, bool) or not isinstance(credit, (int, float)):
                continue
            if str(row.get("credit_kind") or "") == "verification":
                continue  # verification credit != solve credit (#705)
            v = max(0.0, min(1.0, float(credit)))
            c = out[rid]
            c["success"] += v
            c["failure"] += 1.0 - v
            c["rows"] += 1
            if agent is not None and \
                    str(row.get("agent") or "") == str(agent):
                c["agent_success"] += v
                c["agent_failure"] += 1.0 - v
    except Exception as exc:  # noqa: BLE001 — telemetry, never the producer
        warn("recipe_arms.fold", f"{type(exc).__name__}: {exc}")
    return out


def _posterior(pooled: dict, local: dict | None) -> tuple[float, float]:
    """Beta(alpha, beta) — the LAMBDA-tempered pooled mass (minus the
    agent-local rows, counted exactly once) as the warm-start prior,
    the agent-local counts on top (owner comment on #695: cross-agent
    transfer via warm-start, never forced pooling)."""
    from rlvr.meta_arms import LAMBDA  # noqa: PLC0415 — lazy
    if local is None:
        return (1.0 + pooled["success"], 1.0 + pooled["failure"])
    return (1.0 + LAMBDA * pooled["success"] + local["success"],
            1.0 + LAMBDA * pooled["failure"] + local["failure"])


def arm_weights(ws, family: str, agent: str | None = None) -> dict[str, float]:
    """The sampling weights of one family's arms:
    ``prior * max(theta, THETA_FLOOR)`` — every weight strictly
    positive (floored, never deleted, revivable by new success)."""
    arms = ARMS_BY_FAMILY.get(family)
    if not arms:
        return {}
    fold = arm_fold(ws, agent=agent)
    weights: dict[str, float] = {}
    for a in arms:
        c = fold[a.recipe_id]
        if agent is None:
            local, pooled = None, {"success": c["success"],
                                   "failure": c["failure"]}
        else:
            # a cold agent still runs the warm-start path (LAMBDA-
            # tempered peers) — zero local counts, never full pooling
            local = {"success": c["agent_success"],
                     "failure": c["agent_failure"]}
            pooled = {"success": max(0.0, c["success"] - local["success"]),
                      "failure": max(0.0, c["failure"] - local["failure"])}
        alpha, beta = _posterior(pooled, local)
        theta = max(alpha / (alpha + beta), THETA_FLOOR)
        weights[a.recipe_id] = a.prior * theta
    return weights


def _rng_for(family: str, weights: dict[str, float]) -> random.Random:
    """Deterministic draw seed from (family, weights) — the draw moves
    when the evidence moves, never by wall clock (#251 posture)."""
    payload = json.dumps(
        {"family": family,
         "weights": {k: round(v, 9) for k, v in sorted(weights.items())}},
        sort_keys=True, ensure_ascii=False)
    return random.Random(int(hashlib.sha256(
        payload.encode("utf-8")).hexdigest()[:16], 16))


def sample_recipe(ws, family: str, *, agent: str | None = None,
                  rng: random.Random | None = None) -> dict | None:
    """Draw ONE recipe arm of the family (proportional to the floored
    weights) — the gate-time counterfactual/propensity authority.
    Returns ``{recipe_id, propensity, weights}`` or None when the family
    has no registered arms (the honest gap, never a fabricated draw)."""
    weights = arm_weights(ws, family, agent=agent)
    if not weights:
        return None
    order = sorted(weights)
    total = sum(weights.values())
    if total <= 0.0 or not total == total:  # pragma: no cover — floor > 0
        return None
    r = rng if rng is not None else _rng_for(family, weights)
    u = r.random() * total
    chosen, cumulative = order[-1], 0.0
    for rid in order:
        cumulative += weights[rid]
        if u <= cumulative:
            chosen = rid
            break
    return {"recipe_id": chosen,
            "propensity": round(weights[chosen] / total, 6),
            "weights": {k: round(v, 9) for k, v in weights.items()}}


# ---------------------------------------------------------------------------
# the dispatch recording face (called from q_cells at the ALLOW tail)
# ---------------------------------------------------------------------------

def _reason_of(prompt: str | None) -> str | None:
    m = re.search(r'agent-reasoning:[ \t]*([^\n]+)', prompt or '',
                  re.IGNORECASE)
    return (m.group(1).strip()[:200] or None) if m else None


def _emit_recipe_deviation(ws, claim: str | None, view: dict) -> None:
    """One ``recipe_deviation`` event (a registered EMIT_ACTIONS word)
    — the recorded decision, never a gate. Fail-open: a logging failure
    never touches the producer."""
    detail = json.dumps({
        "declared": view.get("recipe_id"),
        "sampled": view.get("sampled_recipe"),
        "propensity": view.get("propensity"),
        "registered": view.get("registered"),
        "reason": view.get("reason"),
    }, ensure_ascii=False)
    try:
        if ws:
            _klog_emit(Path(ws), 'rlvr.recipe_arms', 'recipe_deviation',
                       claim=claim, detail=detail)
    except Exception as exc:  # noqa: BLE001 — logging never breaks dispatch
        warn("recipe_arms.emit", f"{type(exc).__name__}: {exc}")


def record_dispatch_recipe(ws, *, family: str | None,
                           envelope_meta=None,
                           prompt: str | None = None,
                           agent: str | None = None,
                           claim: str | None = None) -> dict:
    """The dispatch-time recipe view — the #691 shape at the tool
    grain. Returns the closed-vocabulary triple
    ``{recipe_id, propensity, source}`` plus the sampler face
    (``sampled_recipe``, ``deviates``, ``registered``, ``reason``):

    - envelope declared the sampler's own draw -> ``sampled`` (the
      dispatch followed the policy; propensity = the draw probability);
    - envelope declared anything else -> ``declared`` (propensity = its
      probability under the sampler; 0.0 outside the arm support — the
      honest number, not a gap) + one ``recipe_deviation`` event when
      it deviates from the draw (registered or not — NEVER rejected);
    - nothing declared and the sampler drew -> ``sampled`` (the
      sampler's recommendation recorded against the dispatch);
    - no family / no arms / sampler failure -> ``none`` (explicit nulls).

    Fail-open throughout: a sampler failure is ONE rate-limited warn and
    degrades to the none view; the caller's dispatch row still lands."""
    gap = {"recipe_id": None, "propensity": None, "source": "none",
           "sampled_recipe": None, "deviates": False, "registered": None,
           "reason": None}
    if not family:
        return gap
    declared = declared_recipe(envelope_meta, prompt)
    receipt = None
    try:
        receipt = sample_recipe(ws, str(family), agent=agent)
    except Exception as exc:  # noqa: BLE001 — telemetry, never the gate
        warn("recipe_arms.sample", f"{type(exc).__name__}: {exc}")
    weights = (receipt or {}).get("weights") or {}
    sampled = (receipt or {}).get("recipe_id")
    if declared is None:
        if receipt is None:
            return gap
        view = dict(gap)
        view.update({"recipe_id": sampled, "propensity": receipt["propensity"],
                     "source": "sampled", "sampled_recipe": sampled,
                     "registered": True})
        return view
    registered = declared in ARMS_BY_ID
    propensity = None
    deviates = False
    if receipt is not None:
        total = sum(weights.values())
        propensity = (round(weights.get(declared, 0.0) / total, 6)
                      if total > 0.0 else None)
        deviates = bool(sampled) and declared != sampled
    view = dict(gap)
    view.update({"recipe_id": declared, "propensity": propensity,
                 # declared == the gate's own draw IS the on-policy
                 # face: the dispatch followed the sampler (recorded as
                 # sampled); anything else is the declared deviation
                 "source": ("declared" if deviates or receipt is None
                            else "sampled"),
                 "sampled_recipe": sampled,
                 "deviates": deviates, "registered": registered,
                 "reason": _reason_of(prompt)})
    if deviates:
        _emit_recipe_deviation(ws, claim, view)
    return view


# ---------------------------------------------------------------------------
# the S2-shape replay (offline only — no online switch)
# ---------------------------------------------------------------------------

def _disagreement_count(ws, argmax: dict[str, str | None],
                        agent: str | None) -> int:
    """Dispatch rows whose recorded recipe is NOT the family's current
    argmax (the replay's disagreement numerator)."""
    from rlvr import q_cells as _qc  # noqa: PLC0415 — lazy
    n = 0
    for row in _qc.JSONLQStore(ws).observations():
        if not isinstance(row, dict) or row.get("source") != "dispatch":
            continue
        if agent is not None and str(row.get("agent") or "") != str(agent):
            continue
        rid = row.get("recipe_id")
        if not isinstance(rid, str) or rid not in ARMS_BY_ID:
            continue
        fam = ARMS_BY_ID[rid].method_family
        if argmax.get(fam) is not None and rid != argmax[fam]:
            n += 1
    return n


def replay_report(ws, *, agent: str | None = None) -> dict:
    """The offline replay over recorded history (S2 shape): rerun the
    CURRENT weights over every recipe-carrying dispatch row, report
    arm-level separation (per-recipe mean settled credit + the argmax
    arm per family) and the disagreement rate (recorded recipe != the
    family's current argmax). Offline evidence — this face never moves
    a dispatch decision. Empty history -> rows 0, rate None."""
    from rlvr import q_cells as _qc  # noqa: PLC0415 — lazy
    rows = skipped = 0
    per_recipe: dict[str, list[float]] = {rid: [] for rid in ARMS_BY_ID}
    families: dict[str, int] = {}
    for row in _qc.JSONLQStore(ws).observations():
        if not isinstance(row, dict):
            continue
        rid = row.get("recipe_id")
        if row.get("source") == "settlement" and isinstance(rid, str) \
                and rid in per_recipe \
                and not isinstance(row.get("credit"), bool) \
                and isinstance(row.get("credit"), (int, float)):
            per_recipe[rid].append(float(row["credit"]))
        if row.get("source") != "dispatch":
            continue
        if agent is not None and str(row.get("agent") or "") != str(agent):
            continue
        if not isinstance(rid, str) or rid not in ARMS_BY_ID:
            skipped += 1
            continue
        rows += 1
        fam = ARMS_BY_ID[rid].method_family
        families[fam] = families.get(fam, 0) + 1
    argmax: dict[str, str | None] = {}
    fam_docs: dict[str, dict] = {}
    for fam in sorted(families):
        weights = arm_weights(ws, fam, agent=agent)
        best = max(sorted(weights), key=lambda k: weights[k]) \
            if weights else None
        argmax[fam] = best
        fam_docs[fam] = {
            "argmax": best,
            "weights": {k: round(v, 9) for k, v in weights.items()},
            "mean_credit": {
                rid: (round(sum(v) / len(v), 6) if v else None)
                for rid, v in sorted(per_recipe.items())
                if ARMS_BY_ID[rid].method_family == fam},
        }
    disagreements = _disagreement_count(ws, argmax, agent)
    return {"shape": "S2", "rows": rows, "skipped": skipped,
            "disagreement_rate": (round(disagreements / rows, 6)
                                  if rows else None),
            "families": fam_docs}

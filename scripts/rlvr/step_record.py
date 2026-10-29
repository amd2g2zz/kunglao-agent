# -*- coding: utf-8 -*-
"""rlvr/step_record.py — the `step/1` record layer (card P1 of the
learning-loop live-wire program).

One step = ONE loop of the scientific method (the owner's ruling on the
learning layer): assert discriminable hypotheses, take the
highest-discrimination action, and close the loop with an EXPLICIT
hypothesis contraction — which hypotheses survive, flip, or die. The
step is the atomic learning unit P2 settles and P3 reviews; episodes
are made of steps, not the other way around.

Grain discipline (the family precedent): ``rlvr.step_ledger`` (the
PostToolUse shadow account) records tool-call telemetry at hash-only
grain; ``rlvr.hypotheses`` owns the layer-scoped hypothesis registry at
family/primitive/composition grain. `step/1` is the mission-step grain —
same family, different altitude; nothing here reads or writes either.

Faces:
  - ``validate_step(doc)`` — the fail-closed `step/1` validator (the
    episode_schema error style: StepRecordError names the offending
    field). HARD rules: every hypothesis is discriminable (a
    kill-experiment clause must be statable) and the conclusion must
    reference at least one of the step's hypotheses (the contraction is
    explicit, never ambient narration).
  - ``index_view`` / ``segment_view`` / ``tree_view`` — the three
    trajectory windows P3 reviews through: the action->conclusion
    table, the anchor->deviation segment, the hypothesis-state chain.
  - ``backward_plan`` / ``claim_checkpoints`` — goal-backward planning
    (the orchestrator's first act): the minimal checkpoint chain
    derived from the success criterion; claims open only at gaps (the
    checkpoints no known evidence covers).

Pure module: no IO, no store. Conclusion verdicts are mechanical
(word-bounded markers over the conclusion text) so the views stay
deterministic and pinned.
"""
from __future__ import annotations

import re

SCHEMA = "step/1"

#: the reward source vocabulary (step/1: reward = {value, source})
REWARD_SOURCES = ("phi_gain", "evidence", "checkpoint", "cost")

#: hypothesis key vocabulary — the claim and its kill-experiment clause
#: are each accepted under any of these equivalent keys
_CLAIM_KEYS = ("claim", "statement", "hypothesis")
_KILL_KEYS = ("kill_test", "kill_experiment", "falsifier", "experiment")
_ID_KEYS = ("id", "tag", "name")

_STRING_FIELDS = ("task", "observation", "action", "result")

# Mechanical contraction vocabulary (word-bounded, case-insensitive).
# "kill" is deliberately NOT a refute marker — "kill test/kill
# experiment" is the neutral narrative noun; death is stated as
# dies/died/refuted/falsified/...
_REFUTE_RE = re.compile(
    r"\b(dies|died|refuted|refutes|refute|rejected|rejects|reject|"
    r"contradicted|contradicts|contradict|disconfirmed|disconfirms|"
    r"disconfirm|flipped|flips|flip|falsified|falsifies|falsify|wrong|"
    r"failed|fails)\b", re.IGNORECASE)
_CONFIRM_RE = re.compile(
    r"\b(survives|survived|survive|confirmed|confirms|confirm|"
    r"corroborated|corroborates|corroborate|holds|hold)\b",
    re.IGNORECASE)

# clauses are the contraction's resolution unit (tree deaths and
# verdicts are clause-scoped so "H2 dies; H1 survives" kills only H2)
_CLAUSE_SPLIT_RE = re.compile(r"[.;\n。；]")
_CRITERION_SPLIT_RE = re.compile(r"\n+|;|。|；|\.\s+|\band\b|\bthen\b",
                                 re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)

#: function words too generic to count as a reference between a
#: conclusion and a hypothesis claim (or between criterion and evidence)
_STOPWORDS = frozenset({
    "the", "this", "that", "these", "those", "with", "from", "into",
    "onto", "over", "under", "have", "has", "had", "been", "were",
    "will", "would", "could", "should", "must", "shall", "then", "than",
    "when", "what", "which", "while", "there", "their", "they", "them",
    "also", "very", "more", "most", "some", "such", "only", "same",
    "both", "each", "after", "before", "until", "upon", "just", "like",
    "made", "make", "does", "done", "its"})


class StepRecordError(ValueError):
    """A document is not a legal `step/1` record. The message names the
    offending field (fail-closed, machine-readable)."""


def _fail(field: str, why: str) -> StepRecordError:
    return StepRecordError(f"step.{field}: {why}")


def _req(doc: dict, field: str):
    if field not in doc:
        raise _fail(field, "missing (schema step/1 requires it)")
    return doc[field]


def _as_str(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(field, "must be a non-empty string")
    return value


def _salient_terms(text) -> set[str]:
    """Content tokens (length >= 4, stopwords dropped, case-folded) —
    the mechanical reference test between a conclusion and a hypothesis
    claim, and between a checkpoint and known evidence. Deterministic;
    never a model call."""
    return {t for t in (w.casefold() for w in _TOKEN_RE.findall(str(text)))
            if len(t) >= 4 and t not in _STOPWORDS}


def _first_str(doc: dict, keys) -> str | None:
    for k in keys:
        v = doc.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None


def _hyp_claim(hyp: dict) -> str:
    return _first_str(hyp, _CLAIM_KEYS) or ""


def _hyp_identity(hyp: dict) -> str:
    """A hypothesis's identity within the trajectory tree: its explicit
    id when carried, else its claim text."""
    return _first_str(hyp, _ID_KEYS) or _hyp_claim(hyp)


def _id_in_text(ident: str, text: str) -> bool:
    """Word-bounded id reference: 'H1' must not reach inside 'H10'."""
    if not ident:
        return False
    return re.search(r"\b" + re.escape(ident) + r"\b", text,
                     re.IGNORECASE) is not None


# --- validator ---------------------------------------------------------------

def _validate_hypothesis(i: int, hyp) -> None:
    if not isinstance(hyp, dict):
        raise _fail("hypotheses", f"[{i}] not a mapping")
    if _first_str(hyp, _CLAIM_KEYS) is None:
        raise _fail(f"hypotheses[{i}]",
                    "missing a claim (accepted keys: "
                    f"{', '.join(_CLAIM_KEYS)})")
    if _first_str(hyp, _KILL_KEYS) is None:
        raise _fail(f"hypotheses[{i}]",
                    "not discriminable: no kill-experiment clause "
                    f"(accepted keys: {', '.join(_KILL_KEYS)}) — a "
                    "hypothesis no experiment could kill is refused")


def _contraction_references(conclusion: str, hypotheses: list) -> bool:
    """True when the conclusion references at least one of the step's
    hypotheses — by the hypothesis's id, or by sharing a salient term
    with its claim."""
    cterms = _salient_terms(conclusion)
    for hyp in hypotheses:
        if not isinstance(hyp, dict):
            continue
        ident = _hyp_identity(hyp)
        if ident and _id_in_text(ident, conclusion):
            return True
        if _salient_terms(_hyp_claim(hyp)) & cterms:
            return True
    return False


def _validate_environment(doc: dict) -> None:
    environment = _req(doc, "environment")
    if not isinstance(environment, dict):
        raise _fail("environment", "must be a mapping")
    env_type = environment.get("type")
    if not isinstance(env_type, str) or not env_type.strip():
        raise _fail("environment.type",
                    "must be a non-empty string (what kind of world "
                    "the step ran in)")


def _validate_confidence(doc: dict) -> None:
    confidence = _req(doc, "confidence")
    if isinstance(confidence, bool) or \
            not isinstance(confidence, (int, float)) or \
            not 0.0 <= float(confidence) <= 1.0:
        raise _fail("confidence", "must be a number in [0.0, 1.0]")


def _validate_reusable_when(doc: dict) -> None:
    reusable = _req(doc, "reusable_when")
    if not isinstance(reusable, list) or not reusable:
        raise _fail("reusable_when",
                    "must be a non-empty list of observable conditions")
    for i, cond in enumerate(reusable):
        _as_str(cond, f"reusable_when[{i}]")


def _validate_reward(doc: dict) -> None:
    reward = _req(doc, "reward")
    if not isinstance(reward, dict):
        raise _fail("reward", "must be a mapping {value, source}")
    value = reward.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail("reward.value", "must be a number")
    if reward.get("source") not in REWARD_SOURCES:
        raise _fail("reward.source", f"must be one of {REWARD_SOURCES}")


def validate_step(doc) -> dict:
    """Validate one document against `step/1`. Returns the document on
    success; raises StepRecordError naming the offending field
    otherwise. Pure — no IO, no mutation (returns the input
    reference)."""
    if not isinstance(doc, dict):
        raise _fail("(root)", "not a mapping")
    schema = doc.get("schema")
    if schema is not None and schema != SCHEMA:
        raise _fail("schema", f"must be {SCHEMA!r} (or absent)")
    for field in _STRING_FIELDS:
        _as_str(_req(doc, field), field)
    _validate_environment(doc)
    hypotheses = _req(doc, "hypotheses")
    if not isinstance(hypotheses, list) or not hypotheses:
        raise _fail("hypotheses",
                    "must be a non-empty list of discriminable hypotheses")
    for i, hyp in enumerate(hypotheses):
        _validate_hypothesis(i, hyp)
    conclusion = _as_str(_req(doc, "conclusion"), "conclusion")
    if not _contraction_references(conclusion, hypotheses):
        raise _fail("conclusion",
                    "hypothesis contraction not explicit: the conclusion "
                    "references none of the step's hypotheses (name which "
                    "hypotheses survive, flip, or die — by id or by the "
                    "claim's own terms)")
    _validate_confidence(doc)
    _validate_reusable_when(doc)
    if not isinstance(doc.get("used_recalled"), bool):
        raise _fail("used_recalled", "must be a bool")
    _validate_reward(doc)
    return doc


# --- trajectory views ----------------------------------------------------------

def _as_steps(steps) -> list:
    if not isinstance(steps, (list, tuple)):
        raise _fail("(views)", "steps must be an ordered list")
    return list(steps)


def index_view(steps) -> list[dict]:
    """The action->conclusion table: one row per step, trajectory
    order."""
    return [{"i": i, "action": s.get("action"),
             "conclusion": s.get("conclusion")}
            for i, s in enumerate(_as_steps(steps))]


def _step_verdict(step: dict) -> str | None:
    """The mechanical contraction verdict of one conclusion: 'refute'
    when any refute marker fires (a deviation — contradiction outranks
    confirmation), 'confirm' when only confirm markers fire, None when
    the conclusion decides nothing."""
    text = str(step.get("conclusion") or "")
    if _REFUTE_RE.search(text):
        return "refute"
    if _CONFIRM_RE.search(text):
        return "confirm"
    return None


def segment_view(steps):
    """The review window from the LAST confirmed anchor (a conclusion
    confirming its hypothesis) to the deviation (the first later step
    that flips/contradicts). Open-ended (deviation=None, window runs to
    the trajectory end) when no deviation follows the anchor; None when
    the trajectory holds no confirmed anchor at all."""
    steps = _as_steps(steps)
    anchor = None
    for i, s in enumerate(steps):
        if _step_verdict(s) == "confirm":
            anchor = i
    if anchor is None:
        return None
    deviation = None
    for j in range(anchor + 1, len(steps)):
        if _step_verdict(steps[j]) == "refute":
            deviation = j
            break
    end = len(steps) if deviation is None else deviation + 1
    return {"anchor": anchor, "deviation": deviation,
            "steps": [steps[k] for k in range(anchor, end)]}


def _killed_identities(step: dict, hypotheses: list) -> list[str]:
    """Hypotheses this step's conclusion kills, among ``hypotheses`` —
    the trajectory-alive set when called from tree_view. A hypothesis
    dies when it is referenced (word-bounded id, or salient claim
    terms) inside a clause that carries a refute marker (clause-scoped,
    so 'H2 dies; H1 survives' kills only H2)."""
    killed: list[str] = []
    for clause in _CLAUSE_SPLIT_RE.split(str(step.get("conclusion") or "")):
        if not _REFUTE_RE.search(clause):
            continue
        cterms = _salient_terms(clause)
        for hyp in hypotheses:
            if not isinstance(hyp, dict):
                continue
            ident = _hyp_identity(hyp)
            if not ident or ident in killed:
                continue
            if _id_in_text(ident, clause) or \
                    _salient_terms(_hyp_claim(hyp)) & cterms:
                killed.append(ident)
    return killed


def tree_view(steps) -> list[dict]:
    """The hypothesis-state chain: per step, the alive-hypothesis set
    after that step's contraction. A hypothesis asserted by the step
    joins; one killed by a refute clause leaves — the kill scan runs
    over the WHOLE trajectory-alive set (registered at first
    assertion), so a step may explicitly kill a hypothesis it did not
    itself assert. Fresh lists; the input trajectory is never
    mutated."""
    registry: dict[str, dict] = {}
    order: list[str] = []
    chain: list[dict] = []
    for i, s in enumerate(_as_steps(steps)):
        hyps = [h for h in (s.get("hypotheses") or [])
                if isinstance(h, dict)]
        for hyp in hyps:
            ident = _hyp_identity(hyp)
            if ident and ident not in registry:
                registry[ident] = hyp
                order.append(ident)
        killed = _killed_identities(s, [registry[a] for a in order])
        order = [a for a in order if a not in killed]
        chain.append({"i": i, "alive": list(order)})
    return chain


# --- goal-backward planning ------------------------------------------------------

def backward_plan(success_criterion: str,
                  known_evidence: list[str]) -> list[dict]:
    """Decompose the success criterion into an ordered minimal
    checkpoint chain ({id, criterion, evidence_needed, gap}). Clause
    conjunctions are the split face; duplicate clauses collapse. A
    checkpoint is a gap ONLY when no known-evidence item covers it
    (salient-term overlap) — claims open only at the gaps, so the goal
    selects the analysis slice instead of full coverage. An empty
    criterion is refused (the goal is the selector)."""
    text = str(success_criterion or "").strip()
    if not text:
        raise _fail("success_criterion",
                    "empty — the goal selects the analysis slice; "
                    "refusing to plan without it")
    evidence_terms: set[str] = set()
    for item in (known_evidence or []):
        evidence_terms |= _salient_terms(item)
    chain: list[dict] = []
    seen: set[str] = set()
    for clause in _CRITERION_SPLIT_RE.split(text):
        criterion = clause.strip(" \t-•*")
        if not criterion:
            continue
        key = criterion.casefold()
        if key in seen:
            continue
        seen.add(key)
        chain.append({
            "id": f"ck-{len(chain) + 1}",
            "criterion": criterion,
            "evidence_needed": f"observable evidence that: {criterion}",
            "gap": not bool(_salient_terms(criterion) & evidence_terms),
        })
    return chain


def claim_checkpoints(plan: list[dict]) -> list[dict]:
    """The checkpoints a claim may be opened for — the gap ones only
    (a covered checkpoint never mints a claim). Fresh dicts; the plan
    is never mutated."""
    if not isinstance(plan, (list, tuple)):
        raise _fail("(plan)", "plan must be a backward_plan chain")
    return [dict(ck) for ck in plan
            if isinstance(ck, dict) and ck.get("gap")]


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)

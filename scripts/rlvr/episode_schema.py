# -*- coding: utf-8 -*-
"""rlvr/episode_schema.py — the episode schema `episode/1` (issue 824).

The unified RL model (#806 axis, axioms A1-A5) gives the pool ONE grain:
the episode = one task. This module is the schema half of the P1 model
contract: the machine-readable frontmatter every pool file carries and
the fail-closed validator that refuses anything else.

    an episode file = runs/episodes/episode-<claim>.md
    = YAML frontmatter (schema episode/1) + a SHORT summary body

Machine-readable, not prose: `context_features` / `commits[]` /
`outcome` / `cost` / `utility` / `reusable_fragments` / `milestones[]`
/ `reward` — the fields the pool's write/read/update policies and the
derived indexers consume (A2: one pool contract, no parallel stores).

The summary-compression face lives here as LIMITS: fragments, commit
summaries, and the body are capped (`FRAGMENT_CHAR_MAX` /
`FRAGMENT_MAX` / `BODY_CHAR_MAX`). A write attempt carrying a raw log
(an over-cap blob) raises EpisodeError — the pool never becomes a log
dump (the write-side half of the #824 raw-log RED pin; the gate half
is episode_pool.WriteRefused).

The commit vocabulary is the axis's six commits — select / persist /
tune / switch / verify / deliver (the attribution three-way
persist/tune/switch IS the action space). Zero telemetry points
(Standard 11): a refused validation raises to the caller; nothing
emits.
"""
from __future__ import annotations

from pathlib import Path

import yaml

SCHEMA = "episode/1"

#: the six commits (the loop's action space; #806 axis)
COMMIT_ACTIONS = ("select", "persist", "tune", "switch", "verify", "deliver")

#: outcome status vocabulary
OUTCOME_STATUSES = ("completed", "failed", "blocked")

#: summary caps — the raw-log refusal face (summaries only, never logs)
FRAGMENT_CHAR_MAX = 240
FRAGMENT_MAX = 12
BODY_CHAR_MAX = 2000

#: context features are short tokens (the #812 exogenous vocabulary is
#: the production source; P2 wires the feed)
_FEATURE_TOKEN_MAX = 64
_FEATURE_MAX = 16

# policy constants (the state.py precedent) — summary caps above, no
# fitted parameters anywhere in this module.


class EpisodeError(ValueError):
    """A document is not a legal `episode/1` episode. The message names
    the offending field (fail-closed, machine-readable)."""


def _fail(field: str, why: str) -> "EpisodeError":
    return EpisodeError(f"episode.{field}: {why}")


def _is_real_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _req(doc: dict, field: str):
    if field not in doc:
        raise _fail(field, "missing (schema episode/1 requires it)")
    return doc[field]


def _as_str(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(field, "must be a non-empty string")
    return value


def _validate_identity(doc: dict) -> None:
    _as_str(_req(doc, "id"), "id")
    _as_str(_req(doc, "claim"), "claim")
    _as_str(_req(doc, "created"), "created")
    _as_str(_req(doc, "updated"), "updated")


def _validate_features(doc: dict) -> None:
    features = _req(doc, "context_features")
    if not isinstance(features, list) or len(features) > _FEATURE_MAX:
        raise _fail("context_features",
                    f"must be a list of at most {_FEATURE_MAX} tokens")
    for f in features:
        if not isinstance(f, str) or not f.strip() \
                or len(f) > _FEATURE_TOKEN_MAX:
            raise _fail("context_features",
                        f"each feature must be a non-empty token "
                        f"(<= {_FEATURE_TOKEN_MAX} chars), got {f!r}")


def _validate_commits(doc: dict) -> None:
    commits = _req(doc, "commits")
    if not isinstance(commits, list):
        raise _fail("commits", "must be a list")
    for i, c in enumerate(commits):
        if not isinstance(c, dict):
            raise _fail("commits", f"[{i}] not a mapping")
        seq = c.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
            raise _fail(f"commits[{i}].seq", "must be a positive int")
        action = c.get("action")
        if action not in COMMIT_ACTIONS:
            raise _fail("commits",
                        f"[{i}].action {action!r} not in the six-commit "
                        f"vocabulary {COMMIT_ACTIONS}")
        summary = c.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise _fail(f"commits[{i}].summary", "must be a summary string")
        if len(summary) > FRAGMENT_CHAR_MAX:
            raise _fail(f"commits[{i}].summary",
                        f"raw-log shape: summary over the "
                        f"{FRAGMENT_CHAR_MAX}-char cap (summaries only)")


def _validate_outcome(doc: dict) -> None:
    outcome = _req(doc, "outcome")
    if not isinstance(outcome, dict):
        raise _fail("outcome", "must be a mapping")
    if outcome.get("status") not in OUTCOME_STATUSES:
        raise _fail("outcome",
                    f"status must be one of {OUTCOME_STATUSES}")
    if not isinstance(outcome.get("verified"), bool):
        raise _fail("outcome.verified", "must be a bool")
    ref = outcome.get("evidence_ref")
    if not isinstance(ref, str):
        raise _fail("outcome.evidence_ref",
                    "must be a string ('' = the claim's canonical "
                    "verification surfaces)")


def _validate_cost_utility(doc: dict) -> None:
    cost = _req(doc, "cost")
    if not isinstance(cost, dict) or \
            not isinstance(cost.get("tokens"), (int, float)) or \
            not isinstance(cost.get("seconds"), (int, float)) or \
            cost["tokens"] < 0 or cost["seconds"] < 0:
        raise _fail("cost", "must be {tokens, seconds} non-negative numbers")
    utility = _req(doc, "utility")
    if not isinstance(utility, dict) or \
            not isinstance(utility.get("retrievals"), int) or \
            not isinstance(utility.get("citations"), int) or \
            not isinstance(utility.get("utility"), (int, float)):
        raise _fail("utility",
                    "must be {retrievals, citations, utility} counters")


def _validate_fragments(doc: dict) -> None:
    fragments = _req(doc, "reusable_fragments")
    if not isinstance(fragments, list) or len(fragments) > FRAGMENT_MAX:
        raise _fail("reusable_fragments",
                    f"must be a list of at most {FRAGMENT_MAX} fragments")
    for i, f in enumerate(fragments):
        if not isinstance(f, str) or not f.strip():
            raise _fail(f"reusable_fragments[{i}]", "must be a summary")
        if len(f) > FRAGMENT_CHAR_MAX:
            raise _fail(f"reusable_fragments[{i}]",
                        f"raw-log shape: fragment over the "
                        f"{FRAGMENT_CHAR_MAX}-char cap (summaries only)")


def _validate_milestones(doc: dict) -> None:
    milestones = _req(doc, "milestones")
    if not isinstance(milestones, list):
        raise _fail("milestones", "must be a list")
    for i, m in enumerate(milestones):
        if not isinstance(m, dict):
            raise _fail("milestones", f"[{i}] not a mapping")
        _as_str(m.get("id"), f"milestones[{i}].id")
        _as_str(m.get("desc"), f"milestones[{i}].desc")
        if not isinstance(m.get("verified"), bool):
            raise _fail(f"milestones[{i}].verified", "must be a bool")
        mref = m.get("evidence_ref")
        if not isinstance(mref, str):
            raise _fail(f"milestones[{i}].evidence_ref",
                        "must be a string ('' = canonical surfaces)")


def validate_episode(doc, *, body: str = "") -> dict:
    """Validate one episode document against `episode/1`. Returns the
    document on success; raises EpisodeError naming the offending field
    otherwise. Pure — no IO, no mutation (returns the input reference)."""
    if not isinstance(doc, dict):
        raise _fail("(root)", "not a mapping")
    if doc.get("schema") != SCHEMA:
        raise _fail("schema", f"must be {SCHEMA!r}")
    _validate_identity(doc)
    _validate_features(doc)
    _validate_commits(doc)
    _validate_outcome(doc)
    _validate_cost_utility(doc)
    _validate_fragments(doc)
    _validate_milestones(doc)

    # P2 settlement card: the stamped mission reward rides as a bare
    # float (reward_block carries the A1 decomposition) — a real number
    # is a legal reward shape alongside the {r, ...} mapping; bools stay
    # refused.
    reward = doc.get("reward", {})
    if not isinstance(reward, dict) and not _is_real_number(reward):
        raise _fail("reward",
                    "must be a mapping or a real number when present")
    if not isinstance(doc.get("surprise", False), bool):
        raise _fail("surprise", "must be a bool when present")
    if not isinstance(doc.get("attribution", ""), str):
        raise _fail("attribution", "must be a string when present")

    if len(body) > BODY_CHAR_MAX:
        raise _fail("body",
                    f"raw-log shape: body over the {BODY_CHAR_MAX}-char "
                    f"cap (summaries only)")
    return doc


def render_episode(doc: dict, *, body: str = "") -> bytes:
    """Canonical bytes for one episode file (frontmatter + body).
    Deterministic: same document -> same bytes.

    The closing frame rides as a YAML COMMENT (`# ---`), not a bare
    `---` marker (the P2 settlement card): a second document marker
    makes the FILE a two-document YAML stream, which `yaml.safe_load`
    refuses — and the mission-episode consumption face reads the file
    whole (the P2 RED pin). The comment keeps the stream
    single-document while read_episode_file's split still finds its
    second `---` substring; legacy files (bare `---` closer) keep
    parsing on the read face."""
    validate_episode(doc, body=body)
    front = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True,
                           default_flow_style=False)
    return (f"---\n{front}# ---\n{body}").encode("utf-8")


def write_episode_file(path: Path, doc: dict, *, body: str = "") -> None:
    """Write one episode file atomically enough for a contract face:
    validate FIRST, then write (a bad episode never touches disk)."""
    data = render_episode(doc, body=body)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def read_episode_file(path: Path) -> tuple[dict, str]:
    """Parse one episode file -> (frontmatter doc, body). Raises
    EpisodeError when the frontmatter is not a legal episode (a bad
    episode is RED at read time too — the validator is the one gate)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        raise _fail("(file)", "no frontmatter block")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise _fail("(file)", "malformed frontmatter block")
    try:
        doc = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise _fail("(frontmatter)", f"unparseable YAML: {exc}") from exc
    validate_episode(doc if isinstance(doc, dict) else {}, body=parts[2])
    return doc, parts[2]

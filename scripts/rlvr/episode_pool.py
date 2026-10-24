# -*- coding: utf-8 -*-
"""rlvr/episode_pool.py — the memory pool's physical layer + the three
policy gates (issue 824, P1 of the #806 axis rewrite).

THE POOL — one loop / one learner / one pool (A2). The physical layer
rides the EXISTING workspace runs/ zone, the what-happened layer that
already hosts dispatch-ledger.jsonl / case-bank.jsonl /
experience.jsonl: one markdown+frontmatter file per episode at

    runs/episodes/episode-<claim>.md

Zero new storage engines — the directory convention is the pool; the
derived views (pool_indexer) compute over these files and write
nothing. The directory is created lazily by the write gate (eager init
scaffolding is #791 init-v2 territory — the carrier-table row lands
there, not here).

THE THREE POLICIES AS HOOK GATES (policy, not agent discipline):

  WRITE — two walls, both fail-closed:
    (1) the TRUST gate (A4: the reward channel's integrity at the
        memory boundary): the episode outcome's evidence reference
        resolves through the UNMODIFIED `verifier_integrity.
        resolve_verification` to a PASSED record — absence, escape,
        unparseable, or a failing record refuses;
    (2) the ADMISSION policy: terminal-with-nonzero-reward (a verified
        completion IS the +1 terminal reward; an explicitly stamped
        non-zero `reward.r` admits too), OR a failure with a non-empty
        clean `attribution`, OR a `surprise` event. Summaries only: an
        over-cap fragment/body is the raw-log shape and is refused
        (the gate half of the raw-log RED pin; the schema half is
        episode_schema's caps).
  READ — retrieval at exactly three legal phases (episode_start /
      commit_boundary / blocked); feature-intersection match,
      utility-ranked, deterministic (claim-id tie-break); every
      returned episode has its retrieval counter bumped and its
      `last_retrieved` window opened (the update policy's decay key).
  UPDATE — every settlement updates stats: cited episodes gain
      citation mass + max-revalue (capped at UTILITY_MAX);
      retrieved-but-uncited episodes decay (UTILITY_DECAY); the window
      closes after settlement. Capacity evicts by lowest utility,
      never by age (utility, not time, decides).

Zero telemetry points (Standard 11): refusals raise to the caller with
the reason; nothing emits. Settlement/verifier semantics are only ever
CALLED (resolve_verification), never modified.
"""
from __future__ import annotations

from pathlib import Path

from rlvr import episode_schema as es
from rlvr.episode_schema import read_episode_file, write_episode_file

EPISODES_REL = Path("runs") / "episodes"

#: legal retrieval phases (#824: episode start + commit boundaries;
#: mid-execution only when blocked)
READ_PHASES = ("episode_start", "commit_boundary", "blocked")

#: update-policy constants (documented policy constants — state.py
#: precedent; nothing fitted)
UTILITY_MAX = 1.0
UTILITY_DECAY = 0.5
REVALUE_STEP = 0.1


class WriteRefused(Exception):
    """The write gate refused an episode (trust or admission or schema).
    The message carries the machine-readable reason."""


class ReadRefused(Exception):
    """The read face was called outside the three legal phases."""


# ------------------------------------------------------------- IO helpers

def episode_path(ws, claim: str) -> Path:
    return Path(ws) / EPISODES_REL / f"episode-{claim}.md"


def list_episodes(ws) -> list[Path]:
    """All episode files, sorted (deterministic). Missing pool -> []."""
    d = Path(ws) / EPISODES_REL
    if not d.is_dir():
        return []
    return sorted(d.glob("episode-*.md"))


def load_all(ws) -> list[tuple[Path, dict]]:
    """Every episode document (fail-closed: a bad episode raises — the
    pool never contains one, so a raise is a contract breach signal)."""
    return [(p, read_episode_file(p)[0]) for p in list_episodes(ws)]


# ------------------------------------------------------------- WRITE gate

def _trust_resolves(ws, claim: str, ref: str) -> bool:
    """The trust spine, CALLED not modified (#809 face): the evidence
    reference resolves to a PASSED record. Fail-closed."""
    try:
        from verifier_integrity import resolve_verification  # noqa: PLC0415
        passed, _word, _detail = resolve_verification(
            Path(ws), claim, ref or "")
        return passed
    except Exception:  # noqa: BLE001 — resolver fault refuses (fail-closed)
        return False


def _admission(doc: dict) -> str | None:
    """The admission policy: None admits, a string is the refusal
    reason. Terminal-nonzero-reward OR clean-attribution failure OR
    surprise."""
    status = doc["outcome"]["status"]
    reward = doc.get("reward") or {}
    r = reward.get("r")
    if status == "completed":
        return None  # a verified completion IS the +1 terminal reward
    if isinstance(r, (int, float)) and r != 0:
        return None  # an explicitly stamped non-zero terminal reward
    if doc.get("surprise"):
        return None
    if status == "failed" and str(doc.get("attribution") or "").strip():
        return None
    return ("admission: episode is neither terminal-with-nonzero-reward, "
            "nor a clean-attribution failure, nor a surprise event "
            f"(status={status!r})")


def write_episode(ws, doc: dict, *, body: str = "") -> Path:
    """The WRITE gate: schema -> trust -> admission, then land the file.
    Nothing is written on any refusal."""
    ws = Path(ws)
    try:
        es.validate_episode(doc, body=body)
    except es.EpisodeError as exc:
        raise WriteRefused(f"schema: {exc}") from exc

    claim = doc["claim"]
    outcome = doc["outcome"]
    if outcome["status"] != "completed" and not outcome.get("verified"):
        raise WriteRefused(
            "trust: outcome.verified is false — only verified outcomes "
            "enter the pool (A4)")
    if not _trust_resolves(ws, claim, outcome.get("evidence_ref") or ""):
        raise WriteRefused(
            f"trust: the outcome evidence reference for {claim} does not "
            "resolve to a PASSED record (verifier_integrity, fail-closed)")

    why = _admission(doc)
    if why:
        raise WriteRefused(why)

    path = episode_path(ws, claim)
    write_episode_file(path, doc, body=body)
    return path


# -------------------------------------------------------------- READ face

def _feature_match(doc: dict, features: list[str]) -> bool:
    want = {str(f) for f in features}
    have = {str(f) for f in doc.get("context_features") or []}
    return bool(want & have)


def retrieve(ws, features: list[str], *, phase: str) -> list[dict]:
    """The READ face: feature-intersection match, utility-ranked
    (descending, claim-id tie-break), deterministic. Each returned
    episode's retrieval counter is bumped and its decay window opens.
    Refuses any phase outside the three legal ones."""
    if phase not in READ_PHASES:
        raise ReadRefused(
            f"phase {phase!r} not in {READ_PHASES} — retrieval happens at "
            "episode start, commit boundaries, and when blocked only")
    matched: list[tuple[tuple, dict, Path]] = []
    for path, doc in load_all(ws):
        if not _feature_match(doc, features):
            continue
        key = (-float(doc.get("utility", {}).get("utility") or 0.0),
               str(doc.get("claim")))
        matched.append((key, doc, path))
    matched.sort(key=lambda t: t[0])
    out: list[dict] = []
    for _key, doc, path in matched:
        util = doc.setdefault("utility", {})
        util["retrievals"] = int(util.get("retrievals") or 0) + 1
        doc["last_retrieved"] = _utc_now_z()
        write_episode_file(path, doc)
        out.append(doc)
    return out


def _utc_now_z() -> str:
    try:
        from harness_common import utc_now_z  # noqa: PLC0415 — lazy
        return utc_now_z()
    except Exception:  # noqa: BLE001 — the stamped window needs a clock
        import datetime
        return datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------- UPDATE policy

def update_on_settlement(ws, claim: str, *, cited: tuple[str, ...] = ()) \
        -> dict:
    """The UPDATE policy at settlement: cited episodes gain citation
    mass + max-revalue; retrieved-but-uncited episodes decay; every
    touched window closes. Returns the per-claim outcome map."""
    cited_set = {str(c) for c in cited}
    out: dict[str, dict] = {}
    for path, doc in load_all(ws):
        c = str(doc.get("claim"))
        util = doc.setdefault("utility", {})
        retrieved = bool(doc.get("last_retrieved"))
        if c in cited_set:
            util["citations"] = int(util.get("citations") or 0) + 1
            util["utility"] = min(UTILITY_MAX,
                                  float(util.get("utility") or 0.0)
                                  + REVALUE_STEP)
        elif retrieved:
            util["utility"] = max(0.0,
                                  float(util.get("utility") or 0.0)
                                  * UTILITY_DECAY)
        else:
            continue
        doc.pop("last_retrieved", None)  # the window closes at settlement
        write_episode_file(path, doc)
        out[c] = dict(util)
    _ = claim  # the settlement's own stats ride `cited` (contract face)
    return out


def prune(ws, *, capacity: int) -> list[str]:
    """Capacity by utility, not time: the lowest-utility episodes are
    evicted (deterministic: utility ascending, claim id as tie-break).
    Returns the evicted claims."""
    rows = load_all(ws)
    if len(rows) <= capacity:
        return []
    rows.sort(key=lambda t: (float(t[1].get("utility", {}).get("utility")
                                  or 0.0),
                             str(t[1].get("claim"))))
    evicted = [str(doc["claim"]) for _p, doc in rows[:len(rows) - capacity]]
    for path, doc in rows[:len(rows) - capacity]:
        path.unlink()
        _ = doc
    return evicted

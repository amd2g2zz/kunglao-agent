# -*- coding: utf-8 -*-
"""rlvr/episode_settle.py — the mission-terminal settlement line
(P2 of the learning-loop live-wire program).

The unified model's organs existed but nothing chained them at a
workspace's TERMINAL: the A1 reward signal (reward_signal), the pool's
three gates (episode_pool), and the derived views (pool_indexer). This
module is that chain:

    mission terminal -> settle pending rollouts (reward.settle_workspace,
    THE engine face, called not modified) -> build ONE episode document
    from the workspace's own state (the rollout ledger's committed rows,
    the claim register's outcomes, the cost events) -> stamp the A1
    reward (reward_signal.episode_reward — the float plus the full
    reward_block) -> land it through the pool's WRITE gate -> the
    derived views see it.

Contract:
  - OPEN claims refuse loudly (MissionNotTerminal) — a mission that has
    not reached terminal state writes no episode;
  - ONE mission = ONE episode, anchored at the register's first claim
    id (register order, deterministic);
  - idempotent: a second settle over the same terminal workspace writes
    zero episodes (the mission episode file is the settle mark);
  - cost-honest: spend_usd sums the workspace's cost-event faces
    (cost_events.jsonl — the cost-gate face — and runs/cost_events.jsonl,
    each writer owning its file, so no double count);
  - trust: this face NEVER mints a verdict. A claim whose canonical
    verification surface is ABSENT gets a MIRROR stamped from the claim
    register's own terminal status (PROVEN -> verified) — the register's
    stamp projected onto the trust spine's canonical surface so
    verifier_integrity resolves it UNMODIFIED. A real record owns its
    surface and is never overwritten; a failed mission rides the pool's
    verified-failure admission (episode_pool's failed face) and needs no
    mirror.

Return: {"episodes_written": int, "settled": int, "by_band": {...}} —
settled/by_band are the settlement engine's own counters over the
pending rollouts.

Zero telemetry points (Standard 11): refusals raise to the caller.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from rlvr import episode_pool
from rlvr import episode_schema
from rlvr import pool_indexer

#: the claim register's terminal status vocabulary, mapped to the trust
#: spine's verdict words (PASS_VERDICTS / FAIL_VERDICTS members)
_TERMINAL_PASS = frozenset({"proven", "verified"})
_TERMINAL_FAIL = frozenset({"negative", "refuted"})
#: a mission is terminal when no claim is OPEN (or status-less)
_OPEN_STATUSES = frozenset({"open", ""})

#: the workspace's cost-event faces (cost_gate writes the root file,
#: the loop runner writes runs/ — each owns its file)
_COST_FACES = ("cost_events.jsonl", "runs/cost_events.jsonl")

#: committed rollout-row kind -> the six-commit action (episode/1's
#: vocabulary); unmapped kinds ride the neutral persist
_COMMIT_ACTION_BY_KIND = {"task": "deliver", "mainline_decision": "switch"}


class MissionNotTerminal(Exception):
    """The claim register still holds OPEN claims — a mission that has
    not reached terminal state writes no episode."""


def settle_mission(ws) -> dict:
    """THE mission-terminal settlement line. See the module docstring
    for the chain and the contract. Idempotent; loud on non-terminal."""
    ws = Path(ws)
    claims = _read_register(ws)
    _require_terminal(claims)
    settled = _settle_pending_rollouts(ws)
    anchor = _anchor(claims)
    if episode_pool.episode_path(ws, anchor).is_file():
        return {"episodes_written": 0, "settled": settled["settled"],
                "by_band": settled["by_band"]}
    _stamp_trust_mirrors(ws, claims)
    doc = _build_episode(ws, anchor, claims)
    from rlvr import reward_signal  # noqa: PLC0415 — lazy (late facade line)
    block = reward_signal.episode_reward(ws, doc)
    doc["reward"] = float(block["r"])
    doc["reward_block"] = block
    # body stays empty: the mission summary rides the frontmatter, so
    # the file is one clean YAML document for the whole-file read face
    episode_pool.write_episode(ws, doc, body="")
    derived_views(ws)  # the chain's last link: the views see the episode
    return {"episodes_written": 1, "settled": settled["settled"],
            "by_band": settled["by_band"]}


def derived_views(ws) -> dict:
    """The derived views over the settled pool (the chain's last link):
    the pool indexer's value table and playbook view, computed over the
    episode files at call time — the views own no storage (A3), so the
    refresh is a read, never a write. Raises loudly if the pool holds
    an unreadable episode (the indexer's fail-closed read face)."""
    return {"value_table": pool_indexer.value_table(ws),
            "playbook": pool_indexer.playbook_view(ws)}


# ------------------------------------------------------------ register IO

def _read_register(ws: Path) -> list[dict]:
    p = ws / "claim-register.yaml"
    if not p.is_file():
        raise MissionNotTerminal(
            "claim-register.yaml: no claim register — the mission's "
            "terminal state is undecidable, nothing settles")
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    claims = doc.get("claims") if isinstance(doc, dict) else None
    if not isinstance(claims, list):
        raise ValueError(
            "claim-register.yaml: 'claims' is not a list — malformed "
            "register")
    return [c for c in claims if isinstance(c, dict)]


def _require_terminal(claims: list[dict]) -> None:
    open_ids = [str(c.get("id") or f"claim[{i}]")
                for i, c in enumerate(claims)
                if str(c.get("status") or "").strip().casefold()
                in _OPEN_STATUSES]
    if open_ids:
        raise MissionNotTerminal(
            f"claim register holds OPEN claims {open_ids} — a mission "
            "that has not reached terminal state writes no episode")


def _anchor(claims: list[dict]) -> str:
    """The mission episode's claim anchor: the first FAILING claim when
    the mission failed (the failed-face trust binds to the failing
    claim's own verification record), else the register's first claim
    (register order, deterministic)."""
    for c in claims:
        cid = str(c.get("id") or "").strip()
        status = str(c.get("status") or "").strip().casefold()
        if cid and status not in _TERMINAL_PASS:
            return cid
    for c in claims:
        cid = str(c.get("id") or "").strip()
        if cid:
            return cid
    raise ValueError(
        "claim register: no claim carries an id — no anchor for the "
        "mission episode")


# ------------------------------------------------------------------ trust

def _has_real_record(ws: Path, cid: str) -> bool:
    """True when ANY canonical surface carries a parseable verdict for
    the claim — a real record owns the claim, and a mirror at position
    0 would shadow it (the canonical order is decisive). Absent- (or
    verdict-less-) everywhere is the only mirror precondition."""
    from verifier_integrity import (  # noqa: PLC0415 — lazy
        _record_verdict_word, canonical_records)
    for rel in canonical_records(cid):
        p = ws / rel
        if not p.is_file():
            continue
        found, _word = _record_verdict_word(p, cid)
        if found:
            return True
    return False


def _stamp_trust_mirrors(ws: Path, claims: list[dict]) -> list[str]:
    """Project the register's own terminal stamp onto the trust spine's
    canonical surface, ONLY where no real record exists at ANY
    canonical position (a real record's verdict — pass or fail — owns
    the claim; a position-0 mirror would shadow it). Returns the claims
    mirrored."""
    stamped: list[str] = []
    for c in claims:
        cid = str(c.get("id") or "").strip()
        status = str(c.get("status") or "").strip().casefold()
        if not cid or _has_real_record(ws, cid):
            continue
        word = "verified" if status in _TERMINAL_PASS else (
            "refuted" if status in _TERMINAL_FAIL else None)
        if word is None:
            continue
        path = ws / "runs" / f"verification-{cid}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# mission-terminal trust mirror (rlvr.episode_settle).\n"
            f"# Source: claim-register.yaml status {status} — the "
            "register's own terminal stamp projected onto the trust "
            "spine's canonical surface.\n"
            "# A real verification record owns this surface and is "
            "never overwritten.\n"
            f"verdict: {word}\n"
            f"claim: {cid}\n", encoding="utf-8")
        stamped.append(cid)
    return stamped


# ------------------------------------------------------------ episode body

def _settle_pending_rollouts(ws: Path) -> dict:
    from rlvr import reward as reward_settlement  # noqa: PLC0415 — lazy
    out = reward_settlement.settle_workspace(ws)
    return {"settled": int(out.get("settled") or 0),
            "by_band": dict(out.get("by_band") or {})}


def _committed_rows(ws: Path) -> list[dict]:
    """The trajectory's committed rows, read RAW (the episode document
    folds history; the schema-complete settlement currency face stays
    ledger.read's)."""
    from rlvr import ledger  # noqa: PLC0415 — lazy
    from kunglao_log import iter_jsonl  # noqa: PLC0415 — lazy
    p = ws / ledger.LEDGER_REL
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8", errors="replace")
    return [r for r in iter_jsonl(text.splitlines()) if isinstance(r, dict)]


def _spend_usd(ws: Path) -> float:
    from kunglao_log import iter_jsonl  # noqa: PLC0415 — lazy
    total = 0.0
    for rel in _COST_FACES:
        p = ws / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for row in iter_jsonl(text.splitlines()):
            if isinstance(row, dict) and \
                    isinstance(row.get("amount"), (int, float)) and \
                    not isinstance(row.get("amount"), bool):
                total += float(row["amount"])
    return total


def _commit_summary(row: dict) -> str:
    rid = str(row.get("rollout_id") or row.get("kind") or "row")
    n = len(row.get("signals") or [])
    return f"{rid}: committed rollout row ({n} signals)"[:episode_schema.FRAGMENT_CHAR_MAX]


def _build_episode(ws: Path, anchor: str, claims: list[dict]) -> dict:
    """ONE episode document from the workspace's own state. Completed
    iff every claim reached a passed terminal status; otherwise failed
    with the clean attribution naming the claims that did not. The
    mission summary rides the frontmatter (extra keys are legal) so the
    file's body stays empty — the whole-file YAML read face sees one
    clean document."""
    from harness_common import utc_now_z  # noqa: PLC0415 — lazy
    statuses = [str(c.get("status") or "").strip().casefold()
                for c in claims]
    passed = all(s in _TERMINAL_PASS for s in statuses)
    failed_ids = [str(c.get("id") or f"claim[{i}]")
                  for i, (c, s) in enumerate(zip(claims, statuses))
                  if s not in _TERMINAL_PASS]
    rows = _committed_rows(ws)
    spend = _spend_usd(ws)
    now = utc_now_z()
    features = sorted({f"register:{s}" for s in statuses if s})
    fragments = []
    for c in claims:
        frag = f"{str(c.get('id') or '')}: {str(c.get('title') or '')}"
        frag = frag.strip(": ").strip()
        if frag:
            fragments.append(frag[:episode_schema.FRAGMENT_CHAR_MAX])
    doc = {
        "schema": episode_schema.SCHEMA,
        "id": f"mission-{anchor}",
        "claim": anchor,
        "created": now,
        "updated": now,
        "context_features": features,
        "commits": [
            {"seq": i + 1,
             "action": _COMMIT_ACTION_BY_KIND.get(
                 str(r.get("kind") or ""), "persist"),
             "summary": _commit_summary(r)}
            for i, r in enumerate(rows)
        ],
        "outcome": {"status": "completed" if passed else "failed",
                    "verified": True,
                    "evidence_ref": ""},
        "cost": {"tokens": 0, "seconds": 0, "spend_usd": spend},
        "utility": {"retrievals": 0, "citations": 0, "utility": 0.0},
        "reusable_fragments": fragments[:episode_schema.FRAGMENT_MAX],
        "milestones": [],
        "summary": (
            f"mission-terminal settle: "
            f"{sum(1 for s in statuses if s in _TERMINAL_PASS)}"
            f"/{len(claims)} claims passed-terminal; "
            f"{len(rows)} committed rollout rows folded; "
            f"spend ${spend:.2f}"),
    }
    if not passed:
        doc["attribution"] = (
            "mission failed: claims "
            + ", ".join(failed_ids)
            + " did not reach a passed terminal status")
    return doc

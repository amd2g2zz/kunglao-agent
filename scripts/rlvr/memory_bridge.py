# -*- coding: utf-8 -*-
"""rlvr/memory_bridge.py — the native-memory bridge + recall sensors
(P4 of the learning-loop live-wire program).

The pool rides the native memory surface — zero new storage engines.
This module is the write-through and the sensor strip between the
mission settlement and that surface:

WRITE-THROUGH — ``stamp_family_memory(ws, episode)``: the settled
episode's differential lands on two native faces of one store
(the pool-rides-native-memory pattern):
  - HOT: one index row per memory key in ``runs/memory/index.jsonl``
    (compact summary + usage stats — the fast read face);
  - COLD: one detail file per key under ``runs/memory/<family>/<key>.md``
    (fragment + provenance — sinks here, never lost).
Differential means already-known content writes nothing: an identical
fragment maps to the same key and is skipped (已会零写). A completed
mission with a positive reward marks its family ``mastered`` — the
scheduler's retire face then sees it through ``family_view``.

RECALL SENSORS (the owner's model, all deterministic):
  - ``ignored``  — a recalled key never cited later: retrievals −
    citations (``find_ignored``); ``close_recall_window`` applies it at
    settlement and closes the window;
  - ``cited-and-harmed`` — the citing step's negative reward IS the
    recall's negative mark (``cited_harmed`` event, ``find_harmed``);
  - ``refuted-propagate`` — a refuted assertion NARROWS the reusable_when
    of the row that supplied it: ``refute_narrow`` appends an
    "except when:" clause; originals are never deleted; repeated
    refutation (>= REFUTE_RETIRE_LIMIT) softly retires the row (it stays
    on disk, the gate just stops admitting it).

GATE + BANDIT — ``recall_gate(row)`` raises the admission bar for keys
with consecutive-ignored / harmed history (a pollution sensor: the gate
gets MORE conservative, pinned rising threshold). The score it reads is
a simple exponential-credit bandit over usage feedback
(``bandit_update``, documented constant ALPHA, no trained weights):
cited-and-helped (+1), cited-and-harmed (−1), ignored (small −).
``rank_rows`` surfaces only gate-admitted rows — a key that keeps
getting ignored decays out of the context (the attention-tax hard exit).

Zero telemetry points (Standard 11): refusals raise to the caller.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from kunglao_log import iter_jsonl

MEMORY_DIR = Path("runs") / "memory"
INDEX_REL = MEMORY_DIR / "index.jsonl"
FAMILIES_REL = MEMORY_DIR / "families.jsonl"
ROW_SCHEMA = "memory-key/1"

#: exponential-credit bandit: score = (1-ALPHA)*score + ALPHA*event
BANDIT_ALPHA = 0.4
#: the small negative an uncited retrieval earns (attention tax, real)
IGNORED_PENALTY = -0.15
#: the pollution gate: threshold = BASE + IGNORED_STEP*consec_ignored
#: + HARMED_STEP*harmed, capped at GATE_MAX. Harmed history raises the
#: bar faster than mere ignored retrievals.
GATE_BASE = 0.0
GATE_IGNORED_STEP = 0.15
GATE_HARMED_STEP = 0.35
GATE_MAX = 0.95
#: repeated refutations that softly retire a memory row (narrowing
#: happens on EVERY refutation; the row is never deleted from disk)
REFUTE_RETIRE_LIMIT = 3

_EVENTS = ("retrieved", "cited_helped", "cited_harmed", "settle_uncited")


# ------------------------------------------------------------------ faces

def _now() -> str:
    from harness_common import utc_now_z  # noqa: PLC0415 — lazy
    return utc_now_z()


def _index_path(ws) -> Path:
    return Path(ws) / INDEX_REL


def load_rows(ws) -> list[dict]:
    """All memory rows from the hot index face (missing file -> [])."""
    p = _index_path(ws)
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8", errors="replace")
    return [r for r in iter_jsonl(text.splitlines()) if isinstance(r, dict)]


def _save_rows(ws, rows: list[dict]) -> None:
    p = _index_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")


def _family_of(episode: dict) -> str:
    """The episode's family token: the ``family:`` context feature the
    settle line stamps. A stamp without a family refuses loudly — a
    memory row nobody can schedule for is noise."""
    for f in episode.get("context_features") or []:
        if isinstance(f, str) and f.startswith("family:"):
            return f
    return ""


def _reward_value(episode: dict) -> float | None:
    reward = episode.get("reward") or {}
    r = reward.get("r") if isinstance(reward, dict) else reward
    if isinstance(r, (int, float)) and not isinstance(r, bool):
        return float(r)
    return None


def _is_mastered(episode: dict) -> bool:
    """A verified completion with a positive terminal reward means the
    family's method worked end-to-end — that is ``mastered``."""
    if (episode.get("outcome") or {}).get("status") != "completed":
        return False
    r = _reward_value(episode)
    return r is not None and r > 0.0


def _key_for(family: str, fragment: str) -> str:
    digest = hashlib.sha256(fragment.encode("utf-8")).hexdigest()[:12]
    return f"{family}:{digest}"


def _detail_path(ws, row: dict) -> Path:
    return Path(ws) / MEMORY_DIR / row["family"] / f"{row['key']}.md"


def _render_detail(row: dict) -> str:
    lines = [
        f"# memory row {row['key']}", "",
        f"- family: {row['family']}",
        f"- source: {row.get('source_claim') or ''}",
        f"- updated: {row.get('updated')}",
        "", "## fragment", row.get("summary") or "", "",
        "## reusable_when",
        *(f"- {c}" for c in row.get("reusable_when") or []),
    ]
    if row.get("exceptions"):
        lines += ["", "## exceptions (refutation-narrowed)",
                  *(f"- {e}" for e in row["exceptions"])]
    return "\n".join(lines) + "\n"


def _write_detail(ws, row: dict) -> Path:
    p = _detail_path(ws, row)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_render_detail(row), encoding="utf-8")
    return p


# --------------------------------------------------------- write-through

def stamp_family_memory(ws, episode: dict) -> dict:
    """The settlement differential write-through. One hot index row per
    reusable fragment (or the clean attribution when a failed mission
    has no fragments), one cold detail file each. Already-known content
    (same fragment -> same key) is skipped, not duplicated. A completed
    positive-reward episode marks the family mastered. Returns
    {family, written, skipped, mastered}."""
    ws = Path(ws)
    family = _family_of(episode)
    if not family:
        raise ValueError(
            "stamp_family_memory: episode carries no `family:` context "
            "feature — a memory row nobody can schedule for is refused")
    rows = load_rows(ws)
    known = {r["key"] for r in rows}
    reusable = [str(f) for f in episode.get("reusable_fragments") or []
                if str(f).strip()]
    attribution = str(episode.get("attribution") or "").strip()
    if attribution and (episode.get("outcome") or {}).get("status") \
            == "failed" and attribution not in reusable:
        # a failed mission's lesson IS its clean attribution — it rides
        # first, ahead of the (title-shaped) fragments
        reusable = [attribution] + reusable
    if not reusable:
        reusable = [attribution] if attribution else []
    conditions = [str(f) for f in episode.get("context_features") or []]
    written: list[str] = []
    skipped = 0
    for fragment in reusable:
        key = _key_for(family, fragment)
        if key in known:
            skipped += 1
            continue
        row = {"schema": ROW_SCHEMA, "key": key, "family": family,
               "summary": fragment, "reusable_when": conditions,
               "exceptions": [], "score": 0.0, "retrievals": 0,
               "citations": 0, "consec_ignored": 0, "harmed": 0,
               "refutations": 0, "retired": False,
               "source_claim": str(episode.get("claim") or ""),
               "created": _now(), "updated": _now()}
        rows.append(row)
        known.add(key)
        written.append(key)
        _write_detail(ws, row)
    _save_rows(ws, rows)
    mastered = _is_mastered(episode)
    _mark_family(ws, family, mastered)
    return {"family": family, "written": written, "skipped": skipped,
            "mastered": mastered}


def _mark_family(ws: Path, family: str, mastered: bool) -> None:
    p = Path(ws) / FAMILIES_REL
    fams: dict[str, dict] = {}
    if p.is_file():
        for r in iter_jsonl(
                p.read_text(encoding="utf-8", errors="replace")
                .splitlines()):
            if isinstance(r, dict) and r.get("family"):
                fams[str(r["family"])] = r
    prev = fams.get(family) or {}
    fams[family] = {"family": family,
                    "mastered": bool(mastered)
                    or bool(prev.get("mastered")),
                    "updated": _now()}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n"
                for r in fams.values()), encoding="utf-8")


def family_view(ws) -> dict:
    """{family -> {mastered}} — the scheduler's ``pool_state.memory``
    shape, read from the bridge's own family face."""
    p = Path(ws) / FAMILIES_REL
    if not p.is_file():
        return {}
    out: dict[str, dict] = {}
    for r in iter_jsonl(
            p.read_text(encoding="utf-8", errors="replace").splitlines()):
        if isinstance(r, dict) and r.get("family"):
            out[str(r["family"])] = {"mastered": bool(r.get("mastered"))}
    return out


# ---------------------------------------------------------------- sensors

def _get_row(rows: list[dict], key: str) -> dict:
    for r in rows:
        if r.get("key") == key:
            return r
    raise ValueError(f"record_usage: unknown memory key {key!r}")


def bandit_update(row: dict, value: float) -> dict:
    """One exponential-credit step: score <- (1-ALPHA)*score + ALPHA*value,
    clamped to [-1, 1]. Returns a NEW row (input never mutated)."""
    score = (1.0 - BANDIT_ALPHA) * float(row.get("score") or 0.0) \
        + BANDIT_ALPHA * float(value)
    return dict(row, score=max(-1.0, min(1.0, score)),
                updated=_now())


def record_usage(ws, key: str, event: str) -> dict:
    """Feed one usage event into a memory row and persist it. Events:
    retrieved (retrieval counted), cited_helped / cited_harmed (the
    citing step's reward IS the recall's reward), settle_uncited (the
    window closed with no citation — the ignored sensor). Unknown keys
    and unknown events refuse loudly. Returns the updated row."""
    rows = load_rows(ws)
    row = _get_row(rows, key)
    if event not in _EVENTS:
        raise ValueError(
            f"record_usage: unknown event {event!r} (legal: {_EVENTS})")
    if event == "retrieved":
        new = dict(row, retrievals=int(row.get("retrievals") or 0) + 1,
                   updated=_now())
    elif event in ("cited_helped", "cited_harmed"):
        new = bandit_update(dict(row, citations=int(
            row.get("citations") or 0) + 1, consec_ignored=0),
            1.0 if event == "cited_helped" else -1.0)
        if event == "cited_harmed":
            new["harmed"] = int(row.get("harmed") or 0) + 1
    else:  # settle_uncited
        new = bandit_update(
            dict(row, consec_ignored=int(row.get("consec_ignored") or 0) + 1),
            IGNORED_PENALTY)
    _save_rows(ws, [new if r.get("key") == key else r for r in rows])
    return new


def close_recall_window(ws, cited_keys) -> dict:
    """The settlement-side ignored sensor: every row retrieved-but-never-
    cited takes one ``settle_uncited`` mark (its streak grows, its score
    pays the attention tax). The retrieval window then closes for EVERY
    row carrying an open retrievals−citations delta — cited or not — so
    a healthy window's residual can never strike the key one window
    later (a citation breaks the streak across the boundary, not just
    inside one window). Returns the ignored keys."""
    cited = {str(c) for c in cited_keys or []}
    rows = load_rows(ws)
    ignored: list[str] = []
    out_rows: list[dict] = []
    changed = False
    for r in rows:
        ret = int(r.get("retrievals") or 0)
        cit = int(r.get("citations") or 0)
        if ret <= cit:
            out_rows.append(r)
            continue
        changed = True  # an open delta closes this window, cited or not
        if r["key"] in cited:
            out_rows.append(dict(r, retrievals=cit, updated=_now()))
            continue
        ignored.append(r["key"])
        updated = bandit_update(
            dict(r, consec_ignored=int(r.get("consec_ignored") or 0) + 1),
            IGNORED_PENALTY)
        updated["retrievals"] = cit
        out_rows.append(updated)
    if changed:
        _save_rows(ws, out_rows)
    return {"ignored": ignored, "updated": len(ignored)}


def find_ignored(rows: list[dict]) -> list[str]:
    """Keys whose retrievals exceed citations — recalled but never
    cited (the retrievals−citations delta), deterministic order."""
    return [r["key"] for r in rows
            if int(r.get("retrievals") or 0)
            > int(r.get("citations") or 0)]


def find_harmed(rows: list[dict]) -> list[str]:
    """Keys with at least one cited-and-harmed mark."""
    return [r["key"] for r in rows if int(r.get("harmed") or 0) > 0]


def refute_narrow(ws, key: str, exception: str) -> dict:
    """A refuted assertion propagates to the row that supplied it:
    an ``except when:`` clause NARROWS the reusable_when (original
    conditions are never deleted). Each hit counts; at
    REFUTE_RETIRE_LIMIT the row is softly retired (it stays on disk,
    the gate stops admitting it). Unknown key or empty exception -> loud."""
    exception = str(exception or "").strip()
    if not exception:
        raise ValueError("refute_narrow: empty exception clause")
    rows = load_rows(ws)
    row = _get_row(rows, key)
    refutations = int(row.get("refutations") or 0) + 1
    new = dict(row,
               exceptions=list(row.get("exceptions") or [])
               + [f"except when: {exception}"],
               refutations=refutations,
               retired=bool(row.get("retired"))
               or refutations >= REFUTE_RETIRE_LIMIT,
               updated=_now())
    _save_rows(ws, [new if r.get("key") == key else r for r in rows])
    _write_detail(ws, new)
    return new


# ------------------------------------------------------------------ gate

def recall_gate(row: dict) -> dict:
    """The pollution gate: the admission bar RISES with consecutive-
    ignored and harmed history (harmed faster), is capped at GATE_MAX,
    and refuses retired rows outright. A row admits when its bandit
    score clears the bar."""
    threshold = min(
        GATE_MAX,
        GATE_BASE
        + GATE_IGNORED_STEP * int(row.get("consec_ignored") or 0)
        + GATE_HARMED_STEP * int(row.get("harmed") or 0))
    admit = (not bool(row.get("retired"))) \
        and float(row.get("score") or 0.0) >= threshold
    return {"threshold": threshold, "admit": admit}


def rank_rows(rows: list[dict], features) -> list[dict]:
    """The recall ranking face: gate-admitted rows whose reusable_when
    intersects the query features, score descending, key tie-break.
    A pollution-gated key simply stops surfacing."""
    want = {str(f) for f in features or []}
    out = []
    for r in rows:
        if not recall_gate(r)["admit"]:
            continue
        if not want & {str(c) for c in r.get("reusable_when") or []}:
            continue
        out.append(r)
    out.sort(key=lambda r: (-float(r.get("score") or 0.0), r["key"]))
    return out


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)

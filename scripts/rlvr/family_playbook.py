#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/family_playbook.py — the Type-2 transfer store (issue #960).

Cross-rollout transfer has exactly three channels (owner-approved
first-principles convergence): Type-1 re-measurable facts ride the
probe faces (#956), Type-3 numeric direction value rides the #954
posterior, and Type-2 — THIS module — stable strategy knowledge rides
the FAMILY PLAYBOOK. The P8 round-1 evidence: the cold arm learned
stable strategy facts that died with its workspace and the next rollout
started from zero. Type-2 knowledge is SMALL and STABLE (a few to a few
dozen lines per family), so the owner-approved design dissolves the
recall-control problem instead of solving it: the playbook is injected
WHOLE at init — no retrieval layer, no mis-recall, no context pollution,
no valence loops. Nothing here recalls, ranks, or searches.

THE STORE: one markdown file per family at
``experiments/blocked-path-units/playbooks/<family>.md`` — operator-
local, NEVER tracked (mirrors the eval-corpus root convention:
``KUNGLAO_PLAYBOOK_ROOT`` wins at call time, else the repo-relative
default; /experiments/ is gitignored).

THE SCHEMA (kunglao-playbook/1) — markdown, hard line budget
(DEFAULT_LINE_BUDGET = 60), each entry one block::

    # playbook: <family>
    <!-- kunglao-playbook/1; injected whole at init; hard line budget -->

    ### <situation-precondition>
    <strategy line(s)>
    evidence: <artifact-path-ref> [<ref> ...]

``parse`` tolerates stray blank lines, HTML comments and out-of-form
preamble (fail-open read); ``serialize`` emits ONE canonical form, so
the round trip is byte-stable (parse -> serialize -> parse -> serialize
is byte-identical; pinned in tests/test_rl_v3_playbook_960.py).
``evidence`` refs are VERIFIED at patch time (scripts/rlvr/
playbook_distill.py's mechanical gate) against the distilling
workspace — a seed file written by hand is never gate-checked.

The injection face is ``session_block``: a clearly-labeled whole-file
block for the init prompt (provenance stated in the label so the prompt
stays honest), empty when the family has no playbook file. Gating
(KUNGLAO_PLAYBOOK=1) lives at the CONSUMER (eval_loop_runner) — this
module is a pure function of the file system.

The name is deliberately NOT ``playbook`` — that module (issue #826)
is the episode-fragment compression face and is untouched by this card.

stdlib only.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

#: the schema stamp (the comment line of every canonical file)
SCHEMA_COMMENT = ("<!-- kunglao-playbook/1; injected whole at init; "
                  "hard line budget -->")

#: the hard line budget of a canonical playbook file (issue #960) —
#: the eviction discipline (宁缺毋滥) is enforced against THIS number
DEFAULT_LINE_BUDGET = 60

#: operator-root override (eval_dataset.eval_root convention: read at
#: CALL time so tests and runners can redirect without import-order traps)
ENV_PLAYBOOK_ROOT = "KUNGLAO_PLAYBOOK_ROOT"

ROOT = Path(__file__).resolve().parents[2]

#: a family name must be a plain path-safe token — anything else has no
#: playbook (fail-closed: a hostile family string can never escape the
#: playbooks directory)
_FAMILY_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*\Z")

_EVIDENCE_SPLIT_RE = re.compile(r"[,\s]+")


# ---- the immutable schema faces -------------------------------------------
@dataclass(frozen=True)
class PlaybookEntry:
    """One strategy entry: situation-precondition -> strategy line(s)
    -> evidence artifact refs (verified at patch time, not here)."""
    situation: str
    lines: tuple[str, ...]
    evidence: tuple[str, ...] = ()

    def __post_init__(self):
        # normalizer: a bare str for lines/evidence becomes a 1-tuple —
        # serialize() extends these fields, and extending a bare str
        # would explode it char-by-char into the file
        for field in ("lines", "evidence"):
            value = getattr(self, field)
            if isinstance(value, str):
                object.__setattr__(self, field, (value,))


@dataclass(frozen=True)
class PlaybookDoc:
    """A whole parsed playbook file (immutable; update = new instance)."""
    family: str
    title: str
    entries: tuple[PlaybookEntry, ...] = ()


# ---- the operator-root face -----------------------------------------------
def playbook_root() -> Path:
    """THE playbook-root face: KUNGLAO_PLAYBOOK_ROOT wins, else the
    repo-relative operator-local default (never a tracked path)."""
    override = os.environ.get(ENV_PLAYBOOK_ROOT, "")
    return Path(override) if override else (
        ROOT / "experiments" / "blocked-path-units" / "playbooks")


def playbook_path(family: str, root: Path | None = None) -> Path | None:
    """The family's playbook file, or None when the family name is not a
    plain path-safe token (the fail-closed shape — no file, no block)."""
    name = str(family or "").strip()
    if not _FAMILY_RE.match(name) or ".." in name:
        return None
    base = Path(root) if root is not None else playbook_root()
    return base / f"{name}.md"


# ---- parse / serialize (round-trip byte-stable) ----------------------------
def _family_from_title(title: str) -> str:
    return title[len("# playbook:"):].strip() if \
        title.startswith("# playbook:") else ""


def parse(text: str, family: str = "") -> PlaybookDoc:
    """Parse a playbook file body. Tolerant: blank lines, single-line
    HTML comments and pre-entry preamble are dropped; an entry keeps its
    situation heading, its strategy lines (stripped) and its evidence
    refs (comma/whitespace separated, first-occurrence dedup). An entry
    without an evidence line parses with no refs — the VERIFICATION of
    refs is the patch gate's job, never the reader's."""
    title = ""
    blocks: list[tuple[str, list[str], list[str], set[str]]] = []
    cur: tuple[str, list[str], list[str], set[str]] | None = None
    for raw in str(text or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        if title == "" and cur is None and not blocks \
                and line.startswith("# "):
            title = stripped
            continue
        if line.startswith("### "):
            cur = (stripped[4:].strip(), [], [], set())
            blocks.append(cur)
            continue
        if cur is None:
            continue
        if stripped == "evidence:" or stripped.startswith("evidence:"):
            for ref in _EVIDENCE_SPLIT_RE.split(stripped.split(":", 1)[1]):
                if ref and ref not in cur[3]:
                    cur[2].append(ref)
                    cur[3].add(ref)
            continue
        cur[1].append(stripped)
    doc_family = family or _family_from_title(title)
    entries = tuple(PlaybookEntry(situation=s, lines=tuple(ls),
                                  evidence=tuple(ef))
                    for s, ls, ef, _seen in blocks)
    return PlaybookDoc(family=doc_family,
                       title=title or (f"# playbook: {doc_family}"
                                       if doc_family else ""),
                       entries=entries)


def serialize(doc: PlaybookDoc) -> str:
    """The ONE canonical form — the byte-stable round-trip half. Title,
    schema comment, then one blank-line-separated block per entry; an
    entry with no refs simply has no evidence line."""
    title = doc.title or (f"# playbook: {doc.family}"
                          if doc.family else "# playbook")
    out = [title, SCHEMA_COMMENT]
    for entry in doc.entries:
        out.append("")
        out.append(f"### {entry.situation}")
        out.extend(entry.lines)
        if entry.evidence:
            out.append("evidence: " + " ".join(entry.evidence))
    return "\n".join(out) + "\n"


def line_count(doc: PlaybookDoc) -> int:
    """The budgeted quantity: the canonical file's line count."""
    return len(serialize(doc).splitlines())


def entry_line_count(entry: PlaybookEntry) -> int:
    """An entry's contribution: heading + strategy lines + evidence."""
    return 1 + len(entry.lines) + (1 if entry.evidence else 0)


# ---- the store faces -------------------------------------------------------
def load_family(family: str, root: Path | None = None) -> PlaybookDoc | None:
    """The whole playbook for a family, or None when there is no file
    (no family playbook is a NORMAL state — cold arm — never an error).
    Unreadable file also degrades to None (the injection is an
    enhancement; a broken store must never block a session)."""
    path = playbook_path(family, root)
    if path is None or not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return parse(text, family=str(family))


def save(doc: PlaybookDoc, path: Path) -> Path:
    """Write the canonical form (ONE write — the distill pipeline builds
    the complete new file in memory first, so a half-applied patch is
    structurally impossible)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize(doc), encoding="utf-8")
    return path


def fit_budget(doc: PlaybookDoc,
               budget: int = DEFAULT_LINE_BUDGET) -> tuple[PlaybookDoc, int]:
    """Capacity culling (the eviction policy): while the canonical file
    exceeds the budget, retire whole entries LOWEST-EVIDENCE-COUNT
    FIRST; ties break by file position, later entry culled first (the
    head of the file is the long-survived core). Deterministic; returns
    (new_doc, culled_count). The header is two lines, so the loop always
    terminates."""
    entries = list(doc.entries)
    culled = 0
    while entries and line_count(
            PlaybookDoc(family=doc.family, title=doc.title,
                        entries=tuple(entries))) > budget:
        worst = min(range(len(entries)),
                    key=lambda i: (len(entries[i].evidence), -i))
        entries.pop(worst)
        culled += 1
    return (PlaybookDoc(family=doc.family, title=doc.title,
                        entries=tuple(entries)), culled)


# ---- the injection face ----------------------------------------------------
BLOCK_LABEL = (
    "FAMILY PLAYBOOK (injected WHOLE at init from the operator-local "
    "playbook store — distilled strategy knowledge from prior rollouts "
    "of this family; provenance context, not a task instruction):")


def session_block(family: str, root: Path | None = None) -> str:
    """The init-injection block: label + the whole canonical playbook.
    Empty when the family has no playbook file (or an unreadable one) —
    the caller's prompt stays byte-identical to the no-playbook shape.
    NO retrieval, NO selection: the whole file or nothing."""
    doc = load_family(family, root)
    if doc is None or not doc.entries:
        return ""
    body = serialize(doc).rstrip(chr(10))
    # review round 1 MEDIUM: the line budget is enforced at INJECTION too
    # — a hand-seeded (never gate-checked) oversized file must not ride
    # into every init prompt whole
    if len(doc.entries) > 0 and (body.count(chr(10)) + 1) > 120:
        import kunglao_log as _kl
        _kl.warn("playbook_inject", f"{family}: playbook exceeds the "
                 "injection budget — skipped (shrink the playbook)")
        return ""
    return f"{BLOCK_LABEL}\n\n{body}"

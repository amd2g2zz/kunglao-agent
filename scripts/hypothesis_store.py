#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hypothesis_store.py — hypothesis layer carrier (#528).

Hypotheses are first-class claims about WHAT MIGHT BE TRUE before a
verifier has weighed in: claim motivation, active competitor_group
state, and candidate task_specs. They live in <ws>/hypotheses/ — a layer
DISTINCT from notes/, which is the result layer (user correction
2026-08-20: first judge, then revise notes — never the other way around;
a hypothesis is never read back out of notes/).

File format — one markdown file per hypothesis, frontmatter + body:

    ---
    id: H-001
    claim_id: C-001
    competitor_group: prng-vs-cipher
    candidates: [AES, ChaCha20]
    status: open            # open | refuted | superseded
    schema_rev: 1
    ---

    # H-001 …motivation body…

State machine (strict, single-direction):

    open ──refuting_fact_id──> refuted      (terminal: the fact that killed it)
    open ──superseded_by──────> superseded  (terminal: successor hyp id)

`open -> open` is idempotent (cold-start rehydrate re-asserts 'open' and
must not error). Terminal states never reopen: a decided hypothesis is
history, not a live question.

FAIL-OPEN read: list_all() skips unparseable files instead of raising —
digest sec_g and state_anchor both consume this store and must degrade,
never block cold start (a corrupt hypotheses/ file cannot brick the
workspace).

Consumers (#528):
  - scripts/digest_build.py::build_sec_g   (digest open-hypotheses section)
  - hooks/state_anchor.py::build_anchor    (structured hyp pointers)
Provenance: the hypotheses/ carrier is eagerly scaffolded by
kunglao-init (#538 CARRIER_READMES / SCAFFOLD_DIRS).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = "1"

# The state machine vocabulary. Order matters for error messages only.
HYPOTHESIS_STATUSES = ("open", "refuted", "superseded")
_TERMINAL_STATUSES = frozenset(("refuted", "superseded"))

_FRONT_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


class InvalidTransition(ValueError):
    """A hypothesis state change violated the state machine."""


@dataclass
class Hypothesis:
    id: str
    claim_id: str
    competitor_group: str
    candidates: list[str] = field(default_factory=list)
    status: str = "open"  # one of HYPOTHESIS_STATUSES
    refuting_fact_id: str | None = None
    superseded_by: str | None = None
    body: str = ""
    path: Path | None = None

    def to_frontmatter(self) -> str:
        lines = [
            "---",
            f"id: {self.id}",
            f"claim_id: {self.claim_id}",
            f"competitor_group: {self.competitor_group}",
            "candidates: [" + ", ".join(self.candidates) + "]",
            f"status: {self.status}",
            f"schema_rev: {SCHEMA_VERSION}",
        ]
        if self.refuting_fact_id:
            lines.append(f"refuting_fact_id: {self.refuting_fact_id}")
        if self.superseded_by:
            lines.append(f"superseded_by: {self.superseded_by}")
        return "\n".join(lines) + "\n---\n"


class HypothesisStore:
    """Reader/transition-writer over <root>/*.md hypothesis files."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def list_all(self) -> list[Hypothesis]:
        """All parseable hypotheses, id-sorted. Unparseable files are
        skipped (FAIL-OPEN: one bad file must not poison digest/anchor)."""
        if not self.root.is_dir():
            return []
        out: list[Hypothesis] = []
        for p in sorted(self.root.glob("*.md")):
            try:
                out.append(self._parse(p))
            except InvalidTransition:
                continue  # malformed file — degrade, do not block
        return out

    def list_open(self) -> list[Hypothesis]:
        return [h for h in self.list_all() if h.status == "open"]

    def get(self, hyp_id: str) -> Hypothesis:
        p = self.root / f"{hyp_id}.md"
        if not p.exists():
            raise KeyError(hyp_id)
        return self._parse(p)

    def transition(
        self,
        hyp_id: str,
        new_status: str,
        *,
        refuting_fact_id: str | None = None,
        superseded_by: str | None = None,
    ) -> Hypothesis:
        """Apply a state-machine transition and write it back to disk.

        Raises InvalidTransition on any rule violation; the file on disk
        is only touched after every check passed, so a rejected call
        leaves no half-updated state."""
        if new_status not in HYPOTHESIS_STATUSES:
            raise InvalidTransition(
                f"unknown status: {new_status!r} "
                f"(valid: {', '.join(HYPOTHESIS_STATUSES)})")
        h = self.get(hyp_id)
        if new_status == h.status:
            # idempotent: rehydrate re-asserting 'open' must not error
            return h
        if h.status in _TERMINAL_STATUSES:
            raise InvalidTransition(
                f"{hyp_id} is terminal ({h.status}) — terminal states "
                "do not reopen; write a NEW hypothesis instead")
        if new_status == "refuted" and not refuting_fact_id:
            raise InvalidTransition(
                "refuting_fact_id required when refuting a hypothesis — "
                "the 'why was I wrong' trail may not be empty")
        if new_status == "superseded" and not superseded_by:
            raise InvalidTransition(
                "superseded_by required when superseding a hypothesis — "
                "name the successor that replaces this one")
        h.status = new_status
        h.refuting_fact_id = refuting_fact_id
        h.superseded_by = superseded_by
        self._write(h)
        return h

    # ---------- internals ----------

    def _parse(self, path: Path) -> Hypothesis:
        text = path.read_text(encoding="utf-8", errors="replace")
        m = _FRONT_RE.match(text)
        if not m:
            raise InvalidTransition(f"no frontmatter: {path}")
        fm, body = m.group(1), m.group(2)
        fields: dict[str, str] = {}
        for line in fm.splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            fields[k.strip()] = v.strip()
        if "id" not in fields or "claim_id" not in fields:
            raise InvalidTransition(f"missing id/claim_id: {path}")
        cands_raw = fields.get("candidates", "[]")
        cands = [c.strip() for c in cands_raw.strip("[]").split(",") if c.strip()]
        status = fields.get("status", "open")
        if status not in HYPOTHESIS_STATUSES:
            raise InvalidTransition(f"unknown status {status!r}: {path}")
        return Hypothesis(
            id=fields["id"],
            claim_id=fields["claim_id"],
            competitor_group=fields.get("competitor_group", ""),
            candidates=cands,
            status=status,
            refuting_fact_id=fields.get("refuting_fact_id") or None,
            superseded_by=fields.get("superseded_by") or None,
            body=body.strip(),
            path=path,
        )

    def _write(self, h: Hypothesis) -> None:
        if h.path is None:
            h.path = self.root / f"{h.id}.md"
        h.path.parent.mkdir(parents=True, exist_ok=True)
        h.path.write_text(
            h.to_frontmatter() + "\n" + h.body + "\n", encoding="utf-8")

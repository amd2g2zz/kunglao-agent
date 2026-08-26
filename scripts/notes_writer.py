#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notes_writer.py — notes/ result-layer writer with supersedes-chain
enforcement (#528 work item 4).

notes/ is the RESULT layer (user correction 2026-08-20): first judge,
then revise notes. A correction (e.g. N-001 PROVEN 'AES' -> N-002 PROVEN
'ChaCha20') is always a NEW note declaring `supersedes: <prior-id>`; the
prior note is never deleted or modified — its conclusion stays queryable
and the chain is the audit trail. This catches the 'silently overwrite
conclusion' anti-pattern that produced an AES->ChaCha20 redaction with
no history.

Rules enforced at write time:
  1. SUPERSedeRequired — a note whose claim already carries a note with
     a terminal stamp (verify_status=passes, or status PROVEN/VERIFIED)
     is presumed a CORRECTION and must name `supersedes: <prior-id>`.
     Scoping: only notes for the SAME claim_id gate each other (two
     notes on different claims are not a correction pair).
  2. verify_status reset — a correction NEVER inherits verification: a
     note carrying `supersedes:` must be written verify_status=pending.
     The old evidence did not verify the new conclusion; the independent
     verifier must re-sign-off (#236 R1 maker-checker).
  3. chain integrity — the supersedes target must exist, and the chain
     walker terminates on cycles/missing links.

File format matches the notes layer the convergence note-gate reads
(convergence_check._note_layer_gaps: frontmatter claim_id +
verify_status) and the fact-CONFLICT convention's supersedes vocabulary
(references/schema.md).

Consumers (#528): the notes-write path behind hooks/write_guard.py
(#532 PreToolUse face) — a Write/Edit to notes/*.md carrying no
supersedes while a stamped same-claim note exists is the shape this
writer rejects.
"""
from __future__ import annotations

import re
from pathlib import Path

_FM_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_MAX_CHAIN_WALK = 64  # cycle breaker: chains deeper than this are broken

# verify_status vocabulary the convergence note-gate recognizes
# (references/schema.md note.verify_status).
_VERIFY_PENDING = "pending"


class SupersedeRequired(ValueError):
    """Writing a note that corrects an existing stamped note without a
    supersedes chain."""


def _frontmatter(path: Path) -> dict[str, str]:
    """Minimal 'key: value' frontmatter read. {} when absent/unparseable."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    m = _FM_RE.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip()
    return out


class NotesWriter:
    """Reader/validator/writer over <root>/*.md notes."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ---------- write ----------

    def write_note(
        self,
        *,
        stem: str,
        claim_id: str,
        body: str,
        title: str,
        status: str = "note",
        verify_status: str = _VERIFY_PENDING,
        supersedes: str | None = None,
    ) -> Path:
        """Write notes/<stem>.md enforcing the supersedes contract.

        Raises:
          SupersedeRequired — same-claim stamped prior exists and no
            supersedes pointer was given.
          ValueError — verify_status not 'pending' on a correction, or the
            supersedes target does not exist.
        """
        if supersedes:
            if not (self.root / f"{supersedes}.md").exists():
                raise ValueError(
                    f"supersedes target {supersedes!r} does not exist under "
                    f"{self.root} — a fake chain pointer is not a correction")
            if verify_status != _VERIFY_PENDING:
                raise ValueError(
                    f"a superseding note ({stem}) must be written "
                    f"verify_status=pending — the correction does not "
                    f"inherit {verify_status!r} from the prior note; an "
                    f"independent verifier must re-sign-off (#236 R1)")
        elif self._has_stamped_note_for(claim_id, excluding=stem):
            prior = self._stamped_note_for(claim_id, excluding=stem)
            raise SupersedeRequired(
                f"writing {stem} while a stamped note exists for the same "
                f"claim ({prior}); supply supersedes=<prior-id> to keep the "
                f"correction traceable (#528)")
        fm = ["---", f"id: {stem}", f"claim_id: {claim_id}",
              f"status: {status}", f"verify_status: {verify_status}"]
        if supersedes:
            fm.append(f"supersedes: {supersedes}")
        fm.append("---\n")
        target = self.root / f"{stem}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "\n".join(fm) + f"\n# {title}\n\n{body}\n", encoding="utf-8")
        return target

    # ---------- chain ----------

    def get_chain(self, stem: str) -> list[str]:
        """Walk supersedes links newest -> oldest. Terminates on a missing
        link, a cycle, or the walk cap ([]-terminated prefix returned)."""
        chain: list[str] = []
        seen = {stem}
        cur = stem
        while len(chain) < _MAX_CHAIN_WALK:
            fm = _frontmatter(self.root / f"{cur}.md")
            nxt = fm.get("supersedes")
            if not nxt or nxt in seen:
                break
            chain.append(nxt)
            seen.add(nxt)
            cur = nxt
        return chain

    # ---------- internals ----------

    def _notes_for(self, claim_id: str, *, excluding: str) -> list[Path]:
        out: list[Path] = []
        if not self.root.is_dir():
            return out
        for p in sorted(self.root.glob("*.md")):
            if p.stem == excluding:
                continue
            fm = _frontmatter(p)
            if fm.get("claim_id") == claim_id:
                out.append(p)
        return out

    def _stamped_note_for(self, claim_id: str, *, excluding: str) -> str | None:
        """Id of a same-claim note carrying a terminal stamp (the note a
        correction would be correcting), or None."""
        for p in self._notes_for(claim_id, excluding=excluding):
            fm = _frontmatter(p)
            vs = (fm.get("verify_status") or "").strip().lower()
            status = (fm.get("status") or "").strip().upper()
            if vs == "passes" or status in ("PROVEN", "VERIFIED"):
                return p.stem
        return None

    def _has_stamped_note_for(self, claim_id: str, *, excluding: str) -> bool:
        return self._stamped_note_for(claim_id, excluding=excluding) is not None


def check_write(notes_dir: Path, note_text: str, note_name: str) -> list[str]:
    """Adjudicate a PENDING note write against the supersedes contract.

    The write_guard (#532) shadow-adjudication face: given the post-image
    text of notes/<note_name> and the notes/ directory it would land in,
    return violation strings ([] = allow). Checks, in order:
      1. chainless correction — the note's claim already has a stamped
         note and this write carries no `supersedes:` -> the AES->ChaCha20
         silent-overwrite shape.
      2. fake chain — `supersedes:` names a note that does not exist.
      3. inherited stamp — a `supersedes:` note written with
         verify_status != pending (the correction did not re-verify).
    Non-correction writes (no stamped same-claim prior) are untouched.
    """
    root = Path(notes_dir)
    # parse the pending note's frontmatter
    m = _FM_RE.match(note_text)
    fm: dict[str, str] = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()
    claim_id = fm.get("claim_id") or ""
    supersedes = fm.get("supersedes") or None
    verify_status = (fm.get("verify_status") or "").strip().lower()
    if supersedes:
        if not (root / f"{supersedes}.md").exists():
            return [f"supersedes target {supersedes!r} does not exist — "
                    f"a fake chain pointer is not a correction (#528)"]
        if verify_status and verify_status != _VERIFY_PENDING:
            return [f"a superseding note must be verify_status=pending, "
                    f"got {verify_status!r} — a correction never inherits "
                    f"verification (#528; independent re-sign-off is #236 R1)"]
        return []
    if not claim_id:
        return []  # no claim linkage — outside the correction gate
    writer = NotesWriter(root)
    prior = writer._stamped_note_for(  # noqa: SLF001 — same-module face
        claim_id, excluding=Path(note_name).stem)
    if prior is None:
        return []
    return [f"notes/{note_name} corrects {prior} (same claim {claim_id}, "
            f"stamped) without `supersedes: {prior}` — corrections keep a "
            f"traceable chain, the prior conclusion is never silently "
            f"overwritten (#528)"]


# ---------------------------------------------------------------------------
# #762 K3 SEAM — placeholder ONLY. Do not implement here.
#
# Wave 3 wires hypothesis -> note supersession through this name once J3/H2
# land (#759 hypothesis-persistence / #761). Until then ANY call must fail
# loudly: a silent pass-through here would let a claim closure masquerade as
# a hypothesis rewrite with no chain, re-opening the exact AES->ChaCha20
# silent-overwrite class this module exists to prevent.
# ---------------------------------------------------------------------------
def note_supersedes_hypothesis(*args, **kwargs):
    """TODO(#762 K3, Wave 3): thin interface for rewriting an assumption via
    the notes/ supersedes chain (J3/H2 consumers land in #759/#761).

    Deliberately NOT implemented in the K1+K2 slice — the shape of the
    hypothesis face is Wave 3's decision; pre-welding it here would freeze
    wrong seams (#762 design.md D6).
    """
    raise NotImplementedError(
        "#762 K3 lands in Wave 3 (after #759/#761, J3/H2) - "
        "note_supersedes_hypothesis is a reserved seam, not wired yet")

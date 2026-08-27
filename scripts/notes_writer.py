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
import sys
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
# #759 Wave-3 wiring (was the #762 K3 reserved seam) — a NOTE can now retire
# an OPEN HYPOTHESIS: notes/<id>.md declaring `supersedes_hypothesis: H-NNN`
# flips that hypothesis open→superseded with superseded_by=<note id> (the
# assumption now lives in the result-layer note), emits the
# `hypothesis_superseded` event, and returns affected_claims (the hyp's claim
# + same competitor_group peers) so the caller/receipt exposes the re-rank
# scope. NO automatic claim-register rewrite — the next value/priority recalc
# absorbs the signal. Claim closures without any resolvable pointer are
# rejected LOUDLY: a closure must never masquerade as a hypothesis rewrite
# without a chain (#762 placeholder doctrine).
#
# Pointer disambiguation vs the #528 note→note chain: plain `supersedes:` is
# honored ONLY when it resolves under hypotheses/ and NOT under notes/
# (both resolving = ambiguous = rejected).
# ---------------------------------------------------------------------------
class InvalidHypothesisPointer(ValueError):
    """The note names no hypothesis target this module can resolve."""


def note_supersedes_hypothesis(notes_dir: Path, note_id: str, *,
                               hypotheses_dir: Path | None = None,
                               workspace: Path | None = None) -> dict:
    """Retire an OPEN hypothesis via the notes/ supersedes chain (#759).

    Returns {"ok", "note", "hypothesis", "status", "affected_claims"}.
    Raises:
      FileNotFoundError — the note does not exist.
      InvalidHypothesisPointer — no pointer / unresolvable / ambiguous.
      hypothesis_store.InvalidTransition — source hypothesis not open
        (terminal states never reopen; write a NEW hypothesis, #528).
    """
    from hypothesis_store import HypothesisStore, InvalidTransition

    root = Path(notes_dir)
    hyps_root = Path(hypotheses_dir) if hypotheses_dir else root.parent / "hypotheses"
    fm = _frontmatter(root / f"{note_id}.md")
    if not fm:
        raise FileNotFoundError(f"note {note_id} does not exist under {root}")
    pointer = (fm.get("supersedes_hypothesis") or "").strip()
    if not pointer:
        cand = (fm.get("supersedes") or "").strip()
        if cand:
            in_notes = (root / f"{cand}.md").exists()
            in_hyps = (hyps_root / f"{cand}.md").exists()
            if in_hyps and in_notes:
                raise InvalidHypothesisPointer(
                    f"supersedes: {cand} resolves to BOTH a note and a "
                    f"hypothesis — ambiguous; use supersedes_hypothesis:")
            if in_hyps:
                pointer = cand
    if not pointer or not (hyps_root / f"{pointer}.md").exists():
        raise InvalidHypothesisPointer(
            f"note {note_id} declares no resolvable hypothesis pointer "
            f"(supersedes_hypothesis: H-NNN) — retiring an assumption "
            f"requires naming it (#762 K3)")
    store = HypothesisStore(hyps_root)
    target = store.get(pointer)
    if target.status != "open":
        raise InvalidTransition(
            f"{pointer} is {target.status!r} — decided hypotheses stay "
            f"decided (#528); write a NEW hypothesis instead")
    peers = [h.claim_id for h in store.list_all()
             if h.id != pointer and h.competitor_group == target.competitor_group]
    affected = sorted({target.claim_id, *peers})
    store.transition(pointer, "superseded", superseded_by=note_id)
    try:
        from kunglao_log import emit
        emit(workspace, actor="notes_writer", action="hypothesis_superseded",
             artifact=f"notes/{note_id}.md",
             detail=f"{pointer} <- {note_id} | affected_claims={','.join(affected)}")
    except Exception:  # noqa: BLE001 — observability never gates the rewrite
        pass
    return {"ok": True, "note": note_id, "hypothesis": pointer,
            "status": "superseded", "superseded_by": note_id,
            "affected_claims": affected}


def main(argv: list[str] | None = None) -> int:
    """CLI face: python notes_writer.py <ws> --supersede-hyp <NOTE_ID>
    [--notes-dir notes] [--hypotheses-dir hypotheses]"""
    import argparse
    import json as _json
    import sys as _sys

    ap = argparse.ArgumentParser(prog="notes_writer.py")
    ap.add_argument("workspace")
    ap.add_argument("--supersede-hyp", metavar="NOTE_ID",
                    help="retire the OPEN hypothesis named by this note's "
                         "supersedes_hypothesis frontmatter")
    ap.add_argument("--notes-dir", default="notes")
    ap.add_argument("--hypotheses-dir", default="hypotheses")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    try:
        out = note_supersedes_hypothesis(
            ws / args.notes_dir, args.supersede_hyp,
            hypotheses_dir=ws / args.hypotheses_dir, workspace=ws)
    except (FileNotFoundError, ValueError) as exc:
        print(f"supersede-hyp FAIL: {exc}", file=_sys.stderr)
        return 2
    print(_json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

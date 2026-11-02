#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/playbook_distill.py — the terminal distillation call (issue #960).

ONE frozen-model call per rollout terminal: the terminal material (the
workspace's facts/*.md + blockers/*.md + evidence/probe-*.json probe
readings) plus the CURRENT family playbook go in; a STRUCTURED PLAYBOOK
PATCH comes out; the mechanical gate verifies it; the new playbook file
lands in ONE canonical write. The frozen model is never fine-tuned —
this is inference-time extraction, the distillation program's landing
correction (the call produces playbook entries, not T2 text).

FAIL-CLOSED is the shape of the whole face: any fault — executor crash,
timeout, non-JSON output, malformed entries, zero gated ops — returns
``{"applied": False, "patch": [], ...}`` with ONE loud stderr warn and
leaves the playbook file byte-untouched. Never a crash, never a
half-applied patch (the new file is built in memory and written once;
scripts/rlvr/family_playbook.save is the only writer).

THE MECHANICAL GATE (no learned judge — the model proposes, arithmetic
disposes):
  - shape: op ∈ {add, modify, retire}, non-empty section; add/modify
    need non-empty text; modify/retire must address an EXISTING entry
    heading; add must NOT duplicate one;
  - evidence: every add/modify carries ≥1 evidence_ref that resolves to
    an EXISTING file in the distilling workspace (ws-relative or
    absolute); unresolvable refs are dropped, an entry left with zero
    verified refs is dropped;
  - capacity: the patched playbook must fit the hard line budget —
    family_playbook.fit_budget culls lowest-evidence-count entries
    first (the 宁缺毋滥 eviction policy, mechanical).

DETERMINISM CONSTRAINT (recorded): the bench executor is ``claude -p``
print mode, and that CLI exposes no temperature/seed pin — same-input
byte-determinism is therefore pinned AT THE EXECUTOR SEAM (tests inject
a deterministic stub; bench_runner.py's convention, mirrored). The
deterministic pipeline AROUND the call (material ordering, prompt
assembly, gate, apply, cull, serialize) is fully pinned: given the same
executor output, two distill runs are byte-identical.

Cost contract: exactly ONE model call per distill run (the stub counts).

stdlib only.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

if __package__ in (None, ""):
    # direct-path execution: the package parent (scripts/) is NOT on
    # sys.path (path[0] is scripts/rlvr/) — insert it before the sibling
    # imports (the q_cells direct-execution pattern)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rlvr import family_playbook as fpb  # noqa: E402

#: the structured patch vocabulary
PATCH_OPS = ("add", "modify", "retire")

#: the executor's wall cap (a hang is an infra fault -> fail-closed)
DISTILL_WALL_CAP_S = 600.0

#: mechanical cap on the terminal material riding one prompt (bytes of
#: text, deterministic file order, mid-file truncation marker)
MATERIAL_CAP_CHARS = 120_000

TRUNCATION_MARKER = "\n[truncated by playbook_distill]\n"

#: the terminal material globs (deterministic order: sorted per glob)
TERMINAL_GLOBS = (("facts", "*.md"), ("blockers", "*.md"),
                  ("evidence", "probe-*.json"))

Executor = Callable[[str], str]


class DistillExecutorError(RuntimeError):
    """The default executor's fault shape (rc != 0 / spawn failure)."""


def _warn(reason: str) -> None:
    """The loud stderr warn — the fail-closed face is SILENT nowhere."""
    try:
        from kunglao_log import warn  # noqa: PLC0415 — lazy, keeps the
        # module import-light under `import rlvr` (the __init__ loads
        # every submodule eagerly; kunglao_log stays out until needed)
        warn("playbook_distill", reason)
    except Exception:  # noqa: BLE001 — the warn must never become the crash
        # the fail-open fallback: kunglao_log itself failed, so raw stderr
        # is the last resort (the logging-arch skip-set exempts fail-open)
        print(f"[kunglao-agent] playbook_distill WARN (fail-open): {reason}",
              file=__import__("sys").stderr)


# ---- the default executor (the bench convention, mirrored) -----------------
def default_executor(prompt: str) -> str:
    """The real seam: `claude -p` print mode (bench_runner.py's executor
    pattern — never --dangerously-skip-permissions; a pure text call
    needs no permission mode). Tests inject a stub instead."""
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt],
            timeout=DISTILL_WALL_CAP_S, capture_output=True, text=True,
            check=False, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        raise DistillExecutorError(
            f"distill-call-timeout cap={DISTILL_WALL_CAP_S:.0f}s") from exc
    except OSError as exc:
        raise DistillExecutorError(f"distill-call-spawn-failed: {exc}") from exc
    if proc.returncode != 0:
        raise DistillExecutorError(
            f"distill-call rc={proc.returncode}: "
            f"{(proc.stderr or '')[-300:]}")
    return proc.stdout


# ---- terminal material + prompt --------------------------------------------
def collect_material(ws) -> list[tuple[str, str]]:
    """The terminal material: (relpath, text) for facts/*.md,
    blockers/*.md and evidence/probe-*.json — sorted per glob (global
    order = glob order), each file whole until the shared char cap,
    then ONE deterministic truncation. Missing dirs contribute nothing."""
    ws = Path(ws)
    out: list[tuple[str, str]] = []
    budget = MATERIAL_CAP_CHARS
    for sub, pattern in TERMINAL_GLOBS:
        paths = sorted((ws / sub).glob(pattern)) if (ws / sub).is_dir() else []
        for path in paths:
            if budget <= 0:
                break
            try:
                text = path.read_text(encoding="utf-8",
                                      errors="replace")
            except OSError:
                continue
            rel = f"{sub}/{path.name}"
            if len(text) > budget:
                out.append((rel, text[:budget] + TRUNCATION_MARKER))
                budget = 0
                break
            out.append((rel, text))
            budget -= len(text)
    return out


def build_prompt(ws, family: str, playbook_text: str,
                 material: list[tuple[str, str]] | None = None) -> str:
    """The distillation prompt: the task, the current playbook, the
    terminal material verbatim, and the output contract. Deterministic
    in the inputs (sorted material, whole-file playbook)."""
    if material is None:
        material = collect_material(ws)
    blocks = "\n".join(f"--- {rel} ---\n{text.rstrip()}"
                       for rel, text in material)
    current = playbook_text.rstrip() if playbook_text.strip() \
        else "(empty — this family has no playbook yet)"
    return (
        "You are distilling ONE completed rollout into a playbook "
        "patch. Below: the CURRENT playbook for task family "
        f"'{family}', then the terminal material of the rollout that "
        "just finished (its facts, blockers and probe readings — the "
        "only citable evidence). Produce a SMALL, STABLE patch of "
        "durable strategy knowledge: generalize the rollout's findings "
        "into situation-precondition -> strategy entries a future "
        "rollout of this family can act on. Prefer improving existing "
        "entries over adding new ones; retire entries the material "
        "refutes.\n\n"
        f"CURRENT PLAYBOOK:\n{current}\n\n"
        f"TERMINAL MATERIAL (verbatim):\n{blocks or '(none)'}\n\n"
        "OUTPUT CONTRACT — return ONLY a JSON array (no prose, no code "
        "fences), each element exactly:\n"
        '{"op": "add" | "modify" | "retire", '
        '"section": "<situation-precondition heading>", '
        '"text": "<strategy line(s)>", '
        '"evidence_refs": ["<path from TERMINAL MATERIAL>"]}\n'
        "Rules: add/modify MUST cite at least one real path from the "
        "TERMINAL MATERIAL; retire needs no text or refs; modify and "
        "retire address an entry by its exact situation heading; every "
        "ref must be a path that exists in the workspace listed above.")


# ---- parse + the mechanical gate --------------------------------------------
def parse_patch(text: str) -> list[dict]:
    """The model output -> a patch list. Raises ValueError on anything
    that is not a JSON array of objects (the caller fails closed)."""
    raw = str(text or "").strip()
    if raw.startswith("```"):  # tolerate one fenced block
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    doc = json.loads(raw)
    if not isinstance(doc, list) or not all(isinstance(e, dict)
                                            for e in doc):
        raise ValueError("patch is not a JSON array of objects")
    return doc


def _verified_refs(refs, ws: Path) -> list[str]:
    """The evidence face of the gate: keep the refs that resolve to an
    EXISTING file (ws-relative or absolute), deduped, order kept."""
    verified: list[str] = []
    ws_root = ws.resolve()
    for ref in refs if isinstance(refs, list) else []:
        if not isinstance(ref, str) or not ref.strip():
            continue
        candidate = Path(ref.strip())
        # review round 1 MEDIUM: ws-relative only, resolved, and contained
        # (a ../ escape or an absolute path is not workspace evidence)
        if candidate.is_absolute():
            continue
        resolved = (ws / candidate).resolve()
        if not resolved.is_file() or not resolved.is_relative_to(ws_root):
            continue
        if ref.strip() not in verified:
            verified.append(ref.strip())
    return verified


def _shape_fault(entry: dict, sections: set[str]) -> str | None:
    """The shape face of the gate: reason-or-None. Addressing rules —
    add must not duplicate a section; modify/retire must hit one."""
    op = entry.get("op")
    section = entry.get("section")
    if op not in PATCH_OPS:
        return f"unknown-op:{op!r}"
    if not isinstance(section, str) or not section.strip():
        return "missing-section"
    section = section.strip()
    if op == "retire":
        return None if section in sections \
            else f"retire-missing-section:{section[:80]}"
    text = entry.get("text")
    if not isinstance(text, str) or not text.strip():
        return "missing-text"
    if op == "add" and section in sections:
        return f"add-duplicate-section:{section[:80]}"
    if op == "modify" and section not in sections:
        return f"modify-missing-section:{section[:80]}"
    return None


def gate_patch(patch: list[dict], ws, doc: fpb.PlaybookDoc
               ) -> tuple[list[dict], list[tuple[dict, str]]]:
    """The mechanical patch gate. Returns (gated, dropped) where dropped
    carries (entry, reason) for every refused op. Pure: verifies shapes,
    section addresses and evidence-ref EXISTENCE against ``ws`` — never
    judges the strategy text (no learned judge; 宁缺毋滥 is structural:
    an uncited entry cannot pass)."""
    ws = Path(ws)
    sections = {e.situation for e in doc.entries}
    gated: list[dict] = []
    dropped: list[tuple[dict, str]] = []
    for entry in patch:
        fault = _shape_fault(entry, sections)
        if fault is not None:
            dropped.append((entry, fault))
            continue
        op = str(entry["op"])
        section = str(entry["section"]).strip()
        if op == "retire":
            gated.append({"op": op, "section": section,
                          "text": "", "evidence_refs": []})
            continue
        if op == "add" and section in sections:
            dropped.append((entry, "add-duplicate-intra-patch"))
            continue
        verified = _verified_refs(entry.get("evidence_refs"), ws)
        if not verified:
            dropped.append((entry, "no-verified-evidence"))
            continue
        text = str(entry["text"])
        if fpb.entry_line_count(fpb.PlaybookEntry(
                situation=section, lines=tuple(text.splitlines()),
                evidence=tuple(verified))) + 2 > fpb.DEFAULT_LINE_BUDGET:
            dropped.append((entry, "entry-exceeds-budget"))
            continue
        gated.append({"op": op, "section": section, "text": text,
                      "evidence_refs": verified})
        if op == "add":
            sections.add(section)
    return gated, dropped


def apply_patch(doc: fpb.PlaybookDoc,
                gated: list[dict]) -> fpb.PlaybookDoc:
    """Apply a GATED patch: retire removes, modify replaces the strategy
    text and unions the evidence refs (old order first, new appended),
    add appends. Deterministic; immutably (new doc)."""
    entries = list(doc.entries)
    for op in gated:
        kind, section = op["op"], op["section"]
        if kind == "retire":
            entries = [e for e in entries if e.situation != section]
            continue
        text_lines = tuple(op["text"].splitlines())
        if kind == "modify":
            entries = [
                e if e.situation != section else fpb.PlaybookEntry(
                    situation=e.situation, lines=text_lines,
                    evidence=tuple(
                        list(e.evidence)
                        + [r for r in op["evidence_refs"]
                           if r not in e.evidence]))
                for e in entries]
            continue
        entries.append(fpb.PlaybookEntry(
            situation=section, lines=text_lines,
            evidence=tuple(op["evidence_refs"])))
    return fpb.PlaybookDoc(family=doc.family, title=doc.title,
                           entries=tuple(entries))


# ---- the registered seam ----------------------------------------------------
def distill(ws, family: str, playbook_path: Path | None = None,
            *, executor: Executor | None = None,
            budget: int = fpb.DEFAULT_LINE_BUDGET) -> dict:
    """THE terminal distillation call: one frozen-model call -> gated
    patch -> canonical playbook write.

    Returns a summary dict — ``applied`` (the file was rewritten),
    ``patch`` (the gated ops applied; [] on ANY failure), ``reason``
    (machine-readable), ``dropped`` / ``culled`` (gate + capacity
    counts), ``calls`` (model calls spent: 0 or 1 — the cost contract).
    Fail-closed: every fault below warns loudly on stderr and leaves
    the playbook file byte-untouched."""
    ws = Path(ws)
    executor = executor or default_executor
    path = playbook_path or fpb.playbook_path(family)
    result: dict = {"applied": False, "patch": [], "reason": "",
                    "dropped": 0, "culled": 0, "calls": 0}

    def fail(reason: str) -> dict:
        result["reason"] = reason
        _warn(f"{family}: {reason} — playbook left unchanged")
        return result

    if path is None:
        return fail("unsanitary-family-name")
    # the CURRENT playbook reads from THE path (the --playbook override
    # wins; load_family's <family>.md mapping is not consulted here)
    try:
        current = fpb.parse(path.read_text(encoding="utf-8"),
                            family=str(family)) if path.is_file() \
            else fpb.PlaybookDoc(family=str(family), title="")
    except (OSError, UnicodeDecodeError):
        return fail("current-playbook-unreadable")
    material = collect_material(ws)
    if not material:
        return fail("no-terminal-material")
    try:
        raw = executor(build_prompt(ws, str(family),
                                    fpb.serialize(current),
                                    material))
    except Exception as exc:  # noqa: BLE001 — the model face fails closed
        return fail(f"executor-fault:{type(exc).__name__}:"
                    f"{str(exc)[:200]}")
    result["calls"] = 1
    try:
        patch = parse_patch(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        return fail(f"parse-fault:{type(exc).__name__}:"
                    f"{str(exc)[:200]}")
    gated, dropped = gate_patch(patch, ws, current)
    result["dropped"] = len(dropped)
    if not gated:
        return fail("no-gated-ops")
    merged = apply_patch(current, gated)
    fitted, culled = fpb.fit_budget(merged, budget)
    result["culled"] = culled
    fpb.save(fitted, path)
    result.update({"applied": True, "patch": gated})
    return result


def main(argv: list[str] | None = None) -> int:
    """Operator CLI: one terminal distillation over a workspace.
    `python scripts/rlvr/playbook_distill.py <ws> <family>`"""
    import argparse  # noqa: PLC0415 — CLI-only import
    ap = argparse.ArgumentParser(
        prog="playbook_distill.py",
        description="kunglao Type-2 playbook distillation (#960)")
    ap.add_argument("ws", help="the finished rollout's workspace")
    ap.add_argument("family", help="task family (e.g. tf-snake)")
    ap.add_argument("--playbook", default=None,
                    help="override the playbook file path")
    ap.add_argument("--json", action="store_true",
                    help="print the summary doc on stdout")
    args = ap.parse_args(argv)
    summary = distill(args.ws, args.family,
                      Path(args.playbook) if args.playbook else None)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

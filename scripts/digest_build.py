#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""digest_build.py — mechanical digest generation (issue #3, design-spec §3.6).

A six-section markdown digest (2-4KB), purely mechanical with no LLM,
injected at cold start instead of reading the full progress.txt.
Numeric fidelity: facts' unit fields carried verbatim into sec_c
(numeric-fidelity.md).
Completeness: a newly verified fact enters the digest within 1 round
(build_digest recomputation reflects it).

Usage:
  python digest_build.py <workspace>            # write runs/digest.md
  python digest_build.py <workspace> --stdout   # print only
"""
from __future__ import annotations

# #534: observability lifeline — module-level emit on load.
import kunglao_log  # noqa: E402

# #534: observability lifeline — module-level emit on load.
try:
    kunglao_log.emit(ws, actor="digest_build", action="converge",
                          detail="module wired")
except NameError:
    pass

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# #538 W-5: the _INDEX row schema and its parser live in THE single module
# (tools/_lib/index_schema.py) shared with scripts/update_index.py — the old
# inline 5-column split here was the second, divergent contract (and parsed
# free text as status in live workspaces).
_LIB_DIR = Path(__file__).resolve().parent.parent / "tools" / "_lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))
import index_schema as _INDEX_SCHEMA  # noqa: E402,F401  (identity anchor for tests)
from index_schema import (  # noqa: E402,F401 — re-export face (digest_build.IndexSchemaError read via module attr)
    IndexSchemaError,
    parse_index_text,
)

SCHEMA_VERSION = "digest-v1"
DIGEST_PATH = Path("runs") / "digest.md"

# #528 sec_g: the open-hypotheses section is pointer-sized and BOUNDED —
# a pathological hypotheses/ dir must not blow the 4096-byte cold-start
# cap (same bounding posture as every other digest section).
MAX_SEC_G_HYPS = 12


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _facts_index(ws: Path) -> list[dict]:
    """Parse facts/_INDEX.md via the shared single-schema parser (#538 W-5).

    Row: F<id> | <status> | <claim_id> | <one-line conclusion>[ | unit=...].
    The optional 5th `unit=` field is digest-specific display metadata; it is
    derived here (split off the conclusion), NOT part of the shared schema.
    A malformed status raises IndexSchemaError — never silently re-typed.
    (#863: the pre-contract `<ws>/_INDEX.md` fixture fallback was removed —
    every reader derives from the canonical facts/ location.)"""
    index = ws / "facts" / "_INDEX.md"
    if not index.exists():
        return []
    out = []
    for row in parse_index_text(_read_text(index)):
        conclusion = row["conclusion"]
        unit = "n/a"
        # unit= rides as a 5th pipe column in legacy rows; recover it from
        # the conclusion tail without re-splitting the shared row.
        if " | unit=" in conclusion:
            conclusion, _, unit = conclusion.partition(" | unit=")
        out.append({"id": row["fact_id"], "status": row["status"],
                    "claim": row["claim_id"], "conclusion": conclusion,
                    "unit": unit})
    return out


def _claims(ws: Path) -> list[dict]:
    reg = _load_yaml(ws / "claim-register.yaml")
    return reg.get("claims") or []


def _failure_rules(ws: Path) -> list[dict]:
    fr = _load_yaml(ws / "failure-registry.yaml")
    return fr.get("rules") or []


def build_sec_g(ws: Path) -> str:
    """Digest sec_g: OPEN hypotheses, pointers only (#528).

    Reads ONLY from <ws>/hypotheses/ (hypothesis_store, the single
    parser). NEVER from notes/ — notes is the result layer (user
    correction 2026-08-20: first judge, then revise notes), and
    re-importing a 'hypothesis' from notes is the exact path that
    produced the AES->ChaCha20 silent-overwrite anti-pattern.

    Refuted/superseded hypotheses are deliberately absent: only UNRESOLVED
    questions re-hydrate at restart; decided ones live in the notes/
    facts/ trail, not duplicated here.

    Returns "" when there is nothing to show (no dir, no open hypotheses)
    so build_digest emits no section at all — pre-#528 workspaces keep
    their exact six-section digest.
    """
    hyp_dir = Path(ws) / "hypotheses"
    if not hyp_dir.is_dir():
        return ""
    # Imported lazily: digest_build must stay importable even if the
    # hypothesis layer module moves (the build path wraps this in
    # try/except anyway, but the import failure should not fire at module
    # import time for unrelated callers).
    from hypothesis_store import HypothesisStore
    open_hyps = HypothesisStore(hyp_dir).list_open()[:MAX_SEC_G_HYPS]
    if not open_hyps:
        return ""
    lines = ["## sec_g — open hypotheses (#528, pointers only)", "",
             "| hyp_id | claim_id | competitor_group | candidates |",
             "|---|---|---|---|"]
    for h in open_hyps:
        cands = ", ".join(h.candidates) if h.candidates else "-"
        lines.append(f"| {h.id} | {h.claim_id} | "
                     f"{h.competitor_group or '-'} | {cands} |")
    lines.append("")
    return "\n".join(lines)


def build_sec_h(ws: Path) -> str:
    """Digest sec_h: execution surfaces (#699), per-channel event counts.

    Reads ONLY runs/logs/kunglao-*.jsonl (the kunglao_log emit trail),
    streamed line-by-line (no whole-file buffering) and parsed via
    kunglao_log.iter_jsonl (the #863 Family K tolerance single source;
    non-dict rows like a literal ``null`` are filtered here so a stray
    line can't vanish the whole section). Rows without a channel key
    (pre-#699 legacy) count under ``local`` — the .get() gap aggregates
    as the un-tagged bucket rather than vanishing. Returns "" when there
    are no log rows at all so build_digest emits no section
    (build_sec_g precedent: pre-existing workspaces keep their exact
    digest shape).
    """
    logs_dir = Path(ws) / "runs" / "logs"
    if not logs_dir.is_dir():
        return ""
    counts: dict = {}
    total = 0
    for p in sorted(logs_dir.glob("kunglao-*.jsonl")):
        try:
            with p.open(encoding="utf-8", errors="replace") as f:
                for row in kunglao_log.iter_jsonl(f):
                    if not isinstance(row, dict):
                        continue
                    ch = row.get("channel") or "local"
                    counts[ch] = counts.get(ch, 0) + 1
                    total += 1
        except OSError:
            continue
    if not total:
        return ""
    lines = ["## sec_h — execution surfaces (#699, per-channel event counts)",
             ""]
    for ch in sorted(counts):
        lines.append(f"- {ch}: {counts[ch]}")
    lines.append("")
    return "\n".join(lines)


def build_digest(ws: Path) -> str:
    """Six-section mechanical digest. No LLM; recomputing on the same ws changes only the head timestamp (pure function apart from the timestamp)."""
    task_spec = _load_yaml(ws / "task_spec.yaml")
    claims = _claims(ws)
    facts = _facts_index(ws)
    rules = _failure_rules(ws)
    progress = _read_text(ws / "progress.txt")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    anchor_ver = f"f{len(facts)}-c{len(claims)}-r{len(rules)}"

    L: list[str] = []
    # ---- head ----
    L.append("## head")
    L.append(f"schema: {SCHEMA_VERSION} | anchor: {anchor_ver} | reconciled: {now}")
    L.append(f"workspace: {ws} | cold-start digest (mechanical, no LLM)")
    L.append("")

    # ---- sec_a: task_spec primary questions/constraints (3-5 lines) ----
    L.append("## sec_a — task_spec")
    pqs = task_spec.get("primary_questions") or []
    if pqs:
        for q in pqs[:5]:
            L.append(f"- Q: {q}")
    else:
        L.append("- (no primary_questions)")
    for key in ("scope", "constraints", "depth"):
        v = task_spec.get(key)
        if v:
            L.append(f"- {key}: {v}")
    L.append("")

    # ---- sec_b: claims index ----
    L.append("## sec_b — claims index")
    L.append("C-NN | status | conclusion | anchor")
    for c in claims:
        cid = c.get("id", "?")
        status = c.get("status", "?")
        stmt = c.get("statement", "")
        anchors = c.get("anchors") or []
        anc = anchors[0] if anchors else "—"
        L.append(f"{cid} | {status} | {stmt} | {anc}")
    if not claims:
        L.append("(no claims)")
    L.append("")

    # ---- sec_c: verified facts (unit carried verbatim, numeric fidelity) ----
    L.append("## sec_c — verified facts (unit verbatim, numeric fidelity)")
    L.append("F-NN | boundary | conclusion | unit")
    for f in facts:
        L.append(f"{f['id']} | {f['status']} | {f['conclusion']} | unit={f['unit']}")
    if not facts:
        L.append("(no facts)")
    L.append("")

    # ---- sec_d: architectural conclusions (reasoning chain preserved, not compressed to one line) ----
    L.append("## sec_d — architectural conclusions (reasoning chain preserved)")
    proven = [c for c in claims if c.get("status") in ("PROVEN", "VERIFIED")]
    if proven:
        for c in proven:
            L.append(f"- {c.get('id')}: {c.get('statement')} (status={c.get('status')})")
    else:
        L.append("- (no terminal conclusions yet)")
    L.append("")

    # ---- sec_e: failure rules (structured WHEN/THEN/anchor) ----
    L.append("## sec_e — failure rules (structured)")
    if rules:
        for r in rules:
            when = r.get("when", "?")
            then = r.get("then", "?")
            anc = r.get("anchor", "—")
            L.append(f"- WHEN {when} → THEN {then} | anchor: {anc}")
    else:
        L.append("- (no failure rules yet)")
    L.append("")

    # ---- sec_f: pointer table ----
    L.append("## sec_f — pointers (on-demand read)")
    for name in ("progress.txt", "claim-register.yaml", "facts/_INDEX.md",
                 "failure-registry.yaml", "task_spec.yaml"):
        p = ws / name
        mark = "OK" if p.exists() else "--"
        L.append(f"- [{mark}] {name}")
    if progress:
        L.append("")
        L.append("progress.txt (tail):")
        tail = progress.strip().splitlines()[-3:]
        for ln in tail:
            L.append(f"  {ln}")

    # ---- sec_g: seed-then-list (#662 -> #528) — FAIL-OPEN ----
    # Seed PQ scaffolds BEFORE listing: the cold-start digest is the
    # mechanical enforcement point for ">=1 H-NN per primary_question before
    # any C-NN dispatch" (#662 design D4). A seeding failure must never
    # block cold start — degrade to listing whatever exists.
    try:
        from hypothesis_seeder import seed_from_task_spec
        seed_from_task_spec(ws)
    except Exception:  # noqa: BLE001 — seeding failure never blocks cold start
        pass
    # ---- sec_g: open hypotheses (#528) — FAIL-OPEN ----
    # A hypotheses-layer failure must never block cold start: the digest
    # degrades to the pre-#528 six-section shape instead of raising
    # (issue #528 work item: digest build failure must not block restart).
    try:
        sec_g = build_sec_g(ws)
    except Exception:  # noqa: BLE001 — degrade, never block cold start
        sec_g = ""
    if sec_g:
        L.append("")
        L.extend(sec_g.splitlines())

    # ---- sec_h: execution surfaces (#699) — FAIL-OPEN ----
    # Per-channel event counts from runs/logs/kunglao-*.jsonl. A logging
    # layer failure must never block cold start (same discipline as sec_g):
    # degrade to the pre-#699 digest shape instead of raising.
    try:
        sec_h = build_sec_h(ws)
    except Exception:  # noqa: BLE001 — degrade, never block cold start
        sec_h = ""
    if sec_h:
        L.append("")
        L.extend(sec_h.splitlines())

    return "\n".join(L) + "\n"


def write_digest(ws: Path) -> Path:
    """Write runs/digest.md, return the path."""
    out = ws / DIGEST_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_digest(ws), encoding="utf-8")
    return out


def digest_completeness(ws: Path) -> bool:
    """Whether a newly verified fact is already in the digest."""
    md = build_digest(ws)
    for f in _facts_index(ws):
        if f["id"] not in md:
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="digest_build.py", description="mechanical digest generation")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--stdout", action="store_true", help="print only, do not write")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    if args.stdout:
        print(build_digest(ws))
    else:
        p = write_digest(ws)
        print(f"digest written: {p} ({p.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""difficulty_thresholds.py — #16 difficulty-gated success thresholds.

Issue #16: promotion requirements are FLAT today — every claim needs the same
verify pass regardless of how resistant the sample is. This module owns the
per-tier policy table and the query API consumers compose with.

Feed (open-loop input, #15/PR #80): scripts/difficulty_calibration.py writes
evidence/difficulty.json (schema ``difficulty-calibration/1``: tier/score/
dominant_factor/factors/families/coverage) and mounts the same doc as the
task_spec.yaml ``difficulty:`` key. This module READS that tier and never
recalibrates — difficulty factors stay #15's business.

Fail-closed default: a missing, corrupt, or unknown-tier difficulty feed
resolves to ``hard`` — NEVER silently down-grades to easy. A workspace whose
resistance is unknown gets the protective posture, not the cheap one.

Policy table (defaults — one-line rationale each; the 1/1/2/2 + F/F/T/T
shape from the #16 plan):

  easy   required_independent_verifications=1  — LEGACY PIN: exactly today's
         behavior; simple samples must NOT be complexified (owner ruling).
  easy   redteam_rounds=1                      — one adversarial pass, as today.
  easy   associated_task_consistency=False     — no sweep: a simple sample's
         claims don't gain truth from cross-checking neighbors.
  easy   heuristic_first_allowed=False         — no heuristic-first mandate on
         samples with no resistance evidence.

  medium — identical to easy: the medium band is feature noise, not a
         confirmed wall (#15: score 0.15-0.40 with no multi-front discovery),
         so the legacy flow stays until a wall is actually on the board.

  hard   required_independent_verifications=2  — one confirmed resistance wall;
         a single verifier can share the maker's blind spot, so PROVEN needs a
         second DISTINCT verifier record.
  hard   redteam_rounds=1                      — re-attack rounds stay a MAX
         thing; hard avoids attrition loops (#15 rejects score attrition).
  hard   associated_task_consistency=True      — protective planning: a wall
         found in one claim must be swept against its associated tasks.
  hard   heuristic_first_allowed=True          — heuristic-first problem
         discovery is now a legitimate discovery posture (guidance, not gate).

  max    required_independent_verifications=2  — multi-front resistance (#15
         MAX discovery rule): two independent verifications minimum.
  max    redteam_rounds=2                      — re-attack after the first
         round's findings are addressed; low fault tolerance.
  max    associated_task_consistency=True      — MAX planning is protective:
         consistency checks across associated tasks before PROVEN.
  max    heuristic_first_allowed=True          — heuristic-first discovery is
         the MAX posture (owner ruling on #16 anchors).

Enforcement points (compose, minimal, test-visible):
  - scripts/kunglao_record.py claim_migrator — PROVEN promotion refuses when
    the claim has fewer than required_independent_verifications DISTINCT
    verifier records (easy/medium keep the legacy messages verbatim).
  - hooks/worker_budget_gates.py compare_register_change_proven_gate — the
    same depth check as a hook-side backstop violation.
  - scripts/heartbeat_loop_prompt.py build_prompt — guidance-only line when
    associated_task_consistency is set (guidance surfaces stay guidance).

Verification-record counting reuses the #57/#72 record shapes:
  - red-team DIFFs  runs/verify-redteam-*.md naming the claim  (PR #57)
  - verifier-class dispatch rows in runs/logs/kunglao-*.jsonl  (PR #57)
  - outcome records under runs/ remain visible to the orchestrator through
    worker_death's snapshots (PR #72) but a death is not a verification —
    death records never count toward the depth requirement.

CLI:  python difficulty_thresholds.py <workspace> [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCHEMA = "difficulty-thresholds/1"

# Fail-closed posture: unknown/missing tier never down-grades to easy.
FALLBACK_TIER = "hard"

DIFFICULTY_FEED = "evidence/difficulty.json"
SOURCE_FEED = "evidence/difficulty.json"
SOURCE_TASK_SPEC = "task_spec.yaml:difficulty"
SOURCE_UNKNOWN_TIER = "fail-closed:unknown-tier"
SOURCE_NO_FEED = "fail-closed:no-difficulty-feed"

# POLICY DEFAULTS (#16). Keys are the tier names #15 emits (the only enum
# surface of the feed). Values are dicts so consumers get one flat row.
THRESHOLDS: dict[str, dict] = {
    "easy": {
        "required_independent_verifications": 1,
        "redteam_rounds": 1,
        "associated_task_consistency": False,
        "heuristic_first_allowed": False,
    },
    "medium": {
        "required_independent_verifications": 1,
        "redteam_rounds": 1,
        "associated_task_consistency": False,
        "heuristic_first_allowed": False,
    },
    "hard": {
        "required_independent_verifications": 2,
        "redteam_rounds": 1,
        "associated_task_consistency": True,
        "heuristic_first_allowed": True,
    },
    "max": {
        "required_independent_verifications": 2,
        "redteam_rounds": 2,
        "associated_task_consistency": True,
        "heuristic_first_allowed": True,
    },
}

TIERS = tuple(THRESHOLDS)


# ---------- query API ----------

def get_thresholds(tier: str | None) -> dict:
    """Policy thresholds for one tier (flat dict + schema/tier/source).

    Unknown / blank tier -> the FALLBACK_TIER row with a fail-closed source
    and a note naming the offending value — never a silent down-grade.
    """
    key = str(tier or "").strip().lower()
    if key in THRESHOLDS:
        row = dict(THRESHOLDS[key])
        row.update({"schema": SCHEMA, "tier": key, "source": "explicit-tier"})
        return row
    row = dict(THRESHOLDS[FALLBACK_TIER])
    row.update({
        "schema": SCHEMA,
        "tier": FALLBACK_TIER,
        "source": SOURCE_UNKNOWN_TIER,
        "note": f"unknown tier {tier!r} — fail-closed to {FALLBACK_TIER} "
                "(never silently down-grade to easy)",
    })
    return row


def _read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _task_spec_tier(ws: Path) -> str | None:
    """The ``difficulty:`` key PR #80 mounts into task_spec.yaml (secondary
    surface — the file feed wins). Lazy yaml import: guidance callers keep a
    stdlib-only path; an unavailable yaml just means no fallback."""
    spec_path = ws / "task_spec.yaml"
    if not spec_path.is_file():
        return None
    try:
        import yaml
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — any parse trouble = surface absent
        return None
    if not isinstance(spec, dict):
        return None
    doc = spec.get("difficulty")
    if isinstance(doc, dict) and str(doc.get("tier") or "").strip():
        return str(doc["tier"]).strip().lower()
    return None


def thresholds_for_workspace(ws: Path | str) -> dict:
    """Resolve the tier for a workspace, then return its thresholds.

    Order: evidence/difficulty.json (#15 file feed) -> task_spec.yaml
    ``difficulty:`` key (the same doc, mounted) -> fail-closed FALLBACK_TIER.
    Never raises: a missing/corrupt feed is the fail-closed posture with a
    recorded source note, not an error.
    """
    ws = Path(ws)
    feed = _read_json(ws / "evidence" / "difficulty.json")
    tier: str | None = None
    source = SOURCE_NO_FEED
    note = (f"no readable {DIFFICULTY_FEED} (and no task_spec difficulty key)"
            f" — fail-closed to {FALLBACK_TIER}")
    if isinstance(feed, dict) and str(feed.get("tier") or "").strip():
        tier = str(feed["tier"]).strip().lower()
        source = SOURCE_FEED
        note = ""
    else:
        spec_tier = _task_spec_tier(ws)
        if spec_tier:
            tier = spec_tier
            source = SOURCE_TASK_SPEC
            note = ""
    if tier is None:
        th = get_thresholds(FALLBACK_TIER)
        th["source"] = source
        th["note"] = note
        return th
    th = get_thresholds(tier)
    if th["tier"] != tier:  # feed carried a value outside the policy table
        th["source"] = f"{source}+{SOURCE_UNKNOWN_TIER}"
        th["note"] = (f"difficulty feed said tier={tier!r} — not a policy "
                      f"tier; fail-closed to {FALLBACK_TIER}")
    else:
        th["source"] = source
    return th


def count_verifications(ws: Path | str, claim_id: str) -> int:
    """DISTINCT verifier engagement records for one claim (query API).

    Composes with blind_gate's #57 record shapes (see count_claim_verifier_records);
    a workspace whose gate machinery is unavailable counts 0 (fail closed:
    the enforcement faces block on 0, they never assume evidence).
    """
    try:
        from blind_gate import count_claim_verifier_records
        return int(count_claim_verifier_records(Path(ws), claim_id)["verifications"])
    except Exception:  # noqa: BLE001 — gate machinery unavailable = no credit
        return 0


def guidance_line(ws: Path | str) -> str:
    """The difficulty-aware red-team rigor line for orchestrator guidance
    surfaces ("#16 plan: append a difficulty-aware line when tier is
    hard/max"). Empty string below hard — guidance must not complexify
    simple samples."""
    th = thresholds_for_workspace(ws)
    if not th.get("associated_task_consistency"):
        return ""
    return (f"difficulty {th['tier']} (#16): run {th['redteam_rounds']} "
            f"red-team rounds per claim and a consistency sweep of associated "
            f"tasks before PROVEN (need "
            f"{th['required_independent_verifications']} independent "
            f"verifications)")


# ---------- CLI face ----------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="#16: resolve the difficulty-gated thresholds for a "
                    "workspace (reads evidence/difficulty.json, fail-closed "
                    "to hard)")
    ap.add_argument("path", type=Path, help="workspace root")
    ap.add_argument("--json", action="store_true", help="print the JSON doc")
    ap.add_argument("--claim", help="also count distinct verifier records "
                                    "for this claim id")
    args = ap.parse_args(argv)

    th = thresholds_for_workspace(args.path)
    if args.claim:
        th["claim"] = args.claim
        th["verifier_records"] = count_verifications(args.path, args.claim)
    if args.json:
        print(json.dumps(th, ensure_ascii=False, indent=2))
    else:
        extra = (f" verifier_records={th['verifier_records']} (claim "
                 f"{args.claim})") if args.claim else ""
        print(f"difficulty-thresholds: tier={th['tier']} "
              f"required_independent_verifications="
              f"{th['required_independent_verifications']} "
              f"redteam_rounds={th['redteam_rounds']} source={th['source']}"
              f"{extra}")
        if th.get("note"):
            print(f"  note: {th['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

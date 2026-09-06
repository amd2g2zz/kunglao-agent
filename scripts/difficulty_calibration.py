#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""difficulty_calibration.py — #15 sample difficulty calibration (easy/medium/hard/max).

Calibrates sample difficulty from SAMPLE-INTRINSIC observable factors only
(owner ruling on #15): features are composed from scanner outputs that already
exist at prescan time — NO new scanning, NO external labels:

  evidence/die.json   (tools/static/die_probe.py): derived.detected_packer,
                      derived.section_table[].entropy, derived.high_entropy_sections,
                      derived.language / compiler_version / compiler_string,
                      resources (VERSION_INFO / ICON / MANIFEST)
  evidence/apkid.json (scripts/apkid_scanner.py): summary.packer / obfuscator /
                      anti_debug / anti_vm, findings[].matched_files (native libs)

Difficulty is an OPEN-LOOP INPUT for #16: the tier must be machine-readable and
the schema stable. #16 consumes evidence/difficulty.json or the ``difficulty:``
key mounted in task_spec.yaml; this module never acts on the tier itself.

Evidence-gap contract: missing/unusable scanner evidence defaults to tier
``easy`` + an explicit ``evidence_gap`` factor. Absence is NEVER scored as
difficulty — a source that did not report contributes 0 and the gap is
documented in ``notes`` (conservatism by construction: with die-only evidence
the achievable ceiling is the die weight mass, 0.62, so a die-only sample can
reach ``hard`` but never ``max``).

Experiment first (plan PASS bar, issue #15): the feature set + weights below
were validated for tier separation over a synthetic 9-profile corpus
(tests/fixtures/difficulty_15/, harness tests/experiment_difficulty_15.py)
BEFORE locking the implementation. Measured result (weights v1, locked):

    profile                       intended  achieved  score
    c_tool_unpacked               easy      easy      0.0000
    go_cli_plain                  easy      easy      0.1000
    android_proguard_basic        medium    medium    0.1956
    go_stripped_medium            medium    medium    0.2150
    android_proguard_anti_medium  medium    medium    0.2872
    upx_windows_tool              hard      hard      0.4787
    android_obfuscator_anti       hard      hard      0.4978
    die_only_themida              hard      hard      0.5667
    android_max_hardened          max       max       0.8120

    -> 4-way separation clean (bands: easy <=0.10 | medium 0.1956-0.2872 |
       hard 0.4787-0.5667 | max 0.8120; thresholds 0.15/0.40/0.65 sit in the
       gaps). No 2-tier fallback needed; data maturity can open wider tiers
       without a schema change (tier is the only enum surface).

Weight rationale (derived from what separates, not hand-waved):
  packer_present 0.22 — strongest single predictor of analysis resistance
  (severity: vmprotect/themida-class 1.0, weak/unpackable packers 0.6);
  obfuscator_count 0.16 / anti_analysis 0.16 — each obfuscator/anti rule is an
  independent tool-family wall; entropy_max 0.14 + entropy_high_frac 0.10 —
  packed/encrypted payload visibility; resources_stripped 0.10 — surface
  reduction; native_libs 0.08 — second instruction set + ABI surface;
  compiler_unknown 0.04 — tie-breaker only (weak, kept out of MAX decisions).

MAX discovery rule (heuristic-first, ruling #3): MAX fires on MULTI-FRONT
resistance — (packer AND (anti-analysis OR obfuscator)) OR >=3 active factor
families — not on raw score alone, and never on attrition/mechanical loops.
Simple samples are never complexified: all-zero features stay easy regardless
of thresholds.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

try:  # single time source (#863 Family F) when scripts/ is on sys.path
    from harness_common import utc_now_z as _utc_now
except ImportError:  # CLI run outside the repo layout — keep the module usable
    def _utc_now() -> str:
        from datetime import datetime, timezone
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


SCHEMA = "difficulty-calibration/1"
EVIDENCE_FILES = ("die", "apkid")

# Tier thresholds — sit in the measured corpus gaps (see module docstring).
TIER_MEDIUM = 0.15
TIER_HARD = 0.40
TIER_MAX = 0.65

# Feature weights (sum 1.00) — locked by the #15 experiment (docstring).
WEIGHTS: dict[str, float] = {
    "packer_present": 0.22,
    "entropy_max": 0.14,
    "entropy_high_frac": 0.10,
    "resources_stripped": 0.10,
    "obfuscator_count": 0.16,
    "anti_analysis": 0.16,
    "native_libs": 0.08,
    "compiler_unknown": 0.04,
}

# Packer severity from the NAME the scanner reported (sample-intrinsic).
SEVERE_PACKERS = ("vmprotect", "themida")

# Factor families for the multi-front MAX discovery rule.
FAMILIES: dict[str, tuple[str, ...]] = {
    "packing": ("packer_present",),
    "obfuscation": ("obfuscator_count",),
    "anti_analysis": ("anti_analysis",),
    "surface_reduction": ("resources_stripped",),
}


class CalibrationMountError(Exception):
    """task_spec.yaml exists but is unparseable / not a mapping — fail-closed."""


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _die_usable(die: object) -> bool:
    """die.json counts as present only when at least one data block survived."""
    return (isinstance(die, dict)
            and bool(die.get("derived") or die.get("detects")
                     or die.get("records") or die.get("section_table")))


def _apkid_usable(apkid: object) -> bool:
    """apkid.json is present only on status ok (unavailable/error = absent)."""
    return isinstance(apkid, dict) and apkid.get("status") == "ok"


def _packer_severity(name: str) -> float:
    return 1.0 if any(sev in name.lower() for sev in SEVERE_PACKERS) else 0.6


def _die_entropy_max(die: dict) -> float:
    """Max section entropy; total_entropy fallback when no section table."""
    table = die.get("derived", {}).get("section_table") or die.get("section_table") or []
    entropies = [float(r.get("entropy") or 0.0) for r in table if isinstance(r, dict)]
    if not entropies and die.get("total_entropy") is not None:
        entropies = [float(die["total_entropy"] or 0.0)]
    return max(entropies) if entropies else 0.0


def _die_high_frac(die: dict) -> float:
    derived = die.get("derived", {})
    high = derived.get("high_entropy_sections") or die.get("high_entropy_sections") or []
    table = derived.get("section_table") or die.get("section_table") or []
    if table:
        return _clamp01(len(high) / max(1, len(table)))
    if high:
        return _clamp01(len(high) / 3.0)
    return 0.0


def _die_resources_stripped(die: dict) -> float:
    """0.0 when the binary still carries informative resources, else 1.0."""
    res = die.get("resources")
    if not isinstance(res, dict):
        return 1.0
    informative = (res.get("VERSION_INFO") or res.get("ICON")
                   or res.get("MANIFEST") or die.get("manifest"))
    return 0.0 if informative else 1.0


def _die_compiler_unknown(die: dict) -> float:
    derived = die.get("derived", {}) or {}
    if not derived.get("language"):
        return 1.0
    if not (derived.get("compiler_version") or derived.get("compiler_string")):
        return 0.5
    return 0.0


def _apkid_native_libs(apkid: dict) -> float:
    for finding in apkid.get("findings") or []:
        for path in finding.get("matched_files") or []:
            text = str(path)
            if text.endswith(".so") or text.startswith("lib/"):
                return 1.0
    return 0.0


def _summary_count(apkid: dict, *keys: str) -> int:
    summary = apkid.get("summary") or {}
    return sum(len(summary.get(k) or []) for k in keys)


def features_from_evidence(evidence: dict) -> dict:
    """Compose scanner outputs into normalized 0..1 difficulty factors.

    evidence: {"die": <die.json doc>|None, "apkid": <apkid.json doc>|None}.
    Returns {"coverage": {...}, "factors": {name: {score, source}}, "gaps": [...]}
    — only sources that actually reported contribute factors (pure function).
    """
    evidence = evidence if isinstance(evidence, dict) else {}
    die = evidence.get("die")
    apkid = evidence.get("apkid")
    die_ok, apkid_ok = _die_usable(die), _apkid_usable(apkid)

    factors: dict[str, dict] = {}
    gaps: list[str] = []

    if die_ok:
        derived = die.get("derived", {}) or {}
        die_packers = [str(derived.get("detected_packer") or "")]
        factors["packer_present"] = {
            "score": max((_packer_severity(p) for p in die_packers if p), default=0.0),
            "source": "die"}
        factors["entropy_max"] = {
            "score": _clamp01((_die_entropy_max(die) - 6.0) / 1.8), "source": "die"}
        factors["entropy_high_frac"] = {
            "score": _die_high_frac(die), "source": "die"}
        factors["resources_stripped"] = {
            "score": _die_resources_stripped(die), "source": "die"}
        factors["compiler_unknown"] = {
            "score": _die_compiler_unknown(die), "source": "die"}
    else:
        gaps.append("evidence/die.json absent or unusable — "
                    "entropy/resources/compiler factors not scored (stay 0)")

    if apkid_ok:
        apkid_factors: dict[str, tuple[float, str]] = {
            "obfuscator_count": (
                _clamp01(_summary_count(apkid, "obfuscator") / 2.0), "apkid"),
            "anti_analysis": (
                _clamp01(_summary_count(apkid, "anti_debug", "anti_vm") / 2.0),
                "apkid"),
            "native_libs": (_apkid_native_libs(apkid), "apkid"),
        }
        apkid_packers = (apkid.get("summary") or {}).get("packer") or []
        if apkid_packers:
            sev = max(_packer_severity(str(p)) for p in apkid_packers)
            if "packer_present" in factors:
                factors["packer_present"] = {
                    "score": max(factors["packer_present"]["score"], sev),
                    "source": "die+apkid"}
            else:
                factors["packer_present"] = {"score": sev, "source": "apkid"}
        for name, (score, source) in apkid_factors.items():
            factors[name] = {"score": score, "source": source}
    else:
        gaps.append("evidence/apkid.json absent or unusable (status not ok) — "
                    "obfuscator/anti-analysis/native factors not scored (stay 0)")

    return {"coverage": {"die": die_ok, "apkid": apkid_ok},
            "factors": factors, "gaps": gaps}


def calibrate(features: dict) -> dict:
    """features_from_evidence() output -> stable machine-readable verdict.

    Output schema (stable for #16): schema/tier/score/dominant_factor/factors/
    families/coverage/notes. Pure + deterministic — no timestamps here (the
    CLI face adds generated_at at the file boundary only).
    """
    factors_in = features.get("factors") or {}
    coverage = features.get("coverage") or {"die": False, "apkid": False}
    gaps = features.get("gaps") or []

    factors_out: dict[str, dict] = {}
    score = 0.0
    for name in sorted(factors_in):
        payload = factors_in[name]
        weight = WEIGHTS.get(name, 0.0)
        contribution = round(weight * float(payload.get("score", 0.0)), 4)
        score += contribution
        factors_out[name] = {"score": round(float(payload.get("score", 0.0)), 4),
                             "weight": weight,
                             "contribution": contribution,
                             "source": payload.get("source", "")}
    score = round(score, 4)

    def _fscore(name: str) -> float:
        return float(factors_in.get(name, {}).get("score", 0.0))

    families_out = {}
    for family in sorted(FAMILIES):
        active = any(_fscore(member) >= 0.5 for member in FAMILIES[family])
        top = max((_fscore(m) for m in FAMILIES[family]), default=0.0)
        families_out[family] = {"active": active, "score": round(top, 4)}
    active_families = sum(1 for f in families_out.values() if f["active"])

    notes: list[str] = list(gaps)
    packer = _fscore("packer_present")
    multi_front = packer >= 0.5 and (_fscore("anti_analysis") >= 0.5
                                     or _fscore("obfuscator_count") >= 0.5)

    if not factors_out:
        tier = "easy"
        notes.append("no scanner evidence reported — default tier easy; "
                     "absence is never scored as difficulty (issue #15 gap rule)")
        dominant = "evidence_gap"
        factors_out["evidence_gap"] = {
            "detail": "; ".join(notes), "score": 0.0, "weight": 0.0,
            "contribution": 0.0, "source": "none"}
    else:
        if multi_front or active_families >= 3:
            tier = "max"
            notes.append(
                f"MAX via multi-front discovery rule (packer+anti/obfuscator="
                f"{multi_front}, active families={active_families}) — "
                "heuristic-first problem discovery, not score attrition")
        elif score >= TIER_MAX:
            tier = "max"
        elif score >= TIER_HARD:
            tier = "hard"
        elif score >= TIER_MEDIUM:
            tier = "medium"
        else:
            tier = "easy"
        dominant = max(sorted(factors_out),
                       key=lambda k: factors_out[k]["contribution"])
        if not (coverage.get("die") and coverage.get("apkid")):
            missing = [s for s in EVIDENCE_FILES if not coverage.get(s)]
            notes.append(f"partial evidence — scored from present sources only, "
                         f"missing: {', '.join(missing)} (ceiling capped by "
                         "absent weight mass; tier is conservative)")

    return {"schema": SCHEMA,
            "tier": tier,
            "score": score,
            "dominant_factor": dominant,
            "factors": factors_out,
            "families": families_out,
            "coverage": {"die": bool(coverage.get("die")),
                         "apkid": bool(coverage.get("apkid"))},
            "thresholds": {"medium": TIER_MEDIUM, "hard": TIER_HARD,
                           "max": TIER_MAX},
            "notes": notes}


# ---------- workspace faces ----------

def _load_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def resolve_evidence_dir(path: Path) -> Path | None:
    """<ws>/evidence, an evidence dir itself, or None."""
    if (path / "evidence").is_dir():
        return path / "evidence"
    if path.is_dir() and any((path / f"{n}.json").is_file() for n in EVIDENCE_FILES):
        return path
    return None


def calibrate_workspace(ws: Path | str) -> dict:
    """Read <ws>/evidence/*.json (tolerant) -> calibrate() result. Never raises."""
    ev_dir = resolve_evidence_dir(Path(ws))
    evidence = {name: None for name in EVIDENCE_FILES}
    if ev_dir is not None:
        for name in EVIDENCE_FILES:
            evidence[name] = _load_json(ev_dir / f"{name}.json")
    return calibrate(features_from_evidence(evidence))


def mount(ws: Path | str, result: dict, *, mount_spec: bool = True) -> Path:
    """Write evidence/difficulty.json (+ merge ``difficulty:`` into
    task_spec.yaml when present and ``mount_spec``, preserving user keys —
    intake_promise shape).

    #104: the CLI merge is opt-in (--mount); a bare invocation writes only
    evidence/difficulty.json. Callers that own the mount decision (init)
    keep the default mount_spec=True.

    task_spec absent -> evidence/difficulty.json is the only surface (rc ok);
    task_spec unparseable -> CalibrationMountError (fail-closed, no silent drop).
    """
    ws = Path(ws)
    ev_dir = ws / "evidence"
    ev_dir.mkdir(parents=True, exist_ok=True)
    doc = _boundary_doc(result)
    out = ev_dir / "difficulty.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")

    spec_path = ws / "task_spec.yaml"
    if mount_spec and spec_path.exists():
        try:
            spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise CalibrationMountError(
                f"task_spec.yaml unparseable: {exc}") from exc
        if not isinstance(spec, dict):
            raise CalibrationMountError(
                f"task_spec.yaml must be a YAML mapping, got {type(spec).__name__}")
        spec["difficulty"] = doc
        spec_path.write_text(
            yaml.safe_dump(spec, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="#15: calibrate sample difficulty from scanner evidence "
                    "(writes evidence/difficulty.json)")
    ap.add_argument("path", type=Path,
                    help="workspace root or evidence directory")
    ap.add_argument("--json", action="store_true", help="print the result JSON")
    ap.add_argument("--mount", action="store_true",
                    help="also merge the difficulty block into task_spec.yaml")
    args = ap.parse_args(argv)

    ws = args.path
    result = calibrate_workspace(ws)
    try:
        # #104: the task_spec merge is gated behind --mount — a bare run
        # writes evidence/difficulty.json only and says so.
        out_path = mount(ws, result, mount_spec=args.mount)
    except CalibrationMountError as exc:
        print(f"difficulty-calibration: ERROR {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(_boundary_doc(result), ensure_ascii=False, indent=2))
    else:
        print(f"difficulty-calibration: tier={result['tier']} "
              f"score={result['score']} dominant={result['dominant_factor']} "
              f"wrote {out_path}"
              + (" + task_spec.yaml difficulty key" if args.mount else
                 " (task_spec.yaml NOT merged — pass --mount)"))
    return 0


def _boundary_doc(result: dict) -> dict:
    """CLI/file payload = pure result + generated_at (boundary only, never in
    the pure core — keeps calibrate() deterministic byte-for-byte)."""
    doc = dict(result)
    doc["generated_at"] = _utc_now()
    return doc


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feature_mining.py — #460 Part A: historical-run feature-table mining.

Read-only, deterministic mining of (signature features → method/outcome)
tuples that ALREADY EXIST in e2e run artifacts, into
``runs/feature-table.jsonl`` rows (schema ``feature-table/1``) — the
data floor under Part B's feature-conditioned prior (predict-before-try,
the SATzilla move; NO prior math lives here).

Sources joined per run (run-state.json is the anchor — see
openspec/changes/issue-460-feature-mining/design.md):

  <root>/runs/e2e/<run_id>/run-state.json   identity + ws/task_dir pointers
  <ws>/task_spec.yaml                       lane, prescan states, difficulty block
  <ws>/claim-register.yaml                  claim → source (attribution fallback)
  <ws>/evidence/{die,apkid,difficulty}.json probe outputs (usable rules reused
                                            from difficulty_calibration)
  <ws>/runs/logs/e2e-audit.jsonl            dispatch attempt/result rows
  <ws>/runs/rollout-ledger.jsonl            task/<claim> settlements (via
                                            rlvr.ledger.settled — the U4 fold)
  <task_dir>/task.yaml                      workspace_scaffold (language/entry)

Contract highlights (spec scenarios are the tests):

  - pointer resolution: absolute verbatim; relative against the mining
    root (fixture shape);
  - row identity from run-state fields (run_id/family/unit);
  - signature_hash = sha256[:12] over canonical (sorted, compact, UTF-8)
    JSON of the features object — the INSTANCE-signature namespace,
    distinct from state_signature's pre-dispatch progress state;
  - outcomes: one entry per dispatch attempt, FIFO-per-claim pairing
    with the earliest LATER same-claim result; act_result closed
    vocabulary landed/timeout/blocked/unknown (rc-null → unknown);
    attribution via method_families.declared_value (envelope first, v0
    prose marker second) with the claim-register source as fallback —
    never fabricated; settled/credit from the ledger fold;
  - tolerance: a missing/unparseable/undecodable run-state skips the
    run with a warn; dangling pointers degrade fields to nulls;
  - determinism: rows sorted by (family, task_id, run_id, root),
    sorted-key JSON + "\\n", no wall-clock in rows — same input set →
    byte-identical output;
  - disclosure: runs predating the unified audit stream mine with
    empty outcomes (checkpoint/report acts[] fallback = follow-up card).

Inputs are NEVER written. Process data (kunglao-wt roots) stays live;
only sanitized fixtures are committed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import yaml

from difficulty_calibration import _apkid_usable, _die_usable  # presence rules
from method_families import declared_value  # the #432 dual-face contract
from rlvr.ledger import settled  # the U4 single settlement interface


def _warn(reason: str) -> None:
    """Stderr-only miner diagnostics — deliberately NOT kunglao_log.warn:
    that tracer's ledger face resolves a workspace by cwd walk-up (any
    directory carrying a ``runs/`` marker qualifies) and APPENDS a warn
    row into it — for this miner the input root itself, breaking the
    read-only contract. The miner's warns are operator diagnostics, not
    workspace telemetry (review finding 1)."""
    print(f"[feature_mining] WARN (fail-open): {reason}", file=sys.stderr)

SCHEMA = "feature-table/1"
OUT_DEFAULT = Path("runs") / "feature-table.jsonl"
AUDIT_REL = Path("runs") / "logs" / "e2e-audit.jsonl"
HASH_LEN = 12

FEATURE_KEYS = ("lane", "project_type", "target_kind", "packer_flags",
                "difficulty_factors", "probe_outputs")
FAMILY_KEYS = ("packing", "obfuscation", "anti_analysis", "surface_reduction")
ACT_RESULTS = frozenset({"landed", "timeout", "blocked", "unknown"})
OUTCOME_KEYS = ("claim", "method_family_or_claim_source", "act_result",
                "settled", "credit")


# ---------------------------------------------------------------------------
# canonical hash + schema validation (the importable faces the tests pin)
# ---------------------------------------------------------------------------

def signature_hash(features: dict) -> str:
    """sha256[:12] over canonical JSON of the features object (sorted keys,
    compact separators, UTF-8) — the instance-signature namespace."""
    canonical = json.dumps(features, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:HASH_LEN]


_HEX = frozenset("0123456789abcdef")


def _check_identity(row: dict) -> list[str]:
    errs: list[str] = []
    if row.get("schema") != SCHEMA:
        errs.append(f"schema: expected {SCHEMA!r}, got {row.get('schema')!r}")
    for key in ("run_id", "family", "task_id"):
        if not isinstance(row.get(key), str) or not row.get(key):
            errs.append(f"{key}: non-empty string required")
    sig = row.get("signature_hash")
    if not (isinstance(sig, str) and len(sig) == HASH_LEN
            and set(sig) <= _HEX):
        errs.append(f"signature_hash: {HASH_LEN} lowercase hex required, "
                    f"got {sig!r}")
    return errs


def _check_scalar(feats: dict, key: str) -> list[str]:
    v = feats.get(key)
    return ([] if v is None or isinstance(v, str)
            else [f"features.{key}: string-or-null required"])


def _check_target_kind(feats: dict) -> list[str]:
    tk = feats.get("target_kind")
    if not isinstance(tk, dict) or set(tk) != {"language", "entry_suffix"}:
        return ["features.target_kind: {language, entry_suffix} required"]
    errs = []
    for k, v in tk.items():
        if v is not None and not isinstance(v, str):
            errs.append(f"features.target_kind.{k}: string-or-null")
    return errs


def _check_packer_flags(feats: dict) -> list[str]:
    pf = feats.get("packer_flags")
    if not isinstance(pf, dict):
        return ["features.packer_flags: object required"]
    errs = []
    for k in FAMILY_KEYS:
        if not isinstance(pf.get(k), bool):
            errs.append(f"features.packer_flags.{k}: boolean required")
    for k in ("detected_packers", "detected_obfuscators"):
        v = pf.get(k)
        if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
            errs.append(f"features.packer_flags.{k}: string list required")
    return errs


def _check_difficulty(feats: dict) -> list[str]:
    df = feats.get("difficulty_factors")
    if df is None:
        return []
    if not isinstance(df, dict):
        return ["features.difficulty_factors: object-or-null required"]
    errs = []
    for k in ("tier", "dominant_factor"):
        if not isinstance(df.get(k), str):
            errs.append(f"features.difficulty_factors.{k}: string")
    if not isinstance(df.get("score"), (int, float)):
        errs.append("features.difficulty_factors.score: number")
    for k in ("factors", "families", "coverage"):
        if not isinstance(df.get(k), dict):
            errs.append(f"features.difficulty_factors.{k}: mapping")
    return errs


def _check_probe_outputs(feats: dict) -> list[str]:
    po = feats.get("probe_outputs")
    # additive vocabulary: the floss face is optional — legacy two-face
    # rows stay valid, rows with floss evidence carry exactly three
    if not isinstance(po, dict) or not (
            {"die", "apkid"} <= set(po) <= {"die", "apkid", "floss"}):
        return ["features.probe_outputs: {die, apkid[, floss]} required"]
    die_fields = {"prescan_state", "usable", "detected_packer", "entropy_max"}
    apkid_fields = {"prescan_state", "usable", "packers", "obfuscators"}
    if not isinstance(po["die"], dict) or set(po["die"]) != die_fields:
        return ["features.probe_outputs.die: enumerated fields"]
    if not isinstance(po["apkid"], dict) or set(po["apkid"]) != apkid_fields:
        return ["features.probe_outputs.apkid: enumerated fields"]
    if "floss" in po:
        floss_fields = {"survivors", "constants"}
        fl = po["floss"]
        if not isinstance(fl, dict) or set(fl) != floss_fields:
            return ["features.probe_outputs.floss: enumerated fields"]
        for k in sorted(floss_fields):
            v = fl[k]
            if v is None:
                continue
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                return [f"features.probe_outputs.floss.{k}: "
                        "non-negative int or null"]
    return []


def _check_outcome(i: int, o: object) -> list[str]:
    if not isinstance(o, dict) or set(o) != set(OUTCOME_KEYS):
        return [f"outcomes[{i}]: {set(OUTCOME_KEYS)} required"]
    errs = []
    if not isinstance(o["claim"], str) or not o["claim"]:
        errs.append(f"outcomes[{i}].claim: non-empty string")
    src = o["method_family_or_claim_source"]
    if src is not None and not isinstance(src, str):
        errs.append(f"outcomes[{i}].method_family_or_claim_source:"
                    " string-or-null")
    if o["act_result"] not in ACT_RESULTS:
        errs.append(f"outcomes[{i}].act_result: one of {sorted(ACT_RESULTS)}")
    if not isinstance(o["settled"], bool):
        errs.append(f"outcomes[{i}].settled: boolean required")
    if o["credit"] is not None and not isinstance(o["credit"], (int, float)):
        errs.append(f"outcomes[{i}].credit: number-or-null")
    return errs


def validate_row(row: object) -> list[str]:
    """Field-precise feature-table/1 check: [] iff the row is well-formed.
    The same check the regression tests apply (the spec's schema
    requirement); never raises."""
    if not isinstance(row, dict):
        return ["row: not a JSON object"]
    errs = _check_identity(row)
    feats = row.get("features")
    if not isinstance(feats, dict):
        return [*errs, "features: object required"]
    errs += [f"features.{k}: missing" for k in FEATURE_KEYS if k not in feats]
    for key in ("lane", "project_type"):
        errs += _check_scalar(feats, key)
    errs += _check_target_kind(feats)
    errs += _check_packer_flags(feats)
    errs += _check_difficulty(feats)
    errs += _check_probe_outputs(feats)
    outcomes = row.get("outcomes")
    if not isinstance(outcomes, list):
        return [*errs, "outcomes: list required"]
    for i, o in enumerate(outcomes):
        errs += _check_outcome(i, o)
    return errs


# ---------------------------------------------------------------------------
# tolerant readers (decode errors count as unparseable — the #438 lesson)
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # UnicodeDecodeError is a ValueError
        return None


def _read_yaml(path: Path) -> dict | None:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _resolve(pointer: object, root: Path) -> Path:
    """Absolute pointers verbatim (live shape); relative against the
    mining root (fixture shape)."""
    p = Path(str(pointer or ""))
    return p if p.is_absolute() else root / p


# ---------------------------------------------------------------------------
# features
# ---------------------------------------------------------------------------

def _difficulty_features(block: object) -> dict | None:
    """The MOUNTED calibration block reshaped (recomputation from raw
    scanner evidence is forbidden — the block is what the run saw);
    timestamps/notes excluded (instance signature must not drift). A
    block missing its identity scalars (tier/dominant_factor str, score
    number) is malformed and degrades to None (absence never scored)."""
    if not isinstance(block, dict):
        return None
    if not (isinstance(block.get("tier"), str)
            and isinstance(block.get("dominant_factor"), str)
            and isinstance(block.get("score"), (int, float))
            and not isinstance(block.get("score"), bool)):
        return None
    factors = block.get("factors")
    factors = factors if isinstance(factors, dict) else {}
    families = block.get("families")
    families = families if isinstance(families, dict) else {}
    coverage = block.get("coverage")
    coverage = coverage if isinstance(coverage, dict) else {}
    return {
        "tier": str(block["tier"]),
        "score": block["score"],
        "dominant_factor": str(block["dominant_factor"]),
        "factors": {str(k): (v.get("score") if isinstance(v, dict) else None)
                    for k, v in factors.items()},
        "families": {str(k): (bool(v.get("active"))
                              if isinstance(v, dict) else False)
                     for k, v in families.items()},
        "coverage": {"die": bool(coverage.get("die")),
                     "apkid": bool(coverage.get("apkid"))},
    }


def _die_salients(doc: object) -> dict:
    doc = doc if isinstance(doc, dict) else {}
    usable = _die_usable(doc)
    derived = doc.get("derived") or {}
    table = derived.get("section_table") or doc.get("section_table") or []
    entropies = []
    for r in table if isinstance(table, list) else []:
        if not isinstance(r, dict) or r.get("entropy") is None:
            continue
        try:
            value = float(r["entropy"])
        except (TypeError, ValueError):  # non-numeric entropy is data noise
            continue
        if math.isfinite(value):  # NaN/inf would break strict JSON
            entropies.append(value)
    return {"usable": usable,
            "detected_packer": derived.get("detected_packer") if usable else None,
            "entropy_max": max(entropies) if entropies else None}


def _apkid_salients(doc: object) -> dict:
    summary = (doc.get("summary") or {}) if isinstance(doc, dict) else {}
    if not isinstance(summary, dict):
        summary = {}

    def _str_list(key: str) -> list[str]:
        raw = summary.get(key)
        if not isinstance(raw, list):
            return []
        # coerce BEFORE set/sort: mixed-type lists (["UPX", 3]) must
        # degrade, not crash the whole table (review finding 3)
        return [str(x) for x in raw]

    return {"usable": _apkid_usable(doc),
            "packers": _str_list("packer"),
            "obfuscators": _str_list("obfuscator")}


def _int_or_none(value: object) -> int | None:
    """Non-negative true-int or None (bools/floats/negatives never
    count — the same data-noise rule the token face applies)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _floss_salients(path: Path) -> dict:
    """The floss-filtered face's salients: the survivor-set size and
    the embedded-constant count (base64 candidates + high-entropy
    blobs — the constant-heavy shape of an obfuscated bundle). Only
    content counts are read (never timestamps/provenance), so the same
    artifact mines to the same salients. Degradations are honest
    Nones: a missing/corrupt artifact, an error-class doc, or missing
    category counts — absence never scores."""
    doc = _read_json(path)
    doc = doc if isinstance(doc, dict) else {}
    stats = doc.get("input_stats")
    stats = stats if isinstance(stats, dict) else {}
    inventory = doc.get("string_inventory")
    inventory = inventory if isinstance(inventory, dict) else {}
    counts = inventory.get("per_category_counts")
    counts = counts if isinstance(counts, dict) else {}
    survivors = _int_or_none(stats.get("total_after_denoise"))
    if survivors is None:
        return {"survivors": None, "constants": None}
    bases = [counts.get("base64_candidates"),
             counts.get("high_entropy_blobs")]
    if any(_int_or_none(b) is None for b in bases):
        return {"survivors": survivors, "constants": None}
    return {"survivors": survivors,
            "constants": sum(_int_or_none(b) for b in bases)}


def _probe_outputs(spec: dict | None, ev_dir: Path) -> dict:
    prescan = ((spec or {}).get("promise") or {}).get("prescan") or {}
    die_state = ((prescan.get("die") or {}).get("state")) \
        if isinstance(prescan.get("die"), dict) else None
    apkid_state = ((prescan.get("apkid") or {}).get("state")) \
        if isinstance(prescan.get("apkid"), dict) else None
    die_doc = _read_json(ev_dir / "die.json")
    apkid_doc = _read_json(ev_dir / "apkid.json")
    die = _die_salients(die_doc)
    apkid = _apkid_salients(apkid_doc)
    probes = {
        "die": {"prescan_state": die_state if isinstance(die_state, str)
                else None,
                "usable": die["usable"],
                "detected_packer": die["detected_packer"],
                "entropy_max": die["entropy_max"]},
        "apkid": {"prescan_state": apkid_state if isinstance(apkid_state, str)
                  else None,
                  "usable": apkid["usable"],
                  "packers": apkid["packers"],
                  "obfuscators": apkid["obfuscators"]},
    }
    # the floss face is opt-in evidence: it rides only when the artifact
    # yielded a survivor count, so floss-less workspaces mine the legacy
    # two-face shape byte-identically (the additive-vocabulary contract)
    floss = _floss_salients(ev_dir / "floss-filtered.json")
    if floss["survivors"] is not None:
        probes["floss"] = floss
    return probes


def _features(state: dict, ws: Path, task_dir: Path) -> dict:
    spec = _read_yaml(ws / "task_spec.yaml")
    task = _read_yaml(task_dir / "task.yaml")
    scaffold = (task or {}).get("workspace_scaffold")
    if not isinstance(scaffold, dict):
        scaffold = {}
    entry = scaffold.get("entry")
    difficulty = _difficulty_features(
        (spec or {}).get("difficulty")) or _difficulty_features(
        _read_json(ws / "evidence" / "difficulty.json"))
    families = (difficulty or {}).get("families") or {}
    probes = _probe_outputs(spec, ws / "evidence")
    detected = probes["die"]["detected_packer"]
    die_packers = {str(detected)} if detected else set()
    packers = sorted(die_packers | set(probes["apkid"]["packers"]))
    language = scaffold.get("language")
    entry_suffix = Path(str(entry)).suffix.lower() if entry else None
    return {
        "lane": (state.get("lane")
                 or (spec or {}).get("lane") or None),
        "project_type": state.get("type") or None,
        "target_kind": {
            "language": language if isinstance(language, str) else None,
            "entry_suffix": entry_suffix or None,
        },
        "packer_flags": {
            **{k: bool(families.get(k)) for k in FAMILY_KEYS},
            "detected_packers": [str(p) for p in packers],
            "detected_obfuscators": sorted(
                {str(o) for o in probes["apkid"]["obfuscators"]}),
        },
        "difficulty_factors": difficulty,
        "probe_outputs": probes,
    }


# ---------------------------------------------------------------------------
# outcomes (audit stream join)
# ---------------------------------------------------------------------------

def _detail(row: dict) -> dict:
    d = row.get("detail")
    if isinstance(d, str):
        try:
            d = json.loads(d)
        except ValueError:
            return {}
    return d if isinstance(d, dict) else {}


def _act_result(result_detail: dict) -> str:
    rc = result_detail.get("rc")
    timed_out = bool(result_detail.get("timed_out"))
    if rc is None:
        return "unknown"          # orchestrator/dry face — never "blocked"
    if timed_out or rc == -1:
        return "timeout"
    if rc == 0:
        return "landed"
    return "blocked"


def _envelope(run_dir: Path, claim: str) -> tuple[dict | None, str]:
    """The per-claim dispatch prompt (runner convention, rewritten per
    dispatch — last-write-wins is a disclosed approximation). Claim ids
    carrying path-hostile characters never reach the filesystem (no
    separator/null traversal surface at all)."""
    if any(c in claim for c in ("/", "\\", "\0")) or claim in (".", ".."):
        return None, ""
    p = run_dir / f"dispatch-prompt-{claim}.md"
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        # ValueError covers the embedded-null-byte path case (#460 review)
        return None, ""
    first = text.split("\n", 1)[0].strip()
    try:
        envelope = json.loads(first)
    except ValueError:
        envelope = None
    meta = envelope.get("kunglao_dispatch") \
        if isinstance(envelope, dict) else None
    return (meta if isinstance(meta, dict) else None), text


def _outcomes(run_dir: Path, ws: Path, sources: dict[str, str]) -> list[dict]:
    stream = ws / AUDIT_REL
    try:
        lines = stream.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        lines = []
    pending: dict[str, list[int]] = {}
    ordered: list[tuple[int, str]] = []          # (attempt index, claim)
    results: dict[int, dict] = {}                # attempt index → detail
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            _warn(f"unparseable audit line skipped in {ws}")
            continue
        if not isinstance(row, dict):
            continue
        action, claim = row.get("action"), row.get("claim")
        if not isinstance(claim, str) or not claim:
            continue
        if action == "dispatch_attempt":
            ordered.append((len(ordered), claim))
            pending.setdefault(claim, []).append(len(ordered) - 1)
        elif action == "dispatch_result":
            queue = pending.get(claim)
            if queue:  # FIFO: earliest LATER result pairs with oldest attempt
                results[queue.pop(0)] = _detail(row)
    settled_by_anchor = {}
    # kind-scoped: the join is task/<claim> — a self_distill/hybrid_distill
    # rollout anchored at the same string is NOT this claim's settlement
    for folded in settled(ws, kind="task"):
        s = folded.get("settlement") or {}
        if s and folded.get("anchor"):
            settled_by_anchor[str(folded["anchor"])] = s.get("reward")

    out: list[dict] = []
    for index, claim in ordered:
        envelope_meta, prompt_text = _envelope(run_dir, claim)
        declared = declared_value(envelope_meta, prompt_text)
        detail = results.get(index)
        out.append({
            "claim": claim,
            "method_family_or_claim_source": (
                declared if declared else sources.get(claim)),
            "act_result": _act_result(detail) if detail is not None
            else "unknown",
            "settled": claim in settled_by_anchor,
            "credit": settled_by_anchor.get(claim),
        })
    return out


def _claim_sources(ws: Path) -> dict[str, str]:
    doc = _read_yaml(ws / "claim-register.yaml")
    out: dict[str, str] = {}
    for claim in (doc or {}).get("claims") or []:
        if isinstance(claim, dict) and isinstance(claim.get("id"), str):
            src = claim.get("source")
            if isinstance(src, str) and src.strip():
                out[claim["id"]] = src.strip()
    return out


# ---------------------------------------------------------------------------
# mining
# ---------------------------------------------------------------------------

def mine_run(root: Path, run_dir: Path) -> dict | None:
    """One feature-table row, or None when the run is skipped: bad
    anchor (missing/unparseable/undecodable run-state.json) OR a row the
    feature-table/1 shape itself rejects (identity fields absent,
    non-string scalars) — the miner never ships a row its own validator
    refuses (review finding 4; an honest skip beats a lying row)."""
    try:
        state = json.loads(
            (run_dir / "run-state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _warn(f"skipped {run_dir.name}: run-state.json missing/unreadable")
        return None
    if not isinstance(state, dict):
        _warn(f"skipped {run_dir.name}: run-state not an object")
        return None
    ws = _resolve(state.get("ws"), root)
    task_dir = _resolve(state.get("task_dir"), root)
    features = _features(state, ws, task_dir)
    row = {
        "schema": SCHEMA,
        "run_id": str(state.get("run_id") or run_dir.name),
        "family": str(state.get("family") or ""),
        "task_id": str(state.get("unit") or ""),
        "signature_hash": signature_hash(features),
        "features": features,
        "outcomes": _outcomes(run_dir, ws, _claim_sources(ws)),
    }
    errs = validate_row(row)
    if errs:
        _warn(f"skipped {run_dir.name}: row fails feature-table/1 "
              f"({errs[0]}{' …' if len(errs) > 1 else ''})")
        return None
    return row


def mine(roots: list[Path], out: Path) -> dict:
    """Mine every root (deduped by resolved path); write the sorted
    feature table; return the summary. Never writes under any root.
    Rows are keyed (family, task_id, run_id, root) — the root term makes
    the bytes independent of argument order; the root itself rides the
    row only as the side-table key ``_root`` and is never serialized."""
    seen: list[Path] = []
    for r in roots:
        resolved = r.resolve()
        if resolved not in seen:
            seen.append(resolved)
    rows: list[dict] = []
    scanned = skipped = 0
    for root in seen:
        base = root / "runs" / "e2e"
        if not base.is_dir():
            continue
        for run_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            scanned += 1
            row = mine_run(root, run_dir)
            if row is None:
                skipped += 1
                continue
            row["_root"] = root
            rows.append(row)
    rows.sort(key=lambda r: (r["family"], r["task_id"], r["run_id"],
                             str(r["_root"])))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(
        json.dumps({k: v for k, v in r.items() if k != "_root"},
                   ensure_ascii=False, sort_keys=True) + "\n"
        for r in rows), encoding="utf-8")
    return {"roots": len(seen), "runs": scanned, "rows": len(rows),
            "skipped": skipped}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="feature_mining.py",
        description="#460 Part A: mine e2e run artifacts into a "
                    "feature-table/1 jsonl (deterministic, read-only)")
    parser.add_argument("roots", nargs="+",
                        help="worktree roots carrying runs/e2e/* "
                             "(explicit; nothing is discovered ambiently)")
    parser.add_argument("--out", default=str(OUT_DEFAULT),
                        help=f"output path (default {OUT_DEFAULT})")
    args = parser.parse_args(argv)
    summary = mine([Path(r) for r in args.roots], Path(args.out))
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())

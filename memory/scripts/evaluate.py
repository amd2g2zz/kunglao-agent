"""Candidate lab for kunglao-agent memory distillation (issue #82).

The ONLY place candidates receive scores. Evaluator-owned scoring follows the
#81 executable-l2-evaluation contract (scripts/kunglao_eval.py, read-only
import): the lab hands the evaluator only public inputs (candidate body, case
ids, writable receipts outdir); hidden oracles and scorer inputs are never
exposed to the candidate; receipts are the only promotion evidence and are
replayable (same inputs -> same receipt_digest).

Corpus: memory/candidates/corpus/manifest.json pins sha256 of every
case/oracle file plus the held-in/held-out split and policy invariants
(overclaims, invalid_work). held-in = staging-cohort-derived cases;
held-out = unseen cases. A manifest digest mismatch fails evaluation with a
failure receipt (fail-closed, never a green score).

Default evaluator wraps scripts/kunglao_eval.py (#81): run_episode(arm="A",
fault=None, assessor=<candidate discipline>) + score_episode(case, hidden
oracle, result). Baseline = the current production rule set's discipline
(registry current, default naive), evaluated on the same held-out cases — the
promotion gate's held-out gain is measured against it.

Staging clear (issue #82): staging entries are cleared ONLY after the
candidate record is content-verified AND a completed receipt exists; snapshot
dirs are never deleted (source-evidence retention).

Usage:
  python evaluate.py evaluate <candidate-id>    # run the lab, write receipts
  python evaluate.py status                     # expire stale candidates
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kunglao_eval as ke  # noqa: E402  (#81, read-only import)

import distill  # noqa: E402

RECEIPT_SCHEMA = "kunglao-candidate-receipt/1"


def default_evaluator(case: dict, oracle: dict, discipline: str) -> dict:
    """#81 harness: deterministic bounded episode + evaluator-owned oracle scoring.

    arm="A" (product mechanisms on), no fault, assessor = the candidate rule's
    discipline (anchored rules mandate anchor-based conclusions; naive rules
    conclude from any successful dispatch — overclaiming on adversarial cases).
    """
    result = ke.run_episode(case, "A", None, seed=0, assessor=discipline)
    scored = ke.score_episode(case, oracle, result)
    return {
        "overall": scored["oracle"]["overall"],
        "dimensions": scored["oracle"]["dimensions"],
        "transcript_hash": result["transcript_hash"],
        "budgets": result["budgets"],
        "failure_taxonomy": scored["failure_taxonomy"],
    }


# ----------------------------- corpus -----------------------------

def corpus_manifest(corpus_dir: Path | None = None) -> dict:
    return json.loads(
        (corpus_dir or distill.CORPUS_DIR).joinpath("manifest.json").read_text(encoding="utf-8")
    )


def verify_manifest(corpus_dir: Path | None = None) -> tuple[bool, str]:
    """Hash-pin check: every case/oracle file must exist and match manifest sha256."""
    try:
        m = corpus_manifest(corpus_dir)
    except OSError as exc:
        return False, f"corpus manifest unreadable: {exc}"
    for rel, expected in (m.get("files") or {}).items():
        p = Path(rel) if Path(rel).is_absolute() else ROOT / rel
        if not p.exists():
            return False, f"corpus file missing: {rel}"
        if distill._file_sha256(p) != expected:
            return False, f"corpus file digest mismatch: {rel}"
    return True, ""


def _resolve_file(rel: str) -> Path:
    return Path(rel) if Path(rel).is_absolute() else ROOT / rel


def _load_case_oracle(case_id: str, manifest: dict) -> tuple[dict, dict]:
    files = manifest.get("files") or {}
    case_rel = next((k for k in files if k.endswith(f"{case_id}/case.json")),
                    f"eval/fixtures/{case_id}/case.json")
    oracle_rel = next((k for k in files if k.endswith(f"{case_id}/oracle.json")),
                      f"eval/fixtures/{case_id}/oracle.json")
    return (json.loads(_resolve_file(case_rel).read_text(encoding="utf-8")),
            json.loads(_resolve_file(oracle_rel).read_text(encoding="utf-8")))


# ----------------------------- receipts -----------------------------

def _stable_receipt_fields(rec: dict) -> dict:
    """Digest basis: exclude wall_ms / timestamps / own digest / dims time_ms
    (replayability, mirrors #81 _stable_fields)."""
    out = json.loads(json.dumps(rec))
    for k in ("wall_ms", "started_at", "finished_at", "receipt_digest"):
        out.pop(k, None)
    dims = (out.get("oracle") or {}).get("dimensions")
    if isinstance(dims, dict):
        dims.pop("time_ms", None)
    return out


def recompute_and_set_digest(rec: dict) -> str:
    rec["receipt_digest"] = distill._sha(_stable_receipt_fields(rec))
    return rec["receipt_digest"]


def _assemble_receipt(candidate_id: str, case_id: str, split: str, discipline: str,
                      rule_digest: str, case: dict, oracle: dict, eval_result: dict) -> dict:
    rec = {
        "schema": RECEIPT_SCHEMA,
        "candidate_id": candidate_id,
        "case_id": case_id,
        "split": split,
        "discipline": discipline,
        "rule_digest": rule_digest,
        "digests": {"case": distill._sha(case), "oracle": distill._sha(oracle),
                    "code": distill._sha(Path(__file__).read_bytes()),
                    "env": f"py{sys.version_info.major}.{sys.version_info.minor}"},
        "transcript_hash": eval_result["transcript_hash"],
        "oracle": {"overall": eval_result["overall"],
                   "dimensions": eval_result["dimensions"]},
        "failure_taxonomy": eval_result["failure_taxonomy"],
        "budgets": eval_result["budgets"],
        "wall_ms": 0,
        "started_at": distill.utc_now(),
        "finished_at": distill.utc_now(),
        "cleanup": {"reset": "ok"},
        "non_evidence": eval_result["overall"] == "INCONCLUSIVE",
    }
    recompute_and_set_digest(rec)
    return rec


def _receipt_md(rec: dict, label: str) -> str:
    dims = (rec.get("oracle") or {}).get("dimensions") or {}
    lines = [
        f"# Receipt {label}",
        "",
        f"- schema: {rec.get('schema')}",
        f"- candidate_id: {rec.get('candidate_id')}",
        f"- case_id: {rec.get('case_id')}  split: {rec.get('split')}",
        f"- discipline: {rec.get('discipline')}",
        f"- overall: {rec.get('oracle', {}).get('overall')}",
        f"- non_evidence: {rec.get('non_evidence')}",
        f"- receipt_digest: {rec.get('receipt_digest')}",
        "",
        "## Dimensions",
        "",
    ]
    for name, d in dims.items():
        if isinstance(d, dict):
            lines.append(f"- {name}: pass={d.get('pass')} {d.get('detail', '')}".rstrip())
        else:
            lines.append(f"- {name}: {d}")
    return "\n".join(lines) + "\n"


# ----------------------------- scoring -----------------------------

def recompute_scores(receipts: list) -> dict:
    """PASS-fraction per split; gain = held-out − baseline held-out (issue #82 b).

    INCONCLUSIVE / FAIL receipts are non-pass (never contribute to gain).
    """
    splits: dict = {}
    for split in ("held-in", "held-out", "baseline-held-out"):
        rs = [r for r in receipts if r.get("split") == split]
        npass = sum(1 for r in rs if (r.get("oracle") or {}).get("overall") == "PASS")
        splits[split] = {"pass": npass, "total": len(rs)}
    held_out, baseline = splits["held-out"], splits["baseline-held-out"]
    gain = 0.0
    if held_out["total"] and baseline["total"]:
        gain = held_out["pass"] / held_out["total"] - baseline["pass"] / baseline["total"]
    return {"held_in": splits["held-in"], "held_out": held_out,
            "baseline_held_out": baseline, "gain": round(gain, 4)}


def journal_evaluated(candidate_id: str, *, scores: dict, receipt_files: list,
                      discipline: str) -> None:
    distill.journal_append({
        "ts": distill.utc_now(), "action": "evaluated", "candidate_id": candidate_id,
        "reason": None, "receipt_ref": receipt_files,
        "digests": {"scores": scores},
        "discipline": discipline,
    })


# ----------------------------- staging clear gate -----------------------------

def _clear_staging_after_eval(candidate_id: str, fm: dict) -> None:
    """Staging clear gate (issue #82): verified candidate + completed receipt only."""
    meta = fm.get("metadata") or {}
    hashes = meta.get("source_hashes") or {}
    try:
        path, _, _ = distill.load_candidate(candidate_id)
    except (OSError, ValueError):
        return
    rows = distill.journal_rows(candidate_id)
    gen = next((r for r in rows if r.get("action") == "generated"), None)
    if gen is None or gen.get("digests", {}).get("content") != distill._file_sha256(path):
        return  # candidate not content-verified -> keep staging
    if not any(r.get("action") == "evaluated" for r in rows):
        return  # no completed receipt yet -> keep staging
    for name, expected in hashes.items():
        p = distill.STAGING_DIR / name
        if p.exists() and distill._file_sha256(p) == expected:
            p.unlink()


# ----------------------------- expiry -----------------------------

def expire_scan(*, now: datetime | None = None) -> list:
    """Mark candidates older than CANDIDATE_EXPIRY_DAYS without promotion expired."""
    if not distill.CANDIDATE_DIR.exists():
        return []
    now = now or datetime.now(tz=timezone.utc)
    expired: list = []
    for path in sorted(distill.CANDIDATE_DIR.glob("cand-*.md")):
        cid = path.stem
        rows = distill.journal_rows(cid)
        if any(r.get("action") == "promoted" for r in rows):
            continue
        gen = next((r for r in rows if r.get("action") == "generated"), None)
        if gen is None:
            continue
        try:
            gen_ts = datetime.strptime(gen["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        if (now - gen_ts).days < distill.CANDIDATE_EXPIRY_DAYS:
            continue
        archive = distill.CANDIDATE_DIR / ".expired"
        archive.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(archive / path.name))
        distill.journal_append({"ts": distill.utc_now(), "action": "expired",
                                "candidate_id": cid,
                                "reason": f"no promotion within {distill.CANDIDATE_EXPIRY_DAYS} days",
                                "receipt_ref": None, "digests": {}})
        expired.append(cid)
    return expired


# ----------------------------- lab entry -----------------------------

def evaluate_candidate(candidate_id: str, evaluator=default_evaluator,
                       *, corpus_dir: Path | None = None) -> bool:
    """Run the candidate lab: held-in + held-out + baseline trials -> receipts.

    On any failure: failure receipt (stage=evaluation) + journal `failed` row;
    staging evidence is retained. Returns True iff a full receipt set was
    written and journaled.
    """
    try:
        path, fm, body = distill.load_candidate(candidate_id)
    except (OSError, ValueError) as exc:
        distill.write_failure_receipt(stage="evaluation", reason=f"candidate unreadable: {exc}",
                                      candidate_id=candidate_id, input_digests={})
        return False
    meta = fm.get("metadata") or {}
    discipline = ((meta.get("evaluation") or {}).get("discipline")
                  or distill.derive_discipline(body))
    ok, err = verify_manifest(corpus_dir)
    if not ok:
        distill.write_failure_receipt(stage="evaluation", reason=err, candidate_id=candidate_id,
                                      input_digests={"manifest": err})
        return False
    m = corpus_manifest(corpus_dir)
    baseline = (distill.load_registry().get("current") or {}).get("discipline") \
        or m.get("baseline_discipline", "naive")
    rule_digest = distill._file_sha256(path)
    receipts: list = []
    try:
        for split, mkey in (("held-in", "held_in"), ("held-out", "held_out")):
            for case_id in m.get(mkey, []):
                case, oracle = _load_case_oracle(case_id, m)
                res = evaluator(case, oracle, discipline)
                receipts.append(_assemble_receipt(candidate_id, case_id, split, discipline,
                                                  rule_digest, case, oracle, res))
        for case_id in m.get("held_out", []):
            case, oracle = _load_case_oracle(case_id, m)
            res = evaluator(case, oracle, baseline)
            receipts.append(_assemble_receipt(candidate_id, case_id, "baseline-held-out",
                                              baseline, rule_digest, case, oracle, res))
    except Exception as exc:
        distill.write_failure_receipt(stage="evaluation", reason=str(exc),
                                      candidate_id=candidate_id,
                                      input_digests={"rule": rule_digest})
        return False
    files: list = []
    for rec in receipts:
        label = f"{candidate_id}-{rec['case_id']}-{rec['split']}"
        jp = distill.RECEIPTS_DIR / f"receipt-{label}.json"
        jp.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        mp = distill.RECEIPTS_DIR / f"receipt-{label}.md"
        mp.write_text(_receipt_md(rec, label), encoding="utf-8")
        files.append(str(jp))
    scores = recompute_scores(receipts)
    journal_evaluated(candidate_id, scores=scores, receipt_files=files, discipline=discipline)
    _clear_staging_after_eval(candidate_id, fm)
    print(f"EVALUATED: {candidate_id} held_in={scores['held_in']} "
          f"held_out={scores['held_out']} gain={scores['gain']}")
    return True


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evaluate.py", description="candidate lab")
    sub = ap.add_subparsers(dest="cmd")
    evp = sub.add_parser("evaluate", help="evaluate a candidate in the lab")
    evp.add_argument("candidate_id")
    sub.add_parser("status", help="expire stale candidates (--status scan)")
    args = ap.parse_args(argv)
    if args.cmd == "evaluate":
        return 0 if evaluate_candidate(args.candidate_id) else 1
    if args.cmd == "status":
        expired = expire_scan()
        print(f"expired: {expired}" if expired else "no expired candidates")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

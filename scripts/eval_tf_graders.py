#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_tf_graders.py — the TF F1-F4 graders (#356).

Small mechanical scripts over the two trace faces the TF family produces:

  transcript  bare / CC-default sessions: stream-json lines whose
              ``assistant`` rows carry tool_use content blocks
              (name + input.command) paired with ``user`` rows carrying
              tool_result blocks (is_error);
  ledger      kunglao-loop workspaces: runs/logs/kunglao-*.jsonl rows with
              action="tool_call" and the per-action ``tool`` field
              (kunglao_log schema; contracts.EVENT_FIELD carries the
              action word).

Scores (the schema recorded in the campaign file):
  F1 solve      the checker verdict per (unit x toolset-variant), paired
                with the trace: solve.status solved/failed/unknown;
  F2 re-route   solved(blocked) / solved(unblocked) per unit, rates over
                fixed variant sets: f2 = blocked_rate / unblocked_rate,
                plus f2_reroute which EXCLUDES bypass solves (the
                documented shadow limitation: absolute-path invocation);
  F3 coverage   distinct tools actually used (successful invocations)
                cover every manifest-required role;
  F4 waste      tool invocations contributing nothing: observed failures
                (exit != 0), superseded route switches (a role already
                satisfied by a different tool), and post-coverage churn
                (invocations after the coverage-complete point). Unknown
                exits never count — an honest unknown is not waste.

Bypass faces: a toolbox tool invoked BY PATH (any separator before the
basename) is flagged bypass=True. Transcript commands make bypass
decidable; ledger rows without a command detail carry
bypass_known=False (never fabricated).

Deterministic: no wall clock, no dict-order dependence; identical
artifacts score identically byte-for-byte.

stdlib only.
"""
from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

SCHEMA_MANIFEST = "kunglao-eval-tf-manifest/1"
SCHEMA_SCORES = "kunglao-eval-tf-scores/1"
SCHEMA_AGG = "kunglao-eval-tf-aggregate/1"

UNBLOCKED = "unblocked"
_CLASSES = ("solved", "blocked-solved", "blocked-failed", "failed",
            "bypass-solved")


# ------------------------------------------------------------- manifest
def load_manifest(path: Path) -> dict:
    """kunglao-eval-tf-manifest/1 loader; a wrong schema is a loud
    ValueError, never a silent fallback."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA_MANIFEST or \
            not isinstance(doc.get("roles"), list):
        raise ValueError(f"bad TF manifest schema: {path}")
    return doc


def _resolve(manifest: dict | Path) -> dict:
    if isinstance(manifest, Path):
        return load_manifest(manifest)
    if isinstance(manifest, dict):
        if manifest.get("schema") != SCHEMA_MANIFEST:
            raise ValueError("manifest dict lacks " f"{SCHEMA_MANIFEST}")
        return manifest
    raise ValueError(f"unsupported manifest: {type(manifest).__name__}")


def role_of(manifest: dict, tool: str) -> str | None:
    """The role implementing ``tool`` (whole-name match), or None."""
    for role in manifest.get("roles", []):
        if tool in role.get("implements", []):
            return role["role"]
    return None


# ------------------------------------------------------------ extraction
def _tool_tokens(command: str, tools: set[str]) -> list[tuple[str, bool]]:
    """(tool, bypass) pairs for every toolbox tool token in a command.

    Whole-token match on the basename: 'unfold' never matches 'fold'. A
    separator before the basename (./toolbox/peek, /abs/peek) is the
    documented PATH-shadow bypass face."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    hits: list[tuple[str, bool]] = []
    for tok in tokens:
        base = tok.replace("\\", "/").rsplit("/", 1)[-1]
        if base in tools:
            hits.append((base, tok != base))
    return hits


def _sep_hit(name: str, text: str) -> bool:
    return bool(re.search(rf"[\\/]{re.escape(name)}\b", text))


def _read_json_rows(path: Path) -> list[dict]:
    """Tolerant JSONL reader: dict rows only, dirty lines skipped."""
    rows: list[dict] = []
    for line in Path(path).read_text(encoding="utf-8",
                                     errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _result_exits(rows: list[dict]) -> dict[str, int | None]:
    """tool_use_id -> exit (is_error -> 1) from the transcript's
    tool_result blocks."""
    exits: dict[str, int | None] = {}
    for row in rows:
        if row.get("type") != "user":
            continue
        for block in (row.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                exits[block.get("tool_use_id")] = \
                    1 if block.get("is_error") else 0
    return exits


def _use_rows(rows: list[dict]) -> list[tuple[str, str]]:
    """(tool_use id, command) pairs from the assistant rows, in order."""
    uses: list[tuple[str, str]] = []
    for row in rows:
        if row.get("type") != "assistant":
            continue
        for block in (row.get("message") or {}).get("content") or []:
            if not (isinstance(block, dict)
                    and block.get("type") == "tool_use"):
                continue
            uses.append((str(block.get("id") or ""),
                         str(((block.get("input") or {}).get("command"))
                             or "")))
    return uses


def extract_transcript(path: Path, manifest: dict) -> list[dict]:
    """tool_use events -> ordered invocation rows. Pipelines split into
    per-tool rows in command order; exit comes from the paired
    tool_result (is_error -> 1), unpaired -> None (honest unknown)."""
    manifest = _resolve(manifest)
    tools = {t for r in manifest["roles"] for t in r["implements"]}
    rows = _read_json_rows(Path(path))
    exits = _result_exits(rows)
    invs: list[dict] = []
    for ref, command in _use_rows(rows):
        for tool, bypass in _tool_tokens(command, tools):
            invs.append({
                "seq": len(invs) + 1, "tool": tool,
                "role": role_of(manifest, tool),
                "exit": exits.get(ref), "bypass": bypass,
                "bypass_known": True, "via": "transcript", "ref": ref,
            })
    return invs


def extract_ledger(path: Path, manifest: dict) -> list[dict]:
    """kunglao_log tool_call rows -> invocation rows. ``path`` is a day
    file or a logs dir (kunglao-*.jsonl, name order = stream order)."""
    manifest = _resolve(manifest)
    p = Path(path)
    files = sorted(p.glob("kunglao-*.jsonl")) if p.is_dir() else [p]
    invs: list[dict] = []
    for f in files:
        for line in f.read_text(encoding="utf-8",
                                errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict) or \
                    row.get("action") != "tool_call" or not row.get("tool"):
                continue
            raw = str(row["tool"])
            bypass = _sep_hit(raw.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
                              raw) if ("/" in raw or "\\" in raw) else False
            detail = row.get("detail")
            name = raw.replace("\\", "/").rsplit("/", 1)[-1]
            if detail is not None and not bypass:
                bypass = _sep_hit(name, str(detail))
            invs.append({
                "seq": len(invs) + 1, "tool": name,
                "role": role_of(manifest, name),
                "exit": row["exit"] if isinstance(row.get("exit"), int)
                else None,
                "bypass": bypass,
                "bypass_known": bypass or detail is not None,
                "via": "ledger", "ref": str(row.get("ts") or ""),
            })
    return invs


# ---------------------------------------------------------------- scoring
def _coverage(manifest: dict, invs: list[dict]) -> list[str]:
    covered = []
    for role in manifest["roles"]:
        if any(i["role"] == role["role"] and i["exit"] == 0 for i in invs):
            covered.append(role["role"])
    return covered


def _waste(manifest: dict, invs: list[dict]) -> dict:
    """F4: failures + superseded route switches + post-coverage churn.
    Unknown exits never count (an honest unknown is not waste)."""
    complete_at: int | None = None
    roles = [r["role"] for r in manifest["roles"]]
    for i in invs:
        if all(any(j["role"] == r and j["exit"] == 0 and j["seq"] <= i["seq"]
                   for j in invs) for r in roles):
            complete_at = i["seq"]
            break
    reasons: list[dict] = []
    for i in invs:
        why: list[str] = []
        if i["exit"] is not None and i["exit"] != 0:
            why.append("failed")
        if i["role"] is not None and any(
                j["seq"] < i["seq"] and j["role"] == i["role"]
                and j["exit"] == 0 and j["tool"] != i["tool"]
                for j in invs):
            why.append("superseded_route")
        if complete_at is not None and i["seq"] > complete_at:
            why.append("post_coverage")
        if why:
            reasons.append({"seq": i["seq"], "tool": i["tool"], "why": why})
    total = len(invs)
    return {"count": len(reasons), "total": total,
            "ratio": (len(reasons) / total) if total else 0.0,
            "reasons": reasons}


def score(manifest: dict | Path, invocations: list[dict], *,
          verdict: str | None = None, variant: str = UNBLOCKED,
          arm: str = "unknown") -> dict:
    """One score doc (kunglao-eval-tf-scores/1) over one trace."""
    m = _resolve(manifest)
    invs = [dict(i, seq=int(i["seq"])) for i in
            sorted(invocations, key=lambda i: int(i["seq"]))]
    roles_covered = _coverage(m, invs)
    required = set((m.get("minimum_required_set") or {}).keys())
    if verdict is None:
        solve = {"verdict": None, "status": "unknown"}
    else:
        solve = {"verdict": str(verdict),
                 "status": "solved" if str(verdict) == "PASS" else "failed"}
    return {
        "schema": SCHEMA_SCORES,
        "task_id": m["task_id"],
        "family": m.get("family"),
        "variant": variant,
        "arm": arm,
        "invocations": invs,
        "roles_covered": roles_covered,
        "coverage_ok": set(roles_covered) >= required,
        "waste": _waste(m, invs),
        "bypass_detected": any(i["bypass"] for i in invs),
        "route": list(dict.fromkeys(
            i["tool"] for i in invs if i["exit"] == 0)),
        "solve": solve,
    }


def aggregate(docs: list[dict]) -> dict:
    """F1/F2 per unit over a fixed set of score docs: classes per verdict
    class, f2 = blocked_rate / unblocked_rate (0.0 on a zero unblocked
    denominator), f2_reroute excludes bypass solves from the numerator."""
    units: dict[str, dict] = {}
    for doc in docs:
        u = units.setdefault(doc["task_id"], {
            "schema": SCHEMA_AGG, "task_id": doc["task_id"],
            "classes": {c: 0 for c in _CLASSES},
            "runs_unblocked": 0, "runs_blocked": 0,
        })
        blocked = doc.get("variant", UNBLOCKED) != UNBLOCKED
        verdict = (doc.get("solve") or {}).get("verdict")
        if blocked:
            u["runs_blocked"] += 1
        else:
            u["runs_unblocked"] += 1
        if verdict == "PASS":
            if blocked and doc.get("bypass_detected"):
                u["classes"]["bypass-solved"] += 1
            elif blocked:
                u["classes"]["blocked-solved"] += 1
            else:
                u["classes"]["solved"] += 1
        elif verdict == "FAIL":
            u["classes"]["blocked-failed" if blocked else "failed"] += 1
    for task_id, u in units.items():
        blocked_rate = (u["classes"]["blocked-solved"]
                        + u["classes"]["bypass-solved"])
        reroute_rate = u["classes"]["blocked-solved"]
        ub = u["classes"]["solved"]

        def _rate(n: int, d: int) -> float:
            return (n / d) if d else 0.0

        unblocked_rate = _rate(ub, u["runs_unblocked"])
        u["f2"] = (_rate(blocked_rate, u["runs_blocked"]) / unblocked_rate
                   if unblocked_rate > 0 else 0.0)
        u["f2_reroute"] = (_rate(reroute_rate, u["runs_blocked"])
                           / unblocked_rate if unblocked_rate > 0 else 0.0)
        for key in ("runs_unblocked", "runs_blocked"):
            del u[key]
    return {"schema": SCHEMA_AGG, "units": units}


# -------------------------------------------------------------- CLI face
def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser(
        prog="eval_tf_graders.py",
        description="TF F1-F4 graders over session transcripts / ledgers")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_score = sub.add_parser("score", help="score one trace artifact")
    p_score.add_argument("--manifest", required=True)
    p_score.add_argument("--artifact", required=True)
    p_score.add_argument("--source", choices=("transcript", "ledger"),
                         required=True)
    p_score.add_argument("--verdict", default=None)
    p_score.add_argument("--variant", default=UNBLOCKED)
    p_score.add_argument("--arm", default="unknown")
    p_score.add_argument("--out", default=None)
    p_agg = sub.add_parser("aggregate", help="F2 over a scores dir")
    p_agg.add_argument("--scores-dir", required=True)
    p_agg.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    if args.cmd == "score":
        m = load_manifest(Path(args.manifest))
        extract = extract_transcript if args.source == "transcript" \
            else extract_ledger
        doc = score(m, extract(Path(args.artifact), m),
                    verdict=args.verdict, variant=args.variant, arm=args.arm)
        text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0
    docs = [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(Path(args.scores_dir).glob("*.json"))]
    agg = aggregate(docs)
    text = json.dumps(agg, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

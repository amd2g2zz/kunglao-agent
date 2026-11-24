#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chain_acceptance.py — the chain-state reader (issue 1079): closeout
completion as a reconciled fact (devkit process gauge, NOT a shipped-product
tool).

The chain-state record (~/.claude/kunglao-chains/<chain-id>/chain.json,
spec §6) makes the closeout segment's completion signal machine-checkable:
`status=accepted` on the closeout row is only valid with a `merge_sha`
(an ancestor of origin/dev) or an explicit `abandoned` reason, rows may not
contradict themselves (pending-with-owner, working/handed_off without
owner or updated_at), and a working row ageing past the stated threshold is
reported — the stagnation signal the carrier exists for.

Trigger discipline — this tool only runs WHERE THE RECORD IS ALREADY READ
OR WRITTEN:
  - the main agent reads chain state when starting the next chain;
  - each segment reads chain state at acceptance (接).
No always-on mechanism, no idle polling. That is the difference from the
withdrawn "process gate" (a pre-commit hook never fires when work stops —
no commit, no hook; issue 1079 scope note). Process records stay OUTSIDE
the repository; this tool changes the shape's reader, not the record
location.

Mechanization history — spec §6 originally said "先用普通 JSON 读写，不预先建
校验器：形状被第一条链真实用过之后，再决定要不要机械化". The shape has now
been used by five chains (N0/S1/S2/S13/S17) with two real distortions
(issue 1079): S2 (issue 1042) recorded both segments accepted while its PR
stayed OPEN (record ahead of fact); S13 (issue 1005) recorded its closeout
row pending while it had been working for about two hours (record behind
fact). The three regression fixtures in
tests/test_devkit_chain_acceptance_1079.py re-enact the three shapes.

Schema gate: `dev-chain/2` = mechanized shape (closeout-evidence rules
apply). `dev-chain/1` = legacy tolerance BOUNDED BY CHAIN ID: only the
five pre-mechanization chains (N0/S1/S2/S13/S17) read clean without
closeout evidence — the rule did not exist when they were written, and
flagging real history is the false positive this tool must never produce.
A chain OUTSIDE the whitelist claiming `dev-chain/1` is an escape, not a
trust decision: the next chain templates its record from the previous one,
and the existing v1 records would be copied unchanged, silently dropping
the closeout evidence rules (the exact failure class of issue 1079).
Non-whitelisted v1, unknown schema, and missing schema all = REFUSE (the
reader cannot vouch for a shape it does not know; upgrade the reader).

Exit codes: 0 = clean; 1 = REFUSE (invalid record); 2 = unverifiable
(tool/env: missing file, non-JSON, origin/dev unresolvable — the check did
NOT run, so nothing is vouched); 3 = STAGNANT (consistent record but a
working row crossed the stated stale threshold).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

RC_PASS = 0
RC_REFUSE = 1
RC_UNVERIFIABLE = 2
RC_STAGNANT = 3

VALID_STATUSES = ("pending", "working", "handed_off", "accepted")
VALID_KINDS = ("develop", "closeout")
SCHEMA_LEGACY = "dev-chain/1"
SCHEMA_MECHANIZED = "dev-chain/2"
STALE_DEFAULT_HOURS = 12
GH_TIMEOUT_S = 10

# The only chains whose records predate the mechanized shape. dev-chain/1
# is bounded to them — a NEW chain claiming v1 would silently skip the
# closeout evidence rules (the next chain templates its record from the
# previous one, and S13/S17 are v1), so the tolerance must be explicit.
LEGACY_CHAIN_IDS = frozenset({"N0", "S1", "S2", "S13", "S17"})

_GITHUB_URL_RE = re.compile(r"github\.com[/:]([^/]+)/([^/.]+)(?:\.git)?$")


class UnverifiableError(RuntimeError):
    """A required check could not run (missing file, bad JSON, no origin/dev)."""


@dataclass(frozen=True)
class Finding:
    severity: str  # INFO / REFUSE / STAGNANT
    text: str

    def __str__(self) -> str:
        return f"{self.severity:8s} {self.text}"


def _parse_ts(value: object) -> datetime | None:
    """Aware ISO8601 timestamp, or None (missing / naive / garbage).

    Naive timestamps are rejected: an age computed against a naive value
    would crash on subtraction with an aware now, and timezone-less claims
    are ambiguous by construction.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _fmt_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_owner_and_updated_at(chain: str, seg: dict, seg_id: str,
                                   status: str, stale_hours: int,
                                   findings: list[Finding]) -> None:
    """owner↔status consistency and the working-row stagnation signal."""
    owner = seg.get("owner")
    if status == "pending" and owner is not None:
        findings.append(Finding(
            "REFUSE",
            f"{chain} seg[{seg_id}]: pending row has owner {owner!r} — "
            "owner↔status contradiction (the record lags the fact if "
            "work is in flight)"))
        return
    if status not in ("working", "handed_off"):
        return
    if not owner:
        findings.append(Finding(
            "REFUSE",
            f"{chain} seg[{seg_id}]: {status} row without an owner — "
            "who is doing the work?"))
    ts = _parse_ts(seg.get("updated_at"))
    if ts is None:
        findings.append(Finding(
            "REFUSE",
            f"{chain} seg[{seg_id}]: {status} row without a valid "
            "updated_at (required; timezone-qualified)"))
        return
    if status == "working":
        age = datetime.now(timezone.utc) - ts
        if age > timedelta(hours=stale_hours):
            findings.append(Finding(
                "STAGNANT",
                f"{chain} seg[{seg_id}]: still working since "
                f"{_fmt_ts(ts)}, older than the {stale_hours}h "
                "threshold — the chain may be stalled"))


def _validate_closeout_evidence(chain: str, seg_id: str, seg: dict,
                                findings: list[Finding],
                                ancestry: list[tuple[str, str]]) -> None:
    """Mechanized closeout rule: merge_sha (ancestry verified by the caller
    against origin/dev) or an explicit abandoned reason."""
    merge_sha = seg.get("merge_sha")
    abandoned = seg.get("abandoned")
    if merge_sha and abandoned:
        findings.append(Finding(
            "REFUSE",
            f"{chain} seg[{seg_id}]: closeout carries both "
            "merge_sha and abandoned — contradictory evidence"))
    elif not merge_sha and not abandoned:
        findings.append(Finding(
            "REFUSE",
            f"{chain} seg[{seg_id}]: closeout accepted without "
            "merge_sha (or an explicit abandoned reason) — "
            "acceptance is a claim, not a reconciled fact"))
    elif merge_sha:
        ancestry.append((seg_id, merge_sha))


def validate(record: dict, *, stale_hours: int = STALE_DEFAULT_HOURS
             ) -> tuple[list[Finding], list[tuple[str, str]]]:
    """Pure shape validation of one chain-state record.

    Returns (findings, ancestry_requests): ancestry_requests is a list of
    (segment_id, merge_sha) pairs the caller must verify against origin/dev
    (git lives in the CLI, not here). No git, no network.
    """
    findings: list[Finding] = []
    ancestry: list[tuple[str, str]] = []
    chain = record.get("chain") or "<record>"

    schema = record.get("schema")
    mechanized = schema == SCHEMA_MECHANIZED
    chain_id = record.get("chain") or "<record>"
    if schema is None:
        findings.append(Finding(
            "REFUSE", f"{chain}: missing top-level 'schema' field"))
    elif schema == SCHEMA_LEGACY and chain_id not in LEGACY_CHAIN_IDS:
        findings.append(Finding(
            "REFUSE",
            f"{chain}: schema dev-chain/1 is limited to the five "
            f"pre-mechanization chains ({', '.join(sorted(LEGACY_CHAIN_IDS))}) — "
            "new records must use dev-chain/2 (closeout accepted requires "
            "merge_sha or an explicit abandoned reason)"))
    elif schema != SCHEMA_LEGACY and not mechanized:
        findings.append(Finding(
            "REFUSE",
            f"{chain}: unknown schema {schema!r} — the reader cannot vouch "
            "for this shape (upgrade devkit/chain_acceptance.py)"))
    else:
        note = ("mechanized shape: closeout acceptance requires merge_sha "
                "or an explicit abandoned reason"
                if mechanized else
                "legacy record (pre-mechanization): closeout-evidence "
                "rules not applied")
        findings.append(Finding("INFO", f"{chain}: schema {schema} — {note}"))

    segments = record.get("segments")
    if not isinstance(segments, list) or not segments:
        findings.append(Finding(
            "REFUSE", f"{chain}: 'segments' must be a non-empty list"))
        return findings, ancestry

    seen_ids: set[str] = set()
    for index, seg in enumerate(segments, start=1):
        if not isinstance(seg, dict):
            findings.append(Finding(
                "REFUSE", f"{chain}: segment #{index} is not an object"))
            continue
        seg_id = seg.get("id") or f"#{index}"
        if seg_id in seen_ids:
            findings.append(Finding(
                "REFUSE", f"{chain} seg[{seg_id}]: duplicate segment id"))
        seen_ids.add(seg_id)

        kind = seg.get("kind")
        status = seg.get("status")
        if kind not in VALID_KINDS:
            findings.append(Finding(
                "REFUSE",
                f"{chain} seg[{seg_id}]: kind {kind!r} — must be one of "
                f"{', '.join(VALID_KINDS)}"))
        if status not in VALID_STATUSES:
            findings.append(Finding(
                "REFUSE",
                f"{chain} seg[{seg_id}]: status {status!r} — must be one of "
                f"{', '.join(VALID_STATUSES)}"))
            continue

        _validate_owner_and_updated_at(
            chain, seg, seg_id, status, stale_hours, findings)
        if mechanized and kind == "closeout" and status == "accepted":
            _validate_closeout_evidence(
                chain, seg_id, seg, findings, ancestry)

    last = segments[-1]
    if isinstance(last, dict) and last.get("kind") != "closeout":
        findings.append(Finding(
            "REFUSE",
            f"{chain}: the last segment must be the closeout "
            f"(spec §6) — found kind {last.get('kind')!r}"))

    return findings, ancestry


def _resolve_dev_tip(repo: Path) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet",
         "refs/remotes/origin/dev"],
        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise UnverifiableError(
            f"origin/dev not found in {repo} — fetch it first "
            f"(git -C {repo} fetch origin dev)")
    return r.stdout.strip()


def _is_ancestor(sha: str, dev_tip: str, repo: Path) -> tuple[bool, str]:
    """(True, '') when sha is reachable from dev_tip, else (False, reason)."""
    r = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor",
         sha, dev_tip],
        capture_output=True, text=True, timeout=30)
    if r.returncode == 0:
        return True, ""
    return False, (r.stderr.strip() or "not a commit at all")


def _run_ancestry_checks(record: dict, findings: list[Finding],
                         ancestry: list[tuple[str, str]],
                         repo_arg: str | None) -> None:
    """Closeout evidence step 2: merge_sha must be an ancestor of origin/dev.

    Raises UnverifiableError when the check cannot run — an unrun check
    vouches for nothing (fail closed, exit 2).
    """
    if not ancestry:
        return
    chain = record.get("chain") or "<record>"
    if repo_arg is None:
        raise UnverifiableError(
            f"{chain}: merge_sha ancestry check needs --repo (a clone with "
            "refs/remotes/origin/dev, e.g. the main worktree)")
    repo = Path(repo_arg)
    if not repo.is_dir():
        raise UnverifiableError(f"{chain}: --repo {repo_arg} is not a directory")
    dev_tip = _resolve_dev_tip(repo)
    for seg_id, sha in ancestry:
        ok, reason = _is_ancestor(sha, dev_tip, repo)
        if not ok:
            findings.append(Finding(
                "REFUSE",
                f"{chain} seg[{seg_id}]: merge_sha {sha} is not an ancestor "
                f"of origin/dev ({dev_tip}) — {reason}"))


def _owner_repo(repo: Path) -> str | None:
    """owner/repo from the repo's remote origin URL, else None."""
    r = subprocess.run(
        ["git", "-C", str(repo), "config", "--get", "remote.origin.url"],
        capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return None
    m = _GITHUB_URL_RE.search(r.stdout.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def _pr_state_summary(record: dict, repo: Path | None) -> str:
    """Best-effort `gh pr view` enrichment; returns text, never raises."""
    branch = record.get("branch")
    if not branch:
        return "PR state unavailable (record has no branch field)"
    if repo is None:
        repo = Path.cwd()
    owner_repo = _owner_repo(repo)
    if not owner_repo:
        return "PR state unavailable (no github remote origin on --repo)"
    try:
        r = subprocess.run(
            ["gh", "pr", "view", str(branch), "-R", owner_repo,
             "--json", "state,mergedAt,url"],
            capture_output=True, text=True, timeout=GH_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return "PR state unavailable (gh lookup failed)"
    if r.returncode != 0:
        detail = (r.stderr or r.stdout).strip().splitlines()
        head = detail[0][:120] if detail else "no PR found"
        return f"PR state unavailable (gh: {head})"
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return "PR state unavailable (gh returned malformed output)"
    if data.get("state") == "MERGED":
        merged = f" merged at {data.get('mergedAt')}" if data.get("mergedAt") else " merged"
        state = f"MERGED{merged}"
    else:
        state = data.get("state") or "UNKNOWN"
    return f"PR state: {state} ({data.get('url', 'no url')})"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chain_acceptance.py",
        description=("Chain-state record reader (#1079): validates "
                     "~/.claude/kunglao-chains/<chain-id>/chain.json at the "
                     "moments the record is already read or written "
                     "(next-chain start, segment acceptance). "
                     "Exit: 0 clean / 1 REFUSE / 2 unverifiable / "
                     "3 STAGNANT."))
    sub = p.add_subparsers(dest="action", required=True)
    c = sub.add_parser("check", help="validate a chain-state record")
    c.add_argument("chain_json",
                   help="path to <chain-id>/chain.json (repo-external "
                        "process record)")
    c.add_argument("--repo", default=None,
                   help="git clone holding refs/remotes/origin/dev "
                        "(required when the record's closeout carries a "
                        "merge_sha; cwd is used for PR lookup)")
    c.add_argument("--stale-hours", type=int, default=STALE_DEFAULT_HOURS,
                   help=f"working rows older than this many hours are "
                        f"reported STAGNANT (default {STALE_DEFAULT_HOURS})")
    c.add_argument("--pr-state", action="store_true",
                   help="on REFUSE, best-effort `gh pr view` of the record's "
                        "branch to report the actual PR state (needs a "
                        "github remote origin and gh)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    chain_json = Path(args.chain_json)
    try:
        record = json.loads(chain_json.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"chain_acceptance: no such record: {chain_json}",
              file=sys.stderr)
        return RC_UNVERIFIABLE
    except json.JSONDecodeError as exc:
        print(f"chain_acceptance: {chain_json} is not valid JSON: {exc}",
              file=sys.stderr)
        return RC_UNVERIFIABLE
    if not isinstance(record, dict):
        print(f"chain_acceptance: {chain_json} is not a JSON object",
              file=sys.stderr)
        return RC_UNVERIFIABLE

    chain = record.get("chain") or Path(chain_json).stem
    findings, ancestry = validate(record, stale_hours=args.stale_hours)
    try:
        _run_ancestry_checks(record, findings, ancestry, args.repo)
    except UnverifiableError as exc:
        print(f"chain_acceptance: {exc}", file=sys.stderr)
        return RC_UNVERIFIABLE

    for finding in findings:
        print(finding)

    refuses = [f for f in findings if f.severity == "REFUSE"]
    stagnants = [f for f in findings if f.severity == "STAGNANT"]
    if refuses:
        if args.pr_state:
            print(f"PRSTATE {chain}: {_pr_state_summary(record, args.repo)}")
        print(f"VERDICT {chain}: REFUSE ({len(refuses)} violation(s)) — "
              "record invalid")
        return RC_REFUSE
    if stagnants:
        print(f"VERDICT {chain}: STAGNANT ({len(stagnants)} row(s)) — "
              "record consistent but a working row crossed the stale "
              "threshold")
        return RC_STAGNANT
    print(f"VERDICT {chain}: PASS — record consistent")
    return RC_PASS


if __name__ == "__main__":
    sys.exit(main())
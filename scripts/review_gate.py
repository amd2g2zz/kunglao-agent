#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""review_gate.py — 1-reviewer all-PASS commit gate (maker-checker mechanical).

Enforces the /goal contract: NO commit may land unless >=1 independent
subagent PASS'd the exact staged content (was >=3 before the 2026-08-14 user
decision to use a single review subagent per PR). Trust boundary: the key
file is orchestrator-held by convention; subagents are instructed never to
commit and the repo pre-commit hook is the mechanical backstop. Local hooks
are bypassable by a determined local actor (git commit --no-verify /
commit-tree / update-ref) — this gate makes honest-workflow compliance
mechanical and forging require deliberate key exfiltration.

Key file path (PINNED — env overrides rejected; an attacker-controllable
env var would let a subagent self-mint and self-approve):
~/.claude/kunglao-review.key

Usage:
  python scripts/review_gate.py key-init <keyfile>            # orchestrator: create session key
  python scripts/review_gate.py mint <repo> <keyfile> <branch> <evidence-glob> <id>...
      # orchestrator: validate evidence (>=1 ids, exactly one PASS file per id,
      # each diff_sha256 == staged diff) -> write .review-gate/<branch>.json
      # HMAC-signed with the key. Exit 0 minted / 2 rejected.
  python scripts/review_gate.py check <repo> <outfile> <branch> [<keyfile>]
      # pre-commit hook: exit 0 pass / 1 invalid-or-missing / 2 stale-diff.
      # Validates branch, >=1 distinct whitelisted reviewer, HMAC signature,
      # and diff_sha256 == current staged diff.
"""
import glob
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import time

AGENT_PREFIXES = ("t4-", "t5-", "t6-", "kunglao-", "r1-", "r2-", "r3-", "reviewer-")


def staged_diff_sha(repo):
    out = subprocess.run(
        ["git", "-C", repo, "diff", "--cached", "--binary"],
        capture_output=True, check=True,
    ).stdout
    return hashlib.sha256(out).hexdigest()


def parse_frontmatter(text):
    fm = {}
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip().strip('"')
    return fm


def sign(key, branch, diff, reviewers, ts):
    payload = "\0".join([branch, diff, ",".join(sorted(reviewers)), str(ts)])
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def default_keyfile():
    # TESTING/DEBUG ONLY — the production hook passes an explicit absolute
    # keyfile arg so `~` is never resolved from USERPROFILE/HOME (which a
    # subagent could override).
    return os.path.expanduser("~/.claude/kunglao-review.key")


def main():
    cmd = sys.argv[1]
    if cmd == "key-init":
        keyfile = sys.argv[2]
        with open(keyfile, "w") as f:
            f.write(secrets.token_bytes(32).hex())
        os.chmod(keyfile, 0o600)
        print(f"key written: {keyfile} (mode 0600)")
        return 0

    repo = sys.argv[2]
    if cmd == "mint":
        keyfile, branch, evglob = sys.argv[3], sys.argv[4], sys.argv[5]
        ids = sys.argv[6:]
        if len(ids) < 1 or len(set(ids)) != len(ids):
            print(f"mint FAIL: need >=1 distinct reviewer ids as args, got {ids}")
            return 2
        key = open(keyfile, "rb").read().strip()
        if len(key) < 32:
            print(f"mint FAIL: key too short ({len(key)} bytes, need >=32) — empty or truncated key")
            return 2
        if os.path.realpath(keyfile) != os.path.realpath(default_keyfile()):
            print(f"WARNING: keyfile {keyfile} != pinned default {default_keyfile()} — check will fail")
        diff = staged_diff_sha(repo)
        by_id, notes, seen, dup_ids = {}, {}, set(), []
        for p in sorted(glob.glob(evglob)):
            try:
                fm = parse_frontmatter(open(p, encoding="utf-8").read())
            except Exception as exc:
                notes[os.path.basename(p)] = f"unparsable: {exc}"
                continue
            rid, verdict, dsha = (
                fm.get("reviewer_id", ""), fm.get("verdict", ""), fm.get("diff_sha256", ""),
            )
            if rid in ids:
                if rid in seen:
                    dup_ids.append(rid)
                    notes[os.path.basename(p)] = f"duplicate evidence for {rid}"
                    continue
                seen.add(rid)
                by_id[rid] = (p, verdict, dsha)
            else:
                notes[os.path.basename(p)] = f"unregistered reviewer_id: {rid or '<none>'}"
        missing = [i for i in ids if i not in by_id]
        bad = [
            f"{rid}: verdict={v} diff_match={d == diff}"
            for rid, (p, v, d) in by_id.items() if v != "PASS" or d != diff
        ]
        if missing or bad or dup_ids:
            print(f"mint FAIL: missing={missing} bad={bad} duplicates={dup_ids}")
            for k, v in notes.items():
                print(f"  {k}: {v}")
            return 2
        reviewers = sorted(ids)
        ts = int(time.time())
        evidence = {
            "branch": branch,
            "diff_sha256": diff,
            "reviewers": reviewers,
            "minted_ts": ts,
            "hmac": sign(key, branch, diff, reviewers, ts),
        }
        out = os.path.join(repo, ".review-gate", branch.replace("/", "-") + ".json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w") as f:
            json.dump(evidence, f, indent=2)
        print(f"mint OK: {out} ({len(reviewers)} reviewers)")
        return 0

    if cmd == "check":
        outfile, branch = sys.argv[3], sys.argv[4]
        keyfile = sys.argv[5] if len(sys.argv) > 5 else default_keyfile()
        if not os.path.exists(outfile):
            print("REVIEW GATE BLOCKED: no evidence file")
            return 1
        ev = json.load(open(outfile))
        if ev.get("branch") != branch:
            print("REVIEW GATE BLOCKED: branch mismatch")
            return 1
        revs = ev.get("reviewers", [])
        if (
            len(revs) < 1
            or len(set(revs)) != len(revs)
            or not all(r.startswith(AGENT_PREFIXES) for r in revs)
        ):
            print("REVIEW GATE BLOCKED: reviewers invalid (need >=1 distinct whitelisted)")
            return 1
        if ev.get("diff_sha256") != staged_diff_sha(repo):
            print("REVIEW GATE BLOCKED: staged diff changed since mint (stale)")
            return 2
        if not os.path.exists(keyfile):
            print("REVIEW GATE BLOCKED: key file missing; orchestrator must mint")
            return 1
        key = open(keyfile, "rb").read().strip()
        if len(key) < 32:
            print("REVIEW GATE BLOCKED: key too short — empty or truncated key")
            return 1
        expect = sign(key, ev.get("branch"), ev.get("diff_sha256"), sorted(revs), ev.get("minted_ts"))
        if not hmac.compare_digest(ev.get("hmac", ""), expect):
            print("REVIEW GATE BLOCKED: HMAC invalid (forged evidence?)")
            return 1
        return 0

    print(f"unknown command: {cmd}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

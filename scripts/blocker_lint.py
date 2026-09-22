#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""blocker_lint.py — blocker schema v2 lint + env-attribution evidence gate (issue 340).

The mechanical enforcement for the layer-diagnosis doctrine at the exact write
point where misattribution is born (audit points E1/E6): a blocker is a
premise other agents will inherit as ground truth, so the write carries a
schema — observed bytes, an attributed diagnosis, differential probe
evidence for any environment-capability verdict, and an expiry.

Schema v2 (templates/state/blocker.md, mandatory fields):
    observed        exact command + verbatim error bytes
    attributed      the diagnosis (the LAYER, never a "dead" verdict)
    probe_evidence  differential probe output justifying an environment-
                    capability attribution (e.g. `su -c id` stdout). The
                    field is mandatory non-empty ONLY when the text makes
                    an env-capability attribution; error text quoted back
                    as "evidence" is rejected too (never sufficient).
    expires         tick count (int > 0) or ISO timestamp

No-backcompat ruling (owner, 2026-09-01): legacy-shape blockers are
REJECTED on write — no compat shims. Files already on disk are the
write_gate's concern only when touched; the expiry sweep (premise_gate)
skips them rather than silently migrating them.

Enforcement point: hooks/write_guard.py adjudicates every Write/Edit
post-image of a blockers/*.md carrier through lint_blocker_text. This
module is pure (no IO beyond the text it is handed) so the same lint can
run in the gate, in tests, and in audits.

CLI: blocker_lint.py <file.md> [...]
Exit 0 = clean (or no files), 1 = violations, 2 = usage error.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# The env-capability attribution pattern set (contract: "build a small
# pattern set with tests"). A match means the text asserts an environment
# capability verdict — the class of claim that misdiagnosed invocation
# errors love ("no root", "frida unavailable"). Pinned by
# tests/test_blocker_evidence_gate_340.py.
# ---------------------------------------------------------------------------
_ENV_PATTERNS = (
    r"no root",
    r"not rooted",
    r"unrooted",
    r"unavailable",
    r"not available",
    r"not supported",
    r"unsupported",
    r"cannot (?:be )?use\w*",
    r"can'?t use",
    r"unable to use",
    r"unusable",
    r"not usable",
    r"unreachable",
    r"not installed",
    r"permission denied",
    r"no permission",
    r"access denied",
)
ENV_ATTRIBUTION_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in _ENV_PATTERNS)

# A probe_evidence value that itself matches an env pattern is suspect: it
# is probably the error text quoted back (the exact non-evidence the gate
# exists to catch). It passes only when it also carries a probe-invocation
# marker — an actual command/output shape (differential probe bytes).
PROBE_MARKERS = (
    "su -c", "su 0", "uid=", "getprop", "uname", "which ", "adb ", "adb:",
    "frida-server", "frida ", "ping ", "vmrun", "ssh ", "docker ", "$ ",
    "cmd:", "rc=", "exit=", "->",
)

V2_REQUIRED_FIELDS = ("observed", "attributed", "probe_evidence", "expires")


_WS_RUN = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Lowercase + collapse whitespace runs to single spaces (review r1,
    the review finding: `cannot  be used` / tab / newline variants must not defeat the
    pattern set — every phrase match and probe-marker search runs on the
    normalized text)."""
    return _WS_RUN.sub(" ", (text or "").lower())


def match_env_attribution(text: str) -> list[str]:
    """Pattern source strings matched in `text` (deduped, order kept).
    Matching runs on the whitespace-normalized text — see _normalize."""
    hits: list[str] = []
    low = _normalize(text)
    for pat in ENV_ATTRIBUTION_PATTERNS:
        if pat.search(low) and pat.pattern not in hits:
            hits.append(pat.pattern)
    return hits


def _is_error_text_evidence(probe_evidence: str) -> bool:
    """True when probe_evidence matches an env pattern but carries no
    probe-invocation marker — i.e. it is the failing error text itself,
    not a differential probe output."""
    low = _normalize(probe_evidence)
    if not match_env_attribution(low):
        return False
    return not any(marker in low for marker in PROBE_MARKERS)


def parse_frontmatter(text: str) -> tuple[dict | None, str]:
    """(frontmatter mapping | None, body). None = missing/unparseable."""
    m = re.match(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", text or "", re.DOTALL)
    if not m:
        return None, text or ""
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None, m.group(2)
    return (meta if isinstance(meta, dict) else None), m.group(2)


def parse_expires(value) -> "int | datetime | None":
    """`expires` accepts a tick count (int > 0) or an ISO timestamp.
    Anything else is None (the lint reports it; the sweep applies its
    configurable default window)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value  # YAML parses an unquoted ISO timestamp for us
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer():
        return int(value) if value > 0 else None
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            n = int(s)
            return n if n > 0 else None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def lint_blocker_text(text: str) -> list[str]:
    """Violations of the v2 blocker schema for one post-image. [] = clean.

    Ruling recorded for review (scope A4): the four v2 fields are
    mandatory on EVERY new blocker write — B1a/B2/orphan blockers also
    observe something and also carry a clock — while `probe_evidence` is
    additionally required to be NON-EMPTY exactly when the text makes an
    environment-capability attribution."""
    meta, _body = parse_frontmatter(text)
    if meta is None:
        return [
            "schema v2 required (no-backcompat ruling 2026-09-01): YAML "
            "frontmatter missing or unparseable — legacy-shape blockers are "
            "rejected on write; rewrite from templates/state/blocker.md with "
            "observed/attributed/probe_evidence/expires (issue 340)"]
    violations: list[str] = []
    for field in ("observed", "attributed"):
        if field not in meta:
            violations.append(
                f"v2 field `{field}` missing — mandatory (schema v2)")
        elif not str(meta.get(field) or "").strip():
            violations.append(
                f"v2 field `{field}` empty — mandatory and non-empty "
                "(exact command + stderr bytes / layer diagnosis)")
    if "probe_evidence" not in meta:
        violations.append(
            "v2 field `probe_evidence` missing — mandatory (schema v2)")
    phrases = match_env_attribution(text)
    pe_text = str(meta.get("probe_evidence") or "").strip()
    if phrases and not pe_text:
        violations.append(
            "environment-capability attribution ("
            + ", ".join(phrases)
            + ") without `probe_evidence` — error text alone is never "
            "sufficient evidence; paste the differential probe "
            "output that justifies the attribution (e.g. `su -c id` stdout)")
    elif phrases and _is_error_text_evidence(pe_text):
        violations.append(
            "`probe_evidence` carries only the error text back — a real "
            "differential probe output is required (command + output bytes, "
            "issue 340); error text alone is never sufficient evidence")
    if "expires" not in meta:
        violations.append(
            "v2 field `expires` missing — mandatory (tick count or ISO "
            "timestamp, issue 340)")
    elif parse_expires(meta.get("expires")) is None:
        violations.append(
            "`expires` unparseable — use a tick count (int > 0) or an ISO "
            "timestamp")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="blocker_lint.py",
        description="blocker schema v2 lint + env-attribution evidence "
                    "gate); the checker behind hooks/write_guard.py")
    parser.add_argument("files", nargs="+", help="blocker .md files")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    bad = 0
    for raw in args.files:
        p = Path(raw)
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"{p.name}: unreadable ({exc})", file=sys.stderr)
            bad += 1
            continue
        for i, msg in enumerate(lint_blocker_text(text), 1):
            print(f"{p.name}: violation[{i}] {msg}", file=sys.stderr)
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())

"""Frontmatter schema validation for kunglao-agent memory entries.

Reads a markdown file, parses the YAML frontmatter, validates against the
schema in `references/memory-protocol.md`. Returns (ok, errors).

Usage:
  python memory_schema.py <path-to-md-file>
Exit 0 if ok, 1 if errors.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REQUIRED_TOP = {"name", "description"}
REQUIRED_META = {"node_type", "type", "originSessionId", "modified"}
ALLOWED_TYPES_STAGING = {"feedback", "success", "failure", "discovery"}
ALLOWED_TYPES_LONGTERM = {"feedback", "success", "rule", "pattern"}
ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _modified_to_str(mod) -> str:
    """Accept either a string (raw YAML) or a datetime/date (auto-parsed by PyYAML).
    Return the canonical ISO-8601 UTC string with trailing Z."""
    import datetime as _dt
    if isinstance(mod, str):
        return mod
    if isinstance(mod, _dt.datetime):
        if mod.tzinfo is None:
            mod = mod.replace(tzinfo=_dt.timezone.utc)
        return mod.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(mod, _dt.date):
        return mod.strftime("%Y-%m-%dT00:00:00Z")
    return str(mod)


def extract_frontmatter(text: str) -> tuple:
    """Return (frontmatter_dict, body). Frontmatter is the YAML between --- fences."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm_text = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as e:
        return {"_parse_error": str(e)}, body
    return fm, body


def validate(path: Path, tier: str = "staging") -> tuple:
    """Validate a memory entry file. tier = 'staging' or 'longterm'."""
    errors: list = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return False, [f"read failed: {e}"]

    fm, body = extract_frontmatter(text)
    if "_parse_error" in fm:
        return False, [f"YAML parse error: {fm['_parse_error']}"]

    for k in REQUIRED_TOP:
        if k not in fm:
            errors.append(f"missing top-level field: {k}")

    meta = fm.get("metadata") or {}
    if not isinstance(meta, dict):
        errors.append("metadata must be a mapping")
        meta = {}

    for k in REQUIRED_META:
        if k not in meta:
            errors.append(f"missing metadata.{k}")

    allowed = ALLOWED_TYPES_STAGING if tier == "staging" else ALLOWED_TYPES_LONGTERM
    t = meta.get("type")
    if t and t not in allowed:
        errors.append(f"metadata.type={t!r} not in {sorted(allowed)} for tier={tier}")

    mod = meta.get("modified")
    if mod:
        mod_str = _modified_to_str(mod)
        if not ISO_UTC_RE.match(mod_str):
            errors.append(f"metadata.modified={mod!r} is not ISO-8601 UTC (YYYY-MM-DDTHH:MM:SSZ)")

    if tier == "longterm":
        if not meta.get("cross_project"):
            errors.append("longterm entries must set metadata.cross_project: true")
        for k in ("claim_id", "worker_id"):
            if k in meta:
                errors.append(f"longterm entries must strip metadata.{k} (got {meta[k]!r})")
        for required_section in ("## Rule", "## Examples"):
            if required_section not in body:
                errors.append(f"longterm body must contain section '{required_section}'")
    else:
        for required_section in ("## Symptom", "## Repro", "## Fix applied"):
            if required_section not in body:
                errors.append(f"staging body must contain section '{required_section}'")

    return (len(errors) == 0), errors


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python memory_schema.py <md-file> [tier=staging|longterm]")
        return 1
    path = Path(sys.argv[1])
    tier = sys.argv[2] if len(sys.argv) > 2 else "staging"
    if not path.exists():
        print(f"FAIL: {path} does not exist")
        return 1
    ok, errors = validate(path, tier)
    if ok:
        print(f"OK: {path.name} (tier={tier})")
        return 0
    print(f"FAIL: {path.name} (tier={tier})")
    for e in errors:
        print(f"  - {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
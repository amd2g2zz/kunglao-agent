"""disasm_constant_check — cross-layer byte-exact checker (#50, a2b5e25c problem 1).

Parses fact / report code-listing `field=value` assertions (the #49 convention)
with their line VA anchors, resolves VA → file offset via pefile sections
(file offset = RVA − section delta), disassembles the site with capstone, and
compares byte-exact:

- fact→disasm: numeric claims vs instruction immediate; scaled `X*K` claims
  require a mul/imul with immediate K at the site; variable claims SKIP
  (not mechanically decidable without dataflow).
- report→fact (cross-layer): listing assertions compared by field name against
  the reference fact's expected value map — numeric byte-exact, scaled exact,
  variable name-equal, numeric-vs-variable → mismatch.
- report→disasm: VA-anchored listing assertions run the same disasm rules.

CLI: --report <listing> --reference <fact> --binary <pe>  (report mode)
     --fact <fact> --binary <pe>                          (fact mode)
     --out <json>      write the JSON result to a file (default: stdout)

The verify-note wire (kunglao_verify.verify, binary_path kwarg) runs fact mode
as a post-gate via the imported `check_fact_disasm` — this module's import
surface must stay stable (issue #284); the report pipeline invokes report mode
pre-handoff.

#277 CLI contract: --json is the default machine output; --out redirects it to
a file. Exit codes: 0 = assertions match, 1 = negative outcome (mismatch or
unmapped VA), 2 = operational error (missing/unreadable input file or invalid
mode selection). PE-load failures are returned inside the JSON result as
ok=false (exit 1), matching the fail-closed verify wire.

Core PE/capstone helpers (va_to_offset / capstone_for / disasm_at / load_pe)
live in tools/lib_disasm.py (issue #284 extraction); they are re-exported here
so existing imports keep working.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pefile  # type annotation for _load() return

from lib_disasm import (  # noqa: E402  (shared PE/capstone helpers, #284)
    capstone_for as _capstone_for,
    disasm_at as _disasm_at,
    load_pe as _load_pe,
    va_to_offset,
)

_FIELD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_VA_PREFIX = re.compile(r"^\s*(?:@0x(?P<a>[0-9a-fA-F]+)\s+|0x(?P<b>[0-9a-fA-F]+)\s*:\s*)")


# ---- parsing (D1) ----

def parse_assertions(text: str, require_va: bool = False) -> list[dict]:
    """Extract `field=value` assertions from text. A line may carry a VA anchor
    (`0x<hex>:` or `@0x<hex> `). Lines whose left-of-= is not a valid field
    name (frontmatter keys, prose) are skipped. require_va drops un-anchored
    assertions (fact-mode contract)."""
    out: list[dict] = []
    if not text:
        return out
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        m = _VA_PREFIX.match(line)
        va: int | None = None
        rest = line
        if m:
            hx = m.group("a") or m.group("b")
            if hx:
                va = int(hx, 16)
            rest = line[m.end():]
        field, sep, value = rest.partition("=")
        if not sep:
            continue
        field = field.strip().rstrip(":").strip()
        if not field or not _FIELD_RE.fullmatch(field):
            continue
        value = value.strip()
        if not value:
            continue
        if require_va and va is None:
            continue
        out.append({"field": field, "value": value, "va": va, "line_no": line_no})
    return out


def _value_kind(v: str) -> str:
    v = v.strip()
    if re.fullmatch(r"0x[0-9a-fA-F]+", v):
        return "hex"
    if re.fullmatch(r"-?\d+", v):
        return "decimal"
    if "*" in v:
        return "scaled"
    return "variable"


def _int(v: str) -> int:
    v = v.strip()
    return int(v, 16) if v.lower().startswith("0x") else int(v, 10)


def _scale_of(v: str) -> int | None:
    m = re.search(r"\*\s*(-?\d+)", v)
    return int(m.group(1), 10) if m else None


# ---- PE / disasm (D2) ----
# va_to_offset / capstone_for / disasm_at / load_pe moved to lib_disasm.py
# (issue #284 extraction) and re-exported above for backward compat.


# ---- rules (D3, D4) ----

def check_assertion_disasm(assertion: dict, insns: list[dict]) -> tuple[bool | None, str]:
    """(ok, reason). ok=None → SKIP (variable claim, unverifiable mechanically)."""
    kind = _value_kind(assertion["value"])
    if kind == "variable":
        return (None, "SKIP: variable-name claim (needs dataflow; caught cross-layer if at all)")
    actuals = [hex(i["imm"]) for i in insns if i["imm"] is not None]
    actual_str = ", ".join(actuals) if actuals else "no immediate"
    if kind == "scaled":
        k = _scale_of(assertion["value"])
        if k is not None and any(i["mnemonic"] in ("mul", "imul") and i["imm"] == k for i in insns):
            return (True, "")
        return (False, f"claim scale {k} but disasm has no multiply with {k} "
                       f"(site mnemonics/immediates: {actual_str})")
    target = _int(assertion["value"])
    if any(i["imm"] == target for i in insns):
        return (True, "")
    return (False, f"claim constant {hex(target)} but disasm immediate(s): {actual_str}")


def _cross_compare(claim: str, expected: str) -> tuple[bool, str]:
    """Report-listing value vs fact expected value (D4 cross-layer)."""
    kc, ke = _value_kind(claim), _value_kind(expected)
    if kc == "variable" and ke == "variable":
        return (True, "") if claim == expected else (
            False, f"variable name mismatch: claim {claim!r} vs fact {expected!r}")
    if kc in ("hex", "decimal") and ke in ("hex", "decimal"):
        return (True, "") if _int(claim) == _int(expected) else (
            False, f"numeric mismatch: claim {claim} ({hex(_int(claim))}) "
            f"vs fact {expected} ({hex(_int(expected))})")
    if kc == "scaled" and ke == "scaled":
        return (True, "") if claim == expected else (
            False, f"scaled mismatch: claim {claim!r} vs fact {expected!r}")
    return (False, f"kind mismatch: claim {claim!r} ({kc}) vs fact {expected!r} ({ke})")


def parse_expected_map(fact_text: str) -> dict[str, str]:
    """field→value from the fact's `expected:` frontmatter field plus every
    `field=value` assertion in its fenced code block (#49 reproduce lines)."""
    out: dict[str, str] = {}
    fm = re.search(r"^---\n(.*?)\n---", fact_text, re.DOTALL)
    if fm:
        m = re.search(r"^expected:\s*(.+)$", fm.group(1), re.MULTILINE)
        if m:
            for part in m.group(1).split(";"):
                f, _, v = part.strip().partition("=")
                f = f.strip().rstrip(":").strip()
                if f and v and _FIELD_RE.fullmatch(f):
                    out[f] = v.strip()
    for bm in re.finditer(r"```[a-zA-Z]*\s*\n(.*?)```", fact_text, re.DOTALL):
        for line in bm.group(1).splitlines():
            f, _, v = line.strip().partition("=")
            f = re.sub(r"^0x[0-9a-fA-F]+\s*:\s*", "", f).strip().rstrip(":").strip()
            if f and v and _FIELD_RE.fullmatch(f):
                out[f] = v.strip()
    return out


# ---- top-level checks (D5, D4) ----

def _load(binary_path: Path) -> tuple[pefile.PE, bytes] | dict:
    try:
        pe = _load_pe(binary_path)
        raw = Path(binary_path).read_bytes()
        return pe, raw
    except Exception as exc:  # pefile parse failure, missing file, etc.
        return {"ok": False, "mismatches": [], "errors": [{"reason": f"binary load failed: {exc}"}],
                "checks": 0, "skipped": []}


def check_fact_disasm(fact_text: str, binary_path: Path) -> dict:
    """D5: fact's own VA-anchored assertions vs capstone disassembly."""
    loaded = _load(binary_path)
    if isinstance(loaded, dict):
        return loaded
    pe, raw = loaded
    assertions = parse_assertions(fact_text, require_va=True)
    mismatches, errors, skipped = [], [], []
    for a in assertions:
        insns = _disasm_at(pe, raw, a["va"])
        if insns is None:
            errors.append({"field": a["field"], "va": hex(a["va"]),
                           "reason": f"VA {hex(a['va'])} not mapped by any section"})
            continue
        ok, reason = check_assertion_disasm(a, insns)
        if ok is None:
            skipped.append(a["field"])
        elif not ok:
            mismatches.append({"field": a["field"], "va": hex(a["va"]),
                               "claim": a["value"], "reason": reason})
    return {"ok": not (mismatches or errors), "mismatches": mismatches,
            "errors": errors, "checks": len(assertions) - len(skipped), "skipped": skipped}


def check_report_listing(listing_text: str, fact_text: str, binary_path: Path) -> dict:
    """D4: report listing vs fact expected (cross-layer) + disasm (VA-anchored)."""
    loaded = _load(binary_path)
    if isinstance(loaded, dict):
        return loaded
    pe, raw = loaded
    listing = parse_assertions(listing_text, require_va=False)
    expected_map = parse_expected_map(fact_text)
    mismatches, errors, skipped = [], [], []
    for a in listing:
        # cross-layer
        if a["field"] in expected_map:
            ok, reason = _cross_compare(a["value"], expected_map[a["field"]])
            if not ok:
                mismatches.append({"field": a["field"],
                                   "va": hex(a["va"]) if a["va"] else None,
                                   "claim": a["value"], "expected": expected_map[a["field"]],
                                   "reason": reason})
                continue
        else:
            skipped.append(a["field"])
        # disasm (VA-anchored only)
        if a["va"]:
            insns = _disasm_at(pe, raw, a["va"])
            if insns is None:
                errors.append({"field": a["field"], "va": hex(a["va"]),
                               "reason": f"VA {hex(a['va'])} not mapped by any section"})
                continue
            ok, reason = check_assertion_disasm(a, insns)
            if ok is False:
                mismatches.append({"field": a["field"], "va": hex(a["va"]),
                                   "claim": a["value"], "disasm": True, "reason": reason})
    return {"ok": not (mismatches or errors), "mismatches": mismatches,
            "errors": errors, "checks": len(listing), "skipped": skipped}


# ---- CLI ----

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="disasm-constant-byte-exact-checker (#50)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--fact", help="fact file (fact mode)")
    mode.add_argument("--report", help="report listing file (report mode)")
    ap.add_argument("--reference", help="reference fact file (report mode)")
    ap.add_argument("--binary", required=True, help="sample PE binary")
    ap.add_argument("--json", action="store_true", help="emit JSON (default)")
    ap.add_argument("--out", metavar="FILE",
                    help="write JSON result to FILE instead of stdout (#277)")
    args = ap.parse_args(argv)
    try:
        if args.fact:
            fact_text = Path(args.fact).read_text(encoding="utf-8", errors="replace")
            result = check_fact_disasm(fact_text, Path(args.binary))
        elif args.report:
            if not args.reference:
                ap.error("--reference is required for --report mode")
            result = check_report_listing(
                Path(args.report).read_text(encoding="utf-8", errors="replace"),
                Path(args.reference).read_text(encoding="utf-8", errors="replace"),
                Path(args.binary))
        else:
            ap.error("specify --fact or --report")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        try:
            Path(args.out).write_text(payload, encoding="utf-8")
        except OSError as exc:
            print(f"error: cannot write --out {args.out}: {exc}", file=sys.stderr)
            return 2
    else:
        print(payload)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())

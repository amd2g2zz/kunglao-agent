#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sign_candidate_verify.py — differential verification of candidate signer
functions against captured request samples.

Two subcommands:

  emit  — validate a candidates artifact and emit (a) a browser-side JS
          harness that calls each candidate with every captured sample,
          fingerprints each result, and compares against the expected
          value; and (b) a machine plan of what will run. The operator
          executes the harness in the target page context (console / CDP
          evaluate) and saves its JSON output.
  apply — merge the harness results back: a candidate is promoted to
          verified=true only when EVERY planned sample ran and matched and
          the match count clears --minimum-matches. Anything less stays
          verified=false with a per-sample reason. Fail loud on malformed
          artifacts (unknown candidates, out-of-range sample indexes).

Input: candidates JSON {"candidates": [{name, locator, samples:
  [{args: [...], expected: str}]}]}; locator = "global:<dotted.path>" |
  "expr:<js expression>". Output: harness .js + plan .json (emit);
  verified candidates JSON + stdout summary (apply). Exit 0 = applied /
  emitted; exit 2 = malformed artifacts or invalid schema.

Usage:
  python tools/web/sign_candidate_verify.py emit --candidates c.json \
      --out harness.js --plan-out plan.json
  python tools/web/sign_candidate_verify.py apply --results r.json \
      --candidates c.json --out verified.json --minimum-matches 2

Examples:
  # 1) emit the harness from recovered candidate functions
  python tools/web/sign_candidate_verify.py emit \
      --candidates artifacts/candidates.json --out harness.js

  # 2) run harness.js in the target page console, save JSON, then verify
  python tools/web/sign_candidate_verify.py apply \
      --results artifacts/results.json --candidates artifacts/candidates.json \
      --out artifacts/verified.json --minimum-matches 2
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HARNESS_TEMPLATE = r"""// sign-candidate differential harness (auto-generated)
// Runs in the TARGET PAGE context: console / CDP evaluate.
// Calls every candidate with every captured sample, fingerprints each
// result, and prints one JSON line to stdout — save it for `apply`.
"use strict";
(function () {
  var PLAN = __PLAN__;
  var out = [];

  function stable(value) {
    if (value === null || typeof value !== "object") {
      return JSON.stringify(value === undefined ? null : value) +
        (value === undefined ? "u" : "");
    }
    if (Array.isArray(value)) {
      return "[" + value.map(stable).join(",") + "]";
    }
    var keys = Object.keys(value).sort();
    return "{" + keys.map(function (k) {
      return JSON.stringify(k) + ":" + stable(value[k]);
    }).join(",") + "}";
  }

  function resolve(locator) {
    var kind = locator.slice(0, locator.indexOf(":"));
    var rest = locator.slice(locator.indexOf(":") + 1);
    if (kind === "global") {
      var parts = rest.split(".");
      var cur = window;
      for (var i = 0; i < parts.length; i++) {
        if (cur == null) return null;
        cur = cur[parts[i]];
      }
      return cur;
    }
    if (kind === "expr") {
      // Function-constructor form (never ev-al): page-global scope
      var fn = new (Function)("return (" + rest + ")");
      return fn();
    }
    return null;
  }

  PLAN.candidates.forEach(function (cand) {
    var fn = null;
    var resolveError = null;
    try {
      fn = resolve(cand.locator);
    } catch (e) {
      resolveError = String((e && e.message) || e);
    }
    cand.samples.forEach(function (sample, idx) {
      if (resolveError) {
        out.push({ candidate: cand.name, sample_index: idx, ok: false,
                   got_fingerprint: null, expected: sample.expected,
                   error: "resolve failed: " + resolveError });
        return;
      }
      if (typeof fn !== "function") {
        out.push({ candidate: cand.name, sample_index: idx, ok: false,
                   got_fingerprint: null, expected: sample.expected,
                   error: "locator did not resolve to a function" });
        return;
      }
      try {
        var result = fn.apply(null, sample.args);
        var fingerprint = stable(Promise.resolve(result) === result
          ? "[promise]" : result);
        out.push({ candidate: cand.name, sample_index: idx,
                   ok: fingerprint === sample.expected,
                   got_fingerprint: fingerprint,
                   expected: sample.expected });
      } catch (e) {
        out.push({ candidate: cand.name, sample_index: idx, ok: false,
                   got_fingerprint: null, expected: sample.expected,
                   error: String((e && e.message) || e) });
      }
    });
  });
  __OUTPUT_IMPL__
})();
"""

STRICT_OUTPUT_IMPL = """
  console.log(JSON.stringify(out));
  return JSON.stringify(out);
"""


def _fail(msg: str) -> int:
    print(f"sign_candidate_verify: {msg}", file=sys.stderr)
    return 2


def _load_json(path: Path, what: str) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(_fail(f"cannot read {what} {path}: {exc}"))
    except json.JSONDecodeError as exc:
        raise SystemExit(_fail(f"{what} {path} is not valid JSON: {exc}"))


def _validate_candidates(data: object) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(
            data.get("candidates"), list) or not data["candidates"]:
        raise SystemExit(_fail(
            "candidates artifact must be {\"candidates\": [non-empty list]}"))
    seen: set[str] = set()
    for cand in data["candidates"]:
        if not isinstance(cand, dict):
            raise SystemExit(_fail("each candidate must be an object"))
        name = cand.get("name")
        if not isinstance(name, str) or not name.strip():
            raise SystemExit(_fail("candidate missing non-empty 'name'"))
        if name in seen:
            raise SystemExit(_fail(f"duplicate candidate name {name!r}"))
        seen.add(name)
        locator = cand.get("locator", "")
        kind = locator.split(":", 1)[0]
        if kind not in ("global", "expr") or ":" not in locator \
                or len(locator) <= len(kind) + 1:
            raise SystemExit(_fail(
                f"candidate {name!r}: locator must be 'global:<dotted.path>' "
                f"or 'expr:<js expression>', got {locator!r}"))
        samples = cand.get("samples")
        if not isinstance(samples, list) or not samples:
            raise SystemExit(_fail(
                f"candidate {name!r}: 'samples' must be a non-empty list"))
        for i, sample in enumerate(samples):
            if not isinstance(sample, dict):
                raise SystemExit(_fail(
                    f"candidate {name!r}: sample {i} must be an object"))
            if not isinstance(sample.get("args"), list):
                raise SystemExit(_fail(
                    f"candidate {name!r}: sample {i} 'args' must be a list"))
            if not isinstance(sample.get("expected"), str):
                raise SystemExit(_fail(
                    f"candidate {name!r}: sample {i} 'expected' must be a "
                    "string (the captured request value)"))
    return data["candidates"]


def cmd_emit(args: argparse.Namespace) -> int:
    cands = _validate_candidates(_load_json(
        Path(args.candidates), "candidates"))
    plan = {"plan_version": 1, "candidates": [
        {"name": c["name"], "locator": c["locator"],
         "samples": [{"args": s["args"], "expected": s["expected"]}
                     for s in c["samples"]]}
        for c in cands]}
    harness = HARNESS_TEMPLATE.replace("__PLAN__", json.dumps(
        plan, ensure_ascii=False).replace("</", "<\\/"))
    harness = harness.replace("__OUTPUT_IMPL__", STRICT_OUTPUT_IMPL)
    Path(args.out).write_text(harness, encoding="utf-8")
    if args.plan_out:
        Path(args.plan_out).write_text(json.dumps(plan, ensure_ascii=False,
                                                  indent=2), encoding="utf-8")
    print(json.dumps({"emitted": str(args.out),
                      "candidates": len(cands),
                      "samples": sum(len(c["samples"]) for c in cands)}))
    return 0


def _verify_candidate(name: str, total: int,
                      seen: dict[tuple[str, int], dict],
                      minimum: int) -> tuple[list[dict], int, bool]:
    checks: list[dict] = []
    matched = 0
    for i in range(total):
        entry = seen.get((name, i))
        if entry is None:
            checks.append({"sample_index": i, "ran": False, "ok": False,
                           "reason": "sample never ran in the harness"})
            continue
        ok = bool(entry.get("ok"))
        reason = "" if ok else (
            "fingerprint mismatch: got "
            f"{entry.get('got_fingerprint')!r}, "
            f"expected {entry.get('expected')!r}")
        if entry.get("error"):
            reason = f"harness error: {entry['error']}"
        if ok:
            matched += 1
        checks.append({"sample_index": i, "ran": True, "ok": ok,
                       "reason": reason,
                       "got_fingerprint": entry.get("got_fingerprint")})
    is_verified = matched == total and matched >= minimum
    if not is_verified:
        count_note = (f"matched {matched}/{total} samples "
                      f"(minimum {minimum})")
        for check in checks:
            if check["ok"] and not check["reason"]:
                check["reason"] = f"sample matched, but not promoted: " \
                                  f"{count_note}"
    return checks, matched, is_verified


def cmd_apply(args: argparse.Namespace) -> int:
    cands = _validate_candidates(_load_json(
        Path(args.candidates), "candidates"))
    results_doc = _load_json(Path(args.results), "results")
    raw_results = (results_doc.get("results")
                   if isinstance(results_doc, dict) else results_doc)
    if not isinstance(raw_results, list):
        return _fail("results artifact must be a list or "
                     "{\"results\": [...]}")

    known = {c["name"]: len(c["samples"]) for c in cands}
    seen: dict[tuple[str, int], dict] = {}
    for entry in raw_results:
        if not isinstance(entry, dict):
            return _fail("each result entry must be an object")
        name = entry.get("candidate")
        idx = entry.get("sample_index")
        if name not in known:
            return _fail(f"result references unknown candidate {name!r}")
        if not isinstance(idx, int) or isinstance(idx, bool) \
                or not (0 <= idx < known[name]):
            return _fail(f"result for {name!r} has out-of-range "
                         f"sample_index {idx!r}")
        key = (name, idx)
        if key in seen:
            return _fail(f"duplicate result for {name}#{idx}")
        seen[key] = entry

    minimum = args.minimum_matches
    if minimum <= 0:
        return _fail("--minimum-matches must be positive")

    verified_out: list[dict] = []
    promoted = 0
    for cand in cands:
        name = cand["name"]
        total = known[name]
        checks, matched, is_verified = _verify_candidate(
            name, total, seen, minimum)
        if is_verified:
            promoted += 1
        verified_out.append({
            "name": name,
            "locator": cand["locator"],
            "samples": cand["samples"],
            "verified": is_verified,
            "matched": matched,
            "total_samples": total,
            "verification": checks,
        })

    summary = {
        "minimum_matches": minimum,
        "candidates_total": len(cands),
        "candidates_verified": promoted,
    }
    payload = dict(summary)
    payload["candidates"] = verified_out
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False,
                                         indent=2), encoding="utf-8")
    print(json.dumps(summary))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="differential verification of candidate signer/"
                    "encryptor functions against captured request samples",
        epilog=(
            "exit codes: 0 = emitted/applied; 2 = malformed artifacts or "
            "invalid schema (never a silent fallback)\n"
            "\n"
            "Examples:\n"
            "  # emit harness + plan from recovered candidates\n"
            "  python tools/web/sign_candidate_verify.py emit "
            "--candidates artifacts/candidates.json --out harness.js\n"
            "\n"
            "  # after running harness.js in the page console: verify\n"
            "  python tools/web/sign_candidate_verify.py apply "
            "--results artifacts/results.json "
            "--candidates artifacts/candidates.json "
            "--out artifacts/verified.json --minimum-matches 2"),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_emit = sub.add_parser("emit", help="emit harness + plan")
    p_emit.add_argument("--candidates", required=True,
                        help="candidates JSON artifact")
    p_emit.add_argument("--out", required=True, help="harness .js output")
    p_emit.add_argument("--plan-out", default=None,
                        help="machine plan .json output")
    p_emit.set_defaults(func=cmd_emit)

    p_apply = sub.add_parser("apply", help="verify + promote candidates")
    p_apply.add_argument("--results", required=True,
                         help="harness results JSON")
    p_apply.add_argument("--candidates", required=True,
                         help="original candidates JSON artifact")
    p_apply.add_argument("--out", required=True,
                         help="verified candidates JSON output")
    p_apply.add_argument("--minimum-matches", type=int, default=2,
                         help="matches required for promotion (default 2; "
                              "promotion additionally requires EVERY "
                              "planned sample to have run and matched)")
    p_apply.set_defaults(func=cmd_apply)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

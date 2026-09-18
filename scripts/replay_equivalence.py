#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""replay_equivalence.py — controlled-variable I/O equivalence oracle.

Mechanical oracle deciding whether a reproduction agrees with its
reference: the same input in, the same bytes out. The structured evidence
artifact is ``evidence/replay-*.json``::

    {
      "schema": "replay-equivalence/1",
      "claim_id": "C-003",
      "captured_inputs": ["cap-01", ...],  # reference-side input inventory
      "variables": {"timestamp": [...], "nonce": [...]},  # declared domains
      "strength": 2,              # t-way covering array (>= 3 after a
                                  # found divergence)
      "prior_divergence": false,
      "withheld_inputs": [{"input_id": "cap-07", "combos": [{...}]}],
      "pairs": [
        {"input_id": "cap-01", "inputs": {...},
         "ref_output": "...", "repro_output": "...",
         "byte_equal": true,      # recomputed from the outputs
         "divergence_offset": null}
      ]
    }

Enforcement (each face is owned by the function named here):

  - artifact_errors / coverage_errors — the pair set is a t-way covering
    array over the declared variables; withheld inputs declare the combos
    their withholding removes; pairs draw inputs from the captured
    inventory; recorded flags must agree with the outputs.
  - mutation_face — one perturbed byte flips the evaluation red.
  - equivalence_verdict / check_claim_admission — a reproduction-flavored
    claim (declared ``reproduction: true`` / ``replay_evidence:``) needs
    a valid artifact with >= 1 matched pair.
  - execute_comparison — the verifier re-runs the reproduction on the
    captured inputs and byte-compares itself.

Exit codes: 0 = green/ok, 1 = red/refused, 2 = lint refusal.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import oracle_anchors  # noqa: E402  — the intake method enum (single source)

SCHEMA_ID = "replay-equivalence/1"
ARTIFACT_GLOB = "replay-*.json"
DEFAULT_STRENGTH = 2
POST_DIVERGENCE_STRENGTH = 3

NO_RUN_NOT_EVIDENCE = (
    "ran without error is NOT evidence of equivalence — no controlled "
    "comparison artifact (evidence/replay-*.json: same captured input -> "
    "byte-identical output on reference and reproduction)")


class ReplayEquivalenceError(ValueError):
    """Loud refusal: corrupt artifact, schema violation, or a broken
    (silent-green) oracle."""


# ------------------------------------------------------------- canonical

def canonical_value(value) -> str:
    """Deterministic scalar identity for domain membership and combo keys —
    1 and "1" stay distinct; nested values serialize stably."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def canonical_output(obj) -> str:
    """Canonical output serialization (the compare basis)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def byte_equal(ref_output: str, repro_output: str) -> bool:
    """BYTE equality of two outputs (UTF-8 encoded)."""
    return str(ref_output).encode("utf-8") == str(repro_output).encode("utf-8")


def first_divergence(a: str, b: str) -> int | None:
    """First differing byte offset; None when equal."""
    ab, bb = str(a).encode("utf-8"), str(b).encode("utf-8")
    if ab == bb:
        return None
    for i, (x, y) in enumerate(zip(ab, bb)):
        if x != y:
            return i
    return min(len(ab), len(bb))


# ------------------------------------------------- covering-array face --

def _declared_domains(doc: dict) -> dict[str, list]:
    variables = doc.get("variables")
    return variables if isinstance(variables, dict) else {}


def _domain_members(variables: dict, var: str) -> set[str]:
    return {canonical_value(v) for v in (variables.get(var) or [])}


def required_combos(variables: dict, strength: int) -> list[tuple]:
    """All t-way value combinations over the declared variable set, as
    canonical ((var, canonical_value), ...) tuples."""
    names = sorted(variables)
    out: list[tuple] = []
    for pick in itertools.combinations(names, strength):
        domains = [_domain_members(variables, v) for v in pick]
        for values in itertools.product(*domains):
            out.append(tuple(zip(pick, values)))
    return out


def _row_combo(row: dict, pick: tuple[str, ...]) -> tuple | None:
    inputs = row.get("inputs") if isinstance(row.get("inputs"), dict) else {}
    cells = []
    for var in pick:
        if var not in inputs:
            return None
        cells.append((var, canonical_value(inputs[var])))
    return tuple(cells)


def _withheld_shadows(doc: dict) -> list[frozenset]:
    """Coverage shadows: every t-way combo that is a subset of a withheld
    input's declared assignment is exempt."""
    shadows: list[frozenset] = []
    for w in doc.get("withheld_inputs") or []:
        if not isinstance(w, dict):
            continue
        cells = set()
        for combo in w.get("combos") or []:
            if isinstance(combo, dict):
                cells.update((k, canonical_value(v))
                             for k, v in combo.items())
        if cells:
            shadows.append(frozenset(cells))
    return shadows


def _covered(doc: dict, strength: int) -> set[tuple]:
    variables = _declared_domains(doc)
    covered: set[tuple] = set()
    for row in doc.get("pairs") or []:
        if not isinstance(row, dict):
            continue
        for pick in itertools.combinations(sorted(variables), strength):
            combo = _row_combo(row, pick)
            if combo is not None:
                covered.add(combo)
    return covered


def coverage_errors(doc: dict) -> list[str]:
    """Every t-way combination must be realized by a pair or shadowed by a
    withheld input; missing combos are named."""
    variables = _declared_domains(doc)
    if not variables:
        return []
    strength = doc.get("strength", DEFAULT_STRENGTH)
    shadows = _withheld_shadows(doc)
    errors: list[str] = []
    for combo in required_combos(variables, strength):
        if combo in _covered(doc, strength):
            continue
        if any(set(combo) <= shadow for shadow in shadows):
            continue
        pretty = ", ".join(f"{var}={val}" for var, val in combo)
        errors.append(
            f"coverage: missing {strength}-way combo over the declared "
            f"variables — {pretty} is realized by no pair and withheld by "
            f"no declared withheld-input")
    return errors


# ------------------------------------------------------- schema errors --

def _pair_input_errors(inputs, pid: str, i: int, variables: dict) -> list[str]:
    """Declared-domain errors for ONE pair's inputs row."""
    if not isinstance(inputs, dict):
        return [f"pairs[{i}] ({pid}): inputs must be a mapping over the "
                f"declared variables"]
    errors: list[str] = []
    for var, val in inputs.items():
        if var not in variables:
            errors.append(
                f"pairs[{i}] ({pid}): input {var!r} is not a declared "
                f"variable")
        elif canonical_value(val) not in _domain_members(variables, var):
            errors.append(
                f"pairs[{i}] ({pid}): input {var}={val} is outside the "
                f"declared domain")
    return errors


def _pair_outputs_errors(row: dict, pid: str, i: int) -> list[str]:
    """The byte-basis + honest-flag face for ONE pair."""
    ref = row.get("ref_output")
    repro = row.get("repro_output")
    if not isinstance(ref, str) or not isinstance(repro, str):
        return [f"pairs[{i}] ({pid}): ref_output and repro_output are "
                f"required strings (the byte basis)"]
    errors: list[str] = []
    flag = row.get("byte_equal")
    if not isinstance(flag, bool):
        errors.append(f"pairs[{i}] ({pid}): byte_equal is required and must "
                      f"be a boolean")
    elif flag != byte_equal(ref, repro):
        errors.append(
            f"pairs[{i}] ({pid}): recorded byte_equal={flag} contradicts "
            f"the outputs — byte_equal is recomputed from the outputs and "
            f"must agree with them")
    offset = row.get("divergence_offset")
    if offset is not None and (not isinstance(offset, int)
                               or isinstance(offset, bool) or offset < 0):
        errors.append(f"pairs[{i}] ({pid}): divergence_offset must be a "
                      f"non-negative int (first-divergent byte offset)")
    return errors


def _pair_errors(doc: dict) -> list[str]:
    variables = _declared_domains(doc)
    captured = {str(c) for c in (doc.get("captured_inputs") or [])}
    seen_ids: set[str] = set()
    errors: list[str] = []
    for i, row in enumerate(doc.get("pairs") or []):
        if not isinstance(row, dict):
            errors.append(f"pairs[{i}]: must be a mapping")
            continue
        pid = str(row.get("input_id") or "").strip()
        if not pid:
            errors.append(f"pairs[{i}]: input_id is required — a pair is "
                          f"anchored to one reference-side input")
            continue
        if pid in seen_ids:
            errors.append(f"pairs[{i}]: duplicate input_id {pid!r} — one "
                          f"input, one controlled comparison")
        seen_ids.add(pid)
        if captured and pid not in captured:
            errors.append(
                f"pairs[{i}]: input_id {pid!r} is not in captured_inputs — "
                f"inputs must be drawn from the reference-side capture "
                f"inventory, never invented")
        errors += _pair_input_errors(row.get("inputs"), pid, i, variables)
        errors += _pair_outputs_errors(row, pid, i)
    return errors


def _strength_errors(doc: dict) -> list[str]:
    variables = _declared_domains(doc)
    strength = doc.get("strength", DEFAULT_STRENGTH)
    errors: list[str] = []
    if not isinstance(strength, int) or isinstance(strength, bool) \
            or strength < 1:
        return [f"strength: must be a positive int, got {strength!r}"]
    if variables and strength > len(variables):
        return [f"strength: {strength} exceeds the declared variable count "
                f"{len(variables)}"]
    if doc.get("prior_divergence") and strength < POST_DIVERGENCE_STRENGTH:
        errors.append(
            f"strength: {strength} with prior_divergence=true — a found "
            f"divergence escalates the covering array to t >= "
            f"{POST_DIVERGENCE_STRENGTH}")
    return errors


def artifact_errors(doc: dict) -> list[str]:
    """The full schema + coverage face. An empty list means the artifact
    is well-formed, its flags agree with its outputs, and its pair set
    covers the declared input space at the declared strength."""
    if not isinstance(doc, dict):
        return [f"artifact must be a mapping, got {type(doc).__name__}"]
    errors: list[str] = []
    if doc.get("schema") != SCHEMA_ID:
        errors.append(f"schema: expected {SCHEMA_ID!r}, got "
                      f"{doc.get('schema')!r}")
    if not str(doc.get("claim_id") or "").strip():
        errors.append("claim_id: required — the artifact is evidence FOR "
                      "one claim")
    if not isinstance(doc.get("captured_inputs"), list) \
            or not doc.get("captured_inputs"):
        errors.append("captured_inputs: required non-empty — the "
                      "reference-side input inventory")
    variables = _declared_domains(doc)
    if not variables:
        errors.append("variables: required mapping of declared input "
                      "variables (name -> value domain)")
    else:
        for var, domain in variables.items():
            if not isinstance(domain, list) or not domain:
                errors.append(f"variables.{var}: domain must be a non-empty "
                              f"list of values")
    pairs = doc.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        errors.append("pairs: required non-empty — the artifact must carry "
                      "at least one executed controlled comparison "
                      "(a matched pair is the equivalence witness)")
    errors += _strength_errors(doc)
    errors += _pair_errors(doc)
    for w in doc.get("withheld_inputs") or []:
        if not isinstance(w, dict) or not str(w.get("input_id") or "").strip():
            errors.append("withheld_inputs: each entry needs input_id + the "
                          "combos its withholding removes")
    withheld_ids = {str(w.get("input_id")).strip()
                    for w in doc.get("withheld_inputs") or []
                    if isinstance(w, dict)}
    pair_ids = {str(r.get("input_id") or "").strip()
                for r in pairs or [] if isinstance(r, dict)}
    for wid in sorted(withheld_ids & pair_ids):
        errors.append(
            f"withheld_inputs: {wid} appears in pairs — a withheld input "
            f"was not run; a pair claiming it ran contradicts the "
            f"withholding declaration")
    errors += coverage_errors(doc)
    return errors


# ------------------------------------------------------ artifact access --

def load_artifacts(evidence_dir, claim_id: str | None = None) -> list[tuple[Path, dict]]:
    """Load ``replay-*.json`` (sorted), optionally filtered to one claim.
    A corrupt file raises — corruption is never read as absence."""
    base = Path(evidence_dir)
    if not base.is_dir():
        return []
    out: list[tuple[Path, dict]] = []
    for p in sorted(base.glob(ARTIFACT_GLOB)):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReplayEquivalenceError(
                f"corrupt replay artifact {p.name}: {exc}") from None
        if claim_id is not None \
                and str(doc.get("claim_id") or "") != str(claim_id):
            continue
        out.append((p, doc))
    return out


def matched_pairs(doc: dict) -> int:
    """Pairs whose outputs actually match on the recomputed byte compare."""
    return sum(1 for row in doc.get("pairs") or []
               if isinstance(row, dict)
               and isinstance(row.get("ref_output"), str)
               and isinstance(row.get("repro_output"), str)
               and byte_equal(row["ref_output"], row["repro_output"]))


# -------------------------------------------------------- mutation gate --

def perturb_output(output: str) -> str:
    """A reproduction output perturbed by ONE byte (deterministic)."""
    s = str(output)
    if not s:
        return "\x01"
    mid = len(s) // 2
    code = ord(s[mid])
    flipped = chr(code + 1) if code < 0x10FFFF else chr(code - 1)
    return s[:mid] + flipped + s[mid + 1:]


def evaluate_pairs(pairs: list[dict]) -> str:
    """THE ORACLE: "green" only when every pair matches on the recomputed
    byte compare; any single mismatching byte -> "red"."""
    for row in pairs or []:
        if not isinstance(row, dict) or "ref_output" not in row \
                or "repro_output" not in row:
            return "red"  # an unreadable pair never witnesses equivalence
        if not byte_equal(row["ref_output"], row["repro_output"]):
            return "red"
    return "green"


def mutation_must_red(pairs: list[dict], evaluate=evaluate_pairs) -> bool:
    """True when a one-byte perturbation flips the evaluation red."""
    if not pairs:
        return False
    perturbed = [dict(p) for p in pairs]
    first = perturbed[0]
    first["repro_output"] = perturb_output(first.get("repro_output", ""))
    return evaluate(perturbed) == "red"


def mutation_face(pairs: list[dict], evaluate=evaluate_pairs) -> None:
    """Raise unless the oracle goes red under a one-byte perturbation."""
    if not mutation_must_red(pairs, evaluate):
        raise ReplayEquivalenceError(
            "silent-green oracle — the equivalence oracle stayed green "
            "under a one-byte perturbation of the reproduction output: it "
            "observes nothing")


# ---------------------------------------------------- declared faces -----

def declared_reproduction_qids(task_spec: dict) -> set[str]:
    """Question ids carrying the declared ``reproduction: true`` bit.

    The workspace-level ``verification_method`` answer arms the set too:
    when the intake collected reproduction / replay-evidence as the
    verification method, EVERY primary question is declared — the
    controlled-comparison face applies to the whole engagement, not only
    to individually flagged questions. static / manual (or an absent
    answer) leave the per-question bits as the sole source.
    """
    spec = task_spec or {}
    out: set[str] = set()
    questions = [q for q in spec.get("primary_questions") or []
                 if isinstance(q, dict)]
    if str(spec.get("verification_method") or "") in \
            oracle_anchors.REPLAY_ORACLE_METHODS:
        out.update(q["id"] for q in questions
                   if isinstance(q.get("id"), str) and q["id"].strip())
    for q in questions:
        if q.get("reproduction") is True \
                and isinstance(q.get("id"), str) and q["id"].strip():
            out.add(q["id"])
    return out


def claim_replay_evidence(claim: dict) -> str | None:
    """The claim's declared artifact path (``replay_evidence:``), or None."""
    val = (claim or {}).get("replay_evidence")
    text = str(val or "").strip()
    return text or None


def claim_is_reproduction_flavored(claim: dict,
                                   repro_qids: set[str]) -> bool:
    """Declared carrier field, or answers a declared question."""
    if claim_replay_evidence(claim) is not None:
        return True
    return str((claim or {}).get("answers_question") or "") in repro_qids


def _find_claim(register: dict, claim_id: str) -> dict | None:
    for c in register.get("claims") or []:
        if isinstance(c, dict) and str(c.get("id") or "") == claim_id:
            return c
    return None


def load_task_spec(ws) -> dict:
    """ws/task_spec.yaml; {} when absent. Corrupt YAML RAISES — the caller
    picks its own degradation posture."""
    p = Path(ws) / "task_spec.yaml"
    if not p.exists():
        return {}
    import yaml
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


# ------------------------------------------- admission / verdict faces --

def equivalence_verdict(ws, claim: dict,
                        repro_qids: set[str] | None = None) -> tuple[bool, str]:
    """(ok, reason) for one claim's artifact face: >= 1 valid artifact with
    a matched pair, or the named refusal. ``repro_qids`` defaults to the
    workspace task_spec's declared set."""
    ws = Path(ws)
    if repro_qids is None:
        repro_qids = declared_reproduction_qids(load_task_spec(ws))
    if not claim_is_reproduction_flavored(claim, repro_qids):
        return True, ""
    evidence = ws / "evidence"
    declared = claim_replay_evidence(claim)
    claim_id = str(claim.get("id") or "")
    if declared:
        # The declared path must resolve inside the evidence root.
        p = (ws / declared)
        norm = declared.replace("\\", "/").lower()
        if norm.startswith(("runs/", "oracle/")) or "oracle-status" in norm:
            return False, (f"declared replay_evidence {declared!r} points "
                           f"into the oracle's own output — self-anchor "
                           f"refused")
        try:
            resolved = p.resolve()
            resolved.relative_to(evidence.resolve())
        except (ValueError, OSError):
            return False, (f"declared replay_evidence {declared!r} does not "
                           f"resolve inside evidence/")
        if not p.is_file():
            return False, (f"{NO_RUN_NOT_EVIDENCE}; declared "
                           f"replay_evidence {declared!r} does not exist")
        try:
            docs = [(p, json.loads(p.read_text(encoding="utf-8")))]
        except (OSError, json.JSONDecodeError) as exc:
            raise ReplayEquivalenceError(
                f"corrupt replay artifact {p.name}: {exc}") from None
    else:
        docs = load_artifacts(evidence, claim_id=claim_id)
        if not docs:
            return False, (
                f"{NO_RUN_NOT_EVIDENCE}; no evidence/replay-*.json names "
                f"claim {claim_id!r} — add the artifact the claim's "
                f"reproduction predicate owes (replay_evidence field or "
                f"claim_id-bearing artifact)")
    total_matched = 0
    for path, doc in docs:
        errs = artifact_errors(doc)
        if errs:
            return False, (f"{path.name}: schema/coverage refusal — "
                           + "; ".join(errs[:3])
                           + (" ..." if len(errs) > 3 else ""))
        total_matched += matched_pairs(doc)
    if total_matched < 1:
        return False, (
            f"{NO_RUN_NOT_EVIDENCE}; {len(docs)} artifact(s) carry 0 "
            f"byte-matched pairs — a reproduction that misses on every "
            f"captured input is honest red evidence, not equivalence")
    return True, ""


def check_claim_admission(ws, register, claim_id: str) -> tuple[bool, str]:
    """(ok, reason) for promoting claim_id. ``register`` is register text
    or parsed dict; an absent claim returns ok (refused upstream)."""
    if isinstance(register, str):
        import yaml
        register = yaml.safe_load(register)
    claim = _find_claim(register if isinstance(register, dict) else {},
                        claim_id)
    if claim is None:
        return True, ""
    return equivalence_verdict(ws, claim)


# -------------------------------------------------- verifier execution --

def execute_comparison(client_path, artifact_path) -> dict:
    """Run the reproduction on each pair's inputs and byte-compare against
    the reference outputs (the verifier executes; it does not read and
    nod). The artifact must pass artifact_errors first; every row is
    recomputed, including matches_recorded against the recorded
    reproduction output; the mutation gate runs on the recomputed rows.

    Returns {"artifact", "claim_id", "verdict", "rows", "mutation_red"}."""
    from oracle_runner import load_client
    artifact_path = Path(artifact_path)
    try:
        doc = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayEquivalenceError(
            f"corrupt replay artifact {artifact_path.name}: {exc}") from None
    errs = artifact_errors(doc)
    if errs:
        raise ReplayEquivalenceError(
            f"{artifact_path.name}: refusing to execute an invalid "
            f"artifact — " + "; ".join(errs[:3])
            + (" ..." if len(errs) > 3 else ""))
    compute = load_client(client_path)
    if compute is None:
        raise ReplayEquivalenceError(
            f"no runnable reproduction client at {client_path} — the "
            f"verifier executes the comparison; without a client there is "
            f"nothing to execute")
    rows: list[dict] = []
    run_pairs: list[dict] = []
    for pair in doc["pairs"]:
        actual = compute(dict(pair.get("inputs") or {}))
        actual_s = actual if isinstance(actual, str) else canonical_output(
            actual)
        rows.append({
            "input_id": pair["input_id"],
            "byte_equal": byte_equal(pair["ref_output"], actual_s),
            "divergence_offset": first_divergence(pair["ref_output"],
                                                  actual_s),
            "matches_recorded": byte_equal(pair["repro_output"], actual_s),
        })
        run_pairs.append({"ref_output": pair["ref_output"],
                          "repro_output": actual_s})
    verdict = "green" if all(r["byte_equal"] for r in rows) else "red"
    mutation_face(run_pairs)
    return {"artifact": artifact_path.name,
            "claim_id": str(doc.get("claim_id") or ""),
            "verdict": verdict,
            "rows": rows,
            "mutation_red": True}


# ------------------------------------------------------------------ CLI --

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="replay-equivalence oracle: check a workspace's replay "
                    "artifacts, evaluate one artifact's pairs, or execute "
                    "the controlled comparison against a reproduction client")
    parser.add_argument("--check-evidence", metavar="DIR",
                        help="validate every replay-*.json under DIR")
    parser.add_argument("--evaluate", metavar="FILE",
                        help="evaluate one artifact's pairs (mutation gate)")
    parser.add_argument("--execute", metavar="CLIENT",
                        help="execute the controlled comparison: run this "
                             "reproduction client on the artifact's "
                             "captured inputs and byte-compare")
    parser.add_argument("--artifact", metavar="FILE",
                        help="the replay artifact used with --execute")
    args = parser.parse_args(argv)
    try:
        if args.execute:
            if not args.artifact:
                parser.error("--execute requires --artifact FILE")
            report = execute_comparison(args.execute, args.artifact)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["verdict"] == "green" else 1
        if args.check_evidence:
            docs = load_artifacts(args.check_evidence)
            if not docs:
                print(NO_RUN_NOT_EVIDENCE, file=sys.stderr)
                return 1
            bad = 0
            for path, doc in docs:
                errs = artifact_errors(doc)
                status = "OK" if not errs else "REFUSED"
                bad += bool(errs)
                print(f"[{status}] {path.name} "
                      f"(claim {doc.get('claim_id')!r}, "
                      f"{len(doc.get('pairs') or [])} pairs, "
                      f"{matched_pairs(doc)} matched)")
                for e in errs:
                    print(f"    - {e}")
            return 1 if bad else 0
        if args.evaluate:
            doc = json.loads(Path(args.evaluate).read_text(encoding="utf-8"))
            errs = artifact_errors(doc)
            if errs:
                for e in errs:
                    print(f"- {e}", file=sys.stderr)
                return 2
            verdict = evaluate_pairs(doc.get("pairs") or [])
            mutation_face(doc.get("pairs") or [])
            print(json.dumps({"verdict": verdict,
                              "matched": matched_pairs(doc),
                              "pairs": len(doc.get("pairs") or [])}))
            return 0 if verdict == "green" else 1
    except (ReplayEquivalenceError, OSError, json.JSONDecodeError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())

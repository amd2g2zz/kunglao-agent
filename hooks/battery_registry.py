#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""battery_registry.py — the hook battery's registration face (issue 805).

mechanisms.yaml's law (不入册不许跑 — issue #878, the tick channel)
extends here to the HOOK battery: the dispatch pre_check checks and the
round-closure kernel faces are a REGISTRY, not an if-chain. Registration
is a launch prerequisite and it is FAIL-CLOSED:

  - every registered face DECLARES its telemetry word AND its liveness
    fingerprint — a new hook/check without a declared fingerprint cannot
    register (the #805 pin: the armed-unwired class dies at registration,
    not at the next incident);
  - the declared fingerprint must EXIST in
    devkit/liveness_fingerprints.json (repo-side join; a deployed tree
    without the fingerprint file enforces the declaration only — the
    registration surface is the repo, changes flow through PRs);
  - the declared entry must RESOLVE to a real top-level function in the
    deployed trees (AST check, no import — an unwired face is
    unregistrable, and no import cycle with the batteries themselves);
  - the launch gate (``launch_gate``) is called by the battery hosts:
    a broken registry or an uncovered code check REFUSES the launch —
    pre_check rejects the dispatch (fail-closed, the gate battery's
    native direction); the closure battery warns and keeps its
    contractual fail-open cage.

Liveness evidence: a full battery pass lands ONE durable row
(runs/gate-telemetry.jsonl, gate=worker_battery, msg=check names) — the
row the per-check fingerprints read. Absence of evidence is the FAIL
that catches the armed-unwired face.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
REPO_DIR = HOOKS_DIR.parent
REGISTRY_PATH = HOOKS_DIR / "battery.yaml"
FINGERPRINTS_PATH = REPO_DIR / "devkit" / "liveness_fingerprints.json"
TAXONOMY_PATH = REPO_DIR / "scripts" / "event_taxonomy.py"

SCHEMA = "kunglao.hook-battery/1"
BATTERIES = ["dispatch", "closure"]
COST_CLASSES = ["cheap", "medium", "expensive"]
GATES = ["always", "dispatch", "verifier_exempt"]
TRIGGER_TYPES = ["tick", "event", "settlement", "stall", "manual"]
PREREQUISITES = ("entry", "cost_class", "telemetry_word",
                 "liveness_fingerprint")

#: the op name of the closure battery's warn-only launch trace (the
#: fail-open cage — round_closure warns, never blocks the stop path)
LAUNCH_WARN_OP = "battery_registry_launch"


def _yaml():
    import yaml
    return yaml


def load_registry(path: Path | None = None,
                  fingerprints_path: Path | None = None
                  ) -> tuple[list[dict], list[str]]:
    """Load + validate the battery registry. Returns (entries, errors);
    errors non-empty means the registry is BROKEN and the launch gate
    refuses (fail-closed). Mirrors mechanism_scheduler.load_registry's
    contract, with the #805 prerequisites added."""
    p = Path(path) if path is not None else REGISTRY_PATH
    try:
        data = _yaml().safe_load(p.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        return [], [f"registry unreadable: {exc}"]
    except Exception as exc:  # yaml or encoding trouble
        return [], [f"registry unparseable: {exc}"]
    if not isinstance(data, dict):
        return [], ["registry root is not a mapping"]
    errors: list[str] = []
    if data.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA!r}, got "
                      f"{data.get('schema')!r}")
    for vocab, required in (("batteries", BATTERIES),
                            ("cost_classes", COST_CLASSES),
                            ("gates", GATES)):
        got = data.get(vocab)
        if not isinstance(got, list) or not got:
            errors.append(f"{vocab} vocabulary missing/empty")
        elif not set(required) <= set(got):
            errors.append(f"{vocab} vocabulary is missing required "
                          f"members: {sorted(set(required) - set(got))}")
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("entries list missing/empty")
        return [], errors

    battery_vocab = set(data.get("batteries") or BATTERIES)
    cost_vocab = set(data.get("cost_classes") or COST_CLASSES)
    gate_vocab = set(data.get("gates") or GATES)
    emit_words = _emit_actions()

    seen: set[str] = set()
    for idx, e in enumerate(entries):
        name = str((e or {}).get("name") or "").strip()
        label = name or f"#{idx}"
        if not name:
            errors.append(f"entry {label}: missing name")
            continue
        if name in seen:
            errors.append(f"entry {name!r}: duplicate name")
            continue
        seen.add(name)
        where = f"entry {name!r}"
        battery = e.get("battery")
        if battery not in battery_vocab:
            errors.append(f"{where}: unknown battery {battery!r}")
        trig = e.get("trigger")
        if not isinstance(trig, dict) or not trig:
            errors.append(f"{where}: missing trigger")
        else:
            if trig.get("type") not in TRIGGER_TYPES:
                errors.append(f"{where}: unknown trigger type "
                              f"{trig.get('type')!r}")
            gate = str(trig.get("gate") or "").strip()
            if not gate:
                errors.append(f"{where}: missing trigger.gate "
                              "(go-live prerequisite)")
            elif gate not in gate_vocab:
                errors.append(f"{where}: unknown trigger.gate {gate!r} "
                              f"(known: {sorted(gate_vocab)})")
        for field in PREREQUISITES:
            if not str(e.get(field) or "").strip():
                errors.append(f"{where}: missing {field} "
                              "(fail-closed go-live prerequisite)")
        cost = e.get("cost_class")
        if str(cost or "").strip() and cost not in cost_vocab:
            errors.append(f"{where}: unknown cost_class {cost!r} "
                          f"(known: {sorted(cost_vocab)})")
        word = str(e.get("telemetry_word") or "").strip()
        if word and not _telemetry_word_ok(word, emit_words):
            errors.append(f"{where}: unknown telemetry_word {word!r} "
                          "(an EMIT_ACTIONS word, a worker_budget.<name> "
                          "gate-telemetry face, or a file:<rel> observable")
        entry = str(e.get("entry") or "").strip()
        if entry:
            err = resolve_entry(entry)
            if err is not None:
                errors.append(f"{where}: {err}")
        fp = str(e.get("liveness_fingerprint") or "").strip()
        if fp:
            known = fingerprint_ids(fingerprints_path)
            if known is not None and fp not in known:
                errors.append(f"{where}: liveness_fingerprint {fp!r} is "
                              "not in the fingerprint file (a declared-"
                              "but-undefined fingerprint is the "
                              "decorative-evidence loophole)")
    return [e for e in entries if isinstance(e, dict)], errors


def validate_registry(path: Path | None = None) -> dict:
    """The mechanical schema gate face. ok=False means the registry is
    broken: the launch gate refuses (fail-closed)."""
    _entries, errors = load_registry(path)
    return {"ok": not errors, "errors": errors,
            "entries": 0 if errors else len(_entries)}


# ---------------------------------------------------------------------------
# resolution + vocabularies (AST — no import, no cycle)
# ---------------------------------------------------------------------------

def resolve_entry(entry: str) -> str | None:
    """``module:func`` -> None when it resolves to a real top-level
    function in hooks/ or scripts/ (dotted modules map to package dirs);
    an error string when the module file or the function is missing."""
    text = str(entry or "").strip()
    module, _, func = text.partition(":")
    module, func = module.strip(), func.strip()
    if not module or not func:
        return f"entry {text!r}: expected module:function"
    for base in (HOOKS_DIR, REPO_DIR / "scripts"):
        mod_path = base / (module.replace(".", "/") + ".py")
        if mod_path.is_file():
            return _func_in_file(mod_path, func, text)
    return (f"entry {text!r}: module file not found in hooks/ or scripts/ "
            "(an unwired face is unregistrable)")


def _func_in_file(path: Path, func: str, entry: str) -> str | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8",
                                        errors="replace"))
    except (OSError, SyntaxError) as exc:
        return f"entry {entry!r}: module unreadable ({exc})"
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == func:
            return None
    return (f"entry {entry!r}: function {func!r} not found in "
            f"{path.name} (an unwired face is unregistrable)")


def _emit_actions() -> set[str]:
    """The controlled vocabulary (scripts/event_taxonomy.EMIT_ACTIONS),
    AST-extracted — no import, works in the deployed tree too."""
    try:
        tree = ast.parse(TAXONOMY_PATH.read_text(encoding="utf-8",
                                                 errors="replace"))
    except (OSError, SyntaxError):
        return set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "EMIT_ACTIONS"
                for t in node.targets):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                return {elt.value for elt in node.value.elts
                        if isinstance(elt, ast.Constant)
                        and isinstance(elt.value, str)}
    return set()


def _telemetry_word_ok(word: str, emit_words: set[str]) -> bool:
    if word in emit_words:
        return True
    if word.startswith("worker_budget.") \
            and len(word) > len("worker_budget."):
        return True
    return word.startswith("file:") and len(word) > len("file:")


# ---------------------------------------------------------------------------
# the liveness fingerprint join (issue #772 file, repo-side)
# ---------------------------------------------------------------------------

def fingerprint_ids(path: Path | None = None) -> set[str] | None:
    """The declared fingerprint ids. None = the fingerprint file is not
    present at this tree (a deployed runtime enforces the DECLARATION;
    the id join is the repo/CI surface)."""
    p = Path(path) if path is not None else FINGERPRINTS_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {str(fp.get("id")) for fp in
            (data.get("fingerprints") or []) if fp.get("id")}


def coverage_audit() -> dict:
    """The registry×fingerprint join audit (#805 pin 2): every registered
    battery face joins a REAL fingerprint — coverage must be total."""
    entries, errors = load_registry()
    if errors:
        return {"ok": False, "errors": errors, "faces": 0,
                "join_complete": False, "unknown_ids": [],
                "missing_fingerprints": []}
    declared = [str(e.get("liveness_fingerprint") or "") for e in entries]
    missing = [e["name"] for e in entries
               if not str(e.get("liveness_fingerprint") or "").strip()]
    ids = fingerprint_ids()
    unknown = sorted({fp for fp in declared
                      if fp and ids is not None and fp not in ids})
    join_complete = (not missing) and (not unknown) and ids is not None
    return {"ok": True, "faces": len(entries),
            "fingerprinted": sum(1 for fp in declared if fp),
            "join_complete": join_complete, "unknown_ids": unknown,
            "missing_fingerprints": missing}


# ---------------------------------------------------------------------------
# the launch gate (registration is a LAUNCH PREREQUISITE)
# ---------------------------------------------------------------------------

def registered_names(battery: str, entries: list[dict] | None = None
                     ) -> set[str]:
    entries = entries if entries is not None else load_registry()[0]
    return {e["name"] for e in entries if e.get("battery") == battery}


def launch_gate(expected, battery: str = "dispatch",
                path: Path | None = None) -> str | None:
    """None when the battery may launch (registry valid, every expected
    face registered); otherwise the refusal message. The dispatch host
    turns a refusal into a REJECT (fail-closed); the closure host turns
    it into ONE warn (its contractual fail-open cage)."""
    entries, errors = load_registry(path)
    if errors:
        return ("hook battery registry BROKEN — registration is a launch "
                f"prerequisite (不入册不许跑): {'; '.join(errors[:5])}")
    names = registered_names(battery, entries)
    uncovered = sorted(set(expected) - names)
    if uncovered:
        return ("hook battery registry does not cover the code battery — "
                f"unregistered check(s) {uncovered} (a new hook/check "
                "registers in hooks/battery.yaml with its telemetry word "
                "+ liveness fingerprint BEFORE it may run)")
    return None

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""script_harvest.py — the workspace script-harvest engine (issue #477).

Post-run sweep that mines workers' own successful scripts into skill
candidates (Code2Skill grounding), riding the #474 online-distillation
landing spine — one module, four organs:

  sweep+classify   the success-trace discriminator: a swept script is a
                   candidate when a PROVEN/VERIFIED fact cites it (exact
                   status set; provenance path / reproduce line / body
                   mention) OR a later act reused it (a done-line
                   deliverable reference, or two independent later
                   referencing documents; bare mentions fire nothing)
  budget           harvest-owned counters in the SAME
                   runs/distill-budget.json ledger document (never-loosen
                   clamp, fail-closed corruption, own type-check — the
                   distill counters untouched)
  verify           staged-then-verified: the candidate is copied into the
                   shelf FIRST and the LANDED copy runs twice (cwd=ws) —
                   rc 0 + non-empty stdout + identical sha256 both times
                   (the byte-exact pin); any failure removes the staged
                   files and archives the candidate, never landing
  land/playbook    tools-local/<name>.py + harvest-manifest/1 (provenance,
                   env-version stamp) + the harvest-playbook/1 chain record

CLI (production faces; the e2e host imports the module directly):
  python script_harvest.py <ws> --scan [--since TS]
  python script_harvest.py <ws> --harvest [--since TS]

The e2e host (checkpoints.finalize) imports the module and emits the
e2e audit rows through its own stream writer; this CLI emits the
production rows via kunglao_log — both vocabularies register the three
words (harvest_scan / script_harvested / harvest_landed).

The engine NEVER writes the global shelf directories and NEVER
mutates the worker's own files: landings stage into tools-local/ and
failures archive under runs/harvest-archive/ (a record, never a move).
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from harness_common import utc_now_z as _utc_now

# the #474 spine is the single source for the shared landing surface
# (ledger path/shelf dir/timeout + the write discipline + the lock) —
# deliberate reuse, never a second landing API (design D4 disposition).
import online_distill as od
from _common import sha256_file, sha256_hex
from lint_facts import parse_frontmatter

# the canonical warn — ONE implementation (process-wide dedupe + the
# ledger face); import-guarded so a scripts/-less host context still
# imports the engine (the warn face degrades to stderr).
try:
    from kunglao_log import warn as _warn
except ImportError:  # partial-deploy lifeline, never blocks the engine
    def _warn(op: str, reason: str) -> None:
        print(f"[kunglao-agent] WARN (fail-open): {op}: {reason}",
              file=sys.stderr)

#: per-run landing cap (harvest-owned; the restraint face — module
#: constants are the CEILING, stored values above clamp down)
HARVEST_LANDS_PER_RUN = 2

ARCHIVE_DIRNAME = "runs/harvest-archive"
PLAYBOOK_NAME = "runs/harvest-playbook.json"
MANIFEST_SCHEMA = "harvest-manifest/1"
PLAYBOOK_SCHEMA = "harvest-playbook/1"
ARCHIVE_SCHEMA = "harvest-archive/1"

#: single sources from the spine — re-exported so consumers pin against
#: the shared surface (never a restated literal)
LEDGER_NAME = od.LEDGER_NAME
TOOLS_LOCAL_DIRNAME = od.TOOLS_LOCAL_DIRNAME
ORACLE_TIMEOUT_S = od.ORACLE_TIMEOUT_S

#: the exact status set for the verified-outcome trace (arm a) — set
#: membership, never substring (worker-declared VERIFIED-BY-* forms do
#: NOT qualify this arm; they can still feed the reuse arm)
CITE_STATUSES = frozenset({"PROVEN", "VERIFIED"})

_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,63}")
_ONE_OFF = "scripts/sample_specific/"
_NAME_CLEAN = re.compile(r"[^a-z0-9-]+")


# ---------------------------------------------------------------------------
# sweep
# ---------------------------------------------------------------------------


def sweep_scripts(ws, since_epoch: float) -> list:
    """Python files written during the run: scripts/ recursive minus the
    declared one-off dir, plus evidence/*.py; mtime at or after the
    host-supplied run-start (`since_epoch` <= 0 disables the floor).
    Sorted, workspace-relative."""
    ws = Path(ws)
    out: list = []
    scripts_dir = ws / "scripts"
    if scripts_dir.is_dir():
        for p in sorted(scripts_dir.rglob("*.py")):
            rel = p.relative_to(ws).as_posix()
            if rel.startswith(_ONE_OFF):
                continue
            if not _in_scope(p, since_epoch):
                continue
            out.append(rel)
    for p in sorted((ws / "evidence").glob("*.py")):
        if _in_scope(p, since_epoch):
            out.append(p.relative_to(ws).as_posix())
    return out


def _in_scope(p: Path, since_epoch: float) -> bool:
    if since_epoch <= 0.0:
        return True
    try:
        return p.stat().st_mtime >= since_epoch
    except OSError as exc:
        _warn("script_harvest_sweep",
              f"stat {p}: {type(exc).__name__}: {exc} (file skipped)")
        return False


# ---------------------------------------------------------------------------
# the discriminator (D1)
# ---------------------------------------------------------------------------


def load_docs(ws) -> list:
    """The citation corpus: facts/F*.md frontmatter+body and
    runs/worker-status-*.md texts, with mtimes. The harvest module's own
    outputs (tools-local/, runs/harvest-*) are NEVER scanned, so a
    landed candidate cannot manufacture reuse for its source."""
    ws = Path(ws)
    docs: list = []
    for p in sorted((ws / "facts").glob("F*.md")):
        rel = p.relative_to(ws).as_posix()
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            mtime = p.stat().st_mtime
        except OSError as exc:
            _warn("script_harvest_docs",
                  f"read {rel}: {type(exc).__name__}: {exc} (skipped)")
            continue
        fm, body, _err = parse_frontmatter(text)
        prov_paths: list = []
        prov = fm.get("provenance")
        if isinstance(prov, list):
            for entry in prov:
                if isinstance(entry, dict) and isinstance(
                        entry.get("path"), str):
                    prov_paths.append(entry["path"])
        docs.append({
            "kind": "fact", "path": rel, "mtime": mtime, "text": text,
            "body": body, "fm": fm,
            "id": str(fm.get("id") or p.stem),
            "status": str(fm.get("status") or ""),
            "claim_id": fm.get("claim_id"),
            "title": fm.get("title"),
            "reproduce": str(fm.get("reproduce") or ""),
            "prov_paths": prov_paths,
        })
    for p in sorted((ws / "runs").glob("worker-status-*.md")):
        rel = p.relative_to(ws).as_posix()
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            mtime = p.stat().st_mtime
        except OSError as exc:
            _warn("script_harvest_docs",
                  f"read {rel}: {type(exc).__name__}: {exc} (skipped)")
            continue
        docs.append({"kind": "status", "path": rel, "text": text,
                     "mtime": mtime})
    return docs


def _final_status_line(text: str) -> str:
    """The lib_kunglao convention: the LAST `status:` line wins."""
    last = ""
    for line in text.splitlines():
        if "status:" in line:
            last = line
    return last


def _done_deliverable(text: str, script_rel: str) -> bool:
    """The done-line deliverable predicate: the final status line is
    `done` AND its artifacts list carries the script path."""
    line = _final_status_line(text)
    return ("status: done" in line
            and "artifacts:" in line
            and script_rel in line)


def _trace_docs(docs: list, script_rel: str,
                 script_mtime: float) -> tuple:
    """The success-trace scan: exact citing facts, later referencing
    docs, and done-line deliverable references for ONE script."""
    citing: list = []
    later_refs: list = []
    done_refs: list = []
    for d in docs:
        if script_rel not in d.get("text", ""):
            continue
        if d["kind"] == "fact" and d["status"] in CITE_STATUSES:
            exact = script_rel in d.get("prov_paths", [])
            if exact or script_rel in d.get("reproduce", "") \
                    or script_rel in d.get("body", ""):
                citing.append(d)
        if d["mtime"] >= script_mtime:
            later_refs.append(d)
            if d["kind"] == "status" and _done_deliverable(
                    d.get("text", ""), script_rel):
                done_refs.append(d)
    return citing, later_refs, done_refs


def classify_script(ws, script_rel: str, docs: list) -> dict | None:
    """The success-trace discriminator. Returns the candidate dict or
    None (one-off). Arm (a): an exact-set PROVEN/VERIFIED fact cites the
    path (exact provenance path / reproduce line / body mention). Arm
    (b): an outcome-bearing later reference — a done-line deliverable
    reference, or two independent later referencing documents; bare
    mentions fire nothing."""
    ws = Path(ws)
    spath = ws / script_rel
    try:
        script_mtime = spath.stat().st_mtime
    except OSError:
        return None
    citing, later_refs, done_refs = _trace_docs(
        docs, script_rel, script_mtime)
    if done_refs:
        reuse = done_refs
    elif len(later_refs) >= 2:
        reuse = later_refs
    else:
        reuse = []
    if not citing and not reuse:
        return None
    all_facts = [d for d in docs if d["kind"] == "fact"
                 and script_rel in d.get("text", "")]
    evidence: list = []
    served_in: list = []
    for d in all_facts:
        t = d.get("title")
        if t and t not in served_in:
            served_in.append(t)
        for pp in d.get("prov_paths", []):
            if pp != script_rel and pp not in evidence:
                evidence.append(pp)
    capability = None
    for d in later_refs:
        if d["kind"] == "status":
            m = od._MARKER_RE.search(d.get("text", ""))
            if m:
                capability = m.group("token")
                break
    stem = script_rel.rsplit("/", 1)[-1][:-3]
    return {
        "script": script_rel,
        "name": normalize_name(stem),
        "signals": {
            "verified_trace": [d["id"] for d in citing],
            "reuse_trace": [d["path"] for d in reuse],
        },
        "facts": [{"id": d["id"], "claim_id": d.get("claim_id"),
                   "status": d["status"]} for d in all_facts],
        "evidence": evidence,
        "served_in": served_in,
        "capability": capability,
    }


def normalize_name(stem: str) -> str | None:
    """The shelf name: the script's stem normalized to the DISTILL
    vocabulary — lowercase, underscores -> hyphens, illegal chars
    collapsed, edges trimmed — validated against the spine's name
    regex; unnormalizable -> None (not landable)."""
    s = stem.lower().replace("_", "-")
    s = _NAME_CLEAN.sub("-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if not _NAME_RE.fullmatch(s or ""):
        return None
    return s


# ---------------------------------------------------------------------------
# the anchored sample (D3) — the spine's bins/ single-file rule
# ---------------------------------------------------------------------------


def resolve_sample(ws) -> tuple:
    """The anchored sample: a single file under bins/ is the sample
    outright; anything else returns (None, "no-anchored-sample").
    No invented input (fail-closed) — the #474 resolution rule minus
    the marker hint."""
    bins = Path(ws) / "bins"
    if not bins.is_dir():
        return None, "no-anchored-sample"
    files = sorted(p for p in bins.iterdir() if p.is_file())
    if len(files) == 1:
        return files[0], "anchored"
    return None, "no-anchored-sample"


# ---------------------------------------------------------------------------
# verification (D3) — staged double-run byte-exact pin
# ---------------------------------------------------------------------------


def _run_once(landed: Path, sample: Path, ws) -> dict:
    """One bounded subprocess of the LANDED copy, cwd = the workspace."""
    try:
        # absolute paths: a relative landed/sample would be re-resolved
        # against cwd (ws) and double-prefix (ws/ws/...) — rc 2
        proc = subprocess.run(
            [sys.executable, str(Path(landed).resolve()),
             str(Path(sample).resolve())],
            capture_output=True, text=True, timeout=ORACLE_TIMEOUT_S,
            cwd=str(ws), encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"rc": None, "reason": "timeout"}
    except OSError as exc:
        return {"rc": None, "reason": f"os-error: {type(exc).__name__}"}
    return {"rc": proc.returncode, "stdout": proc.stdout,
            "stderr": proc.stderr}


def _unstage(tools: Path, name: str) -> None:
    """Remove the staged copy on verification failure (the manifest
    does not exist yet; a leftover would be a bug — cleaned too)."""
    try:
        (tools / f"{name}.py").unlink(missing_ok=True)
        (tools / f"{name}.manifest.json").unlink(missing_ok=True)
    except OSError as exc:
        _warn("script_harvest_unstage",
              f"{name}: {type(exc).__name__}: {exc}")


def _verify(ws, cand: dict, sample: Path) -> dict:
    """Stage into the shelf, run the LANDED copy twice, require rc 0 +
    non-empty stdout + identical sha256 both runs (the byte-exact pin).
    On any failure BOTH staged files are removed and the failure dict is
    returned (the archive record is the caller's face)."""
    ws = Path(ws)
    tools = ws / TOOLS_LOCAL_DIRNAME
    tools.mkdir(parents=True, exist_ok=True)
    name = cand["name"]
    dest = tools / f"{name}.py"
    src = ws / cand["script"]
    dest.write_bytes(src.read_bytes())
    os.chmod(dest, 0o755)
    r1 = _run_once(dest, sample, ws)
    r2 = _run_once(dest, sample, ws)
    if r1.get("reason") == "timeout" or r2.get("reason") == "timeout":
        _unstage(tools, name)
        return {"ok": False, "reason": "timeout"}
    if r1["rc"] != 0:
        reason = "argv-contract" if r1["rc"] == 2 else "rc-nonzero"
        _unstage(tools, name)
        return {"ok": False, "reason": reason, "rc": r1["rc"],
                "stderr_tail": r1["stderr"][-200:]}
    if not r1["stdout"].strip():
        _unstage(tools, name)
        return {"ok": False, "reason": "empty-stdout"}
    sha1 = sha256_hex(r1["stdout"].encode("utf-8", "replace"))
    if r2["rc"] != 0 or not r2["stdout"].strip():
        reason = "argv-contract" if r2["rc"] == 2 else "rc-nonzero"
        _unstage(tools, name)
        return {"ok": False, "reason": reason, "rc": r2["rc"],
                "stderr_tail": r2["stderr"][-200:]}
    sha2 = sha256_hex(r2["stdout"].encode("utf-8", "replace"))
    if sha1 != sha2:
        _unstage(tools, name)
        return {"ok": False, "reason": "digest-mismatch"}
    return {"ok": True, "fixture": {
        "input": sample.relative_to(ws).as_posix(),
        "input_sha256": _file_sha256(sample),
        "stdout_sha256": sha1,
        "runs": 2,
        "cwd": "."}}


def _file_sha256(p: Path) -> str:
    return sha256_file(p)


# ---------------------------------------------------------------------------
# budget (D4) — harvest-owned counters in the shared ledger document
# ---------------------------------------------------------------------------


def _counters_int_ok(doc: dict) -> bool:
    """Harvest type-checks its OWN counter fields: a ledger valid for
    distill but carrying type-garbage harvest counters reads
    harvest-exhausted (fail-closed) — never a crash, never a reset."""
    try:
        int(doc.get("harvest_budget", HARVEST_LANDS_PER_RUN))
        int(doc.get("harvest_used", 0))
    except (TypeError, ValueError):
        return False
    g = doc.get("global")
    if isinstance(g, dict) and "harvest_landed" in g:
        try:
            int(g.get("harvest_landed"))
        except (TypeError, ValueError):
            return False
    return True


def _fresh_with_harvest() -> dict:
    """The spine's fresh ledger plus the harvest counter fields."""
    doc = od._fresh_ledger()
    doc["global"]["harvest_landed"] = 0
    doc["harvest_budget"] = HARVEST_LANDS_PER_RUN
    doc["harvest_used"] = 0
    return doc


def _load_ledger(ws) -> dict | None:
    """The raw ledger document, or None when missing; raises no error —
    an unreadable/corrupt document returns None too (the caller reads
    exhausted, fail-closed)."""
    path = Path(ws) / LEDGER_NAME
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def _reserve_harvest(ws) -> tuple:
    """Atomically check-and-debit ONE harvest landing under the spine's
    lock. Returns (allowed, reason): `budget_ledger_unreadable` (a
    corrupt ledger), `harvest_ledger_type_garbage` (own-field type
    garbage), or `per_run_harvest_budget_exhausted` (cap reached). The
    never-loosen clamp persists (a stored budget above the default
    clamps down; a smaller stored budget is honored)."""
    ws = Path(ws)
    with od._LedgerLock(ws):
        raw = _load_ledger(ws)
        if raw is None and (ws / LEDGER_NAME).is_file():
            return False, "budget_ledger_unreadable"
        if raw is None:
            raw = _fresh_with_harvest()
        if not _counters_int_ok(raw):
            return False, "harvest_ledger_type_garbage"
        if od.ledger_state(ws).get("corrupt"):
            return False, "budget_ledger_unreadable"
        budget = int(raw.get("harvest_budget", HARVEST_LANDS_PER_RUN))
        if budget > HARVEST_LANDS_PER_RUN:
            budget = HARVEST_LANDS_PER_RUN
            raw["harvest_budget"] = budget
        raw["harvest_budget"] = budget
        if int(raw.get("harvest_used", 0)) >= budget:
            return False, "per_run_harvest_budget_exhausted"
        raw["harvest_used"] = int(raw.get("harvest_used", 0)) + 1
        od._atomic_write_json(ws / LEDGER_NAME, raw)
        return True, ""


def _count_landed_harvest(ws, n: int = 1) -> None:
    """Count one landing in `global.harvest_landed` (the lifetime
    observation counter; carried across re-init with `global`)."""
    ws = Path(ws)
    with od._LedgerLock(ws):
        doc = _load_ledger(ws)
        if doc is None:
            doc = _fresh_with_harvest()
        if not isinstance(doc.get("global"), dict):
            doc["global"] = {"acts": 0, "hops": 0, "landed": 0,
                             "harvest_landed": 0}
        doc["global"].setdefault("harvest_landed", 0)
        doc["global"]["harvest_landed"] = (
            int(doc["global"]["harvest_landed"]) + n)
        od._atomic_write_json(ws / LEDGER_NAME, doc)


# ---------------------------------------------------------------------------
# the driver — classify pass, landing, playbook
# ---------------------------------------------------------------------------


def classify_pass(ws, since_epoch: float) -> dict:
    """Sweep + discriminate, no writes (the `--scan` face and the first
    half of run_harvest)."""
    ws = Path(ws)
    result = {"swept": [], "candidates": [], "skipped": [],
              "landed": [], "archived": [], "playbook": None}
    swept = sweep_scripts(ws, since_epoch)
    result["swept"] = swept
    if not swept:
        return result
    docs = load_docs(ws)
    already = landed_source_paths(ws)
    for rel in swept:
        if rel in already:
            result["skipped"].append(rel)
            continue
        cand = classify_script(ws, rel, docs)
        if cand is None:
            result["skipped"].append(rel)
            continue
        result["candidates"].append(cand)
    return result


def landed_source_paths(ws) -> set:
    """`source_path`s of existing harvest manifests under tools-local/ —
    the idempotence face: an already-landed source never re-lands."""
    ws = Path(ws)
    out: set = set()
    tools = ws / TOOLS_LOCAL_DIRNAME
    if not tools.is_dir():
        return out
    for mpath in sorted(tools.glob("*.manifest.json")):
        try:
            doc = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) \
                and doc.get("schema") == MANIFEST_SCHEMA \
                and isinstance(doc.get("source_path"), str):
            out.add(doc["source_path"])
    return out


def _name_collision(ws, cand: dict) -> bool:
    """Landing is refused when `tools-local/<name>.py` exists under a
    manifest whose schema is NOT harvest-manifest/1 (a distilled tool is
    never overwritten), or when the same name maps a different
    source_path."""
    ws = Path(ws)
    name = cand["name"]
    tools = ws / TOOLS_LOCAL_DIRNAME
    if not (tools / f"{name}.py").exists():
        return False
    mpath = tools / f"{name}.manifest.json"
    doc = None
    if mpath.is_file():
        try:
            doc = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = None
    if not isinstance(doc, dict) or doc.get("schema") != MANIFEST_SCHEMA:
        return True  # a foreign/distill face owns the name
    return doc.get("source_path") != cand["script"]


def _archive(ws, cand: dict, reason: str, detail: dict | None = None,
             result: dict | None = None) -> dict:
    """The archive record (runs/harvest-archive/<name>.json) + the
    result row. The worker's own file is never moved or mutated."""
    ws = Path(ws)
    name = cand.get("name")
    slug = name or re.sub(r"[^a-z0-9-]+", "-",
                          str(cand.get("script", "candidate")).lower())
    doc = {"schema": ARCHIVE_SCHEMA, "name": name,
           "script": cand.get("script"), "reason": reason,
           "detail": detail or {}, "ts": _utc_now()}
    od._atomic_write_json(ws / ARCHIVE_DIRNAME / f"{slug}.json", doc)
    row = {"name": name, "script": cand.get("script"),
           "reason": reason}
    if detail:
        row.update({k: v for k, v in detail.items()
                    if k in ("rc",)})
    if result is not None:
        result["archived"].append(row)
    return row


def _land_one(ws, cand: dict, sample: Path, result: dict) -> None:
    """The per-candidate landing chain: name rule -> collision rule ->
    anchored sample -> staged double-run verification -> budget debit ->
    manifest write + the harvest_landed counter. Every refusal archives
    (recorded, never silent) and never lands."""
    name = cand["name"]
    if name is None:
        _archive(ws, cand, "bad-name", result=result)
        return
    if _name_collision(ws, cand):
        _archive(ws, cand, "name-collision", result=result)
        return
    if sample is None:
        _archive(ws, cand, "no-anchored-sample", result=result)
        return
    outcome = _verify(ws, cand, sample)
    if not outcome.get("ok"):
        detail = {k: v for k, v in outcome.items() if k != "ok"}
        _archive(ws, cand, str(outcome.get("reason")),
                 detail=detail, result=result)
        return
    allowed, reason = _reserve_harvest(ws)
    if not allowed:
        _unstage(ws / TOOLS_LOCAL_DIRNAME, name)
        _archive(ws, cand, reason, result=result)
        return
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "name": name,
        "source_path": cand["script"],
        "description": cand.get("description"),
        "capability": cand.get("capability"),
        "served_in": cand.get("served_in") or [],
        "signals": cand.get("signals") or {},
        "facts": cand.get("facts") or [],
        "fixture": outcome["fixture"],
        "version": {"python": platform.python_version(),
                    "platform": sys.platform},
        "landed_ts": _utc_now(),
    }
    tools = ws / TOOLS_LOCAL_DIRNAME
    od._atomic_write_json(tools / f"{name}.manifest.json", manifest)
    _count_landed_harvest(ws, 1)
    result["landed"].append({
        "name": name, "script": cand["script"],
        "tool_path": f"{TOOLS_LOCAL_DIRNAME}/{name}.py",
        "manifest_path": f"{TOOLS_LOCAL_DIRNAME}/{name}.manifest.json",
        "fixture": outcome["fixture"]})


def _write_playbook(ws, result: dict) -> None:
    """The playbook chain record: one chain per landed candidate —
    script -> anchored input -> evidence artifacts -> outcome -> landed
    path (the #478-feeding minimal record; absent when nothing landed)."""
    ws = Path(ws)
    chains: list = []
    for landed in result["landed"]:
        cand = next((c for c in result["candidates"]
                     if c["script"] == landed["script"]), None)
        if cand is None:
            continue
        facts = cand.get("facts") or []
        strongest = next((f for f in facts
                          if f.get("status") in CITE_STATUSES),
                         facts[0] if facts else {})
        chains.append({
            "script": cand["script"],
            "capability_input": {
                "input": landed["fixture"]["input"],
                "sha256": landed["fixture"]["input_sha256"]},
            "evidence": cand.get("evidence") or [],
            "outcome": {"fact": strongest.get("id"),
                        "claim_id": strongest.get("claim_id"),
                        "status": strongest.get("status")},
            "landed_as": landed["tool_path"]})
    if not chains:
        return
    od._atomic_write_json(ws / PLAYBOOK_NAME,
                          {"schema": PLAYBOOK_SCHEMA, "ts": _utc_now(),
                           "chains": chains})
    result["playbook"] = PLAYBOOK_NAME


def run_harvest(ws, since_epoch: float = 0.0) -> dict:
    """The post-run harvest: classify pass + landing phase + the playbook
    co-product. Returns the structured result; row emission is the
    HOST's face (e2e audit emitters / CLI kunglao_log rows)."""
    ws = Path(ws)
    result = classify_pass(ws, since_epoch)
    if not result["candidates"]:
        return result
    sample, _sample_source = resolve_sample(ws)
    for cand in result["candidates"]:
        cand["description"] = _docstring_of(ws / cand["script"])
        _land_one(ws, cand, sample, result)
    if result["landed"]:
        _write_playbook(ws, result)
    return result


def _docstring_of(script: Path) -> str | None:
    """First line of the module docstring (bounded; None when absent or
    the file does not parse — the description is metadata, never a
    gate)."""
    try:
        tree = ast.parse(script.read_text(encoding="utf-8",
                                          errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return None
    doc = ast.get_docstring(tree) or ""
    first = doc.strip().splitlines()[0] if doc.strip() else ""
    return first[:200] or None


# ---------------------------------------------------------------------------
# CLI — the production faces (rows via kunglao_log)
# ---------------------------------------------------------------------------


def _emit_production_row(ws, action: str, *, detail: dict,
                         tool: str | None = None) -> bool:
    """The CLI face's production rows (harvest_scan / script_harvested /
    harvest_landed) via kunglao_log — the 17-field schema, actor
    `orchestrator` (the orchestrator runs the post-run sweep). Never
    raises: a logging failure degrades to False."""
    try:
        import kunglao_log
    except ImportError:
        return False
    return kunglao_log.emit(
        ws, "orchestrator", action, tool=tool,
        detail=json.dumps(detail, sort_keys=True, ensure_ascii=False))


def _parse_since(raw: str | None) -> float:
    """`--since TS` (UTC %Y-%m-%dT%H:%M:%SZ) to epoch; None/empty/0 ->
    0.0 (no floor). A malformed stamp raises ValueError — the CLI turns
    it into a usage error."""
    if not raw:
        return 0.0
    dt = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ")
    return dt.timestamp()


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="script harvest — the post-run sweep that mines "
                    "workers' successful scripts into skill candidates")
    ap.add_argument("ws", help="workspace path")
    ap.add_argument("--scan", action="store_true",
                    help="sweep + classify, no writes (read-only)")
    ap.add_argument("--harvest", action="store_true",
                    help="sweep + verify + land (writes under <ws> only)")
    ap.add_argument("--since", default=None,
                    help="sweep-scope floor, UTC %%Y-%%m-%%dT%%H:%%M:%%SZ "
                         "(default: no floor)")
    args = ap.parse_args(argv)
    ws = Path(args.ws)
    try:
        since = _parse_since(args.since)
    except ValueError:
        print(json.dumps({"error": "bad --since stamp",
                          "want": "%Y-%m-%dT%H:%M:%SZ"}), file=sys.stderr)
        return 2
    if args.scan:
        result = classify_pass(ws, since)
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.harvest:
        result = run_harvest(ws, since)
        detail = {"swept": len(result["swept"]),
                  "candidates": len(result["candidates"]),
                  "skipped": len(result["skipped"]),
                  "archived": len(result["archived"]),
                  "landed": len(result["landed"]),
                  "playbook": result["playbook"]}
        _emit_production_row(ws, "harvest_scan", detail=detail)
        for cand in result["candidates"]:
            _emit_production_row(ws, "script_harvested", detail={
                "phase": "classified", "name": cand["name"],
                "script": cand["script"], "signals": cand["signals"],
                "facts": cand["facts"]})
        for arch in result["archived"]:
            _emit_production_row(ws, "script_harvested", detail={
                "phase": "archived", "name": arch.get("name"),
                "script": arch.get("script"), "reason": arch["reason"]})
        for landed in result["landed"]:
            _emit_production_row(ws, "harvest_landed",
                                 tool=landed["tool_path"], detail={
                                     "name": landed["name"],
                                     "script": landed["script"],
                                     "tool_path": landed["tool_path"]})
        print(json.dumps(result, sort_keys=True))
        return 0
    ap.print_usage()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

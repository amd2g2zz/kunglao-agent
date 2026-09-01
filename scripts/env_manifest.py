#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""env_manifest.py — environment facts single source of truth (#450).

WHY: environment attributes had no machine-readable carrier — they were
scattered across doc caches (expire), snapshot-implicit state (nobody
remembers), and oral experience (does not transfer). Every new session
re-discovered them by wall-banging (issue #450 evidence 1: VM identity by
oral correction, doc IPs stale on first DHCP rotation, a frida start
command pointing at a nonexistent file, snapshot semantics nobody
recorded, VPMC breakage re-hit 4 days later, guest-exec channel difference
found only after repeated 60s hangs).

This module is the FACT side of the environment model. The REQUIREMENT
side ("does THIS task need the VM channel") is #449's
requirements_from_task_spec — consumed here, never modified.

Priority chain (issue design direction):
  1. <workspace>/env-facts.yaml  (user- or probe-written facts)
  2. #449 Requirements derivation    (task_spec constraints.dynamic_re)
  3. conservative default            (VM required, no invented facts)

Filename note (F1 fix, review 2026-08-19): the facts file is
env-facts.yaml, NOT env-manifest.yaml — the old name collides with the
#478 deployment ledger that kunglao-init deploy_env writes into every
workspace ({generated, project_type, components}). Ledger content found
at EITHER name is a stop event (ValueError with guidance), never a
silently-consumed manifest; probe reads/writes env-facts.yaml only, so
init's ledger rewrite can never clear recorded env facts.

Hard rules:
  * single loading point load_manifest — absent -> None; garbage /
    unreadable / non-mapping / ledger-shaped -> ValueError fail-closed
    (#449 M2 mirror: garbage never silently produces invented
    environment facts);
  * concrete values (IPs, VMX paths, start commands, repair-script names)
    are MANIFEST DATA, never code defaults — code carries only policy
    (DHCP live-discovery, cached IPs forbidden) and generic guidance;
  * layout consumers (dispatch_gate._resolve_workspace /
    convergence_check._resolve_ws / lib_kunglao.iter_worker_states) read
    names from here; absent manifest -> DEFAULT_LAYOUT, the pre-#450
    literals, byte-identical (backward-compat anchor).

CLI: env_manifest.py <workspace> [--render | --probe | --json]
     --render  env documentation section (markdown; garbage -> exit 1)
     --probe   minimal discovery via vmrun (list / listSnapshots /
               checkToolsState), merged WITHOUT clobbering user fields;
               discovery failure fails OPEN (guidance, exit 0)
Exit codes: 0 = ok, RC_MANIFEST_DEFECT (1) = manifest present but garbage.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

# UTF-8 stdout unification (same pattern as toolchain.py)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

MANIFEST_FILENAME = "env-facts.yaml"
# Pre-rename facts name (#450 governance 2026-08-19: it collided with the
# #478 deploy ledger). Now the #478 ledger's own name — load_manifest
# checks it as a fallback but a ledger-shaped file there raises.
LEGACY_MANIFEST_FILENAME = "env-manifest.yaml"

# The #478 deploy_env ledger shape (kunglao-init.py writes exactly this):
# no version key, has generated/project_type/components. F1 collision
# detector — this content is an install record, never environment facts.
_DEPLOY_LEDGER_KEYS = ("generated", "project_type", "components")

MANIFEST_VERSION = 1

RC_OK = 0
RC_MANIFEST_DEFECT = 1

# The marker the CLAUDE.md template's unconditional line carries (#449
# leftover conditionalization target — single source for the marker string).
VM_REQUIRED_MARKER = "**VM required**"


@dataclass(frozen=True)
class SnapshotSemantics:
    """Snapshot semantics (issue #450 evidence: analysis-ready had no
    autologin and the login-state repair chain never fired)."""
    name: str | None = None
    autologin: bool | None = None      # None = not recorded
    rollback_fix: str | None = None    # repair step to run AFTER revert


@dataclass(frozen=True)
class VmIdentity:
    """Analysis VM identity. vmx_path/frida_start are DATA (user/probe);
    ip_discovery is POLICY: live DHCP — cached IPs are forbidden (issue
    evidence: one doc IP wrong on the first of three lease rotations)."""
    vmx_path: str | None = None
    ip_discovery: str = "live-dhcp"
    snapshot: SnapshotSemantics = SnapshotSemantics()
    vpmc_compatible: bool | None = None  # None = not recorded
    frida_start: str | None = None


@dataclass(frozen=True)
class GuestChannel:
    """Guest exec channel difference (issue #450 evidence:
    runProgramInGuest hangs permanently under legacy VMware Tools 12416;
    runScriptInGuest returns instantly — found only after repeated hangs)."""
    preferred: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class LayoutConventions:
    """Deployment layout convention names — the strings that used to be
    hardcoded in dispatch_gate / convergence_check / lib_kunglao."""
    workspace_dir: str = "malware-analysis-workspace"
    claim_register: str = "claim-register.yaml"
    worker_worktree_glob: str = ".wt-*"
    worker_worktree_marker: str = ".kunglao-worktree"
    runs_dir: str = "runs"


# The backward-compatibility anchor: these ARE the pre-#450 literals. The
# three layout consumers get every name from here; absent manifest ->
# behavior byte-identical to pre-#450 (pinned by tests + renderer goldens).
DEFAULT_LAYOUT = LayoutConventions()

DEFAULT_VM = VmIdentity()
DEFAULT_GUEST_CHANNEL = GuestChannel()

DEFAULT_MANIFEST_BASIS = ("no env-facts, no task_spec — conservative "
                          "default (VM required)")


@dataclass(frozen=True)
class EnvManifest:
    """Resolved environment fact set (all five #450 fact families + the
    layout conventions + the derived requirement)."""
    needs_vm: bool = True
    basis: str = DEFAULT_MANIFEST_BASIS
    vm: VmIdentity = DEFAULT_VM
    guest_channel: GuestChannel = DEFAULT_GUEST_CHANNEL
    layout: LayoutConventions = DEFAULT_LAYOUT
    source: str = "default"  # manifest-file | task-spec | default


DEFAULT_MANIFEST = EnvManifest()


# ---------- single loading point (fail-closed, #449 M2 mirror) ----------

def _require_mapping(value, what: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be a YAML mapping")
    return value


def _is_deploy_ledger(data: dict) -> bool:
    """#478 deploy_env ledger shape: no version key, has the three ledger
    keys. A facts manifest that omits version only loads when it does NOT
    carry the ledger trio, so the discriminator is exact — the ledger is
    the only writer of {generated, project_type, components}."""
    return ("version" not in data
            and all(k in data for k in _DEPLOY_LEDGER_KEYS))


def _load_manifest_file(path: Path) -> dict | None:
    """Parse ONE candidate file (shared by both names). Empty -> None;
    unparseable / unreadable / non-mapping / ledger shape / unsupported
    version -> ValueError (same fail-closed family)."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"{path.name} unparseable: {exc}") from exc
    except OSError as exc:
        # PermissionError / locked file shares the unparseable route (the
        # UnicodeDecodeError path stays inside the ValueError family too).
        raise ValueError(f"{path.name} unreadable: {exc}") from exc
    if data is None:
        return None
    _require_mapping(data, path.name)
    if _is_deploy_ledger(data):
        raise ValueError(
            f"{path.name} holds the #478 deployment ledger shape "
            f"({{{', '.join(_DEPLOY_LEDGER_KEYS)}}}, no version) — that is "
            "deploy_env's install record, not environment facts, and is "
            "never consumed as a manifest. Environment facts live in "
            f"{MANIFEST_FILENAME} (renamed from {LEGACY_MANIFEST_FILENAME}, "
            "issue #450 governance 2026-08-19: the old name collides with "
            "the #478 ledger). Record facts there by hand or via --probe.")
    version = data.get("version", MANIFEST_VERSION)
    if version != MANIFEST_VERSION:
        raise ValueError(
            f"{path.name} version {version!r} unsupported "
            f"(expected {MANIFEST_VERSION})")
    return data


def load_manifest(ws: Path) -> dict | None:
    """Load <ws>/env-facts.yaml -> raw mapping; None when absent.

    Single loading point. Fail-closed on defect: unparseable, unreadable
    (Windows share lock / permission), non-mapping, an unsupported
    version, or #478 ledger content raises ValueError — garbage never
    silently becomes invented environment facts (mirror of #449
    load_task_spec review M2; consumers treat it as a stop event or fall
    back conservative with a warning).

    F1 collision defense: the pre-rename name env-manifest.yaml is read
    as a fallback only when env-facts.yaml is absent. A version-carrying
    manifest written before the rename still loads; the #478 deploy
    ledger (present in every init'd workspace) raises with guidance
    instead of being parsed as a manifest — previously it silently
    resolved with source "manifest-file".
    """
    path = Path(ws) / MANIFEST_FILENAME
    if path.exists():
        return _load_manifest_file(path)
    legacy = Path(ws) / LEGACY_MANIFEST_FILENAME
    if not legacy.exists():
        return None
    return _load_manifest_file(legacy)


# ---------- per-family parsing (strict where ambiguity would mislead) ----------

def _parse_snapshot(raw) -> SnapshotSemantics:
    if raw is None:
        return SnapshotSemantics()
    _require_mapping(raw, "vm.snapshot")
    autologin = raw.get("autologin")
    if autologin is not None and not isinstance(autologin, bool):
        raise ValueError("vm.snapshot.autologin must be a boolean")
    name = raw.get("name")
    fix = raw.get("rollback_fix")
    if name is not None and not isinstance(name, str):
        raise ValueError("vm.snapshot.name must be a string")
    if fix is not None and not isinstance(fix, str):
        raise ValueError("vm.snapshot.rollback_fix must be a string")
    return SnapshotSemantics(name=name or None, autologin=autologin,
                             rollback_fix=fix or None)


def _parse_vm(raw) -> VmIdentity:
    if raw is None:
        return DEFAULT_VM
    _require_mapping(raw, "vm")
    vpmc = raw.get("vpmc_compatible")
    if vpmc is not None and not isinstance(vpmc, bool):
        raise ValueError("vm.vpmc_compatible must be a boolean")
    for key in ("vmx_path", "frida_start", "ip_discovery"):
        v = raw.get(key)
        if v is not None and not isinstance(v, str):
            # F3: no silent str() coercion — a non-string ip_discovery
            # (e.g. [cached]) is a defect in the same fail-closed family
            # as the bool/str checks, never "['cached']".
            raise ValueError(f"vm.{key} must be a string")
    return VmIdentity(
        vmx_path=raw.get("vmx_path") or None,
        ip_discovery=raw.get("ip_discovery") or "live-dhcp",
        snapshot=_parse_snapshot(raw.get("snapshot")),
        vpmc_compatible=vpmc,
        frida_start=raw.get("frida_start") or None,
    )


def _parse_guest_channel(raw) -> GuestChannel:
    if raw is None:
        return DEFAULT_GUEST_CHANNEL
    _require_mapping(raw, "guest_channel")
    for key in ("preferred", "notes"):
        v = raw.get(key)
        if v is not None and not isinstance(v, str):
            raise ValueError(f"guest_channel.{key} must be a string")
    return GuestChannel(preferred=raw.get("preferred") or None,
                        notes=raw.get("notes") or None)


def _parse_layout(raw) -> LayoutConventions:
    """Per-field merge over DEFAULT_LAYOUT; present-but-empty/garbage
    fields are a DEFECT (they would silently change discovery), not a
    silent fallback to the default."""
    if raw is None:
        return DEFAULT_LAYOUT
    _require_mapping(raw, "layout")
    fields: dict[str, str] = {}
    for key in ("workspace_dir", "claim_register", "worker_worktree_glob",
                "worker_worktree_marker", "runs_dir"):
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"layout.{key} must be a non-empty string")
        fields[key] = value
    return replace(DEFAULT_LAYOUT, **fields)


# ---------- resolve: the priority chain ----------

def _derive_from_task_spec(ws: Path) -> EnvManifest:
    """Priority 2/3: #449 Requirements derivation (consumed, unmodified).

    A garbage task_spec keeps the conservative default (WARNING + needs_vm
    stays True — same posture as #449's toolchain main); it never produces
    a conditioned VM line off unreadable facts."""
    try:
        import toolchain as tc
        spec = tc.load_task_spec(Path(ws))
    except ValueError as exc:
        print(f"WARNING: {exc} — env manifest stays conservative "
              f"(VM required)", file=sys.stderr)
        return DEFAULT_MANIFEST
    if spec is None:
        return DEFAULT_MANIFEST
    reqs = tc.requirements_from_task_spec(spec)
    return EnvManifest(needs_vm=reqs.needs_vm, basis=reqs.basis,
                       source="task-spec")


def resolve(ws: Path) -> EnvManifest:
    """Resolve the environment fact set for a workspace.

    Priority: env-facts.yaml (explicit needs_vm wins when present) >
    #449 task_spec derivation > conservative default. Propagates
    load_manifest's ValueError — the STRICT fail-closed surface (render /
    CLI treat garbage — or #478 ledger content — as a stop event). Hook
    hot paths use layout_conventions / vm_requirement_for, which never
    raise.
    """
    raw = load_manifest(ws)
    if raw is None:
        return _derive_from_task_spec(ws)

    derived = _derive_from_task_spec(ws)
    needs_vm = raw.get("needs_vm")
    if needs_vm is not None and not isinstance(needs_vm, bool):
        raise ValueError("needs_vm must be a boolean when present")
    if needs_vm is None:
        # the manifest is silent on the requirement (probe never writes
        # it) -> fall through to the task_spec derivation; a probe-written
        # default file must not re-harden a static-only workspace.
        return EnvManifest(
            needs_vm=derived.needs_vm, basis=derived.basis,
            vm=_parse_vm(raw.get("vm")),
            guest_channel=_parse_guest_channel(raw.get("guest_channel")),
            layout=_parse_layout(raw.get("layout")),
            source="task-spec" if derived.source == "task-spec"
            else "manifest-file")
    return EnvManifest(
        needs_vm=needs_vm,
        basis=f"{MANIFEST_FILENAME} needs_vm={str(needs_vm).lower()}",
        vm=_parse_vm(raw.get("vm")),
        guest_channel=_parse_guest_channel(raw.get("guest_channel")),
        layout=_parse_layout(raw.get("layout")),
        source="manifest-file")


# ---------- hook-hot-path wrappers (never raise) ----------

def _manifest_path(base: Path) -> Path | None:
    """Bootstrap discovery: the manifest sits at base/ (base IS the
    workspace) or base/<default workspace dir>/ (base is the parent).
    Discovery necessarily uses the DEFAULT name — the only place that
    bootstrap literal lives (D3); an overridden workspace_dir changes
    where claim-register is probed, not where the manifest is sought.
    The legacy name is deliberately NOT a candidate here: the #478 deploy
    ledger sits there in every init'd workspace and must neither steer
    discovery nor warn on every dispatch (load_manifest still examines
    it as a strict fallback for explicit resolve/render/probe calls)."""
    for cand in (Path(base) / MANIFEST_FILENAME,
                 Path(base) / DEFAULT_LAYOUT.workspace_dir / MANIFEST_FILENAME):
        if cand.exists():
            return cand
    return None


def layout_conventions(base: Path) -> LayoutConventions:
    """Layout names for code consumers — NEVER raises (hook hot path:
    dispatch_gate runs this on every Agent dispatch).

    Absent manifest -> DEFAULT_LAYOUT (byte-identical pre-#450 behavior).
    Valid manifest -> its layout merged over the defaults. Garbage ->
    DEFAULT_LAYOUT + one stderr warning — the conservative posture of #449
    (WARNING + conservative HARD); the STRICT fail-closed surface is
    load_manifest/resolve (render treats garbage as a stop event).
    """
    path = _manifest_path(base)
    if path is None:
        return DEFAULT_LAYOUT
    try:
        raw = load_manifest(path.parent)
    except ValueError as exc:
        print(f"WARNING: {exc} — layout falls back to default conventions "
              f"", file=sys.stderr)
        return DEFAULT_LAYOUT
    try:
        return _parse_layout(raw.get("layout"))
    except ValueError as exc:
        print(f"WARNING: {exc} — layout falls back to default conventions "
              f"", file=sys.stderr)
        return DEFAULT_LAYOUT


def vm_requirement_for(ws: Path) -> tuple[bool, str] | None:
    """(needs_vm, basis) for the CLAUDE.md "VM required" line (#449
    leftover conditionalization).

    None = no reliable answer — absent inputs, OR a garbage manifest
    (conservative unconditional line + one stderr warning, never a
    conditioned line based on unreadable facts). Callers keep the
    unconditional line on None/True, byte-identical to pre-#450."""
    try:
        m = resolve(ws)
    except ValueError as exc:
        print(f"WARNING: {exc} — 'VM required' line stays unconditional "
              f"", file=sys.stderr)
        return None
    if m.source == "default":
        return None
    return (m.needs_vm, m.basis)


def conditionalize_vm_required(section: str, basis: str) -> str:
    """Replace the '- **VM required**: ...' line with the not-required
    line carrying the basis. Line-scoped: every other line is untouched;
    a section without the marker passes through unchanged (android)."""
    out: list[str] = []
    replaced = False
    for line in section.splitlines():
        if (not replaced and line.lstrip().startswith("-")
                and VM_REQUIRED_MARKER in line):
            out.append(
                "- **VM not required**: " + basis + " — VM channel "
                "informational (WARN), not a T2+ hard requirement for "
                "this task.")
            replaced = True
        else:
            out.append(line)
    return "\n".join(out)


# ---------- render: env documentation section ----------

def _snapshot_line(m: EnvManifest) -> str:
    snap = m.vm.snapshot
    if snap.name is None and snap.autologin is None \
            and snap.rollback_fix is None:
        return ("- Snapshot: semantics not recorded — verify autologin "
                "state and locate the rollback repair step BEFORE "
                "reverting")
    detail = []
    if snap.autologin is None:
        detail.append("autologin not recorded — verify before relying on "
                      "post-revert logon")
    else:
        detail.append(f"autologin: {'yes' if snap.autologin else 'no'}"
                      + (" (run the rollback repair after revert)"
                         if not snap.autologin else ""))
    if snap.rollback_fix:
        detail.append(f"rollback repair: {snap.rollback_fix}")
    return ("- Snapshot: " + (snap.name or "(name not recorded)")
            + " (" + "; ".join(detail) + ")")


def _vpmc_line(m: EnvManifest) -> str:
    if m.vm.vpmc_compatible is None:
        return ("- VPMC: compatibility not recorded — if VM power-on "
                "fails with \"Module 'VPMC' power on failed\", set "
                "vm.vpmc_compatible=false and strip vpmc.enable from "
                "the VMX")
    if m.vm.vpmc_compatible:
        return "- VPMC: compatible with this host (recorded)"
    return ("- VPMC: incompatible with this host (recorded) — do not set "
            "vpmc.enable=TRUE in the VMX (nested-virtualization hosts "
            "fail power-on)")


def _channel_line(m: EnvManifest) -> str:
    gc = m.guest_channel
    if gc.preferred is None and gc.notes is None:
        return ("- Guest exec channel: preference not recorded — known "
                "pitfall: runProgramInGuest can hang under legacy VMware "
                "Tools; prefer runScriptInGuest")
    pref = gc.preferred or "(preference not recorded)"
    return f"- Guest exec channel: prefer {pref}" + \
        (f" — {gc.notes}" if gc.notes else "")


def render_section(m: EnvManifest) -> str:
    """The env documentation section (--render). Every concrete value
    comes from manifest DATA; absent facts render as honest unknowns with
    generic guidance (never invented)."""
    channel = ("REQUIRED" if m.needs_vm else "NOT REQUIRED")
    lines = [
        "## Environment (env-facts)",
        "",
        f"- VM channel: {channel} (basis: {m.basis})",
    ]
    if m.vm.vmx_path:
        lines.append(f"- VM identity: {m.vm.vmx_path}")
    else:
        lines.append(
            "- VM identity: unknown — run "
            "`python scripts/env_manifest.py <workspace> --probe` "
            "(vmrun list / listSnapshots / checkToolsState) to record it")
    if m.vm.ip_discovery == "live-dhcp":
        lines.append("- IP discovery: live DHCP (cached IPs forbidden — "
                     "leases rotate within a session)")
    else:
        lines.append(f"- IP discovery: {m.vm.ip_discovery}")
    lines.append(_snapshot_line(m))
    lines.append(_vpmc_line(m))
    lines.append(_channel_line(m))
    if m.vm.frida_start:
        lines.append(f"- frida start: {m.vm.frida_start}")
    return "\n".join(lines) + "\n"


# ---------- probe: minimal discovery entry (fail-open) ----------

# SEAM (repo pattern, toolchain_install.py): subprocess/which through
# private names so tests inject deterministic vmrun outputs.
_subprocess_run = subprocess.run
_shutil_which = shutil.which


def _run(args: list[str], timeout: int = 10) -> tuple[int, str, str]:
    """Run a command with timeout; fail-open (1, '', exc) on crash."""
    try:
        r = _subprocess_run(args, capture_output=True, text=True,
                            timeout=timeout, encoding="utf-8",
                            errors="replace")
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError) as exc:
        return 1, "", str(exc)


def _probe_facts() -> tuple[dict | None, list[str]]:
    """Discover the VM facts read-only (vmrun list / listSnapshots /
    checkToolsState — PRESENCE/LIVENESS probes only; capability trials are
    init-only by the #474 contract). Returns (updates, guidance).

    updates is None when discovery failed — callers fail OPEN (guidance,
    exit 0): a missing probe must never block (#450 evidence 3)."""
    vmrun = _shutil_which("vmrun")
    if not vmrun:
        return None, [
            "probe: vmrun not found on PATH — conservative defaults kept, "
            "nothing written.",
            "guidance: install VMware Workstation/Player (vmrun on PATH), "
            "or record the environment facts by hand in "
            f"{MANIFEST_FILENAME}, then re-run --probe",
        ]
    rc, out, err = _run([vmrun, "list"])
    if rc != 0:
        return None, [
            f"probe: vmrun list failed ({err or out[:80]}) — conservative "
            "defaults kept, nothing written.",
            "guidance: fix vmrun (license/PATH), then re-run --probe",
        ]
    vmx_paths = [ln.strip() for ln in out.splitlines()
                 if ln.strip().lower().endswith(".vmx")]
    if not vmx_paths:
        return None, [
            "probe: no running VMs — conservative defaults kept, nothing "
            "written.",
            "guidance: start the analysis VM, then re-run --probe",
        ]
    vmx = vmx_paths[0]
    updates: dict = {"vm": {"vmx_path": vmx}}
    rc, out, err = _run([vmrun, "checkToolsState", vmx])
    if rc == 0 and out:
        updates["guest_channel"] = {
            "notes": f"vmrun checkToolsState={out.splitlines()[0].strip()} "
            "(runProgramInGuest can hang under legacy VMware Tools; "
            "prefer runScriptInGuest)",
        }
    rc, out, err = _run([vmrun, "listSnapshots", vmx])
    if rc == 0:
        snaps = [ln.strip() for ln in out.splitlines()
                 if ln.strip() and not ln.strip().lower()
                 .startswith("total snapshots")]
        if snaps:
            updates["vm"]["snapshot"] = {"name": snaps[0]}
    return updates, [f"probe: recorded VM {vmx}"]


def _merge(existing: dict, updates: dict) -> dict:
    """Deep merge where EXISTING leaf values win (user/probe-written
    facts have priority 1): probe fills gaps, never overwrites. Re-probing
    after switching VMs requires deleting the stale vmx_path first
    (documented behavior, minimal probe)."""
    out = dict(existing)
    for k, v in updates.items():
        if isinstance(v, dict):
            base = out.get(k)
            out[k] = _merge(base if isinstance(base, dict) else {}, v)
        elif k not in out or out.get(k) is None:
            out[k] = v
    return out


def _cmd_probe(ws: Path) -> int:
    """Probe owns env-facts.yaml ONLY (F1): the legacy name is the #478
    deploy ledger's — never read here (no ledger consumption on any
    path), never rewritten (init keeps its own record intact)."""
    path = Path(ws) / MANIFEST_FILENAME
    existing = None
    if path.exists():
        try:
            existing = _load_manifest_file(path)
        except ValueError as exc:
            print(f"ERROR: {exc} — refusing to overwrite (fix "
                  f"{path} by hand)", file=sys.stderr)
            return RC_MANIFEST_DEFECT
    legacy = Path(ws) / LEGACY_MANIFEST_FILENAME
    if legacy.exists():
        print(f"probe: {LEGACY_MANIFEST_FILENAME} present — that name "
              "belongs to the deployment ledger (or a pre-rename "
              f"facts file); probe never reads or writes it. Facts go in "
              f"{MANIFEST_FILENAME}; merge any pre-rename facts by hand.")
    updates, notes = _probe_facts()
    for n in notes:
        print(n)
    if updates is None:
        return RC_OK  # fail-open: discovery failure never blocks
    merged = _merge(existing or {}, {"version": MANIFEST_VERSION})
    merged = _merge(merged, updates)
    path.write_text(yaml.safe_dump(merged, sort_keys=False,
                                   allow_unicode=True), encoding="utf-8")
    print(f"probe: wrote {path} (user fields preserved; needs_vm left to "
          "task_spec derivation)")
    return RC_OK


# ---------- #477 ④: installed ledger (write-through bookkeeping) ----------

def record_installed(ws: Path, name: str, manager: str, reprobe: str,
                     at: str | None = None) -> bool:
    """Merge ONE install-ledger entry into <ws>/env-facts.yaml (#477 ④).

    installed.<name> = {manager, at, reprobe} — the write-through
    bookkeeping face of the facts file: resolve() does not consume it
    (it is orthogonal to the five fact families), and the #478
    deploy-ledger shape detector can never fire on it (version is always
    present). Per-tool UPDATE-WINS: re-installing a tool replaces its
    stale entry (the ledger records the LATEST state — deliberately
    unlike _merge's existing-wins gap-filling); every OTHER top-level
    key survives untouched.

    Returns False (stderr guidance, nothing written) when the existing
    file is a defect — same refuse-to-clobber posture as --probe; the
    caller's install loop treats the ledger as fail-open bookkeeping.
    Non-string fields raise ValueError (fail-closed family — a list
    reprobe value is a defect, never str()-coerced).
    """
    for label, value in (("name", name), ("manager", manager),
                         ("reprobe", reprobe)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"installed-ledger {label} must be a "
                             f"non-empty string, got {value!r}")
    path = Path(ws) / MANIFEST_FILENAME
    existing: dict | None = None
    if path.exists():
        try:
            existing = _load_manifest_file(path)
        except ValueError as exc:
            print(f"ERROR: {exc} — installed ledger refusing to overwrite "
                  f"(fix {path} by hand)", file=sys.stderr)
            return False
    from datetime import datetime, timezone
    entry = {
        "manager": manager,
        "at": at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reprobe": reprobe,
    }
    merged = dict(existing or {})
    merged["version"] = MANIFEST_VERSION
    installed = dict(merged.get("installed") or {})
    installed[name] = entry           # per-tool update-wins (docstring)
    merged["installed"] = installed
    path.write_text(yaml.safe_dump(merged, sort_keys=False,
                                   allow_unicode=True), encoding="utf-8")
    return True


# ---------- main ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="env_manifest",
        description="Environment facts single source",
    )
    parser.add_argument("workspace", help="workspace root path")
    parser.add_argument("--render", action="store_true",
                        help="emit the env documentation section (markdown)")
    parser.add_argument("--probe", action="store_true",
                        help="discover VM facts via vmrun and write the "
                             "manifest (fail-open; merges, never clobbers)")
    parser.add_argument("--json", action="store_true",
                        help="emit the resolved manifest as JSON (default)")
    args = parser.parse_args(argv)

    ws = Path(args.workspace).resolve()
    if args.probe:
        return _cmd_probe(ws)
    try:
        m = resolve(ws)
    except ValueError as exc:
        print(f"ERROR: {exc} — fail-closed (fix "
              f"{ws / MANIFEST_FILENAME})", file=sys.stderr)
        return RC_MANIFEST_DEFECT
    if args.render:
        print(render_section(m))
        return RC_OK
    print(json.dumps({
        "source": m.source,
        "needs_vm": m.needs_vm,
        "basis": m.basis,
        "vm": {
            "vmx_path": m.vm.vmx_path,
            "ip_discovery": m.vm.ip_discovery,
            "snapshot_name": m.vm.snapshot.name,
            "snapshot_autologin": m.vm.snapshot.autologin,
            "snapshot_rollback_fix": m.vm.snapshot.rollback_fix,
            "vpmc_compatible": m.vm.vpmc_compatible,
            "frida_start": m.vm.frida_start,
        },
        "guest_channel": {"preferred": m.guest_channel.preferred,
                          "notes": m.guest_channel.notes},
        "layout": {
            "workspace_dir": m.layout.workspace_dir,
            "claim_register": m.layout.claim_register,
            "worker_worktree_glob": m.layout.worker_worktree_glob,
            "worker_worktree_marker": m.layout.worker_worktree_marker,
            "runs_dir": m.layout.runs_dir,
        },
    }, indent=2, ensure_ascii=False))
    return RC_OK


if __name__ == "__main__":
    from utf8_boot import force_utf8  # #811 入口 UTF-8 保险
    force_utf8()
    sys.exit(main())

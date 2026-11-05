#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""runtime_switches.py — the single registry for runtime switches.

Every keyed environment read in hooks/, scripts/ and devkit/ resolves
through this module. The registry is the ONE place that declares a
switch's name, type, default, owning face, safety direction and declared-
values surface; readers call ``get`` / the typed helpers instead of
touching ``os.environ`` directly.

SAFETY DIRECTION

  supply      knowledge/context supply — silence defaults ON, because a
              missing supply face silently starves every rollout;
  protection  guards and bounds — silence defaults ON, because a missing
              guard is the failure it exists to prevent;
  learning    learning-state and ablation faces — silence defaults OFF,
              because an arm that forgets to declare a learning switch
              would silently learn (or silently ablate) and contaminate
              every comparison read from it;
  ops         timeouts, paths, host configuration — no polarity rule;
              the documented default is simply the previous behavior.

FAIL-CLOSED BOUNDARY

  * an undeclared NAME raises ValueError (no silent default);
  * an unparseable BOOLEAN value raises ValueError (no silent guess);
  * numeric garbage falls back to the declared default (the value layer
    stays fail-open for the operational knobs, whose call sites carry
    their own bounded fallbacks).

ALLOWLISTED RAW READS

A handful of reads are deliberately NOT routed through the registry —
they are environment snapshots rather than switches, and their call
sites own the fallback semantics. Each still gets a registry entry (so
the scanner can prove the name is declared) and an allowlist reason:

  * KUNGLAO_PROBE_TIMEOUT_FLOOR — a local test-harness floor; the call
    site parses it inline and applies it to one probe timeout;
  * KUNGLAO_E2E_MAX_PARALLEL — a floor-1 wave bound parsed at call time
    by the e2e checkpoint scheduler;
  * GITHUB_SHA — the CI tarball-runner revision fallback, not a
    kunglao-controlled switch.

The registry is stdlib-only and pure: no I/O, no module state mutation.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

TYPES = ("bool", "int", "float", "str", "path")
DIRECTIONS = ("supply", "protection", "learning", "ops")
DECLARED_FACES = ("arm", "operator")

SCHEMA = "runtime-switches/1"

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True)
class Switch:
    """One declared runtime switch."""

    name: str
    type: str
    default: Any
    direction: str
    declared: str
    owner: str
    doc: str
    allowlist_reason: str = ""


#: (name, type, default, direction, declared face, owner, doc[, allowlist])
_ENTRIES: tuple[tuple, ...] = (
    # ---------------------------------------------------------- supply
    ("KUNGLAO_RECALL", "bool", True, "supply", "arm",
     "hooks/recall_inject.py",
     "recall-history dispatch injection; ON by default, exact 0 ablates"),
    # ------------------------------------------------------ protection
    ("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "str", "", "protection",
     "operator", "hooks/env_check_gate.py",
     "agent-teams flag; any truthy value rejects the dispatch"),
    ("KUNGLAO_VERIFY_STALE_TICKS", "float", 12.0, "protection", "operator",
     "scripts/convergence_check.py",
     "stale-verification threshold in ticks"),
    ("KUNGLAO_T1_MIN_WRITES", "int", 6, "protection", "operator",
     "scripts/verification_ladder.py",
     "minimum verified writes before a tier-1 round credit"),
    ("KUNGLAO_T1_MIN_INTERVAL_MIN", "float", 30.0, "protection", "operator",
     "scripts/verification_ladder.py",
     "debounce floor between tier-1 probe batches, minutes"),
    ("KUNGLAO_T2_STALL_MIN", "float", 60.0, "protection", "operator",
     "scripts/verification_ladder.py",
     "tier-2 stall threshold, minutes"),
    ("KUNGLAO_PREMISE_EXPIRY_TICKS", "int", 12, "protection", "operator",
     "scripts/premise_gate.py",
     "premise expiry sweep horizon, ticks"),
    ("KUNGLAO_NOOP_BREAKER_N", "int", 6, "protection", "operator",
     "scripts/heartbeat_tick.py",
     "consecutive noop ticks before the heartbeat breaker trips"),
    ("KUNGLAO_CRASHED_STOP_N", "int", 3, "protection", "operator",
     "scripts/e2e/checkpoints.py",
     "consecutive crashed acts before the loop stops"),
    ("KUNGLAO_LIVENESS_WS", "str", "", "protection", "operator",
     "devkit/quality_gates.py",
     "liveness workspace; unset -> the documented loud local SKIP, "
     "set-but-invalid -> the gate failure path"),
    # ------------------------------------------------------- learning
    ("KUNGLAO_PREDICT_BEFORE_TRY", "bool", False, "learning", "arm",
     "scripts/intake_promise.py",
     "feature-conditioned prior activation; OFF unless an arm declares it"),
    ("KUNGLAO_META_RETRIEVAL", "bool", False, "learning", "arm",
     "scripts/rlvr/meta_policy.py",
     "meta-policy retrieval component; OFF unless declared"),
    ("KUNGLAO_META_VALUE_TABLE", "bool", False, "learning", "arm",
     "scripts/rlvr/meta_policy.py",
     "meta-policy value-table component; OFF unless declared"),
    ("KUNGLAO_META_ATTRIBUTION", "bool", False, "learning", "arm",
     "scripts/rlvr/attribution.py",
     "learned method attribution; OFF unless declared"),
    ("KUNGLAO_META_PLAYBOOK", "bool", False, "learning", "arm",
     "scripts/rlvr/playbook.py",
     "compressed playbook context; OFF unless declared"),
    ("KUNGLAO_META_W_REWARD", "float", 1.0, "learning", "operator",
     "scripts/rlvr/meta_policy.py", "value-table reward weight"),
    ("KUNGLAO_META_W_COST", "float", 0.5, "learning", "operator",
     "scripts/rlvr/meta_policy.py", "value-table cost weight"),
    ("KUNGLAO_META_W_PRIOR", "float", 1.0, "learning", "operator",
     "scripts/rlvr/meta_policy.py", "value-table prior weight"),
    ("KUNGLAO_META_N_SHRINK", "float", 4.0, "learning", "operator",
     "scripts/rlvr/meta_policy.py", "value-table shrinkage strength"),
    ("KUNGLAO_META_W_CITATION", "float", 2.0, "learning", "operator",
     "scripts/rlvr/meta_policy.py", "utility-score citation weight"),
    ("KUNGLAO_META_W_RETRIEVAL", "float", 1.0, "learning", "operator",
     "scripts/rlvr/meta_policy.py", "utility-score retrieval weight"),
    ("KUNGLAO_META_RETRIEVE_MAX", "int", 3, "learning", "operator",
     "scripts/rlvr/meta_policy.py", "retrieved case budget"),
    ("KUNGLAO_META_MIN_UTILITY", "float", 0.0, "learning", "operator",
     "scripts/rlvr/meta_policy.py", "minimum utility for a retrieved case"),
    ("KUNGLAO_DIRECTION", "bool", False, "learning", "operator",
     "scripts/rlvr/direction.py",
     "direction-posterior face; exact 1 enables"),
    ("KUNGLAO_EVAL_SETTLE", "bool", False, "learning", "operator",
     "scripts/rlvr/settlement_wire.py",
     "unblinded eval settlement judgment; exact 1 opts in"),
    ("KUNGLAO_PLAYBOOK", "bool", False, "learning", "operator",
     "scripts/eval_loop_runner.py",
     "family playbook session block; exact 1 enables"),
    ("KUNGLAO_SCHEDULER", "str", "", "learning", "operator",
     "scripts/e2e/checkpoints.py",
     "scheduler face; exact uniform flattens the learned prior"),
    # ------------------------------------------------------------ ops
    ("KUNGLAO_WG_DEBUG", "bool", False, "ops", "operator",
     "hooks/write_guard.py", "write-guard debug lines; exact 1 enables"),
    ("KUNGLAO_WARN_BREAKER_ACTION", "str", "", "ops", "operator",
     "hooks/gate_policy.py",
     "ownership action when a warn family trips the bound"),
    ("KUNGLAO_VM_HOST", "str", "", "ops", "operator",
     "scripts/env_check.py", "VM/dynamic-channel host"),
    ("KUNGLAO_VM_SHELL_PORT", "str", "9876", "ops", "operator",
     "scripts/toolchain.py",
     "VM shell port (validated by the call-site defensive parser)"),
    ("KUNGLAO_FRIDA_PORT", "str", "1337", "ops", "operator",
     "scripts/toolchain.py",
     "frida server port (validated by the call-site defensive parser)"),
    ("KUNGLAO_MECH_BUDGET_S", "float", 90.0, "ops", "operator",
     "scripts/mechanism_scheduler.py", "mechanism scheduler budget seconds"),
    ("KUNGLAO_SDK_PLUGIN_DIR", "str", "", "ops", "operator",
     "scripts/eval_sdk_session.py", "SDK session plugin root"),
    ("KUNGLAO_SDK_BUDGET_USD", "str", "", "ops", "operator",
     "scripts/eval_sdk_session.py", "SDK session budget"),
    ("KUNGLAO_SDK_MAX_TURNS", "str", "", "ops", "operator",
     "scripts/eval_sdk_session.py", "SDK session max turns"),
    ("KUNGLAO_SOLO_CAP_S", "float", 0.0, "ops", "operator",
     "scripts/eval_sdk_session.py", "solo-act wall cap"),
    ("KUNGLAO_POSTERIOR_STORE", "str", "", "ops", "operator",
     "scripts/rlvr/strategy_store.py",
     "cross-task posterior-store root override"),
    ("KUNGLAO_EVAL_ROOT", "str", "", "ops", "operator",
     "scripts/eval_dataset.py", "operator-local eval corpus root"),
    ("KUNGLAO_PLAYBOOK_ROOT", "str", "", "ops", "operator",
     "scripts/rlvr/family_playbook.py", "family playbook root override"),
    ("KUNGLAO_MODEL", "str", "", "ops", "operator",
     "scripts/rlvr/meta_arms.py", "model identity for the env fingerprint"),
    ("ANTHROPIC_MODEL", "str", "", "ops", "operator",
     "scripts/rlvr/meta_arms.py",
     "model identity fallback for the env fingerprint"),
    ("KUNGLAO_E2E_ACT_TIMEOUT_S", "int", 1800, "ops", "operator",
     "scripts/e2e/llm_faces.py",
     "one act-timeout default shared by the face and the fingerprint"),
    ("KUNGLAO_CHANNEL", "str", "local", "ops", "operator",
     "scripts/kunglao_log.py", "execution channel identity"),
    ("KUNGLAO_TOOL_DIRS", "str", "", "ops", "operator",
     "scripts/toolchain_negotiation.py",
     "os.pathsep-separated tool enumeration roots"),
    ("GHIDRA_HOME", "str", "", "ops", "operator",
     "scripts/pkg_detect.py", "Ghidra installation root"),
    ("TEMP", "str", "", "ops", "operator",
     "scripts/loop_state.py", "host temp root for task-output scans"),
    ("PATH", "str", "", "ops", "operator",
     "scripts/eval_tf_shadow.py",
     "host PATH for sandbox-environment construction"),
    ("TF_TOOLBOX", "str", "", "ops", "operator",
     "scripts/eval_toolflex.py", "toolflex toolbox directory override"),
    ("KUNGLAO_INIT_REPORT_KEEP", "int", 5, "ops", "operator",
     "scripts/kunglao-init.py", "init-report retention count"),
    ("KUNGLAO_UPGRADE_NO_UV_SYNC", "bool", False, "ops", "operator",
     "scripts/kunglao_upgrade.py",
     "upgrade venv-sync opt-out; exact 1 skips"),
    ("KUNGLAO_BENCH_VM_SNAPSHOT", "str", "", "ops", "operator",
     "scripts/bench_intake.py", "bench safety-check VM snapshot"),
    ("KUNGLAO_FRIDA_ALIAS", "str", "", "ops", "operator",
     "scripts/deploy_shim.py", "on-device frida binary alias"),
    ("VIRTUAL_ENV", "str", "", "ops", "operator",
     "scripts/mcp_repair.py", "active virtualenv root (pollution probe)"),
    ("APPDATA", "str", "", "ops", "operator",
     "scripts/toolchain.py", "VMware inventory root on Windows"),
    ("KUNGLAO_RHO_BACKEND", "str", "", "ops", "operator",
     "scripts/rho_verifier.py", "verifier backend selection"),
    ("KUNGLAO_RHO_ENDPOINT", "str", "", "ops", "operator",
     "scripts/rho_verifier.py", "LLM verifier endpoint"),
    ("KUNGLAO_LOOP_SESSION_CMD", "str", "", "ops", "operator",
     "scripts/eval_loop_runner.py", "session command override"),
    ("KUNGLAO_SANDBOX_PROFILE", "str", "", "ops", "operator",
     "scripts/eval_loop_runner.py", "sandbox seatbelt profile path"),
    ("KUNGLAO_HARNESS_ROOT", "str", "", "ops", "operator",
     "scripts/eval_loop_runner.py", "harness-drift fingerprint root"),
    ("KUNGLAO_GRADING_ROOT", "str", "", "ops", "operator",
     "scripts/eval_loop_runner.py", "grading oracle root (never shown)"),
    ("KUNGLAO_WAIT_POLL_S", "float", 20.0, "ops", "operator",
     "scripts/kunglao_wait.py", "wait-loop poll interval seconds"),
    ("KUNGLAO_WAIT_MAX_ROUNDS", "int", 90, "ops", "operator",
     "scripts/kunglao_wait.py", "wait-loop round cap"),
    ("GITHUB_SHA", "str", "unknown", "ops", "operator",
     "scripts/release_receipt.py",
     "CI tarball-runner revision fallback", "not a kunglao switch"),
    ("KUNGLAO_PROBE_TIMEOUT_FLOOR", "int", 0, "ops", "operator",
     "scripts/toolchain.py",
     "local test-harness probe timeout floor", "call-site inline floor"),
    ("KUNGLAO_VMRUN_PATH", "str", "", "ops", "operator",
     "scripts/toolchain.py", "vmrun binary override"),
    ("KUNGLAO_VBOXMANAGE_PATH", "str", "", "ops", "operator",
     "scripts/toolchain.py", "VBoxManage binary override"),
    ("KUNGLAO_AGENT_DO", "bool", False, "ops", "operator",
     "scripts/toolchain.py",
     "agent-owned repair tier authorization; exact 1 enables"),
    ("KUNGLAO_CLAUDE_JSON", "str", "", "ops", "operator",
     "scripts/toolchain.py", "claude.json override path"),
    ("KUNGLAO_IDA_APP_DIRS", "str", "", "ops", "operator",
     "scripts/toolchain.py", "IDA application roots"),
    ("KUNGLAO_DOCKER_CONTAINER", "str", "", "ops", "operator",
     "scripts/toolchain.py", "docker-over-ssh container name"),
    ("KUNGLAO_E2E_MAX_PARALLEL", "int", 3, "ops", "operator",
     "scripts/e2e/checkpoints.py",
     "e2e wave bound, floor 1", "call-site floor-1 parse"),
    ("KUNGLAO_LUBY_BASE_S", "int", 1800, "ops", "operator",
     "scripts/e2e/checkpoints.py", "Luby restart ladder base seconds"),
    ("KUNGLAO_EXPANSION", "bool", True, "ops", "operator",
     "scripts/e2e/checkpoints.py",
     "loop expansion move; exact 0 disables (pr-operational default)"),
    ("KUNGLAO_OUT", "str", "/out", "ops", "operator",
     "scripts/acceptance_check.py", "acceptance-check output root"),
    ("KUNGLAO_TIMEOUT", "int", 1800, "ops", "operator",
     "scripts/acceptance_check.py", "acceptance-check timeout seconds"),
    ("KUNGLAO_MUTATION_BUDGET", "int", 50, "ops", "operator",
     "scripts/acceptance_check.py", "acceptance-check mutation budget"),
    ("CLAUDE_SESSION_ID", "str", "", "ops", "operator",
     "scripts/verifier_identity.py", "authoring-session identity"),
)

SWITCHES: dict[str, Switch] = {row[0]: Switch(*row) for row in _ENTRIES}

#: raw reads deliberately left at their call sites (name -> files)
ALLOWLIST_SITES: dict[str, frozenset[str]] = {
    "KUNGLAO_PROBE_TIMEOUT_FLOOR": frozenset({"scripts/toolchain.py"}),
    "KUNGLAO_E2E_MAX_PARALLEL": frozenset(
        {"scripts/e2e/checkpoints.py"}),
    "GITHUB_SHA": frozenset({"scripts/release_receipt.py"}),
}


def spec(name: str) -> Switch:
    """The declared switch, or ValueError for an undeclared name."""
    try:
        return SWITCHES[name]
    except KeyError:
        raise ValueError(
            f"unknown runtime switch {name!r} — declare it in "
            "scripts/runtime_switches.py before reading it") from None


def raw(name: str, *, mapping: Mapping[str, str] | None = None) \
        -> str | None:
    """The raw environment value, or None when unset (declared names only)."""
    spec(name)
    env = os.environ if mapping is None else mapping
    return env.get(name)


def _parse_bool(name: str, value: str | None, default: bool) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return default
    if text in _TRUTHY:
        return True
    if text in _FALSY:
        return False
    raise ValueError(
        f"invalid boolean value for {name}: {value!r} — use one of "
        f"{sorted(_TRUTHY)} / {sorted(_FALSY)}, or unset it for the "
        f"declared default {default!r}")


def _parse_int(name: str, value: str | None, default: int) -> int:
    text = (value or "").strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        return default


def _parse_float(name: str, value: str | None, default: float) -> float:
    text = (value or "").strip()
    if not text:
        return default
    try:
        number = float(text)
    except ValueError:
        return default
    return default if number != number else number  # NaN -> default


def _parse_str(value: str | None, default: str) -> str:
    return default if value is None else value


def _parse_path(value: str | None, default: str) -> Path | None:
    text = value or default
    return Path(text) if text else None


_PARSERS = {
    "bool": _parse_bool,
    "int": _parse_int,
    "float": _parse_float,
    "str": _parse_str,
    "path": _parse_path,
}


def get(name: str, *, mapping: Mapping[str, str] | None = None) -> Any:
    """The typed effective value of a declared switch."""
    declared = spec(name)
    value = raw(name, mapping=mapping)
    parser = _PARSERS[declared.type]
    if declared.type in ("str", "path"):
        return parser(value, declared.default)
    return parser(name, value, declared.default)


def _typed(name: str, kind: str, mapping: Mapping[str, str] | None) -> Any:
    declared = spec(name)
    if declared.type != kind:
        raise ValueError(
            f"{name} is declared as {declared.type!r}, not {kind!r}")
    return get(name, mapping=mapping)


def get_bool(name: str, *, mapping: Mapping[str, str] | None = None) -> bool:
    return _typed(name, "bool", mapping)


def get_int(name: str, *, mapping: Mapping[str, str] | None = None) -> int:
    return _typed(name, "int", mapping)


def get_float(name: str, *, mapping: Mapping[str, str] | None = None) -> float:
    return _typed(name, "float", mapping)


def get_str(name: str, *, mapping: Mapping[str, str] | None = None) -> str:
    return _typed(name, "str", mapping)


def get_path(name: str, *, mapping: Mapping[str, str] | None = None) \
        -> Path | None:
    return _typed(name, "path", mapping)


def declared_values(mapping: Mapping[str, str] | None = None) -> dict:
    """The declaration face carried by the dispatch context.

    Every declared switch reports its effective typed value, its declared
    default and whether the value came from the environment or the
    default — so an unset switch is never invisible to the executor.
    """
    env = os.environ if mapping is None else mapping
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    defaults: dict[str, Any] = {}
    for name in SWITCHES:
        values[name] = get(name, mapping=env)
        defaults[name] = SWITCHES[name].default
        present = env.get(name)
        sources[name] = "env" if present not in (None, "") else "default"
    return {
        "schema": SCHEMA,
        "values": values,
        "declared_defaults": defaults,
        "sources": sources,
    }

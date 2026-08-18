#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao-init — workspace initialization + re-init protection (phase 3.5, E-init.1-4).

Standalone CLI (not a kunglao.py subcommand, module-design L448):
    python kunglao-init.py <workspace> [--type windows|linux|android] [--force]
        [--hooks-json <path>] [--profile-root <path>]

#304 type-aware extension:
    --type explicit > magic sniff (MZ/ELF/PK+classes.dex on bins/ first file)
    > interactive input() confirm with sniff default
    The type is persisted to analysis_state.txt project_type=<type>; the
    template is chosen by type.
    Init-completeness = [initialized] marker AND project_type declared

#304 amendment (comment 304-5289955958): toolchain verification =
    verify-first + notify the human + refuse + cleanup.
    Flow: Phase 0 flag guard → resume check → no-sample friendly prompt
    (exit 5) → type determination → toolchain.check preflight (HARD items)
    → on FAIL: per-item install commands + refuse (exit 4) + cleanup.
    Cleanup removes ONLY entries created by this run (cleanup_scaffold,
    created list) — anything not created by this run is never deleted
    (real facts/ content must survive, F2).
    Only on PASS: scaffold + [initialized].
    --skip-toolchain is the test/ops escape hatch; the production path
    never skips.

#304 amendment 2 (review F1): a pre-#304 workspace whose [initialized]
    marker exists but lacks project_type → no longer a direct resume exit 0
    (env_check_gate would reject it forever with no mechanical repair
    path); instead write project_type (explicit > state > sniff >
    confirm) then exit 0.

#411 workspace-path shape gate: before any write (including hook install)
    the resolved workspace is classified (workspace_shape) — an existing
    workspace root (bins/ or claim-register.yaml), a creatable directory,
    or a refuse case. A sample directory (has bin/ but NO bins/) or a file
    passed as the workspace → REFUSE (exit 6, RC_PATH_SHAPE) with guidance,
    ZERO files written; .claude/ and every scaffold entry stay under the
    workspace root. The type sniffer and sample detector read bins/ ONLY
    (never bin/).

Init-completeness predicate (F6): single source in scripts/init_state.py;
this file imports it.


Phase 0 (#276): environment guard — CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS
    defaults to 0 (disabled).
    - flag truthy in process env (1/true/yes/on) → HARD refuse to
      scaffold (exit 3), repair guidance: unset then restart the session;
      do not use the teammate channel
    - unset/0 → in-session os.environ[flag]="0" + analysis_state.txt
      records agent_teams_flag=0 (default disabled)
    - Persisted settings: shell_defaults.apply ensures an existing user
      PowerShell profile (Documents/PowerShell and
      Documents/WindowsPowerShell) contains
      CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=0; actions are logged to init
      output (--profile-root injectable for tests; default Path.home())

Three-phase re-init-protected state machine:
    Phase 1 existence check: claim-register.yaml contains the
    `[initialized]` marker → resume mode
        - state_hash unchanged → exit 0, output "resume"
        - state_hash drifted (external edit) → stderr WARNING (drift),
          still exit 0 resume
    Phase 2 fresh initialization: scaffold (analysis_state.txt /
    global_plan.txt / runs/ etc.)
        + 3 structural seed claims (C-001 sample artifact identity /
        C-002 project type / C-003 sample hash — scaffold facts only,
        #412: init performs NO analysis)
        + idempotent hook deployment
    Phase 3 idempotency verify: marker present + seed count; a rerun does
    not re-seed / re-deploy hooks

state_hash = sha256(claim-register.yaml content (state_hash field
            normalized) + facts/_INDEX.md content + facts/ file listing
            concatenated sorted by name) — recorded in the [initialized]
            marker.

Hook deployment boundary (hard constraint): NEVER write the production
~/.claude/settings.json. Write only:
    - a settings.json copy specified by `--hooks-json <path>` (created if
      absent), or
    - <workspace>/.claude/settings.json (if it exists)
    Neither → skip deployment (log an explanation), never touch HOME.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import sys
from collections.abc import Collection
from pathlib import Path

# #276: reusable CLI manages shell environment default lines (no inline
# execution). Per repo convention, inject scripts/ into sys.path before
# importing sibling modules (compatible with `python -m` style invocations).
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
import shell_defaults  # noqa: E402
import toolchain  # noqa: E402  # #304: type-aware toolchain probes (check-before-scaffold gate)
# #408: ask-then-install — interactive install prompts + MCP registration +
# re-probe (graceful degrade on decline; --assume-yes for CI/headless).
import toolchain_install  # noqa: E402
# F6 (#304 review): init-completeness predicate = single source in init_state.py
from init_state import VALID_TYPES, is_init_complete, read_project_type  # noqa: E402
import mcp_probe  # noqa: E402  (#316: MCP supply manifest/scaffold single source of truth)
# #454: wiring≠activation — the hooks-deployed output names the activation
# TTL window from the single source (never a second hardcoded 30).
from hook_activation import DEFAULT_TTL_MINUTES as HOOK_TTL_MINUTES  # noqa: E402
# #362: CLAUDE.md renders through the shared {{param}} engine (single
# rendering system with scripts/template_gen.py — leftover detection included)
import template_render  # noqa: E402

MARKER = "[initialized]"
SEED_MIN = 3
HOOK_FILES = ("worker_budget.py",)  # DESIGN §7 0.3: PreToolUse + PostToolUse → worker_budget
HASH_RE = re.compile(r"state_hash=([0-9a-f]{64})")

# #367: review-gate pre-commit template + its install-time key placeholder.
# The template must never ship a real key path (the pre-#367 template
# hardcoded the author's Windows user path — dead gate everywhere else);
# the human-run --install-git-hooks stamps the installing user's absolute
# key path into the .git/hooks/pre-commit copy ONCE, at install time. The
# stamped literal preserves #147 anti-forgery: a commit-time HOME/USERPROFILE
# redirection cannot alter it.
REVIEW_HOOK_TEMPLATE = _SCRIPT_DIR.parent / ".claude" / "git-hooks" / "pre-commit"
REVIEW_KEY_PLACEHOLDER = "__KUNGLAO_REVIEW_KEY__"
REVIEW_KEY_NAME = "kunglao-review.key"
# #389: the review-gate hook runs via `uv run --project <skill_root>` — the
# skill root is stamped at install time (same stamp-once pattern as the key).
SKILL_ROOT_PLACEHOLDER = "__KUNGLAO_SKILL_ROOT__"

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"  # #276: defaults to 0 (disabled)
AGENT_TEAMS_STATE_LINE = "agent_teams_flag=0 (default disabled)"

# #304 amendment exit codes (callers branch on codes, not stderr text):
RC_OK = 0
RC_ERROR = 1        # generic (argparse / fatal verify)
RC_FATAL_VERIFY = 2  # post-init idempotency verify failed
RC_FLAG_REJECT = 3   # Phase 0 (#276) agent-teams flag truthy
RC_TOOLCHAIN_REFUSE = 4  # toolchain HARD FAIL — human must install, no scaffold
RC_NO_SAMPLE = 5     # bins/ empty — friendly prompt (place a sample into bins/)
RC_PATH_SHAPE = 6    # #411: target is a sample dir / file, not a workspace root — refuse with guidance

SCAFFOLD_DIRS = ("facts", "blockers", "runs")
SCAFFOLD_FILES = {
    "analysis_state.txt": (
        "# analysis_state — kunglao-init scaffold (empty-structure stubs, DESIGN §7 0.4)\n"
        f"{AGENT_TEAMS_STATE_LINE}\n"
    ),
    "global_plan.txt": "# global_plan — kunglao-init v1 stub\n",
    "claim_deps.yaml": "depends_on: {}\n",
    "task_spec_snapshot.yaml": "{}\n",
    "facts/_INDEX.md": "# _INDEX\n",
}


def utc_now() -> str:
    """UTC ISO-8601 seconds precision, Z suffix (same shape as hooks_selfcheck)."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def atomic_write(path: Path, text: str) -> None:
    """M0.2 store_atomic: write temp → rename (crash-safe)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="kunglao-init",
        description="workspace initialization + re-init protection (standalone CLI, not a kunglao.py subcommand)",
    )
    parser.add_argument("workspace", help="target workspace path (holds bins/, claim-register.yaml, etc.)")
    parser.add_argument("--type", choices=VALID_TYPES, default=None,
                        help="project type: windows|linux|android (#304)")
    parser.add_argument("--force", action="store_true",
                        help="rebuild: back up claim-register first, then re-initialize")
    parser.add_argument("--skip-toolchain", action="store_true",
                        help="skip the toolchain preflight gate (test/ops escape "
                             "hatch from the #304 amendment; the production "
                             "path never skips)")
    parser.add_argument("--hooks-json", metavar="PATH", default=None,
                        help="target settings.json copy for hook deployment; default <workspace>/.claude/settings.json if present, never write HOME")
    parser.add_argument("--profile-root", metavar="PATH", default=None,
                        help="profile root directory (default Path.home(); injectable for tests; #276)")
    parser.add_argument("--no-mcp", action="store_true",
                        help="skip workspace .mcp.json scaffold (#316)")
    parser.add_argument("--install-git-hooks", action="store_true",
                        help="install the review-gate pre-commit hook (#367): copy "
                             ".claude/git-hooks/pre-commit to .git/hooks/pre-commit with "
                             "this user's key path stamped in place of the placeholder")
    parser.add_argument("--assume-yes", action="store_true",
                        help="#408: consent to every ask-then-install prompt "
                             "(CI/headless; non-interactive stdin declines by default)")
    try:
        return parser.parse_args(argv)
    except SystemExit as exc:
        # #414: argparse exits 2 on usage errors by default — that collides
        # with RC_FATAL_VERIFY=2, so a caller would read a trivial invocation
        # mistake as a post-init idempotency-verify failure. Normalize the
        # usage-exit to the documented generic RC_ERROR=1. A --help exit (0)
        # is untouched.
        if exc.code == RC_FATAL_VERIFY:
            raise SystemExit(RC_ERROR) from exc
        raise


def is_truthy(value: str | None) -> bool:
    """Truthy check: 1/true/yes/on, case-insensitive (#276 default-off semantics)."""
    return value is not None and value.strip().lower() in ("1", "true", "yes", "on")


def profile_candidates(profile_root: Path | None = None) -> list[Path]:
    """User PowerShell profile candidates (Documents/PowerShell and Documents/WindowsPowerShell)."""
    root = Path(profile_root) if profile_root is not None else Path.home()
    docs = root / "Documents"
    return [
        docs / "PowerShell" / "Microsoft.PowerShell_profile.ps1",
        docs / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1",
    ]


def guard_agent_teams(profile_root: Path | None = None) -> tuple[int, list[str]]:
    """Phase 0 (#276): flag environment guard.

    - flag truthy in process env → HARD refuse (exit 3), no scaffold, with
      repair guidance: unset then restart the session; do not use the
      teammate channel
    - unset/0 → in-session os.environ[flag]="0" + existing PowerShell
      profile gets CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=0 via
      shell_defaults.apply
    Returns (exit_code, log_lines).
    """
    log: list[str] = []
    val = os.environ.get(FLAG_NAME)
    if is_truthy(val):
        log.append(
            f"kunglao-init: HARD REJECT — {FLAG_NAME} is truthy ({val!r}); "
            f"scaffold blocked. Fix: unset {FLAG_NAME} in the launching shell "
            f"and RESTART this session; do NOT dispatch through the teammate "
            f"channel (kunglao #88, 2026-08-12 incident)."
        )
        return 3, log
    os.environ[FLAG_NAME] = "0"
    log.append(f"kunglao-init: env {FLAG_NAME}=0 (default disabled)")
    found = False
    for profile in profile_candidates(profile_root):
        if not profile.exists():
            continue
        found = True
        result = shell_defaults.apply(profile, FLAG_NAME, "0", shell="powershell")
        log.append(f"kunglao-init: profile {profile}: {result['change']}")
    if not found:
        log.append("kunglao-init: no PowerShell profile found — profile write skipped")
    return 0, log


def ensure_agent_teams_state(ws: Path) -> bool:
    """Record agent_teams_flag=0 (default disabled) in analysis_state.txt; append if missing."""
    p = ws / "analysis_state.txt"
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    if "agent_teams_flag=" in text:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    if text and not text.endswith("\n"):
        text += "\n"
    atomic_write(p, text + f"{AGENT_TEAMS_STATE_LINE}\n")
    return True


def normalize_marker(text: str) -> str:
    """Normalize the state_hash field inside the [initialized] marker (self-consistency hash)."""
    return HASH_RE.sub("state_hash=", text)


def extract_hash(text: str) -> str | None:
    """Read the recorded state_hash out of the [initialized] marker."""
    m = HASH_RE.search(text)
    return m.group(1) if m else None


def compute_state_hash(ws: Path, register_text: str | None = None) -> str:
    """state_hash = sha256(claim-register normalized content + facts/_INDEX.md content + facts/ file manifest).

    The manifest = fact filenames under facts/ concatenated sorted by name
    (design contract wording).
    """
    h = hashlib.sha256()
    if register_text is not None:
        h.update(b"claim-register.yaml:" + normalize_marker(register_text).encode("utf-8"))
    else:
        reg = ws / "claim-register.yaml"
        if reg.exists():
            h.update(b"claim-register.yaml:" + normalize_marker(reg.read_text(encoding="utf-8")).encode("utf-8"))
    facts = ws / "facts"
    idx = facts / "_INDEX.md"
    if idx.exists():
        h.update(b"_INDEX.md:" + idx.read_bytes())
    if facts.is_dir():
        names = sorted(p.name for p in facts.iterdir() if p.is_file())
        h.update(b"facts-manifest:" + "\n".join(names).encode("utf-8"))
    return h.hexdigest()


def seed_claims(sample: str, project_type: str, sample_sha: str) -> list[dict]:
    """3 structural seed claims (scaffold facts only, #412: no analysis).

    C-001 sample artifact identity / C-002 project type / C-003 sample
    sha256. Init performs NO analysis — family/verdict/attribution/
    capability guesses are forbidden here (issue #412); the operator
    defines the analysis task (primary_questions) after init, and claim
    seeding from task_spec happens in the loop (DESIGN §7 0.9).
    """
    return [
        {"id": "C-001", "status": "OPEN", "boundary_type": "positive_observation",
         "evidence_tier_attempted": 0, "promotion_attempts": 0, "depends_on": [],
         "title": f"Sample artifact identity — {sample} (filename; sha256 in C-003)"},
        {"id": "C-002", "status": "OPEN", "boundary_type": "positive_observation",
         "evidence_tier_attempted": 0, "promotion_attempts": 0, "depends_on": [],
         "title": f"Project type — {project_type} (scaffold decision)"},
        {"id": "C-003", "status": "OPEN", "boundary_type": "positive_observation",
         "evidence_tier_attempted": 0, "promotion_attempts": 0, "depends_on": [],
         "title": f"Sample sha256 — {sample_sha}"},
    ]


def claim_register_text(sample: str, sample_sha: str, state_hash: str,
                        project_type: str) -> str:
    """Full claim-register.yaml text: [initialized] marker header + structural seed claims body."""
    claims = seed_claims(sample, project_type, sample_sha)
    lines = [
        f"# [initialized] kunglao-init state_hash={state_hash} seeds={len(claims)} sample={sample}",
        f"# sha256={sample_sha} ts={utc_now()}",
        "# kunglao-init structural seed claims — scaffold facts only "
        "(artifact identity / project type / sample hash; #412: no analysis conclusions)",
        "claims:",
    ]
    for c in claims:
        lines.append(f"- id: {c['id']}")
        lines.append(f"  status: {c['status']}")
        lines.append(f"  boundary_type: {c['boundary_type']}")
        lines.append(f"  evidence_tier_attempted: {c['evidence_tier_attempted']}")
        lines.append(f"  promotion_attempts: {c['promotion_attempts']}")
        lines.append(f"  depends_on: {c['depends_on']}")
        lines.append(f"  title: \"{c['title']}\"")
    return "\n".join(lines) + "\n"


# #411: workspace-path shape classification. A workspace root is a directory
# that IS or CAN BE a kunglao workspace — the sample container is bins/
# (plural), never bin/. A directory whose only sample-looking subdir is bin/
# (singular) is the sample directory itself, not a workspace root.

def workspace_shape(ws: Path) -> str:
    """Classify a target path's workspace shape (#411).

    Returns one of:
      "workspace"  — existing workspace root (bins/ or claim-register.yaml present)
      "creatable"  — not a workspace yet, but a directory that can hold bins/
                     (also a non-existent path with no file suffix — fresh root)
      "sample_dir" — the target is a sample container (named bin/bins) or has
                     a bin/ subdir and no bins/: init must refuse — .claude/
                     would land inside the sample dir
      "file"       — target is a regular file, or a non-existent path named
                     like a sample file (has a suffix): not a workspace
    """
    if ws.is_file():
        return "file"
    if ws.is_dir():
        if (ws / "bins").is_dir() or (ws / "claim-register.yaml").is_file():
            return "workspace"
        # #411: a directory named bin/ or bins/ IS the sample container —
        # running init on it would scatter .claude/ and scaffold files INTO
        # the samples. Refuse (the workspace root is its parent).
        if ws.name.lower() in ("bin", "bins"):
            return "sample_dir"
        if (ws / "bin").is_dir():
            return "sample_dir"
        return "creatable"
    # Non-existent: a fresh path is fine when it can hold bins/. A path named
    # like a sample file (has a suffix) is a misplaced sample, not a workspace.
    if ws.suffix:
        return "file"
    return "creatable"


def _assert_workspace_boundary(ws: Path) -> None:
    """#411 (E-init.5): assert the workspace root is a directory — every
    scaffold write (analysis_state.txt, claim-register.yaml, .claude/, .mcp.json,
    runs/, ...) is an entry under ws. A file at the root would silently scatter
    scaffold files INTO its parent, so fail fast instead."""
    if ws.is_file():
        raise AssertionError(
            f"internal error: workspace root resolved to a file {ws} — "
            "refusing to scaffold outside a workspace directory"
        )


def refuse_path_shape(ws: Path, shape: str) -> int:
    """#411: print path-shape refusal guidance; exit RC_PATH_SHAPE. Nothing is written."""
    if shape == "sample_dir":
        print(
            f"kunglao-init: REFUSE — {ws} is a SAMPLE DIRECTORY, not a workspace root. "
            "A kunglao workspace holds samples under bins/ (plural); the target "
            "has bin/ (singular) and no bins/. Run init on the workspace root and "
            f"place the sample under {ws.parent / 'bins'} — never inside the sample dir.",
            file=sys.stderr,
        )
    elif shape == "file":
        print(
            f"kunglao-init: REFUSE — {ws} is a FILE, not a workspace root. "
            "Run init on the workspace directory that will hold bins/ "
            "(place the sample into <ws>/bins/).",
            file=sys.stderr,
        )
    else:  # defensive: unknown shape must still refuse, never scaffold
        print(
            f"kunglao-init: REFUSE — {ws} is not a workspace root (shape={shape}). "
            "Run init on the workspace directory that holds (or will hold) bins/.",
            file=sys.stderr,
        )
    print(
        "kunglao-init: NOT initialized (no scaffold written, no .claude/ created)",
        file=sys.stderr,
    )
    return RC_PATH_SHAPE


def detect_sample(ws: Path) -> tuple[str, str]:
    """First file under bins/ (sorted by name) as the sample: (filename, sha256). No sample → ("unknown", "")."""
    bins = ws / "bins"
    if not bins.is_dir():
        return "unknown", ""
    files = sorted(p for p in bins.iterdir() if p.is_file())
    if not files:
        return "unknown", ""
    sample = files[0]
    try:
        sha = hashlib.sha256(sample.read_bytes()).hexdigest()
    except OSError:
        sha = ""
    return sample.name, sha


def sniff_type(ws: Path) -> str | None:
    """Magic sniff: read first bins/ file headers → windows|linux|android or None."""
    bins = ws / "bins"
    if not bins.is_dir():
        return None
    files = sorted(p for p in bins.iterdir() if p.is_file())
    if not files:
        return None
    sample = files[0]
    try:
        header = sample.read_bytes()[:512]
    except OSError:
        return None
    # PK zip (APK) + classes.dex marker
    if header[:4] == b"PK\x03\x04" and b"classes.dex" in header:
        return "android"
    # ELF
    if header[:4] == b"\x7fELF":
        return "linux"
    # PE (MZ)
    if header[:2] == b"MZ":
        return "windows"
    return None


def prompt_type(default: str | None = None) -> str:
    """Interactive type prompt (only human step in init-worker flow)."""
    hint = f" [{default}]" if default else ""
    while True:
        try:
            raw = input(f"Project type{hint} (windows|linux|android): ").strip().lower()
        except EOFError:
            if default:
                return default
            print("kunglao-init: ERROR cannot determine type (non-interactive, no --type, no sniff)",
                  file=sys.stderr)
            sys.exit(1)
        if raw and raw in VALID_TYPES:
            return raw
        if not raw and default and default in VALID_TYPES:
            return default
        print(f"Invalid type: {raw!r}. Choose: windows, linux, android")


def resolve_type(ws: Path, explicit: str | None) -> str:
    """Type resolution: explicit > sniff > interactive confirm.
    Returns the resolved type string.
    """
    if explicit:
        return explicit
    sniffed = sniff_type(ws)
    if sniffed:
        # Sniff succeeded — confirm with user
        try:
            raw = input(f"Detected type: {sniffed}. Confirm? [Y/n]: ").strip().lower()
            if raw in ("n", "no"):
                return prompt_type(default=sniffed)
        except EOFError:
            pass  # Non-interactive: accept sniff
        return sniffed
    # No sniff result — interactive prompt
    return prompt_type()


def write_project_type(ws: Path, project_type: str) -> bool:
    """Write project_type=<type> to analysis_state.txt. Returns True if written."""
    p = ws / "analysis_state.txt"
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    if "project_type=" in text:
        # Already has project_type — update it
        lines = text.splitlines()
        new_lines = []
        for line in lines:
            if line.strip().startswith("project_type="):
                new_lines.append(f"project_type={project_type}")
            else:
                new_lines.append(line)
        atomic_write(p, "\n".join(new_lines))
        return True
    # Append
    if text and not text.endswith("\n"):
        text += "\n"
    atomic_write(p, text + f"project_type={project_type}\n")
    return True


CLAUDEMD_TMPL = Path(__file__).resolve().parent.parent / "templates" / "CLAUDE.md.base.tmpl"
SKILL_DIR = Path(__file__).resolve().parent.parent

# #356 W2: per-OS constraint blocks injected into the base template's
# <TYPE_SECTION> slot at render time. Single handwritten source (base.tmpl) +
# these deltas replace the 4 pre-#356 template files (copy-drift defect).
OS_SECTIONS: dict[str, str] = {
    "windows": """## Hard constraints (windows)

- **x64dbg**: only `connect_remote(host=..., ...)` — never `start_session` / `connect_to_session` / `connect_to_instance` / `terminate_session`.
- **VM required**: `KUNGLAO_VM_HOST` must be set and VM must be reachable for T2+ analysis.
""",
    "linux": """## Hard constraints (linux)

- **gdbserver**: primary remote debugger for Linux ELF targets on VM.
- **VM required**: `KUNGLAO_VM_HOST` must be set and VM must be reachable for T2+ analysis.
- **eBPF tracing**: requires kernel >= 6.0 (`uname -r`). Not available on older kernels — this is a WARN gate, not a hard blocker. Other analysis paths proceed normally.
""",
    "android": """## Hard constraints (android)

- **ADB required (root dependency)**: `adb devices` must show at least one device. ADB missing means frida-server/android_server discovery impossible; all downstream dynamic checks cascade from ADB.
- **Device root required**: `adb shell su -c id` must return uid=0. Non-rooted devices cannot run frida-server or perform dynamic analysis. This is a HARD gate.
- **Debug flag (HARD, init-enforced)**: manifest debuggable or `am set-debug-app` / setprop. Must be set and read back for verification — kunglao-init's toolchain check verifies `adb shell getprop ro.debuggable` returns 1; if not settable, init refuses (exit 4) with fix guidance.
- **frida-server (HARD, init-enforced; renamed + custom port)**: Device-side binary must NOT use the default name; custom port (default convention: 1337). kunglao-init verifies it via `adb forward tcp:<port>` + TCP connect; unreachable means init refuses with deployment guidance.
- **GitNexus required**: `gitnexus --version` must succeed. Post-decompile graph building is a mandatory step in the Android flow.
- **IDA android_server (HARD, init-enforced)**: Must be present on device for IDA remote debugging. kunglao-init verifies it via `adb forward tcp:23946` + TCP connect; unreachable means init refuses with deployment guidance.
- **eBPF tracing (WARN)**: Requires Android SDK >= 31 (getprop ro.build.version.sdk). SDK < 31 means eBPF unavailable (not blocking).
- **unidbg (WARN, fallback)**: Requires java + unidbg library. Only used when static+debug+frida all fail. AND-gated: frida data sufficient + decompilation done + still stuck.

## Android analysis flow

```
APK -> aapt/apktool unpack -> jadx DEX->Java
    -> gitnexus analyze(decompiled output dir, build knowledge graph; serve/graph data as analysis artifact)
    -> static analysis(graph-assisted class/call-chain/malicious-logic-entry location)
    -> dynamic needed: ADB -> root -> debug flag -> frida(renamed+port) or android_server
    -> stuck fallback: frida hook + unidbg hybrid (AND three conditions)
```
""",
}


def os_section(project_type: str | None) -> str:
    """OS constraint block for <TYPE_SECTION>; unknown/None -> empty."""
    return OS_SECTIONS.get(project_type or "", "")


def write_claudemd(ws: Path, sample_name: str, sample_sha: str,
                  project_type: str | None = None) -> Path | None:
    """Write CLAUDE.md from template with project info filled in.

    #362: renders through the shared template_render engine ({{param}}
    single-pass + fail-closed leftover detection — an unfilled placeholder
    is a TemplateRenderError, never a silent partial file).

    Idempotent: if CLAUDE.md exists and is non-empty, skip (do not clobber).
    Returns the written path or None if skipped.
    """
    target = ws / "CLAUDE.md"
    if target.exists() and target.read_text(encoding="utf-8").strip():
        return None
    # Single-source base template (#356 W2); OS delta injected at render
    tmpl_path = CLAUDEMD_TMPL
    if not tmpl_path.exists():
        return None
    tmpl = tmpl_path.read_text(encoding="utf-8")

    # Detect venv path
    venv_candidate = ws / ".venv"
    venv_path = str(venv_candidate) if venv_candidate.exists() else ".venv/"

    params = {
        "type_section": os_section(project_type),
        "type": project_type or "windows",
        "sample_sha1": sample_name,
        "sample_sha256": sample_sha,
        "sample_type": "(detected at analysis time)",
        "sample_path": f"bins/{sample_name}",
        # as_posix(): the skill dir lands in CLAUDE.md BASH command lines
        # (`python <skill>/scripts/convergence_check.py .`) where backslashes
        # are shell escapes — str(Path) breaks every rendered command on
        # win32 and drifts the portable golden contract (#457 triage #9-#11;
        # same rule as the #367 hook stamping).
        "skill_dir": SKILL_DIR.as_posix(),
        "venv_path": venv_path,
    }
    text = template_render.render_strict(
        tmpl, params, source=str(tmpl_path))

    # Append Python version note to the venv section (post-render step:
    # the version is runtime state, not a template parameter)
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    text = text.replace(
        "Activate before running scripts.",
        f"Activate before running scripts. Python {py_version}."
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, text)
    return target


def scaffold(ws: Path) -> list[Path]:
    """Idempotent scaffold (DESIGN §7 0.4): mkdir dirs; skip existing non-empty files (no clobber)."""
    created: list[Path] = []
    for name in SCAFFOLD_DIRS:
        d = ws / name
        if not d.is_dir():
            d.mkdir(parents=True)
            created.append(d)
    for name, stub in SCAFFOLD_FILES.items():
        p = ws / name
        if p.exists() and p.read_text(encoding="utf-8").strip():
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(p, stub)
        created.append(p)
    return created


def scaffold_mcp(ws: Path) -> str:
    """#316: workspace .mcp.json scaffold (MCP supply manifest template).

    Idempotent: file already exists → do not overwrite (return "exists");
    otherwise write the valid JSON built by mcp_probe (mcpServers left
    empty, mcp_manifest carries the per-type list + each item's
    purpose/source/register command template).
    """
    target = ws / ".mcp.json"
    if target.exists():
        return "exists"
    text = json.dumps(mcp_probe.build_scaffold_json(), indent=2, ensure_ascii=False)
    atomic_write(target, text + "\n")
    return "created"


def _ensure(entries: list, matcher: str, hook_file: str, hook_dir: Path) -> tuple[list, bool]:
    """Same-named hook command already present under the matcher → skip (idempotent); else append.

    #389: hooks run via `uv run --project <skill_root>` — bare python can
    resolve to 2.x and kill every registered hook; uv uses the skill venv.
    Same-name is not enough: a legacy bare-python entry with the same name
    must be REPLACED in place (position kept, no duplicate append) — the
    fixed-point pattern shared with external_kicker._canonical.
    """
    skill_root = hook_dir.parent.as_posix()
    command = f"uv run --project {skill_root} {(hook_dir / hook_file).as_posix()}"
    canonical = {"matcher": matcher, "hooks": [{"type": "command", "command": command}]}
    new = [e for e in entries if e.get("matcher") == matcher]
    other = [e for e in entries if e.get("matcher") != matcher]
    for idx, e in enumerate(new):
        for h in e.get("hooks", []):
            if h.get("command", "").replace("\\", "/").rsplit("/", 1)[-1] == hook_file:
                if h.get("command", "") == command:
                    return other + new, False  # canonical form already — fixed point
                replaced = list(new)
                replaced[idx] = canonical  # legacy form → replace in place
                return other + replaced, False
    new.append(canonical)
    return other + new, True


def _patch_settings(path: Path) -> int:
    """Merge the kunglao hook into settings.json (other keys preserved); return count of added entries."""
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise RuntimeError(f"settings.json unparseable: {path} ({exc})") from exc
    hooks = existing.get("hooks") or {}
    pre = hooks.get("PreToolUse") or []
    post = hooks.get("PostToolUse") or []
    hook_dir = Path(__file__).resolve().parent.parent / "hooks"
    count = 0
    for event, matcher, hook_file in (
        ("PreToolUse", "Agent", HOOK_FILES[0]),
        ("PostToolUse", "Agent", HOOK_FILES[0]),
    ):
        entries, added = _ensure(pre if event == "PreToolUse" else post, matcher, hook_file, hook_dir)
        if event == "PreToolUse":
            pre = entries
        else:
            post = entries
        count += added
    hooks["PreToolUse"] = pre
    hooks["PostToolUse"] = post
    existing["hooks"] = hooks
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(existing, indent=2, ensure_ascii=False))
    return count


def deploy_hooks(ws: Path, hooks_json: Path | None) -> dict:
    """Idempotent hook deployment (E-init.2). Target: the --hooks-json copy, or <ws>/.claude/settings.json (if present).

    HOME is never a deployment target by default — if neither exists,
    skip with an explanation.
    """
    if hooks_json is not None:
        target = Path(hooks_json).resolve()
    else:
        target = ws / ".claude" / "settings.json"
        if not target.exists():
            return {"deployed": False, "target": None,
                    "reason": "no <workspace>/.claude/settings.json (HOME settings never written)"}
    added = _patch_settings(target)
    return {"deployed": True, "target": str(target), "added": added}


def backup_register(path: Path) -> Path:
    """Back up claim-register before a --force rebuild (E-init.4): claim-register.yaml.bak-<ts>."""
    ts = utc_now().replace(":", "-")
    backup = path.with_name(f"{path.name}.bak-{ts}")
    shutil.copy2(path, backup)
    return backup


def install_git_hooks(ws: Path, home: Path | None = None) -> tuple[bool, str]:
    """#367: install the review-gate pre-commit hook with install-time stamping.

    Copies the tracked template (.claude/git-hooks/pre-commit) to
    <ws>/.git/hooks/pre-commit, substituting two install-time placeholders:
      - the installer's $HOME/.claude/kunglao-review.key (resolved ONCE,
        here — by the human running the installer) for the
        __KUNGLAO_REVIEW_KEY__ placeholder;
      - this script's skill root (_SCRIPT_DIR.parent) for the
        __KUNGLAO_SKILL_ROOT__ placeholder — #389: the gate runs via
        `uv run --project <skill_root>`, which removes both the bare-python
        2.x hazard and the $repo/scripts/ dependency (the workspace is not
        the skill repo).
    The stamped paths are literals in the installed hook: commit-time
    HOME/USERPROFILE redirection cannot alter them (#147 anti-forgery
    preserved). Fail-closed: if the key is absent the hook is still
    installed (its placeholder-residue/missing-key branches block commits
    until a key exists); the human is guided to review_gate.py key-init.

    Returns (installed, message).
    """
    git_dir = ws / ".git"
    if not git_dir.is_dir():
        return False, (f"no git repository at {ws} — --install-git-hooks "
                       "needs .git/hooks/ to install into")
    if not REVIEW_HOOK_TEMPLATE.is_file():
        return False, f"template missing: {REVIEW_HOOK_TEMPLATE}"
    home = Path(home) if home is not None else Path.home()
    key_path = (home / ".claude" / REVIEW_KEY_NAME).resolve()
    skill_root = _SCRIPT_DIR.parent.resolve()
    text = REVIEW_HOOK_TEMPLATE.read_text(encoding="utf-8")
    for placeholder in (REVIEW_KEY_PLACEHOLDER, SKILL_ROOT_PLACEHOLDER):
        if placeholder not in text:
            return False, (f"template carries no {placeholder} "
                           "placeholder — refusing to install an unstampable hook")
    # The comparison guards use the placeholder BOTH sides: replace only the
    # ASSIGNMENTS (right side of key=... / skill_root=...), never the
    # [ "$key" = ... ] / [ "$skill_root" = ... ] literals — replacing all
    # occurrences would neuter the installed copy's own unstamped-hook
    # fail-closed branches into tautologies.
    stamped = re.sub(
        rf'key="{REVIEW_KEY_PLACEHOLDER}"',
        f'key="{key_path.as_posix()}"',
        text, count=1)
    stamped = re.sub(
        rf'skill_root="{SKILL_ROOT_PLACEHOLDER}"',
        f'skill_root="{skill_root.as_posix()}"',
        stamped, count=1)
    if REVIEW_KEY_PLACEHOLDER in re.search(
            r'key="[^"\n]*"', stamped).group(0):
        return False, "internal error: key stamp failed (placeholder not replaced)"
    if SKILL_ROOT_PLACEHOLDER in re.search(
            r'skill_root="[^"\n]*"', stamped).group(0):
        return False, "internal error: skill-root stamp failed (placeholder not replaced)"
    target = git_dir / "hooks" / "pre-commit"
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, stamped)
    target.chmod(0o755)
    msg = (f"review-gate pre-commit installed -> {target} "
           f"(skill root stamped: {skill_root.as_posix()}; "
           f"key path stamped: {key_path.as_posix()})")
    if not key_path.is_file():
        msg += (f"; key ABSENT — create it (human-run): "
                f"uv run --project {skill_root.as_posix()} "
                f"{skill_root.as_posix()}/scripts/review_gate.py key-init "
                f"{key_path.as_posix()}")
    return True, msg


def resume(ws: Path, text: str) -> int:
    """Phase 1 resume mode: no drift → exit 0; drift → stderr WARNING, still exit 0."""
    recorded = extract_hash(text)
    current = compute_state_hash(ws)
    if recorded and current != recorded:
        print(f"kunglao-init: WARNING state drift detected (recorded {recorded}, computed {current}) — external edits present",
              file=sys.stderr)
    print(f"kunglao-init: resume — {ws} already initialized")
    return 0


def initialize(ws: Path, hooks_json: Path | None,
                project_type: str | None = None, no_mcp: bool = False,
                created: "Collection[Path] | None" = None) -> int:
    """Phase 2 fresh initialization + Phase 3 idempotency verify.

    Returns the exit code (0 success / RC_FATAL_VERIFY verify-failure).
    `created` is the scaffold manifest produced by scaffold() — the caller
    (run) keeps it in its own frame so a mid-init failure (template defect)
    can clean up exactly this run's artifacts; pre-existing content is never
    in the manifest and therefore never deleted (L2, #414).
    """
    if created is None:
        created = scaffold(ws)
    if ensure_agent_teams_state(ws):
        print(f"kunglao-init: analysis_state {AGENT_TEAMS_STATE_LINE}")
    sample, sample_sha = detect_sample(ws)

    # #304: Resolve and write project type
    if project_type is None:
        # Try to read existing type from analysis_state.txt
        existing_type = read_project_type(ws)
        if existing_type:
            project_type = existing_type
        else:
            # No type yet — resolve
            project_type = resolve_type(ws, None)
    write_project_type(ws, project_type)
    print(f"kunglao-init: project_type={project_type}")

    # Write CLAUDE.md from type-specific template (idempotent: skip if exists)
    write_claudemd(ws, sample, sample_sha, project_type=project_type)
    # #316: workspace .mcp.json MCP supply scaffold (idempotent; --no-mcp skips)
    if no_mcp:
        print("kunglao-init: .mcp.json skipped (--no-mcp)")
    else:
        outcome = scaffold_mcp(ws)
        if outcome == "created":
            print("kunglao-init: .mcp.json created (MCP supply scaffold, #316)")
        else:
            print("kunglao-init: .mcp.json skipped (exists — idempotent, not overwritten)")
    draft = claim_register_text(sample, sample_sha, state_hash="", project_type=project_type)
    digest = compute_state_hash(ws, register_text=draft)
    reg = ws / "claim-register.yaml"
    atomic_write(reg, claim_register_text(sample, sample_sha, state_hash=digest, project_type=project_type))

    written = reg.read_text(encoding="utf-8")
    seed_count = written.count("id: C-")
    if MARKER not in written or seed_count < SEED_MIN:
        print("kunglao-init: FATAL verify failed — marker or seeds missing after init", file=sys.stderr)
        return RC_FATAL_VERIFY
    hook_report = deploy_hooks(ws, hooks_json)

    # #412: the exit message lists what init did (scaffold + env + type) and
    # does NOT summarize sample content (no sample= in the output).
    print(f"kunglao-init: initialized {ws} (scaffold={seed_count} structural seeds project_type={project_type})")
    print(f"kunglao-init: state_hash={digest}")
    if hook_report["deployed"]:
        print(f"kunglao-init: hooks -> {hook_report['target']} ({hook_report['added']} entries, idempotent)")
        # #454: wiring != activation — wired hooks are DORMANT by design
        # (v1.9.7 default-inactive: no .hook_state.json -> hooks sleep). The
        # wired line must never read as armed: activation is orchestrator-
        # owned (Phase 0) and short-lived (TTL renewed by --renew).
        print(f"kunglao-init: hooks wired but dormant - activation is "
              f"orchestrator-owned (Phase 0, hook_activation.py --tier/--set-active) "
              f"with a {HOOK_TTL_MINUTES}-min TTL renewed by --renew; "
              f"no .hook_state.json -> hooks sleep")
    else:
        print(f"kunglao-init: hooks skipped — {hook_report['reason']}")
    return RC_OK


def run(ws: Path, force: bool = False, hooks_json: Path | None = None,
        profile_root: Path | None = None,
        project_type: str | None = None,
        skip_toolchain: bool = False, no_mcp: bool = False,
        install_git_hooks_flag: bool = False,
        assume_yes: bool = False) -> int:
    """State-machine entry (#304 amended flow, comment 304-5289955958):

    Phase 0 environment guard → re-init check (resume; if project_type is
    missing, upgrade by writing it then exit 0, F1) → no-sample friendly
    prompt → type determination (explicit > sniff > confirm) →
    **toolchain.check preflight** (HARD FAIL → #408 ask-then-install: per-item
    install prompts; consent installs + registers MCP + re-probes; decline
    degrades WARN/HARD per item. Items still HARD after the ask → per-item
    install guidance + refuse + cleanup of artifacts created by this run;
    cleanup removes ONLY this run's scaffold entries — pre-existing content
    is never in the created manifest and therefore never deleted, F2) →
    only on PASS: scaffold + [initialized] marker + project_type.

    #362: template render defects (unfilled {{placeholder}}) surface as a
    clear stderr message + exit RC_ERROR — never a silent partial CLAUDE.md.

    #367: --install-git-hooks installs the review-gate pre-commit hook with
    install-time key-path stamping; it runs on EVERY exit path after the
    flag guard (resume and fresh alike — hook install is orthogonal to
    scaffolding). Install failure (non-git workspace) is a HARD refuse.

    #408: --assume-yes consents to every ask-then-install prompt (CI/headless).
    Non-interactive stdin without it declines by default (no silent install).
    #411: the workspace-path shape gate runs immediately after path
    resolution, BEFORE the hook install and any scaffold write — a sample
    directory passed as the workspace is refused (exit RC_PATH_SHAPE) with
    guidance, and no file is ever written outside the workspace root.
    """
    guard_rc, guard_log = guard_agent_teams(profile_root)
    if guard_rc != 0:
        for line in guard_log:  # HARD REJECT guidance goes to stderr
            print(line, file=sys.stderr)
        return guard_rc
    for line in guard_log:
        print(line)
    ws = Path(ws).resolve()

    # #411: workspace-path shape gate — BEFORE any write (including hook
    # install). A sample directory passed as the workspace would place
    # .claude/ and every scaffold file INSIDE the sample dir; refuse with
    # guidance and write nothing. A valid workspace root (bins/ or
    # claim-register.yaml) or a creatable directory passes through.
    shape = workspace_shape(ws)
    if shape != "workspace" and shape != "creatable":
        return refuse_path_shape(ws, shape)

    # #411 invariant (E-init.5): no scaffold file — including .claude/ — may
    # be written outside the resolved workspace root. Fail fast on a defect
    # rather than polluting a sibling directory.
    _assert_workspace_boundary(ws)

    # #367: hook install first — it must also run for resume-mode workspaces
    if install_git_hooks_flag:
        installed, msg = install_git_hooks(ws)
        print(f"kunglao-init: {msg}")
        if not installed:
            return RC_ERROR

    reg = ws / "claim-register.yaml"
    if reg.exists() and not force:
        text = reg.read_text(encoding="utf-8")
        if MARKER in text:
            if is_init_complete(ws):
                return resume(ws, text)
            # F1 (#304 review): marker present but project_type missing
            # (pre-#304 workspace). resume() alone would exit 0 forever and
            # env_check_gate would keep rejecting — no mechanical repair path.
            # Write the missing type (explicit > state > sniff > confirm)
            # and exit 0; register/marker/seeds untouched.
            if project_type is None:
                existing = read_project_type(ws)
                if existing and existing in VALID_TYPES:
                    project_type = existing
                else:
                    project_type = resolve_type(ws, None)
            write_project_type(ws, project_type)
            print(
                f"kunglao-init: upgraded {ws} — wrote project_type={project_type} "
                f"(pre-#304 workspace: [initialized] without project_type)"
            )
            return 0
    if force and reg.exists():
        backup = backup_register(reg)
        print(f"kunglao-init: --force backup -> {backup}")

    # #304: no-sample cold start -> friendly prompt, refuse (exit 5)
    sample, sample_sha = detect_sample(ws)
    if sample == "unknown" or not sample_sha:
        print(
            "kunglao-init: no analysis target found — place a sample into bins/ "
            "or specify a path, then re-run "
            "kunglao-init.py <ws> --type <windows|linux|android>.",
            file=sys.stderr,
        )
        return RC_NO_SAMPLE

    # Type resolution BEFORE any file is written (explicit > state > sniff > confirm)
    if project_type is None:
        existing = read_project_type(ws)
        if existing and existing in VALID_TYPES:
            project_type = existing
        else:
            project_type = resolve_type(ws, None)

    # #304: toolchain.check BEFORE scaffold — HARD FAIL => ask-then-install
    # (#408), then refuse + cleanup only for items still HARD.
    # Verify-first: a refused init leaves no half-initialized state behind.
    if not skip_toolchain:
        report = toolchain.check(ws, project_type)
        if report.overall_status == toolchain.Status.FAIL:
            # #408: interactive ask per missing item — consent installs +
            # registers MCP + re-probes; decline degrades (WARN static /
            # HARD decompiler). --assume-yes consents headlessly.
            # Non-interactive stdin WITHOUT --assume-yes keeps the #304
            # refusal: no silent install and no silent degrade-and-proceed
            # without explicit consent.
            interactive = getattr(sys.stdin, "isatty", lambda: False)()
            if assume_yes or interactive:
                resolved = toolchain_install.ask_then_install(
                    report, ws, report.project_type, assume_yes=assume_yes)
                if resolved.overall_status == toolchain.Status.FAIL:
                    return refuse_toolchain(ws, resolved)
            else:
                return refuse_toolchain(ws, report)

    # #362: template defect (unfilled {{placeholder}}) → hard error, not a
    # silent partial CLAUDE.md. Clean up THIS RUN's scaffold entries (the
    # created manifest) so a refused init leaves no half-initialized state
    # (verify-first symmetry); anything not created by this run is never
    # deleted (F2, #414).
    created = scaffold(ws)
    try:
        return initialize(ws, hooks_json, project_type=project_type,
                          no_mcp=no_mcp, created=created)
    except template_render.TemplateRenderError as exc:
        removed, preserved = cleanup_scaffold(ws, created=created)
        print(f"kunglao-init: TEMPLATE DEFECT — {exc}", file=sys.stderr)
        print("kunglao-init: NOT initialized (no [initialized] marker written)",
              file=sys.stderr)
        if removed:
            print(f"kunglao-init: removed this run's scaffold entries: "
                  f"{', '.join(removed)}", file=sys.stderr)
        if preserved:
            print(f"kunglao-init: kept pre-existing content (not created by this run, not deleted): "
                  f"{', '.join(preserved)}", file=sys.stderr)
        return RC_ERROR


def cleanup_scaffold(ws: Path, created: "Collection[Path] | None" = None
                     ) -> tuple[list[str], list[str]]:
    """#304 amendment (F2): delete ONLY scaffold entries created by this run (created list).

    Anything not created by this run is never deleted — pre-existing
    files / non-empty directories are refused deletion and listed in
    preserved (real facts/ content must survive; symmetric with --force
    preserving facts on success).
    bins/, CLAUDE.md, claim-register.yaml, .claude/, .venv/ are not in
    the candidate set.

    Returns (removed, preserved) lists of path names.
    """
    created_set = {Path(p).resolve() for p in (created or ())}
    removed: list[str] = []
    preserved: list[str] = []
    for name in SCAFFOLD_FILES:
        p = (ws / name).resolve()
        if p not in created_set:
            if p.exists():
                preserved.append(name)  # pre-existing file, refuse deletion
            continue
        try:
            p.unlink()
            removed.append(name)
        except OSError:
            preserved.append(name)
    for name in SCAFFOLD_DIRS:
        d = (ws / name).resolve()
        if d not in created_set:
            if d.is_dir() and any(d.iterdir()):
                preserved.append(name + "/")  # non-empty directory, refuse deletion
            continue
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            removed.append(name + "/")
    return removed, preserved


def refuse_toolchain(ws: Path, report: "toolchain.ToolchainReport") -> int:
    """#304 amendment: HARD FAIL → per-item friendly install commands (human installs) + refuse + cleanup.

    - exit RC_TOOLCHAIN_REFUSE(4), no [initialized] marker written
    - print [FAIL] name + detail + fix (install command) per item
    - clean up scaffold artifacts created by this run (if any); cleanup
      removes ONLY this run's artifacts — pre-existing content is never
      deleted and is reported as preserved (F2)
    """
    hard_fails = [
        i for i in report.items
        if i.status == toolchain.Status.FAIL and i.tier == toolchain.Tier.HARD
    ]
    removed, preserved = cleanup_scaffold(ws)
    print(
        f"kunglao-init: REFUSE — toolchain HARD check failed "
        f"(type={report.project_type}); install the missing tools, then re-run "
        f"kunglao-init.py {ws} --type {report.project_type}.",
        file=sys.stderr,
    )
    for item in hard_fails:
        print(f"  [FAIL] {item.name}: {item.detail}", file=sys.stderr)
        fix = toolchain.FIXES.get(item.name)
        if fix:
            print(f"      fix: {fix}", file=sys.stderr)
    if removed:
        print(f"kunglao-init: removed artifacts created by this run: {', '.join(removed)}",
              file=sys.stderr)
    if preserved:
        print(f"kunglao-init: preserved pre-existing content (not created by this run, not deleted): {', '.join(preserved)}",
              file=sys.stderr)
    print("kunglao-init: NOT initialized (no [initialized] marker written)", file=sys.stderr)
    return RC_TOOLCHAIN_REFUSE


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(Path(args.workspace), force=args.force, hooks_json=args.hooks_json,
               profile_root=args.profile_root, project_type=args.type,
               skip_toolchain=args.skip_toolchain, no_mcp=args.no_mcp,
               install_git_hooks_flag=args.install_git_hooks,
               assume_yes=args.assume_yes)


if __name__ == "__main__":
    sys.exit(main())

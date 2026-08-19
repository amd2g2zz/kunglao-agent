#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao-init — workspace initialization + re-init protection (phase 3.5, E-init.1-4).

Standalone CLI (not a kunglao.py subcommand, module-design L448):
    python kunglao-init.py [<workspace>] [--type windows|linux|android]
        [--target <bins/ file>] [--resolve <answers.json>] [--force]
        [--hooks-json <path>] [--profile-root <path>]

#455 target alignment (intake step 0): the analysis TARGET is an explicit
    user-aligned input, never the first file in bins/ by sort order. Any
    undecided intake item (workspace / target / target_object / type) makes
    init print a structured pending-decision JSON to stdout and exit
    RC_PENDING_DECISIONS=8 (fail-closed, zero scaffold) — the AGENT layer
    collects answers via Claude Code's native question capability and
    re-runs with --resolve <answers.json>. Scripts NEVER read stdin as a
    user channel (stdin is not the user in Claude Code; isatty is
    untrustworthy) — all input()/confirm sites are gone. Containers
    (MSI/CFBF, APK/zip) are detected, their contents listed, and their
    type is never guessed. The persisted type (explicit > --resolve answer
    > analysis_state.txt) selects the toolchain contract; android never
    touches the VMware/VBox channel (toolchain.CHECK_SETS).

#304 type-aware extension:
    --type explicit > --resolve answer > persisted project_type >
    pending (sniff suggestion rides in pending context ONLY — never
    adopted). The type is persisted to analysis_state.txt
    project_type=<type>; the template is chosen by type.
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
import struct
import sys
import zipfile
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
# #455: the interactive consent channel is gone (no stdin); ask_then_install
# runs only under --assume-yes, decline semantics preserved.
import toolchain_install  # noqa: E402
# #455: shared pending-decision schema — the structured intake channel
# (stdout JSON + --resolve re-entry) shared with #449/#451.
import decision_pending  # noqa: E402
# F6 (#304 review): init-completeness predicate = single source in init_state.py
from init_state import VALID_TYPES, is_init_complete, read_project_type  # noqa: E402
import mcp_probe  # noqa: E402  (#316: MCP supply manifest/scaffold single source of truth)
# #454: wiring≠activation — the hooks-deployed output names the activation
# TTL window from the single source (never a second hardcoded 30).
from hook_activation import DEFAULT_TTL_MINUTES as HOOK_TTL_MINUTES  # noqa: E402
# #362: CLAUDE.md renders through the shared {{param}} engine (single
# rendering system with scripts/template_gen.py — leftover detection included)
import template_render  # noqa: E402
# #445: hook-entry construction + post-write self-check derive from THE
# canonical registration entry — init deploys a worker_budget subset but no
# longer hand-rolls its own entry shape or skips verification.
import hook_activation  # noqa: E402
import yaml  # noqa: E402  # #455: task_spec.yaml -> CLAUDE.md constraint section

MARKER = "[initialized]"
SEED_MIN = 3
HOOK_FILES = ("worker_budget.py",)  # DESIGN §7 0.3: PreToolUse + PostToolUse → worker_budget

# #478 deploy_env — the workspace engineering-environment layer (L1 hooks /
# L2 subagents / L3 MCP record / L4 skills). CORE_AGENTS deploy for every
# type; RE specialists stay orchestrator-dispatched (their routing table
# moved into routing, #135), never workspace-copied. AGENTS_SRC/SKILLS_SRC
# are the REPO's own tracked dirs — a workspace copy is the user's runtime
# artifact.
CORE_AGENTS = ("kunglao-worker.md", "kunglao-redteam.md",
               "kunglao-init-worker.md")
AGENTS_SRC = _SCRIPT_DIR.parent / "agents"
SKILLS_SRC = _SCRIPT_DIR.parent / "skills"
ENV_MANIFEST = "env-manifest.yaml"
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
RC_HOOK_WIRING = 7   # #445: hook deployment self-check FAILED (written layer/coverage/shape mismatch) — init FAIL, never a WARN
RC_PENDING_DECISIONS = 8  # #455: undecided intake item (workspace/target/
                          # target_object/type) — pending list on stdout,
                          # agent re-enters with --resolve; zero scaffold

# #455: intake interaction order (zero-arg entry walks this sequence).
INTAKE_GUIDANCE = (
    "Intake order: workspace path -> analysis target (bins/ file) -> "
    "project type -> task requirements (#449 needs-first intake). Collect "
    "answers for each decision via the Claude Code native question "
    "capability (never script stdin), write them to a JSON file as "
    "{decision_id: value}, and re-run with --resolve <answers.json>."
)

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
    # #455: workspace is OPTIONAL — a zero-arg invocation emits a pending
    # workspace decision (defined interaction order) instead of a bare
    # argparse usage error; --resolve supplies it on re-entry.
    parser.add_argument("workspace", nargs="?", default=None,
                        help="target workspace path (holds bins/, claim-register.yaml, etc.); "
                             "omitted -> pending decision (#455)")
    parser.add_argument("--type", choices=VALID_TYPES, default=None,
                        help="project type: windows|linux|android (#304)")
    parser.add_argument("--target", metavar="NAME", default=None,
                        help="#455: explicit analysis target — a file name under bins/ "
                             "(containers get a target_object round)")
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
    parser.add_argument("--no-hooks", action="store_true",
                        help="#478: skip hook deployment entirely (the ONLY "
                             "legal hooks skip; default deploys "
                             "<ws>/.claude/settings.json + self-check)")
    parser.add_argument("--skills", metavar="A,B", default=None,
                        help="#478: deploy auxiliary skills (comma-separated "
                             "names under skills/) to <ws>/.claude/skills/ — "
                             "pure opt-in, nothing installed without the flag")
    parser.add_argument("--assume-yes", action="store_true",
                        help="#408: consent to every ask-then-install prompt "
                             "(CI/headless; non-interactive stdin declines by default)")
    parser.add_argument("--resolve", metavar="PATH", default=None,
                        help="#455: answers file ({decision_id: value} JSON) collected "
                             "by the agent after a pending-decision exit 8")
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


def detect_sample(ws: Path, target: str) -> tuple[str, str]:
    """The ALIGNED analysis target under bins/ as the sample: (filename, sha256).

    #455: the target is explicit (flag / --resolve / unique file) — never
    the first file by sort order. Unknown target -> ("unknown", "")."""
    p = ws / "bins" / target if target else None
    if p is None or not p.is_file():
        return "unknown", ""
    try:
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        sha = ""
    return p.name, sha


# ---------- #455: target alignment (intake step 0) ----------

# CFBF composite-document signature (MSI / legacy OLE containers).
MAGIC_CFBF = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"
CONTAINER_KINDS = ("msi", "zip", "apk")

# Kind -> type suggestion for the pending context ONLY (never adopted —
# the whole point of #455). Containers deliberately have NO hint.
KIND_TYPE_HINT: dict[str, str] = {"pe": "windows", "elf": "linux"}

# Container contents listing bound (options stay askable; the full list
# rides in context.contents_full).
CONTAINER_OPTIONS_MAX = 12


def file_kind(path: Path) -> str:
    """Magic-byte classification: pe | elf | apk | zip | msi | unknown."""
    try:
        head = path.read_bytes()[:512]
    except OSError:
        return "unknown"
    if head[:8] == MAGIC_CFBF:
        return "msi"
    if head[:4] == b"PK\x03\x04":
        return "apk" if b"classes.dex" in head else "zip"
    if head[:4] == b"\x7fELF":
        return "elf"
    if head[:2] == b"MZ":
        return "pe"
    return "unknown"


def is_container(kind: str) -> bool:
    """MSI/APK/zip are containers — the analysis target is an embedded
    object; the container's own type is never guessed."""
    return kind in CONTAINER_KINDS


def survey_bins(ws: Path) -> list[dict]:
    """Every file under bins/ (name, size, kind), sorted for DISPLAY only —
    no selection decision ever follows from the order (#455). Reads bins/
    ONLY, never bin/ (#411 boundary)."""
    bins = ws / "bins"
    if not bins.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(bins.iterdir()):
        if not p.is_file():
            continue
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        out.append({"name": p.name, "size": size, "kind": file_kind(p)})
    return out


def zip_contents(path: Path) -> list[str]:
    """zip/APK contents listing (entry names)."""
    try:
        with zipfile.ZipFile(path) as zf:
            return zf.namelist()
    except (zipfile.BadZipFile, OSError):
        return []


def _cfb_sector_base(sector: int, sector_size: int) -> int:
    """MS-CFB: sector N lives at (N+1)*sector_size — the 512-byte header
    heads the file and for v4 (4096-byte sectors; every real-world MSI)
    bytes [512, sector_size) are padding. A naive 512+N*sector_size only
    coincides with the spec for 512-byte sectors and silently misaligns
    every v4 inventory (review HIGH-1)."""
    return (sector + 1) * sector_size


def _cfb_fat_ids(data: bytes, sector_size: int) -> list[int] | None:
    """FAT sector ids: header DIFAT[0..108] plus the extended DIFAT chain
    (first at 0x44, count at 0x48) — required once a file has more than
    109 FAT sectors (a 607MB MSI measured during the fix carries 145).
    None on out-of-bounds structure."""
    special = 0xFFFFFFFC  # FATSECT/DIFSECT/ENDOFCHAIN/FREESECT and above
    ids: list[int] = []
    for i in range(109):
        s = struct.unpack_from("<I", data, 0x4C + 4 * i)[0]
        if s < special:
            ids.append(s)
    per_sector = sector_size // 4
    next_dif = struct.unpack_from("<I", data, 0x44)[0]
    seen: set[int] = set()
    while next_dif < special and next_dif not in seen:
        seen.add(next_dif)
        base = _cfb_sector_base(next_dif, sector_size)
        if base + sector_size > len(data):
            return None
        for i in range(per_sector - 1):  # last slot = next DIFAT pointer
            s = struct.unpack_from("<I", data, base + 4 * i)[0]
            if s < special:
                ids.append(s)
        next_dif = struct.unpack_from(
            "<I", data, base + 4 * (per_sector - 1))[0]
    return ids


def _cfb_fat(data: bytes, sector_size: int) -> dict[int, int] | None:
    """FAT from the DIFAT (header + extended chain), spec sector offsets.
    None when the structure is unparseable/out of bounds."""
    fat_sector_ids = _cfb_fat_ids(data, sector_size)
    if fat_sector_ids is None:
        return None
    fat: dict[int, int] = {}
    entries_per_sector = sector_size // 4
    for fat_sector in fat_sector_ids:
        base = _cfb_sector_base(fat_sector, sector_size)
        if base + sector_size > len(data):
            return None
        for j in range(entries_per_sector):
            fat[fat_sector * entries_per_sector + j] = \
                struct.unpack_from("<I", data, base + 4 * j)[0]
    return fat


def cfb_stream_names(data: bytes) -> list[str]:
    """Names-level CFBF (MSI) directory listing per MS-CFB: sector N at
    (N+1)*sector_size, FAT via the DIFAT (header + extended chain),
    directory sectors walked along the FAT chain. Only STREAM entries
    (type 2) are listed — storages (1) and the root entry (5) are
    container structure, not embedded objects (review HIGH-1/LOW-4).
    Payloads/tables are NOT parsed — the #455 contract is an inventory.

    Unparseable structure -> [] (the caller surfaces the failure as an
    empty inventory in the pending context, never a crash)."""
    if len(data) < 512 or data[:8] != MAGIC_CFBF:
        return []
    ssz = struct.unpack_from("<H", data, 0x1E)[0]
    if not 6 <= ssz <= 20:
        return []
    sector_size = 1 << ssz
    first_dir = struct.unpack_from("<I", data, 0x30)[0]
    fat = _cfb_fat(data, sector_size)
    if fat is None:
        return []

    names: list[str] = []
    seen: set[int] = set()
    sector = first_dir
    while 0 <= sector < 0xFFFFFFFC and sector not in seen:
        seen.add(sector)
        base = _cfb_sector_base(sector, sector_size)
        if base + sector_size > len(data):
            break
        for i in range(sector_size // 128):
            entry = base + i * 128
            if data[entry + 66] != 2:  # streams only, structure excluded
                continue
            name_len = struct.unpack_from("<H", data, entry + 64)[0]
            raw = data[entry:entry + max(0, name_len - 2)]
            try:
                name = raw.decode("utf-16-le")
            except UnicodeDecodeError:
                continue
            if name and name not in names:
                names.append(name)
        sector = fat.get(sector, 0xFFFFFFFE)
    return names


def container_contents(path: Path, kind: str) -> list[str]:
    """Contents inventory for a container target (names level)."""
    if kind in ("zip", "apk"):
        return zip_contents(path)
    if kind == "msi":
        try:
            return cfb_stream_names(path.read_bytes())
        except OSError:
            return []
    return []


def emit_pending(ws: Path | None,
                 decisions: list["decision_pending.PendingDecision"],
                 ) -> int:
    """Print the pending-decision list (stdout = machine channel, stderr =
    human guidance) and return RC_PENDING_DECISIONS. Zero scaffold is the
    caller's invariant: this runs before any write."""
    doc = decision_pending.PendingDecisionList(
        flow="kunglao-init",
        workspace=str(ws) if ws is not None else None,
        guidance=INTAKE_GUIDANCE,
        decisions=decisions,
        resume={"argv": ["kunglao-init.py",
                         str(ws) if ws is not None else "<workspace>",
                         "--resolve", "<answers.json>"]},
    )
    print(doc.to_json())
    print(
        "kunglao-init: PENDING user decisions — collect via the agent's "
        "native question channel (AskUserQuestion), then re-run with "
        "--resolve <answers.json> (#455; zero scaffold written)",
        file=sys.stderr,
    )
    return RC_PENDING_DECISIONS


def _aligned_target(files: list[dict], explicit_target: str | None,
                    answers: dict[str, str],
                    ) -> tuple[str | None, str | None, int | None]:
    """Target name decision: explicit --target > --resolve answer > unique
    file in bins/. A multi-file bins/ returns (None, None, None) — the
    caller pends; sort order is NEVER a tiebreaker (#455). Malformed
    resolved target -> RC_ERROR."""
    names = [f["name"] for f in files]
    target = explicit_target or answers.get("target") or None
    if target is not None:
        if target not in names:
            print(
                f"kunglao-init: ERROR resolved target {target!r} is not a "
                f"file under bins/ (available: {', '.join(names) or 'none'})",
                file=sys.stderr)
            return None, None, RC_ERROR
        return target, next(f["kind"] for f in files if f["name"] == target), None
    if len(files) == 1:
        # Uniqueness is determinism, not sort-order arbitrariness.
        return files[0]["name"], files[0]["kind"], None
    return None, None, None


def _container_object(ws: Path, target: str, kind: str,
                      answers: dict[str, str],
                      ) -> tuple[str | None,
                                 "decision_pending.PendingDecision | None",
                                 int | None]:
    """target_object decision for a container target: a --resolve answer
    (validated against the real contents inventory; `__container__` analyzes
    the container itself) or a pending decision listing the contents."""
    contents = container_contents(ws / "bins" / target, kind)
    target_object = answers.get("target_object") or None
    if target_object is not None:
        if target_object not in contents and target_object != "__container__":
            print(
                f"kunglao-init: ERROR resolved target_object "
                f"{target_object!r} is not in the {kind} inventory",
                file=sys.stderr)
            return None, None, RC_ERROR
        return target_object, None, None
    decision = decision_pending.PendingDecision(
        decision_id="target_object",
        question=f"The target {target!r} is a {kind} container — "
                 "which embedded object is the analysis target?",
        kind=decision_pending.KIND_CHOICE,
        options=tuple(contents[:CONTAINER_OPTIONS_MAX] + ["__container__"]),
        default=None,
        context={"kind": kind, "contents_full": contents},
    )
    return None, decision, None


def _aligned_type(ws: Path, kind: str | None, explicit_type: str | None,
                  answers: dict[str, str],
                  ) -> tuple[str | None,
                             "decision_pending.PendingDecision | None",
                             int | None]:
    """Project-type decision: explicit --type > --resolve answer > persisted
    state > pending. A sniff hint (KIND_TYPE_HINT) is pending CONTEXT only —
    never adopted, never a default (#455). Malformed -> RC_ERROR."""
    project_type = explicit_type or answers.get("type") or None
    if project_type is not None and project_type not in VALID_TYPES:
        print(f"kunglao-init: ERROR resolved type {project_type!r} is not "
              f"one of {', '.join(VALID_TYPES)}", file=sys.stderr)
        return None, None, RC_ERROR
    if project_type is None:
        project_type = read_project_type(ws)
        if project_type not in VALID_TYPES:
            project_type = None
    if project_type is not None:
        return project_type, None, None
    suggested = KIND_TYPE_HINT.get(kind) if kind else None
    decision = decision_pending.PendingDecision(
        decision_id="type",
        question="Project type (environment contract selector)?",
        kind=decision_pending.KIND_CHOICE,
        options=tuple(VALID_TYPES),
        default=None,  # a sniff hint is never a default (#455)
        context={"suggested_type": suggested},
    )
    return None, decision, None


def align_target(ws: Path, files: list[dict],
                 explicit_target: str | None, explicit_type: str | None,
                 answers: dict[str, str] | None,
                 ) -> tuple[str | None, str | None, str | None, int | None]:
    """#455 intake step 0 decision matrix.

    Returns (target_name, target_object, project_type, pending_exit) —
    pending_exit is RC_PENDING_DECISIONS when a user decision is missing
    (the three values are then None / partial), None when aligned. Raises
    nothing; malformed resolved values are reported to stderr by the
    caller via the returned exit (fail-closed RC_ERROR handled in run()).

    Order: target (multi-file asks; unique file is deterministic) ->
    target_object (containers list contents, type never guessed) -> type
    (sniff hint is context only)."""
    answers = answers or {}
    target, kind, err = _aligned_target(files, explicit_target, answers)
    if err is not None:
        return None, None, None, err

    pending: list[decision_pending.PendingDecision] = []
    target_object: str | None = None
    if target is not None and kind is not None and is_container(kind):
        target_object, decision, err = _container_object(
            ws, target, kind, answers)
        if err is not None:
            return None, None, None, err
        if decision is not None:
            pending.append(decision)
    elif target is None:
        pending.append(decision_pending.PendingDecision(
            decision_id="target",
            question="bins/ holds multiple files — which one is the "
                     "analysis target?",
            kind=decision_pending.KIND_CHOICE,
            options=tuple(f["name"] for f in files),
            default=None,  # sort order is NOT a suggestion
            context={"bins": files},
        ))

    project_type, decision, err = _aligned_type(ws, kind, explicit_type,
                                                answers)
    if err is not None:
        return None, None, None, err
    if decision is not None:
        pending.append(decision)

    if pending:
        return target, target_object, project_type, emit_pending(ws, pending)
    return target, target_object, project_type, None


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
- **JDWP debugging (WARN, informational; #474 follow-up 2026-08-19)**: NOT a hard requirement — static-only and frida-driven flows never touch jdb. kunglao-init reports JDWP agent reachability via the raw 14-byte `JDWP-Handshake` echo (`adb forward tcp:8700 jdwp:<pid>` then handshake — side-effect-free, never `jdb -attach`). A miss is surfaced to the orchestrator as a capability-absence signal; whether to repair it (start the debuggable app / `am set-debug-app`) is the orchestrator's per-task decision, not an init gate. jdb remains the interactive driver for the analyst (`jdb -connect com.sun.jdi.SocketAttach:...`).
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


def write_state_line(ws: Path, key: str, value: str) -> bool:
    """Write `key=value` to analysis_state.txt (upsert, like
    write_project_type's append-or-replace). Returns True if written."""
    p = ws / "analysis_state.txt"
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    prefix = f"{key}="
    if any(line.strip().startswith(prefix) for line in text.splitlines()):
        new_lines = [f"{key}={value}" if line.strip().startswith(prefix)
                     else line for line in text.splitlines()]
        atomic_write(p, "\n".join(new_lines))
        return True
    if text and not text.endswith("\n"):
        text += "\n"
    atomic_write(p, text + f"{key}={value}\n")
    return True


def task_spec_section(ws: Path) -> str:
    """#455: render the task_spec-driven constraint block for CLAUDE.md.

    Absent task_spec.yaml -> "" (init legitimately precedes the needs-first
    intake; #449 fills it later). Unparseable/non-mapping task_spec ->
    TemplateRenderError -> the run() cleanup path (fail-closed: a corrupt
    contract never renders a silently-partial CLAUDE.md)."""
    p = ws / "task_spec.yaml"
    if not p.exists():
        return ""
    try:
        spec = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise template_render.TemplateRenderError(
            f"task_spec.yaml unparseable: {exc}") from exc
    if not isinstance(spec, dict):
        raise template_render.TemplateRenderError(
            "task_spec.yaml must be a YAML mapping")
    constraints = spec.get("constraints") or {}
    scope = spec.get("scope") or {}
    if not isinstance(constraints, dict) or not isinstance(scope, dict):
        raise template_render.TemplateRenderError(
            "task_spec.yaml constraints/scope must be mappings")
    lines: list[str] = ["## Task constraints (task_spec)", ""]
    if "vm_detonation" in constraints:
        lines.append(f"- vm_detonation: {constraints['vm_detonation']}")
    if "dynamic_re" in constraints:
        lines.append(f"- dynamic_re: {constraints['dynamic_re']}")
    if "time_budget_minutes" in constraints:
        lines.append(f"- time_budget_minutes: {constraints['time_budget_minutes']}")
    out = scope.get("out") or []
    if out:
        lines.append("- scope excluded: " + ", ".join(str(o) for o in out))
    if "depth" in spec:
        lines.append(f"- depth: {spec['depth']}")
    # The block carries its own trailing blank line: the template emits
    # `{{task_spec_section}}## Success criteria` with NO separator newline,
    # so an absent task_spec renders byte-identical to the pre-slot
    # template (zero drift for workspaces without task_spec.yaml).
    lines.append("")
    lines.append("")
    return "\n".join(lines)


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
        "task_spec_section": task_spec_section(ws),  # #455: user contract
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

    #389/#445: entry construction is delegated to THE canonical builder
    (hook_activation.build_hook_entry — uv-form, POSIX path). Same-name is
    not enough: a legacy bare-python entry with the same name must be
    REPLACED in place (position kept, no duplicate append) — the
    fixed-point pattern shared with external_kicker.
    """
    canonical = hook_activation.build_hook_entry(hook_dir, hook_file, matcher)
    command = canonical["hooks"][0]["command"]
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


def _patch_settings(path: Path, hook_dir: Path) -> int:
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


def hook_deploy_rc(report: dict) -> int:
    """#445: hook-deployment report -> init exit code.

    A DEPLOYED registration whose post-write self-check FAILED is a FAIL
    (RC_HOOK_WIRING) — never a warning + RC_OK (the issue's explicit
    demand: hooks written to a layer that does not fire must stop init).
    The nothing-written skip (no settings file present) stays benign —
    nothing was written, so there is nothing to mis-layer.
    """
    if report.get("deployed") and not report.get("selfcheck", {}).get("ok"):
        return RC_HOOK_WIRING
    return RC_OK


def deploy_hooks(ws: Path, hooks_json: Path | None) -> dict:
    """Idempotent hook deployment (E-init.2). Target: the --hooks-json copy, or <ws>/.claude/settings.json (if present).

    HOME is never a deployment target by default — if neither exists,
    skip with an explanation.

    #445: construction comes from hook_activation.build_hook_entry (the
    canonical entry's single construction source) and every write is
    followed by the canonical post-write self-check (layer vs fire layers /
    coverage / command shape). Mismatch lands in the report as
    selfcheck.ok=False and maps to RC_HOOK_WIRING via hook_deploy_rc —
    init FAIL, not a WARN.
    """
    hook_dir = Path(__file__).resolve().parent.parent / "hooks"
    if hooks_json is not None:
        target = Path(hooks_json).resolve()
        layer = "operator-declared"  # the operator named the file explicitly
    else:
        target = ws / ".claude" / "settings.json"
        layer = "project"
        if not target.exists():
            return {"deployed": False, "target": None,
                    "reason": "no <workspace>/.claude/settings.json (HOME settings never written)"}
    added = _patch_settings(target, hook_dir)
    selfcheck = hook_activation.selfcheck_registration(
        target, expected_files=HOOK_FILES, hook_dir=hook_dir,
        workspace=ws, layer=layer)
    return {"deployed": True, "target": str(target), "added": added,
            "selfcheck": selfcheck}


def _deploy_agents(ws: Path) -> list[dict]:
    """#478 L2: copy CORE_AGENTS repo -> <ws>/.claude/agents/, sha256-guarded.

    Idempotent: target hash == source hash -> unchanged; differs -> update
    (the repo source is the truth); absent -> create. Returns the manifest
    component entries. Copy failures raise (OSError) — the caller maps to
    RC_ERROR (fail fast, never a half-deployed agents dir).
    """
    comps: list[dict] = []
    dst_dir = ws / ".claude" / "agents"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in CORE_AGENTS:
        src = AGENTS_SRC / name
        if not src.is_file():
            raise RuntimeError(
                f"#478 L2: core agent source missing: {src} "
                f"(repo layout defect — agents/ must carry {CORE_AGENTS})")
        dst = dst_dir / name
        digest = hashlib.sha256(src.read_bytes()).hexdigest()
        status = "unchanged"
        if not dst.exists() or hashlib.sha256(dst.read_bytes()).hexdigest() != digest:
            atomic_write(dst, src.read_text(encoding="utf-8"))
            status = "deployed"
        comps.append({
            "name": f"agent:{name.removesuffix('.md')}",
            "path": f".claude/agents/{name}",
            "sha256": digest,
            "status": status,
        })
    return comps


def _deploy_skills(ws: Path, skills: list[str] | None) -> dict:
    """#478 L4: pure opt-in skill deployment (`--skills a,b`).

    Copies <repo>/skills/<name>/ -> <ws>/.claude/skills/<name>/ recursively.
    No flag -> nothing installed. Unknown name -> ValueError (caller maps
    to RC_ERROR with the valid-names list — fail fast on typo'd flags).
    Returns the manifest component entry.
    """
    dst_root = ws / ".claude" / "skills"
    if not skills:
        return {"name": "skills", "path": ".claude/skills/",
                "status": "none", "detail": "opt-in (--skills a,b)"}
    valid = sorted(d.name for d in SKILLS_SRC.iterdir() if d.is_dir())
    unknown = [s for s in skills if s not in valid]
    if unknown:
        raise ValueError(
            f"unknown --skills name(s): {', '.join(unknown)} "
            f"(available: {', '.join(valid)})")
    for name in skills:
        src = SKILLS_SRC / name
        dst = dst_root / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    return {"name": "skills", "path": ".claude/skills/",
            "status": f"deployed({','.join(skills)})"}


def _record_mcp(ws: Path, project_type: str) -> list[dict]:
    """#478 L3: probe MCP supply via the SINGLE enumeration
    (mcp_probe.registered_names / check_mcp — reused, never copied) and
    RECORD the state. Registration is NEVER executed by init: the manifest
    register commands carry <path>/<ida-url> placeholders only a human can
    fill, and a broken auto-registration would shadow a working user-level
    one (the exact hazard the empty-scaffold rule avoids). Interactive
    consent (auto-register / custom path / skip) is #451's channel.
    Degradation is WARN: recorded in the manifest + named on stderr —
    never silent, never a FAIL RC (#474: registered != usable).

    #478 review MEDIUM-1: ws must be passed explicitly — `Path(".")` made
    the workspace-level .mcp.json lookup depend on process cwd (workspace
    registrations were missed whenever init ran from another directory).
    """
    mcp_probe.registered_names(mcp_probe.claude_json_path(), ws)  # registry read warms the single-source probe
    comps: list[dict] = []
    for check in mcp_probe.check_mcp(ws, project_type):
        if check.status == "PASS":
            comps.append({"name": f"mcp:{check.name}", "status": "pass",
                          "detail": check.detail})
            continue
        comps.append({
            "name": f"mcp:{check.name}", "status": "manual",
            "tier": check.tier,
            "detail": f"not registered — register: {check.fix}",
        })
        print(f"kunglao-init: mcp {check.tier}-missing {check.name} — "
              f"manual registration recorded in {ENV_MANIFEST} "
              f"(fix: {check.fix})", file=sys.stderr)
    return comps


def deploy_env(ws: Path, project_type: str, hooks_json: Path | None = None,
               no_hooks: bool = False, skills: list[str] | None = None,
               plugin_mode: bool = False) -> dict:
    """#478: the workspace engineering-environment layer — L1 hooks /
    L2 subagents / L3 MCP record / L4 skills + the env-manifest ledger.

    Uniform contract per component: 落位 + probe 验证 + 登记 env manifest +
    降级明示. Returns a report {"hook_report", "manifest"}; hook failures
    surface through hook_report (the #445 RC_HOOK_WIRING channel — deploy
    failure is hook-wiring failure, no new RC). plugin_mode=True is the
    #364 seam: a plugin's hooks.json declares L1/L2, so init skips them
    (behavior locked by test; no plugin form implemented here).
    """
    components: list[dict] = []
    hook_report: dict = {"deployed": False,
                         "reason": "--no-hooks (explicit opt-out)"}
    if plugin_mode:
        # #364 seam: L1/L2 belong to the plugin declaration — skipped.
        hook_report = {"deployed": False,
                       "reason": "plugin_mode (#364 seam: hooks.json owns L1/L2)"}
        components.append({"name": "hooks", "status": "skipped",
                           "detail": hook_report["reason"]})
        components.append({"name": "agents", "status": "skipped",
                           "detail": hook_report["reason"]})
    elif no_hooks:
        components.append({"name": "hooks", "status": "skipped",
                           "detail": "--no-hooks (explicit opt-out)"})
        components.extend(_deploy_agents(ws))
    else:
        # L1: create-then-deploy — the #478 deadlock fix. The scaffold
        # never created .claude/, deploy_hooks required it to exist, so the
        # default path ALWAYS skipped. Absence is no longer a legal default:
        # create the minimal file, then deploy through the #445 canonical
        # path (construction + self-check unchanged).
        settings = ws / ".claude" / "settings.json"
        if hooks_json is None and not settings.exists():
            settings.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(settings, json.dumps({"hooks": {}}, indent=2))
        hook_report = deploy_hooks(ws, hooks_json)
        if hook_report.get("deployed"):
            components.append({
                "name": "hooks", "path": ".claude/settings.json",
                "sha256": hashlib.sha256(
                    Path(hook_report["target"]).read_bytes()).hexdigest(),
                "status": "deployed",
                "detail": f"selfcheck ok={hook_report['selfcheck'].get('ok')}",
            })
        else:
            components.append({"name": "hooks", "status": "skipped",
                               "detail": hook_report.get("reason", "?")})
        components.extend(_deploy_agents(ws))
    components.extend(_record_mcp(ws, project_type))
    try:
        components.append(_deploy_skills(ws, skills))
    except ValueError as exc:
        # fail fast AFTER recording the rest — but the run is RC_ERROR; the
        # caller re-raises via the report.
        return {"hook_report": hook_report, "manifest": None,
                "skills_error": str(exc)}
    manifest = {
        "generated": utc_now(),
        "project_type": project_type,
        "components": components,
    }
    atomic_write(ws / ENV_MANIFEST,
                 yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True))
    return {"hook_report": hook_report, "manifest": manifest,
            "skills_error": None}


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


# #473: task-oracle skeleton — the completion-gate power line. Content is
# deliberately structural (no analysis, no task invention): task_text carries
# a backfill marker the orchestrator's Phase 1 replaces with the user's
# verbatim task; open_items/deferrals start empty; registered_ts proves the
# file is non-empty on disk.
ORACLE_BACKFILL_MARKER = "pending-user-input-backfill"

ORACLE_FILE = "task-oracle.yaml"


def write_task_oracle_skeleton(ws: Path) -> bool:
    """#473: write the workspace task-oracle.yaml skeleton. Returns True when
    written; an existing non-empty oracle is never clobbered (Phase-0
    backfill survives re-inits); empty/corrupt remnants are replaced."""
    target = ws / ORACLE_FILE
    if target.exists() and target.read_text(encoding="utf-8").strip():
        return False
    text = (
        "# task-oracle.yaml — pre-registered completion anchor (#55, #473).\n"
        "# Skeleton written by kunglao-init; the orchestrator backfills\n"
        "# task_text with the user's verbatim task at Phase 1 (SKILL.md)\n"
        "# before the first dispatch.\n"
        f"task_text: {ORACLE_BACKFILL_MARKER}\n"
        "open_items: []\n"
        "deferrals: []\n"
        "adjudication:\n"
        "  stop_hook_active:\n"
        "    second_stop: false\n"
        "    last_decision: \"\"\n"
        "    last_decision_at: \"\"\n"
        f"registered_ts: {utc_now()}\n"
    )
    atomic_write(target, text)
    return True


def initialize(ws: Path, hooks_json: Path | None,
                project_type: str | None = None, no_mcp: bool = False,
                created: "Collection[Path] | None" = None,
                target: str | None = None,
                target_object: str | None = None,
                no_hooks: bool = False,
                skills: "list[str] | None" = None,
                plugin_mode: bool = False) -> int:
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
    # #455: sample identity follows the ALIGNED target (never sorted-first)
    sample, sample_sha = detect_sample(ws, target)
    if target_object:
        write_state_line(ws, "analysis_target_object", target_object)

    # #304: write the resolved project type
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
    # #478 deploy_env: the engineering-environment layer (hooks/agents/
    # mcp-record/skills + env-manifest ledger). Hook failures keep the #445
    # channel (RC_HOOK_WIRING); agents/skills copy failures are RC_ERROR.
    env_report = deploy_env(ws, project_type, hooks_json=hooks_json,
                            no_hooks=no_hooks, skills=skills,
                            plugin_mode=plugin_mode)
    if env_report.get("skills_error"):
        print(f"kunglao-init: ERROR {env_report['skills_error']}", file=sys.stderr)
        return RC_ERROR
    hook_report = env_report["hook_report"]
    rc = hook_deploy_rc(hook_report)  # #445: self-check mismatch FAILs init
    if rc != RC_OK:
        print(f"kunglao-init: hooks selfcheck FAILED — "
              f"{hook_report.get('selfcheck', {}).get('mismatches')}", file=sys.stderr)
        return rc

    # #473 gate power-on: register the task-oracle skeleton. The closing gate
    # chain (completion_gate -> premature_termination_detect) is dead without
    # a workspace oracle — nobody registered one. Init has no user task text,
    # so this writes the STRUCTURE (pending-user-input marker + empty ledgers
    # + registered_ts); the orchestrator backfills task_text at Phase 1
    # (SKILL.md). Idempotent: a pre-existing oracle is never clobbered, and
    # the file is deliberately OUTSIDE the state-hash inputs (it is a
    # workspace artifact, not scaffold state).
    oracle_written = write_task_oracle_skeleton(ws)
    if oracle_written:
        print("kunglao-init: task-oracle.yaml skeleton registered "
              "(task_text pending Phase-0 backfill by the orchestrator)")

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
        print(f"kunglao-init: hooks skipped — {hook_report['reason']}")  # reachable ONLY via --no-hooks / plugin seam (#478)
    return RC_OK


def run(ws: Path | None, force: bool = False, hooks_json: Path | None = None,
        profile_root: Path | None = None,
        project_type: str | None = None,
        skip_toolchain: bool = False, no_mcp: bool = False,
        install_git_hooks_flag: bool = False,
        assume_yes: bool = False,
        target: str | None = None,
        answers: dict[str, str] | None = None,
        no_hooks: bool = False,
        skills: list[str] | None = None,
        plugin_mode: bool = False) -> int:
    """State-machine entry (#304 amended flow, comment 304-5289955958;
    #455 target alignment as intake step 0):

    Phase 0 environment guard → workspace resolution (missing → pending
    `workspace` decision, exit 8 — the zero-arg interaction order is
    defined, never a bare argparse error) → re-init check (resume; if
    project_type is missing, upgrade by writing it then exit 0, F1) →
    no-sample friendly prompt → **target alignment** (multi-file /
    container / undecided type → structured pending list, exit 8, zero
    scaffold; a sniff hint is context only, never adopted) →
    **toolchain.check preflight** (HARD FAIL → #408 ask-then-install ONLY
    under --assume-yes — stdin is not a user channel (#455); the headless
    refusal with per-item install guidance + cleanup is the default) →
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
    # #455: stdout is the MACHINE channel (pending-decision JSON must be
    # parseable alone) — informational guard lines go to stderr.
    for line in guard_log:
        print(line, file=sys.stderr)

    # #455 intake step 0a — workspace resolution. A missing workspace is a
    # PENDING DECISION (defined interaction order), not an argparse error;
    # the --resolve answers may carry it on re-entry.
    answers = answers or {}
    if ws is None:
        ws_answer = answers.get("workspace")
        if not ws_answer:
            return emit_pending(None, [decision_pending.PendingDecision(
                decision_id="workspace",
                question="Workspace path (the directory that holds or will "
                         "hold bins/)?",
                kind=decision_pending.KIND_VALUE,
                options=(), default=None,
            )])
        ws = Path(ws_answer)
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
            # Write the missing type (explicit > --resolve > state >
            # pending) and exit 0; register/marker/seeds untouched.
            if project_type is None:
                project_type = answers.get("type") or read_project_type(ws)
                if project_type not in VALID_TYPES:
                    # #455: no sniff-and-accept — pending decision instead
                    return emit_pending(ws, [decision_pending.PendingDecision(
                        decision_id="type",
                        question="Project type (environment contract selector)?",
                        kind=decision_pending.KIND_CHOICE,
                        options=tuple(VALID_TYPES), default=None,
                        context={"suggested_type": None},
                    )])
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
    files = survey_bins(ws)
    if not files:
        print(
            "kunglao-init: no analysis target found — place a sample into bins/ "
            "or specify a path, then re-run "
            "kunglao-init.py <ws> --type <windows|linux|android>.",
            file=sys.stderr,
        )
        return RC_NO_SAMPLE

    # #455 intake step 0 — target alignment BEFORE any file is written:
    # target (multi-file must ask; unique file is deterministic) ->
    # target_object (containers list contents, type never guessed) ->
    # type (sniff hint is context only). Any undecided item -> pending
    # list (exit RC_PENDING_DECISIONS), zero scaffold.
    target_name, target_object, project_type, pending_rc = align_target(
        ws, files, target, project_type, answers)
    if pending_rc is not None:
        return pending_rc
    assert target_name is not None and project_type is not None  # aligned

    # #304: toolchain.check BEFORE scaffold — HARD FAIL => #408
    # ask-then-install, then refuse + cleanup only for items still HARD.
    # Verify-first: a refused init leaves no half-initialized state behind.
    # #455: stdin is NOT a user channel (isatty untrustworthy) — the
    # interactive ask branch is gone. ask_then_install runs ONLY under
    # --assume-yes; otherwise the #304 headless refusal (per-item install
    # guidance, exit 4) is the single non-consent path. The consent MENU
    # as an AskUserQuestion flow is #451's change.
    if not skip_toolchain:
        report = toolchain.check(ws, project_type)
        if report.overall_status == toolchain.Status.FAIL:
            if assume_yes:
                resolved = toolchain_install.ask_then_install(
                    report, ws, report.project_type, assume_yes=True)
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
                          no_mcp=no_mcp, created=created,
                          target=target_name, target_object=target_object,
                          no_hooks=no_hooks, skills=skills,
                          plugin_mode=plugin_mode)
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
    answers: dict[str, str] = {}
    if args.resolve is not None:
        # #455: fail-closed answers loading — a missing/corrupt answers
        # file is RC_ERROR, never an empty-answers silent proceed.
        try:
            answers = decision_pending.load_answers(Path(args.resolve))
        except ValueError as exc:
            print(f"kunglao-init: ERROR --resolve {args.resolve}: {exc}",
                  file=sys.stderr)
            return RC_ERROR
    skills = ([s.strip() for s in args.skills.split(",") if s.strip()]
              if args.skills else None)
    return run(Path(args.workspace) if args.workspace else None,
               force=args.force, hooks_json=args.hooks_json,
               profile_root=args.profile_root, project_type=args.type,
               skip_toolchain=args.skip_toolchain, no_mcp=args.no_mcp,
               install_git_hooks_flag=args.install_git_hooks,
               assume_yes=args.assume_yes,
               target=args.target, answers=answers,
               no_hooks=args.no_hooks, skills=skills)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env bash
# scripts/install_unidbg.sh — unidbg deployment preconditions installer (#165).
#
# House env-repair CLI shape (init-worker conventions): idempotent, safe to
# re-run, clear per-step verdicts, a failed step is REPORTED and fails the
# run — never silently skipped. No analysis data is touched.
#
# What it does (the deployment preconditions the unidbg-env-filling card
# states as binding before any harness runs):
#   1. JDK presence check (java + javac — a JRE alone cannot build).
#   2. Maven presence check (the repo's mvnw wrapper can serve, but a real
#      Maven is the robust path; a missing Maven with a working wrapper is
#      reported as SKIP-with-reason, not failure).
#   3. unidbg fetched from REMOTE: shallow clone of the MCP-capable master
#      line (override the ref with UNIDBG_REF). The dependency tree resolves
#      over the network on the FIRST build — expect the first build to be
#      the slow one; offline hosts stall here.
#   4. First build of the Android module (test-compile scope: builds main
#      + test classes without running the suite).
#   5. Verify-after-repair: built classes exist for api + android modules.
#
# Idempotency: a marker file (.unidbg-installed.json) records the ref and
# resolved commit. A re-run against the same ref verifies and exits fast;
# use --force to re-clone and rebuild.
#
# Usage:
#   scripts/install_unidbg.sh [--target DIR] [--force] [--dry-run]
#     --target DIR   install location (default: ./vendor/unidbg)
#     --force        re-clone and rebuild even if the marker matches
#     --dry-run      print the step plan with current findings; no side effects
#
# Exit codes: 0 all steps green; 1 a step failed (the failing step is named
# on stderr); 2 usage error.
set -uo pipefail

TARGET="${UNIDBG_TARGET:-./vendor/unidbg}"
FORCE=0
DRY_RUN=0
REF="${UNIDBG_REF:-master}"   # master line = MCP-capable (unidbg-env-filling card)

log_ok()   { printf '[OK]   %s\n' "$1"; }
log_fail() { printf '[FAIL] %s\n' "$1" >&2; }
log_skip() { printf '[SKIP] %s\n' "$1"; }
log_plan() { printf '[PLAN] %s\n' "$1"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --target) TARGET="$2"; shift 2 ;;
        --force)  FORCE=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
        *) printf 'usage error: unknown argument %s\n' "$1" >&2; exit 2 ;;
    esac
done

FAILED=0

# ---- step 1: JDK (java + javac) ----
if command -v java >/dev/null 2>&1 && command -v javac >/dev/null 2>&1; then
    JVM_VER="$(java -version 2>&1 | head -1)"
    log_ok "JDK present (${JVM_VER})"
else
    log_fail "JDK missing or JRE-only: need java AND javac on PATH (install a JDK; this is a human-install blocker)"
    FAILED=1
fi

# ---- step 2: Maven (wrapper-eligible) ----
if command -v mvn >/dev/null 2>&1; then
    log_ok "Maven present ($(mvn -v 2>/dev/null | head -1))"
else
    log_skip "Maven not on PATH — the repo's mvnw wrapper will be used; wrapper still needs the JDK from step 1"
fi

# ---- step 3: fetch from remote (clone or verify) ----
MARKER="${TARGET}/.unidbg-installed.json"
if [ "$DRY_RUN" -eq 1 ]; then
    log_plan "step 3 would fetch ${REF} into ${TARGET} (shallow clone; existing install -> fetch + reset to ref)"
    if [ -f "$MARKER" ]; then
        log_plan "marker found: $(cat "$MARKER" 2>/dev/null || printf 'unreadable') — re-run takes the verify fast path"
    else
        log_plan "no marker: full clone + first build would run"
    fi
    log_plan "step 4 would build the android module (first build resolves the dependency tree over the network)"
    log_plan "step 5 would verify built classes for the api + android modules"
    if [ "$FAILED" -ne 0 ]; then
        printf -- '--dry-run plan blocked: fix the [FAIL] steps above first\n' >&2
        exit 1
    fi
    log_plan "dry run clean"
    exit 0
fi

if [ "$FORCE" -eq 1 ] && [ -d "$TARGET" ]; then
    log_skip "--force: removing previous install at ${TARGET}"
    rm -rf "$TARGET"
fi

if [ -d "$TARGET/.git" ]; then
    CUR_REF="$(git -C "$TARGET" rev-parse --abbrev-ref HEAD 2>/dev/null || printf 'unknown')"
    if [ "$CUR_REF" = "$REF" ]; then
        log_ok "clone present at ${TARGET} on ref ${REF} — verifying remote is fresh"
        git -C "$TARGET" fetch --depth 1 origin "$REF" \
            && git -C "$TARGET" reset --hard "origin/${REF}" >/dev/null 2>&1 \
            && log_ok "repository reset to origin/${REF}" \
            || { log_fail "could not fetch/reset ${TARGET} to origin/${REF} (network or remote problem)"; FAILED=1; }
    else
        log_fail "${TARGET} is on ref '${CUR_REF}', expected '${REF}' — re-run with --force to re-clone on ${REF}"
        FAILED=1
    fi
else
    mkdir -p "$(dirname "$TARGET")"
    git clone --depth 1 --branch "$REF" https://github.com/zhkl0228/unidbg "$TARGET" \
        && log_ok "cloned ${REF} into ${TARGET}" \
        || { log_fail "clone of unidbg (${REF}) failed — check network/proxy; the dependency tree needs the same channel at build time"; FAILED=1; }
fi

# ---- step 4: first build (dependency resolution happens here) ----
if [ "$FAILED" -eq 0 ] && [ -f "${TARGET}/unidbg-android/pom.xml" ]; then
    if command -v mvn >/dev/null 2>&1; then
        BUILD_CMD=(mvn -q -DskipTests test-compile)
    elif [ -x "${TARGET}/mvnw" ]; then
        log_skip "no system Maven — using the repository wrapper (mvnw)"
        BUILD_CMD=("${TARGET}/mvnw" -q -DskipTests test-compile)
    else
        log_fail "no Maven and no mvnw wrapper found in ${TARGET} — cannot build"
        BUILD_CMD=()
        FAILED=1
    fi
    if [ "${#BUILD_CMD[@]}" -gt 0 ]; then
        (cd "$TARGET" && "${BUILD_CMD[@]}") \
            && log_ok "build green (first build resolved the dependency tree; later builds are incremental)" \
            || { log_fail "build failed — read the Maven output above; dependency resolution errors are usually network or JDK-version floors"; FAILED=1; }
    fi
elif [ "$FAILED" -eq 0 ]; then
    log_fail "${TARGET}/unidbg-android/pom.xml not found — clone layout unexpected; refusing to build blind"
    FAILED=1
fi

# ---- step 5: verify-after-repair ----
if [ "$FAILED" -eq 0 ]; then
    FOUND_CLASSES=0
    for d in "${TARGET}/unidbg-api/target/classes" "${TARGET}/unidbg-android/target/classes"; do
        if [ -d "$d" ]; then
            FOUND_CLASSES=$((FOUND_CLASSES + 1))
        fi
    done
    if [ "$FOUND_CLASSES" -eq 2 ]; then
        log_ok "verified: built classes present for api + android modules"
        printf '{"ref": "%s", "commit": "%s"}\n' "$REF" "$(git -C "$TARGET" rev-parse HEAD 2>/dev/null || printf 'unknown')" > "$MARKER"
    else
        log_fail "verification failed: expected built classes in unidbg-api and unidbg-android targets (found ${FOUND_CLASSES}/2)"
        FAILED=1
    fi
fi

if [ "$FAILED" -ne 0 ]; then
    printf 'install_unidbg: FAILED — fix the [FAIL] steps above and re-run (safe to re-run at any point)\n' >&2
    exit 1
fi
log_ok "install_unidbg: all steps green (${REF} at ${TARGET})"

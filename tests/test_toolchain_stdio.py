# -*- coding: utf-8 -*-
"""Tests for issue #451 task ③ — the three stdio defects from the
2026-08-17 user-terminal transcript (issue evidence 2), fixed:

  * 交错 (interleave): stdout prompt lines not flushed before the stderr
    refusal block -> the REFUSE line splices into the dangling prompt.
    Fix: kunglao-init flushes stdout BEFORE writing the stderr refusal;
    toolchain_install flushes its key prompt lines.
  * 乱码 (mojibake): `REFUSE —` rendered as `REFUSE ??` — stderr not
    reconfigured to utf-8 while stdout was (GBK/UTF-8 mixed stream).
    Fix: toolchain.py / kunglao-init.py / toolchain_install.py all
    reconfigure stderr to utf-8/replace (shared helper per script).
  * 伪装 (disguise): a headless (no-consent-channel) degrade printed
    "declined" — indistinguishable from a user refusal. #455 removed
    input()/isatty; #451 finishes the semantics: "declined" appears ONLY
    behind a real user choice (--resolve answer); a headless degrade says
    non-interactive/no-consent-channel instead.

TDD RED phase: written BEFORE the implementation.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load_init_module():
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_stdio_under_test", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _TimelineStream:
    """Stream appending labeled events to ONE shared timeline so cross-stream
    ordering (stdout flush vs stderr write) is pinnable."""

    def __init__(self, label: str, log: list) -> None:
        self._label = label
        self._log = log

    def write(self, s: str) -> int:
        self._log.append((self._label, "write", s))
        return len(s)

    def flush(self) -> None:
        self._log.append((self._label, "flush", ""))

    @property
    def encoding(self) -> str:
        return "utf-8"


class _ReconfigureRecorder:
    """Stream recording reconfigure() calls (utf-8 pinning)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def reconfigure(self, **kwargs):
        self.calls.append(dict(kwargs))

    def write(self, s):  # pragma: no cover — not used in these tests
        return len(s)

    def flush(self):  # pragma: no cover
        pass


# ---------- 交错: stdout flushed before the stderr refusal block ----------

def test_refuse_flushes_stdout_before_stderr_block(tmp_path, monkeypatch):
    """The stderr REFUSE block may not overtake buffered stdout prompt
    lines: on one shared event timeline, a stdout FLUSH must appear BEFORE
    the first stderr WRITE of refuse_toolchain (2026-08-17 transcript: the
    REFUSE line spliced into the dangling floss prompt)."""
    mod = _load_init_module()
    import toolchain as tc

    report = tc.ToolchainReport(project_type="windows", items=[
        tc.CheckResult(name="die", status=tc.Status.FAIL, tier=tc.Tier.HARD,
                       detail="die not found in PATH"),
    ])
    log: list[tuple[str, str, str]] = []
    monkeypatch.setattr(mod.sys, "stdout", _TimelineStream("out", log))
    monkeypatch.setattr(mod.sys, "stderr", _TimelineStream("err", log))

    ws = tmp_path / "ws"
    ws.mkdir()
    mod.refuse_toolchain(ws, report)

    first_err_write = next(
        (i for i, (label, kind, _) in enumerate(log)
         if label == "err" and kind == "write"), None)
    assert first_err_write is not None, "refusal must write to stderr"
    out_flushes_before = [
        i for i, (label, kind, _) in enumerate(log)
        if label == "out" and kind == "flush" and i < first_err_write]
    assert out_flushes_before, \
        f"stdout must be flushed before the stderr refusal block (#451 交错): {log}"


# ---------- 乱码: stderr unified to utf-8 in all three scripts ----------

def test_toolchain_ensures_utf8_stderr():
    """toolchain exposes a shared _ensure_utf8_stderr helper; a stream with
    reconfigure records encoding=utf-8 + errors=replace; a stream without
    the method fails open (False, no raise)."""
    import toolchain as tc
    rec = _ReconfigureRecorder()
    assert tc._ensure_utf8_stderr(rec) is True
    assert rec.calls and rec.calls[0]["encoding"] == "utf-8"
    assert rec.calls[0]["errors"] == "replace"

    class _Bare:
        def write(self, s):
            return len(s)

    assert tc._ensure_utf8_stderr(_Bare()) is False


def test_kunglao_init_ensures_utf8_stderr():
    mod = _load_init_module()
    rec = _ReconfigureRecorder()
    assert mod._ensure_utf8_stderr(rec) is True
    assert rec.calls and rec.calls[0]["encoding"] == "utf-8"


def test_toolchain_install_ensures_utf8_stderr():
    import toolchain_install as ti
    rec = _ReconfigureRecorder()
    assert ti._ensure_utf8_stderr(rec) is True
    assert rec.calls and rec.calls[0]["encoding"] == "utf-8"


# The scripts owning an utf-8 stderr CALL SITE (fault-inject M8 pinned set).
# toolchain_negotiation.py is NOT here: it has no own call — importing
# toolchain (module level) runs toolchain's site for it.
_UTF8_STDERR_CALL_SITE_SCRIPTS = (
    "toolchain.py",           # module level
    "kunglao-init.py",        # first statement of main()
    "toolchain_install.py",   # module level
)


def test_utf8_stderr_helpers_delegate_to_utf8_boot_863f():
    """#863 Family H: the three per-script `_ensure_utf8_stderr` copies
    (3x9, byte-identical bodies) are single-sourced as
    `utf8_boot.ensure_utf8_stderr` (#811 stdio-insurance module) and each
    script binds the SHARED function object by alias — the identity assert
    is the strongest delegation form (the former textual helper-shape
    tripwire could not tell a delegation from a fourth copy)."""
    import toolchain as tc
    import toolchain_install as ti
    import utf8_boot

    for mod in (tc, ti, _load_init_module()):
        assert mod._ensure_utf8_stderr is utf8_boot.ensure_utf8_stderr, (
            f"{mod.__name__}._ensure_utf8_stderr must BE "
            f"utf8_boot.ensure_utf8_stderr (#863 Family H delegation)")


def test_utf8_stderr_call_sites_pinned_in_source():
    """Fault-inject M8 (SURVIVOR -> killed), restated under #863 Family H:
    delegation single-sources the HELPER, but the 乱码 fix is the CALL —
    deleting the `_ensure_utf8_stderr(sys.stderr)` call while keeping the
    helper passed all 67 tests (GBK stderr regains the 乱码 path, zero
    interception). Source tripwire, same手法 as the FAIL-face scan in
    test_toolchain_next_action.py: each script must contain the call
    EXACTLY once — deletion (0) or accidental duplication (2+) is red."""
    for name in _UTF8_STDERR_CALL_SITE_SCRIPTS:
        source = (SCRIPTS / name).read_text(encoding="utf-8")
        n = source.count("_ensure_utf8_stderr(sys.stderr)")
        assert n == 1, (
            f"{name}: expected exactly 1 `_ensure_utf8_stderr(sys.stderr)` "
            f"call site, found {n} — the 乱码 fix is the CALL, not the "
            f"helper; restore the call site (#451 fault-inject M8, #863)")


# ---------- 伪装: headless degrade never wears the "declined" label ----------

def test_headless_degrade_wording_is_not_declined(tmp_path, capsys):
    """toolchain_install (standalone CLI posture, no --assume-yes): the
    non-consent degrade must SAY it is a non-interactive no-channel
    auto-degrade pointing at the decision channel — the word 'declined'
    (a user refusal) must not appear."""
    import toolchain as tc
    import toolchain_install as ti

    report = tc.ToolchainReport(project_type="windows", items=[
        tc.CheckResult(name="die", status=tc.Status.FAIL, tier=tc.Tier.HARD,
                       detail="die not found in PATH"),
    ])
    resolved = ti.ask_then_install(report, ws=tmp_path / "ws",
                                   project_type="windows", assume_yes=False)
    item = next(i for i in resolved.items if i.name == "die")
    assert item.status == tc.Status.WARN
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "declined" not in combined, \
        f"headless degrade must not claim a user refusal: {combined}"
    assert "non-interactive" in combined, combined
    assert "no consent channel" in combined, combined
    assert "--resolve" in combined or "#451" in combined, \
        f"the decision channel must be named: {combined}"


def test_install_prompt_lines_flushed(tmp_path, capsys, monkeypatch):
    """The 'X is missing' prompt lines flush — a dangling un-newlined
    prompt is exactly the 交错 defect (floss prompt + REFUSE splice)."""
    import toolchain as tc
    import toolchain_install as ti

    report = tc.ToolchainReport(project_type="windows", items=[
        tc.CheckResult(name="floss", status=tc.Status.FAIL,
                       tier=tc.Tier.HARD, detail="floss not found in PATH"),
    ])

    flushed: list[str] = []
    real_print = print

    def _flush_spy(*args, **kwargs):
        real_print(*args, **kwargs)
        if kwargs.get("flush"):
            flushed.append(" ".join(str(a) for a in args))

    import builtins
    monkeypatch.setattr(builtins, "print", _flush_spy)
    ti.ask_then_install(report, ws=tmp_path / "ws", project_type="windows",
                        assume_yes=False)
    capsys.readouterr()
    assert any("floss is missing" in line for line in flushed), \
        f"missing-tool prompt lines must flush: {flushed}"

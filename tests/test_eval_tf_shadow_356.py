# -*- coding: utf-8 -*-
"""tests/test_eval_tf_shadow_356.py — the #356 PATH-shadow blocking mechanism.

Blocked-path variants (the TF flexibility measurement): one tool is
mechanically blocked by PREPENDING a shadow dir to the session PATH; the
shadow dir carries a fake tool of the same name that fails HONESTLY (a
distinguishable marker on stderr, nonzero exit) — never a silent no-op.
Faces pinned here:

  (a) SHADOW BUILD — the fake executable exists, is executable, prints the
      KUNGLAO-TF-SHADOW marker with the blocked tool's name and the variant
      id, and exits nonzero;
  (b) PATH PRECEDENCE — with the shadow dir prepended, a PATH lookup of the
      blocked name resolves to the FAKE (not the real toolbox tool); the
      real tool file stays untouched on disk (shadowing blocks invocation,
      not knowledge — the documented limitation);
  (c) HONESTY — the fake never exits 0 and never emits stdout that could
      be mistaken for tool output; every invocation carries the marker;
  (d) ARM-AGNOSTIC WIRING — the same prepended-env works for a plain
      subprocess (the bare/CC-default face: the runner's session subprocess
      inherits PATH) and for a nested script (the loop face: the session's
      child processes inherit the session env);
  (e) IMMUTABILITY — prepend_path never mutates the caller's env dict and
      never falls back to a fabricated PATH.

stdlib only.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import eval_tf_shadow as sh


class TestShadowBuild:
    def test_build_creates_executable_fakes(self, tmp_path):
        shadow = sh.build_shadow(tmp_path / "shadow",
                                 {"peek": "block-peek", "fold": "block-fold"})
        for name in ("peek", "fold"):
            p = shadow / name
            assert p.is_file(), f"fake {name} must exist"
            assert os.access(p, os.X_OK), f"fake {name} must be executable"
            mode = p.stat().st_mode
            assert mode & stat.S_IXUSR, f"fake {name} needs the exec bit"

    def test_fake_errors_honestly_with_marker(self, tmp_path):
        """(a)+(c): invoking the fake fails nonzero, carries the marker and
        the blocked name + variant id on stderr, and emits NO stdout."""
        shadow = sh.build_shadow(tmp_path / "shadow", {"peek": "block-peek"})
        proc = subprocess.run([str(shadow / "peek")], capture_output=True,
                              text=True)
        assert proc.returncode != 0, "the fake must fail, never fake success"
        assert proc.stdout == "", "no stdout: nothing mistakable for output"
        assert sh.SHADOW_MARKER in proc.stderr
        assert "peek" in proc.stderr, "the blocked tool's name is disclosed"
        assert "block-peek" in proc.stderr, "the variant id is disclosed"

    def test_fake_fails_for_any_args_and_stdin(self, tmp_path):
        shadow = sh.build_shadow(tmp_path / "shadow", {"fold": "block-fold"})
        for args in ([], ["--params", "x"], ["a", "b", "c"]):
            proc = subprocess.run([str(shadow / "fold"), *args],
                                  capture_output=True, text=True,
                                  input="whatever")
            assert proc.returncode != 0
            assert sh.SHADOW_MARKER in proc.stderr


class TestPathPrecedence:
    def test_prepended_shadow_wins_path_lookup(self, tmp_path):
        """(b): a real tool and a shadow fake share the name; with the
        shadow prepended, PATH resolution hits the fake."""
        toolbox = tmp_path / "toolbox"
        toolbox.mkdir()
        real = toolbox / "peek"
        real.write_text("#!/bin/sh\necho REAL-OUTPUT\n", encoding="utf-8")
        real.chmod(0o755)
        shadow = sh.build_shadow(tmp_path / "shadow", {"peek": "block-peek"})
        env = sh.prepend_path(shadow, env=dict(os.environ))
        resolved = sh.which_in_env("peek", env)
        assert resolved is not None and Path(resolved).parent == shadow, \
            "PATH lookup must resolve to the shadow fake"
        proc = subprocess.run(["peek"], capture_output=True, text=True,
                              env=env)
        assert proc.returncode != 0, "blocked: the fake answered, not the tool"
        assert "REAL-OUTPUT" not in proc.stdout, \
            "the real tool must never execute under the blocked name"
        assert sh.SHADOW_MARKER in proc.stderr

    def test_real_tool_file_untouched(self, tmp_path):
        """Documented limitation, pinned honestly: shadowing blocks
        INVOCATION BY NAME — the real file stays on disk (absolute-path
        invocation and source reads are NOT prevented; graders flag them
        via the bypass face)."""
        toolbox = tmp_path / "toolbox"
        toolbox.mkdir()
        real = toolbox / "peek"
        real.write_text("#!/bin/sh\necho REAL-OUTPUT\n", encoding="utf-8")
        real.chmod(0o755)
        before = real.read_bytes()
        sh.build_shadow(tmp_path / "shadow", {"peek": "block-peek"})
        env = sh.prepend_path(tmp_path / "shadow", env=dict(os.environ))
        subprocess.run(["peek"], capture_output=True, env=env)
        assert real.read_bytes() == before, "shadow never touches the real file"
        direct = subprocess.run([str(real)], capture_output=True, text=True)
        assert direct.returncode == 0 and "REAL-OUTPUT" in direct.stdout, \
            "absolute-path invocation bypasses the shadow (known limitation)"

    def test_unblocked_names_still_resolve(self, tmp_path):
        """Only the blocked names are shadowed; everything else on PATH
        (python3 included) keeps working — blocking is surgical."""
        shadow = sh.build_shadow(tmp_path / "shadow", {"peek": "block-peek"})
        env = sh.prepend_path(shadow, env=dict(os.environ))
        proc = subprocess.run([sys.executable, "-c",
                               "import json; print(json.dumps({'ok': 1}))"],
                              capture_output=True, text=True, env=env)
        assert proc.returncode == 0
        assert '"ok"' in proc.stdout


class TestArmAgnosticWiring:
    def test_plain_subprocess_inherits_prepended_env(self, tmp_path):
        """(d) bare/CC-default face: the session subprocess receives the
        prepended env; a shell inside it resolves the blocked name to the
        fake (the same face `claude -p` tool shells see)."""
        shadow = sh.build_shadow(tmp_path / "shadow", {"peek": "block-peek"})
        env = sh.prepend_path(shadow, env=dict(os.environ))
        proc = subprocess.run(["sh", "-c", "peek target/blob.enc"],
                              capture_output=True, text=True, env=env,
                              cwd=str(tmp_path))
        assert proc.returncode != 0
        assert sh.SHADOW_MARKER in proc.stderr

    def test_nested_script_inherits_session_env(self, tmp_path):
        """(d) loop face: a session script (the stand-in for the kunglao
        loop session) spawns its own tool calls; the grandchild inherits
        the prepended PATH — no per-runner code is needed."""
        shadow = sh.build_shadow(tmp_path / "shadow", {"fold": "block-fold"})
        env = sh.prepend_path(shadow, env=dict(os.environ))
        nested = tmp_path / "session_sim.py"
        nested.write_text(
            "import subprocess, sys\n"
            "p = subprocess.run(['fold', '--params', 'p.json'],\n"
            "                   capture_output=True, text=True)\n"
            "sys.stderr.write(p.stderr)\n"
            "sys.exit(p.returncode)\n", encoding="utf-8")
        proc = subprocess.run([sys.executable, str(nested)],
                              capture_output=True, text=True, env=env)
        assert proc.returncode != 0
        assert sh.SHADOW_MARKER in proc.stderr


class TestEnvImmutability:
    def test_prepend_path_returns_new_dict_and_keeps_old_path(self, tmp_path):
        base = {"PATH": "/usr/bin:/bin", "HOME": "/x"}
        out = sh.prepend_path(tmp_path / "shadow", env=base)
        assert out is not base, "never mutate the caller's env"
        assert out["PATH"].startswith(str(tmp_path / "shadow")), \
            "shadow dir is FIRST on PATH"
        assert out["PATH"].endswith("/usr/bin:/bin"), "old PATH survives"
        assert base["PATH"] == "/usr/bin:/bin", "caller's dict untouched"
        assert out["HOME"] == "/x"

    def test_prepend_path_without_env_fabricates_nothing(self, tmp_path):
        """env=None means 'inherit the process env' — the function must not
        silently produce a PATH-less env (a session with no PATH resolves
        nothing and fails loudly, which is honest)."""
        out = sh.prepend_path(tmp_path / "shadow", env=None)
        assert str(tmp_path / "shadow") in out["PATH"]
        assert out["PATH"].split(os.pathsep)[0] == str(tmp_path / "shadow")

    def test_verify_shadow_reports_marker_and_rc(self, tmp_path):
        shadow = sh.build_shadow(tmp_path / "shadow", {"peek": "block-peek"})
        env = sh.prepend_path(shadow, env=dict(os.environ))
        report = sh.verify_shadow("peek", shadow, env)
        assert report["rc"] != 0
        assert report["marker"] is True
        assert "block-peek" in report["stderr_tail"]


class TestChainOrdering:
    """The harness-side ordering contract (#356): shadow belt first, then
    the toolbox, then the system PATH. The shadow dir is recognizable by
    its marker file — identity, not name heuristics."""

    def test_shadow_dir_carries_marker_file(self, tmp_path):
        shadow = sh.build_shadow(tmp_path / "shadow", {"peek": "block-peek"})
        assert (shadow / sh.SHADOW_MARKER_FILE).is_file()

    def test_marker_file_naming_is_stable(self):
        assert sh.SHADOW_MARKER_FILE == ".kunglao-tf-shadow"

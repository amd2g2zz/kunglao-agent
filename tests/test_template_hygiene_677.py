#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_template_hygiene_677.py — sanctioned writes keep the header (issue 677).

ws_yaml.py is the single sanctioned mutator of the workspace registers;
its round-trip (safe_load -> mutate -> safe_dump) drops every comment,
so before the fix every sanctioned status write stripped the leading
comment header — the template-version stamp AND the marker family riding
the same block (e.g. [initialized]) — and the stamp contract faulted on
the next selfcheck. Regression pins here: the whole header survives
set/append/del, and a sanctioned write leaves verify_stamps clean.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import template_version as tv  # noqa: E402
import ws_yaml  # noqa: E402

STAMP = tv.stamp_line(tv.read_skill_version())
MARKER = ("# [initialized] kunglao-init state_hash=deadbeef seeds=1 "
          "project_type=python")


def _seed_register(ws: Path, *, stamped: bool = True) -> Path:
    header = (f"{STAMP}\n" if stamped else "") + MARKER + "\n"
    body = (
        "claims:\n"
        "- id: C-001\n"
        "  status: OPEN\n"
        "  wake_condition: seed condition\n"
        "  depends_on: []\n")
    reg = ws / "claim-register.yaml"
    reg.write_text(header + body, encoding="utf-8")
    return reg


def _header_of(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        out.append(line)
    return out


def test_ws_yaml_preserves_stamp_and_marker_comments(tmp_path):
    """set / append / del each leave both header lines byte-identical."""
    ws = tmp_path / "ws"
    ws.mkdir()
    reg = _seed_register(ws)

    ops = (
        ("set", "claims.0.status", "PARTIALLY-VERIFIED"),
        ("append", "claims.0.depends_on", "C-002"),
        ("del", "claims.0.wake_condition"),
    )
    for op in ops:
        rc = ws_yaml.main([op[0], str(reg), op[1], *op[2:]])
        assert rc == 0, f"{op[0]} failed rc={rc}"
        text = reg.read_text(encoding="utf-8")
        header = _header_of(text)
        assert header[0] == STAMP, (op[0], header)
        assert MARKER in header, (op[0], header)
        # the body stays canonical behind the header
        assert ws_yaml.canonical_dump(yaml.safe_load(text)) in text


def test_verify_stamps_empty_after_write(tmp_path):
    """A sanctioned register write never produces a stamp fault: the
    stamped carrier stays stamped and an unstamped register recovers from
    the same-directory CLAUDE.md carrier."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "CLAUDE.md").write_text(
        f"{STAMP}\n\n# workspace body\n", encoding="utf-8")

    stamped = _seed_register(ws)
    assert ws_yaml.main(["set", str(stamped), "claims.0.status", "OPEN"]) == 0
    assert tv.verify_stamps(ws) == {}

    ws2 = tmp_path / "ws2"
    ws2.mkdir()
    (ws2 / "CLAUDE.md").write_text(
        f"{STAMP}\n\n# workspace body\n", encoding="utf-8")
    unstamped = _seed_register(ws2, stamped=False)
    assert ws_yaml.main(
        ["set", str(unstamped), "claims.0.status", "OPEN"]) == 0
    text = unstamped.read_text(encoding="utf-8")
    assert tv.STAMP_RE.search(text) is not None
    assert MARKER in _header_of(text)
    assert tv.verify_stamps(ws2) == {}

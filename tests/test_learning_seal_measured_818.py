# -*- coding: utf-8 -*-
"""tests/test_learning_seal_measured_818.py — the learning channel's
HMAC seal (#799) in the MEASURED leg (issue #818; counts double: the
Wave-0 learning tooth).

The deep replay pins live in tests/test_seal_799.py (fast tier, not
executed by the CI measured-set leg). This file re-pins the seal's core
faces on real tmp workspaces in the measured leg: the armed/unarmed
posture, additive-only sealing, the run-head build anchor (mid-run
refusal + cross-build read refusal), the frozen-bytes verify ladder,
and the learner read filter. The key rides a tmp path via the module's
own seam (monkeypatch) — the production path is never touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kunglao_log import _WARN_LAST
from rlvr import learning_seal as seal  # noqa: E402


@pytest.fixture
def armed(tmp_path, monkeypatch):
    key = tmp_path / "learning.key"
    key.write_bytes(b"k" * 48)
    monkeypatch.setattr(seal, "KEY_PATH", key)
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})
    monkeypatch.setattr(seal, "_NOTICE", {"shown": False})
    _WARN_LAST.clear()
    return key


@pytest.fixture
def unarmed(tmp_path, monkeypatch):
    monkeypatch.setattr(seal, "KEY_PATH", tmp_path / "missing.key")
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})
    monkeypatch.setattr(seal, "_NOTICE", {"shown": False})
    _WARN_LAST.clear()


# ---------- posture ----------

def test_armed_iff_key_provisioned_and_long_enough(
        armed, tmp_path, monkeypatch) -> None:
    assert seal.armed() is True
    assert seal.keyfile() == armed
    # below the 32-byte minimum the channel reads as unarmed
    (armed).write_bytes(b"short")
    assert seal.armed() is False
    monkeypatch.setattr(seal, "KEY_PATH", tmp_path / "void.key")
    assert seal.armed() is False


def test_unarmed_notice_fires_once_per_process(unarmed, capsys) -> None:
    seal.sign_row({"a": 1})
    seal.sign_row({"b": 2})
    err = capsys.readouterr().err
    assert err.count("UNSEALED") == 1          # ONE per-process notice
    assert ">= 32 bytes" in err                # names the repair contract
    assert "missing.key" in err                # names the key path


# ---------- sign_row: additive-only + build anchor ----------

def test_sign_row_armed_appends_seal_block_additively(armed) -> None:
    row = {"kind": "step", "credit": 3}
    out = seal.sign_row(row)
    assert out is not row                        # a NEW row
    assert set(out) == {"kind", "credit", "seal"}
    s = out["seal"]
    assert s["schema"] == seal.SEAL_SCHEMA
    assert s["record_sha256"] == seal.record_sha(out)
    assert isinstance(s["minted_ts"], int)
    assert s["build"] == seal.run_head_version()
    assert len(s["hmac"]) == 64                  # sha256 hex


def test_sign_row_unarmed_returns_row_unchanged(unarmed) -> None:
    row = {"kind": "step"}
    assert seal.sign_row(row) is row             # identity, not a copy


def test_sign_row_midrun_build_change_refuses_the_mint(
        armed, monkeypatch, capsys) -> None:
    row = {"kind": "step"}
    first = seal.sign_row(row)
    assert "seal" in first                       # anchored build seals fine
    # the run-head anchor is FROZEN: a live-version divergence refuses
    monkeypatch.setattr(seal, "_live_version", lambda: "x-other-build")
    refused = seal.sign_row({"kind": "step2"})
    assert "seal" not in refused                 # rides unsealed
    assert "REFUSED" in capsys.readouterr().err


def test_run_head_version_anchor_is_frozen_per_process(armed) -> None:
    a = seal.run_head_version()
    b = seal.run_head_version()
    assert a == b                                # anchored once


# ---------- record_sha + verify ladder ----------

def test_record_sha_excludes_the_seal_key_and_is_tamper_evident() -> None:
    row = {"a": 1, "b": 2}
    sha = seal.record_sha(row)
    sealed = {**row, "seal": {"schema": "x"}}
    assert seal.record_sha(sealed) == sha        # seal key never counts
    assert seal.record_sha({**row, "a": 9}) != sha


def test_verify_row_full_ladder(armed) -> None:
    sealed = seal.sign_row({"kind": "step", "credit": 1})
    ok, why = seal.verify_row(sealed)
    assert (ok, why) == (True, None)

    # not a mapping
    assert seal.verify_row(["nope"]) == (False, "row is not a mapping")
    # no seal block
    assert seal.verify_row({"kind": "step"})[0] is False
    assert "no seal block" in seal.verify_row({"kind": "step"})[1]
    # unknown schema
    forged = {**sealed, "seal": {**sealed["seal"], "schema": "seal/0"}}
    assert "unknown schema" in seal.verify_row(forged)[1]
    # foreign build (mixed-build rows never fold)
    foreign = {**sealed, "seal": {**sealed["seal"], "build": "x-old"}}
    assert "mid-run build change" in seal.verify_row(foreign)[1]
    # unreadable mint time
    bad_ts = {**sealed, "seal": {**sealed["seal"], "minted_ts": "soon"}}
    assert "mint time unreadable" in seal.verify_row(bad_ts)[1]
    # tampered bytes flip the frozen sha
    tampered = {**sealed, "credit": 999}
    assert "tamper detected" in seal.verify_row(tampered)[1]
    # a foreign-key HMAC is invalid
    forged_hmac = {**sealed, "seal": {**sealed["seal"], "hmac": "0" * 64}}
    assert "HMAC invalid" in seal.verify_row(forged_hmac)[1]


def test_verify_row_key_missing_at_verify_time(
        armed, tmp_path, monkeypatch) -> None:
    sealed = seal.sign_row({"kind": "step"})
    monkeypatch.setattr(seal, "KEY_PATH", tmp_path / "void.key")
    ok, why = seal.verify_row(sealed)
    assert ok is False
    assert "key missing" in why


def test_trusted_rows_armed_filters_forged_and_names_sha(
        armed, capsys) -> None:
    good = seal.sign_row({"kind": "a"})
    bad = {"kind": "forged"}                      # never sealed
    kept = seal.trusted_rows([good, bad, "not-a-dict"], op="unit-test")
    assert kept == [good]
    err = capsys.readouterr().err
    assert "refused unsealed/forged learning row" in err
    assert "no mass banked" in err


def test_trusted_rows_unarmed_rides_legacy(unarmed) -> None:
    rows = [{"kind": "a"}, {"kind": "b"}]
    out = seal.trusted_rows(rows, op="unit-test")
    assert out == rows                            # byte-identical pass
    assert out is not rows                        # via a copy

# -*- coding: utf-8 -*-
"""A0 (#823): KUNGLAO_VALUE_ALGO experiment flag — fail-loud contract.

The flag gates the N-arm of the AB-VALUE experiment. Unlike production
hooks (fail-open), a flag misread must NEVER silently fall back to the
O-arm: a silent fallback would contaminate the experiment's assignment.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import value_config


def test_unset_defaults_to_off(monkeypatch):
    monkeypatch.delenv(value_config.ENV_NAME, raising=False)
    assert value_config.is_enabled() is False


def test_on_values(monkeypatch):
    for v in ("1", "true", "yes", "on", "n"):
        monkeypatch.setenv(value_config.ENV_NAME, v)
        assert value_config.is_enabled() is True, v


def test_off_values(monkeypatch):
    for v in ("0", "false", "no", "off", ""):
        monkeypatch.setenv(value_config.ENV_NAME, v)
        assert value_config.is_enabled() is False, v


def test_unknown_value_fails_loud(monkeypatch):
    monkeypatch.setenv(value_config.ENV_NAME, "maybe")
    with pytest.raises(value_config.FlagError):
        value_config.is_enabled()


def test_flag_off_arm_is_o(monkeypatch):
    monkeypatch.delenv(value_config.ENV_NAME, raising=False)
    assert value_config.arm() == "O"


def test_flag_on_arm_is_n(monkeypatch):
    monkeypatch.setenv(value_config.ENV_NAME, "1")
    assert value_config.arm() == "N"

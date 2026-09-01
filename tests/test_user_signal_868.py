# -*- coding: utf-8 -*-
"""#868 dual-gate user feedback lifecycle tests."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import dual_gate_lifecycle as dgl
import user_signal_router as usr

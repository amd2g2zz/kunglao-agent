# -*- coding: utf-8 -*-
"""RED tests for anomaly_detector (issue #663, openspec/changes/issue-663-anomaly-detection/).

TDD: these tests import `anomaly_detector` (does NOT exist yet) and `lint_facts`
schema bump (ACTIVE_SCHEMA_REV=2) — both RED until implementation lands.

Covers tasks.md §3:
  RED1: common API call + populated baseline -> score [0.0, 0.3]
  RED2: rare syscall pattern + populated baseline -> score [0.7, 1.0]
  RED3: empty baseline corpus -> 0.0 (fail-open per design.md D5)
  RED4: malformed / empty / None fact body -> 0.0 (fail-open per design.md D5)
  RED5: scan_anomalies with >= 1 high-score fact -> >= 1 anomaly dict
  RED6: scan_anomalies with all low-score facts -> []
  RED9: lint_fact accepts boundary_type=anomaly; ACTIVE_SCHEMA_REV=2 reported

RED7 (convergence_check integration) and RED8 (claim_migrator integration) are
deferred — they require the workspace factory fixture from conftest.py; will
land alongside the gate-integration tasks in tasks.md §5.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))


# ---------- helpers ----------

def _fact(ws: Path, fact_id: str, status: str, claim_id: str, conclusion: str,
          extra: str = "") -> Path:
    """Write facts/<fact_id>.md + append its _INDEX row (mirrors test_fact_contradiction_gate.py)."""
    facts = ws / "facts"
    facts.mkdir(parents=True, exist_ok=True)
    body = f"# {fact_id}\n\nAnswers claim {claim_id}\n\n{extra}".rstrip() + "\n"
    f = facts / f"{fact_id}.md"
    f.write_text(body, encoding="utf-8")
    index = facts / "_INDEX.md"
    text = index.read_text(encoding="utf-8") if index.exists() else ""
    text += f"{fact_id} | {status} | {claim_id} | {conclusion}\n"
    index.write_text(text, encoding="utf-8")
    return f


# Common baseline: high-frequency RE terms (mimics what re-library would load)
COMMON_BASELINE_TERMS = {
    # All at 100 (max) — represents a fully-populated RE-library baseline where
    # any common RE token is at max frequency. RED1 (common APIs) and RED6
    # (all-common workspace) score 0 under this baseline; RED2/RED5 (rare
    # tokens) still trigger via missing-token = 1.0 rarity.
    "AES": 100, "BCryptGenerateSymmetricKey": 100, "CryptEncrypt": 100,
    "CryptDecrypt": 100, "VirtualAlloc": 100, "LoadLibraryA": 100,
    "GetProcAddress": 100, "WinHttpOpen": 100, "common": 100, "api": 100,
    "call": 100, "called": 100, "encrypted": 100, "key": 100, "decryption": 100,
    "decrypted": 100, "with": 100, "for": 100, "generation": 100,
    "another": 100,
}
COMMON_BASELINE_PAIRS = {
    # Exact pair for RED1's conclusion text (so semantic_unusualness = 0)
    ("C-1", "BCryptGenerateSymmetricKey called for AES key generation"): 30,
    # Pairs for RED6's all-low-score workspace
    ("C-1", "common api call with AES"): 25,
    ("C-2", "common api call for decryption"): 20,
}
COMMON_BASELINE_PATHS = {
    "bins/normal.exe": 20, "bins/sample.dll": 15,
}


def _common_baseline():
    """Build a BaselineCorpus with high-frequency common RE terms."""
    from anomaly_detector import BaselineCorpus
    return BaselineCorpus(
        term_freq=COMMON_BASELINE_TERMS,
        pair_freq=COMMON_BASELINE_PAIRS,
        path_freq=COMMON_BASELINE_PATHS,
    )


# =====================================================================
# RED1: common API call -> low anomaly score
# =====================================================================

def test_red1_common_api_low_score():
    """RED1: BCryptGenerateSymmetricKey + AES in populated baseline -> score [0.0, 0.3]."""
    from anomaly_detector import score_fact
    baseline = _common_baseline()
    score = score_fact(
        "BCryptGenerateSymmetricKey called for AES key generation",
        baseline,
    )
    assert 0.0 <= score <= 0.3, f"expected low score [0.0, 0.3], got {score}"


# =====================================================================
# RED2: rare syscall -> high anomaly score
# =====================================================================

def test_red2_rare_syscall_high_score():
    """RED2: rare syscall pattern not in baseline -> score [0.7, 1.0]."""
    from anomaly_detector import score_fact
    baseline = _common_baseline()
    score = score_fact(
        "CustomSyscall0xFE with nonstandard qword argument",
        baseline,
    )
    assert score >= 0.7, f"expected high score [0.7, 1.0], got {score}"


# =====================================================================
# RED3: empty baseline -> score 0.0 (fail-open per design.md D5)
# =====================================================================

def test_red3_empty_baseline_returns_zero():
    """RED3: empty baseline corpus -> score 0.0, no crash."""
    from anomaly_detector import score_fact, BaselineCorpus
    baseline = BaselineCorpus()  # all dicts empty
    score = score_fact("anything goes here", baseline)
    assert score == 0.0, f"expected 0.0 on empty baseline, got {score}"


# =====================================================================
# RED4: malformed fact body -> score 0.0 (fail-open)
# =====================================================================

def test_red4_malformed_body_returns_zero():
    """RED4: empty / whitespace / None fact body -> 0.0, no crash."""
    from anomaly_detector import score_fact
    baseline = _common_baseline()
    assert score_fact("", baseline) == 0.0
    assert score_fact("   \n\t  ", baseline) == 0.0
    # None must not crash — fail-open returns 0.0
    assert score_fact(None, baseline) == 0.0  # type: ignore[arg-type]


# =====================================================================
# RED5: scan_anomalies returns anomaly dict with required keys
# =====================================================================

def test_red5_scan_returns_anomaly_dict(tmp_path):
    """RED5: scan_anomalies on workspace with >= 1 high-score fact -> >= 1 anomaly."""
    from anomaly_detector import scan_anomalies
    ws = tmp_path / "ws"
    _fact(ws, "F001", "PROVEN", "C-1", "rare syscall 0xFE nonstandard qword",
          extra="```yaml\nsample_refs:\n  - bins/odd.exe\n```")
    baseline = _common_baseline()
    anomalies = scan_anomalies(
        ws / "facts" / "_INDEX.md", ws / "facts",
        baseline=baseline, threshold=0.7,
    )
    assert len(anomalies) >= 1, f"expected >= 1 anomaly, got {anomalies}"
    a = anomalies[0]
    assert a["fact_id"] == "F001"
    assert 0.7 <= a["score"] <= 1.0, f"score {a['score']} not in [0.7, 1.0]"
    assert a["top_dimension"] in ("lexical", "semantic", "path"), \
        f"unexpected top_dimension: {a['top_dimension']}"
    # claim_id propagated from _INDEX row
    assert a["claim_id"] == "C-1"


# =====================================================================
# RED6: scan_anomalies with all low-score facts -> []
# =====================================================================

def test_red6_scan_all_low_returns_empty(tmp_path):
    """RED6: workspace with all low-score facts -> []."""
    from anomaly_detector import scan_anomalies
    ws = tmp_path / "ws"
    _fact(ws, "F001", "PROVEN", "C-1", "common api call with AES")
    _fact(ws, "F002", "PROVEN", "C-2", "common api call for decryption")
    baseline = _common_baseline()
    anomalies = scan_anomalies(
        ws / "facts" / "_INDEX.md", ws / "facts",
        baseline=baseline, threshold=0.7,
    )
    assert anomalies == [], f"expected [] for all-low-score workspace, got {anomalies}"


# =====================================================================
# RED7 (integration): convergence_check DRAIN_BLOCKED on anomaly
# =====================================================================

def test_red7_convergence_drain_blocks_on_anomaly(tmp_path):
    """RED7: workspace with >= 1 high-score PROVEN fact -> convergence_check
    DRAIN verdict BLOCKED with anomaly named in action + anomaly_count >= 1."""
    from convergence_check import decide
    ws = tmp_path / "ws"
    # No claim-register.yaml -> no open claims -> reaches DRAIN stage.
    # PROVEN high-score fact triggers ANOMALY_DETECTED.
    _fact(ws, "F001", "PROVEN", "C-1", "rare syscall 0xFE nonstandard qword",
          extra="```yaml\nsample_refs:\n  - bins/odd.exe\n```")
    decision = decide(ws)
    assert decision["decision"] == "BLOCKED", \
        f"expected BLOCKED (anomaly observation gate), got {decision['decision']}"
    assert "anomaly" in decision["action"].lower(), \
        f"action should mention anomaly, got: {decision['action']!r}"
    assert decision["anomaly_count"] >= 1, \
        f"expected anomaly_count >= 1, got {decision['anomaly_count']}"
    # Anomaly detail includes fact_id
    assert any(a["fact_id"] == "F001" for a in decision["anomalies"])


# =====================================================================
# RED8 (integration): claim_migrator does NOT downgrade to STAMP on anomaly alone
# =====================================================================

def test_red8_claim_migrator_no_anomaly_downgrade(tmp_path):
    """RED8: anomaly observation MUST NOT trigger STAMP downgrade (per design.md D8).

    Per D8: anomaly is a co-resident note observation, NOT a verdict demotion.
    The fact's own status stays PROVEN; the anomaly surfaces in notes/ for
    analyst review. This test asserts the design invariant directly: a
    PROVEN claim with a co-resident anomaly note is unaffected by the
    note's presence (the migrator does not consult notes/ for verdict
    demotion — that's a separate scan_anomalies call's job).
    """
    import yaml
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    # Minimal claim-register.yaml with a single PROVEN claim
    claim_register = ws / "claim-register.yaml"
    claim_register.write_text(textwrap.dedent("""\
        claims:
          - id: C-1
            status: PROVEN
            answers_question: q1
        """), encoding="utf-8")
    # PROVEN fact + a co-resident anomaly note in notes/
    _fact(ws, "F001", "PROVEN", "C-1", "rare syscall 0xFE nonstandard qword",
          extra="```yaml\nsample_refs:\n  - bins/odd.exe\n```")
    notes_dir = ws / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "F001.md").write_text(
        "---\nid: F001\nclaim_id: C-1\nboundary_type: anomaly\n"
        "score: 1.0\ntop_dimension: lexical\nverify_status: pending\n---\n\n"
        "# Anomaly observation for F001\n", encoding="utf-8")
    # Re-read register to verify claim stays PROVEN (anomaly did NOT touch it)
    reg_data = yaml.safe_load(claim_register.read_text(encoding="utf-8"))
    claim_status = next(c["status"] for c in reg_data["claims"] if c["id"] == "C-1")
    assert claim_status == "PROVEN", \
        f"anomaly MUST NOT downgrade claim status (design D8); got {claim_status}"


# =====================================================================
# RED9 (schema): lint_fact accepts boundary_type=anomaly + ACTIVE_SCHEMA_REV >= 2
# =====================================================================

def test_red9_lint_facts_accepts_anomaly(tmp_path):
    """RED9: lint_fact accepts boundary_type=anomaly; schema_rev=2 reported."""
    from lint_facts import lint_fact, ACTIVE_SCHEMA_REV
    assert ACTIVE_SCHEMA_REV >= 2, f"schema bump required (>= 2), got {ACTIVE_SCHEMA_REV}"
    fm = {
        "id": "F001",
        "type": "fact",
        "title": "anomaly test",
        "status": "PROVEN",
        "created": "2026-08-25",
        "last_reviewed": "2026-08-25",
        "claim_id": "C-1",
        "boundary_type": "anomaly",
        "promotion_gate": "",  # anomaly is in EMPTY_GATE_TYPES (mirrors contradiction)
        "source": "static-decompile",
        "confidence": "high",
        "provenance": [
            {"role": "sample_raw", "path": "bins/x",
             "content_sha256": "0" * 64, "credibility": "A1"}
        ],
        "claim": "test claim statement",
        "reproduce": "echo x",
        "expected": "x",
        "verified": False,
    }
    issues = lint_fact("F001", fm, set())
    bad = [c for _, c, _ in issues if c == "BAD_BOUNDARY_TYPE"]
    assert not bad, f"anomaly boundary_type must be accepted (lint_fact BAD_BOUNDARY_TYPE issues: {bad})"

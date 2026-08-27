# -*- coding: utf-8 -*-
"""tests/test_progress_report_663.py — issue #663 acceptance criterion #3:
scripts/progress_report.py output surfaces anomaly count.

Card 7 of v0.1.3-open-issues-batch.plan.md already landed the main anomaly
detector (commit 63975fe on dev, scripts/anomaly_detector.py + convergence_check
ANOMALY_DETECTED gate). The single remaining gap is progress_report.py:
operators running `python scripts/progress_report.py <ws>` see claims / workers
/ blockers / C0-C7 but NOT how many anomaly observation notes exist. They
have to count notes/*.md by hand.

RED contract (3 cases, all must fail before GREEN implementation):
  1. workspace has 3 notes with `boundary_type: anomaly` (YAML block form,
     the canonical _write_anomaly_note output) + 1 plain note → output
     contains `## Anomalies: 3 observation notes`.
  2. workspace has NO notes/ directory → output contains `## Anomalies: 0`
     and the report does NOT raise.
  3. workspace has 1 YAML-block anomaly note + 1 line-level frontmatter
     anomaly note (no closing `---`) → output contains `## Anomalies: 2`.

Both frontmatter forms are exercised because anomaly_detector.py writes
the YAML-block form today, but operators sometimes hand-write the
line-level form for fast notes — the count must catch both.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

YAML_BLOCK_TMPL = (
    "---\n"
    "id: {fact_id}\n"
    "type: observation\n"
    "boundary_type: anomaly\n"
    "score: 0.875\n"
    "top_dimension: lexical\n"
    "anomaly_threshold: 0.7\n"
    "verify_status: pending\n"
    "claim_id: C-1\n"
    "---\n\n"
    "# Anomaly observation for {fact_id}\n"
)

LINE_LEVEL_TMPL = (
    "---\n"
    "id: {fact_id}\n"
    "type: observation\n"
    "boundary_type: anomaly\n"
    "score: 0.912\n"
    "top_dimension: semantic\n"
    "---\n"
    # NOTE: no closing `---` block — line-level frontmatter style.
    # Some operators hand-write this for fast notes.
    "\n# Hand-written anomaly note for {fact_id}\n"
)

PLAIN_TMPL = (
    "---\n"
    "id: {fact_id}\n"
    "type: observation\n"
    "verify_status: pending\n"
    "---\n\n"
    "# Generic observation for {fact_id}\n"
)


def _write_note(notes_dir: Path, fact_id: str, tmpl: str = YAML_BLOCK_TMPL) -> Path:
    """Write one note file under <ws>/notes/<fact_id>.md."""
    notes_dir.mkdir(parents=True, exist_ok=True)
    p = notes_dir / f"{fact_id}.md"
    p.write_text(tmpl.format(fact_id=fact_id), encoding="utf-8")
    return p


def _capture_report(workspace: Path, capsys) -> str:
    """Invoke progress_report.report() and return captured stdout."""
    import progress_report
    rc = progress_report.report(workspace)
    assert rc == 0, f"progress_report.report() returned non-zero: {rc}"
    return capsys.readouterr().out


# ---------------------------------------------------------------------------
# RED 1 — three YAML-block anomaly notes + one plain note → Anomalies: 3
# ---------------------------------------------------------------------------

def test_anomaly_count_three_yaml_block(tmp_path, capsys):
    """Three YAML-block `boundary_type: anomaly` notes + one plain note →
    `## Anomalies: 3 observation notes` appears in output."""
    notes = tmp_path / "notes"
    _write_note(notes, "F001")
    _write_note(notes, "F002")
    _write_note(notes, "F003")
    _write_note(notes, "F999", tmpl=PLAIN_TMPL)  # boundary_type missing → not anomaly

    out = _capture_report(tmp_path, capsys)
    assert "## Anomalies: 3 observation notes" in out, (
        f"expected '## Anomalies: 3 observation notes' in progress_report "
        f"output, got:\n{out}"
    )


# ---------------------------------------------------------------------------
# RED 2 — no notes/ directory → Anomalies: 0, no raise
# ---------------------------------------------------------------------------

def test_anomaly_count_zero_no_notes_dir(tmp_path, capsys):
    """Workspace with NO notes/ directory → `## Anomalies: 0` in output,
    report() does NOT raise (fail-open)."""
    # tmp_path exists but is empty (no notes/ subdir)
    out = _capture_report(tmp_path, capsys)
    assert "## Anomalies: 0 observation notes" in out, (
        f"expected '## Anomalies: 0 observation notes' for empty workspace, "
        f"got:\n{out}"
    )


# ---------------------------------------------------------------------------
# RED 3 — mixed YAML-block and line-level frontmatter → Anomalies: 2
# ---------------------------------------------------------------------------

def test_anomaly_count_mixed_frontmatter_forms(tmp_path, capsys):
    """One YAML-block anomaly + one line-level frontmatter anomaly → both
    counted, output reads `## Anomalies: 2 observation notes`."""
    notes = tmp_path / "notes"
    _write_note(notes, "F010", tmpl=YAML_BLOCK_TMPL)
    _write_note(notes, "F020", tmpl=LINE_LEVEL_TMPL)

    out = _capture_report(tmp_path, capsys)
    assert "## Anomalies: 2 observation notes" in out, (
        f"expected both frontmatter forms counted (Anomalies: 2), got:\n{out}"
    )

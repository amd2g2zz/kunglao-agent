# -*- coding: utf-8 -*-
"""tests/test_icd203_alignment.py — kunglao facts × malware-veri-notes schema alignment (#336).

RED→GREEN contract (SDD+TDD):
  1. old-format fact (pre-migration kunglao style)  → lint_facts reports errors (RED)
  2. migrate_facts.py output                        → lint_facts 0 errors   (GREEN)
  3. templates/fact-frontmatter.md example          → lint_facts 0 errors on first write
  4. edge cases: credibility / content_sha256 / status×source×confidence matrix /
     promotion_gate semantics / id slug / no-frontmatter files

Migration is tested against fixture facts that mirror the live workspace shape
(F001-style PROVEN, F005-style PARTIALLY-VERIFIED, F017-style pure_negative,
F022-style body-only file).
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

import lint_facts as lf
import migrate_facts as mf

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "fact-frontmatter.md"
STATE_MAPPING = ROOT / "references" / "state-mapping.md"

# ── fixtures ──────────────────────────────────────────────────────────

OLD_F001_FM = """---
id: F001
type: fact
claim: "Sample Overview: Language, Architecture, Packer"
status: PROVEN
boundary_type: observation
promotion_gate: L1 sha256 reproduce via runs/verify-f001.py
source: mal-recon deep report + evidence/die.json + evidence/signature.json
verified: 2026-08-12
reproduce: "python ../runs/verify-f001.py"
expected: 2825d7b347418a04ce2dcfe1d88888a5a04a04f3a78bffe4e305e2f2ac80c5be
provenance:
  - {role: "sample_raw", path: "bins/sample.bin"}
  - {role: "recompute_script", path: "runs/verify-f001.py"}
---

# F001 — Sample Overview: Language, Architecture, Packer

## Identity

SHA256 `aaaa` | PE32+ x86-64 | no packer
"""

OLD_F005_FM = """---
id: F005
type: fact
claim: "XOR String Decode Results"
status: PARTIALLY-VERIFIED
boundary_type: observation
promotion_gate: L1 sha256 reproduce via runs/verify-f005.py
source: evidence/xor-decode.py + runs/verify-f005.py (reverse-search + pefile section
verified: 2026-08-12
reproduce: python ../runs/verify-f005.py
expected: 67f24edfba8504697d5b5b01840898b47c5525d5313f40ba844dbfdba3fd398a
claim_id: C-005
provenance:
  - {role: "sample_raw", path: "bins/sample.bin"}
  - {role: "recompute_script", path: "runs/verify-f005.py"}
---

# F005 — XOR String Decode Results

## Algorithm Confirmation

XOR key = index + 0x4d, cdk.steam.work @ 0x21A640.
"""

OLD_F017_FM = """---
id: F017
type: fact
claim: "No Standard Cryptographic Primitives (C-017)"
status: PARTIALLY-VERIFIED
boundary_type: pure_negative
promotion_gate: L1 sha256 reproduce via runs/verify-f017.py
source: byte-pattern scan across 2625024 bytes + runs/verify-f017.py
verified: 2026-08-12
reproduce: python ../runs/verify-f017.py
expected: d9f5524c3070908367caff841665c8464bbe4409e2ca346046c6e330543d710a
claim_id: C-017
provenance:
  - {role: "sample_raw", path: "bins/sample.bin"}
  - {role: "recompute_script", path: "runs/verify-f017.py"}
---

# F017 — No Standard Cryptographic Primitives (C-017)

## Finding

The binary contains **zero** standard cryptographic algorithm artifacts.
"""

F022_BODY_ONLY = """# F022 — C-022 加密层识别与明文恢复 (test-scope/sample_enc.bin)

status: PARTIALLY-VERIFIED (awaiting independent verifier)
claim: C-022
boundary_type: positive_observation

## 结论 (finding)

test-scope/sample_enc.bin 的加密层 = XOR/ADD self-syncing stream, key=0x01。
"""


def _write(p: Path, content: str | bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_workspace(tmp_path: Path, *, f022: bool = False) -> Path:
    """Minimal kunglao workspace: bins/, runs/, facts/, notes/, _INDEX.md.

    Evidence files referenced by the curated FACT_MIGRATION_MAP entries for the
    fixture facts (F001/F005/F017) exist so content_sha256 is computable."""
    ws = tmp_path / "ws"
    sample = b"\x90\x90MZfake-sample-bytes"
    _write(ws / "bins" / "sample.bin", sample)
    _write(ws / "runs" / "verify-f001.py", "print('magic=0x20b sections=6')\n")
    _write(ws / "runs" / "verify-f005.py", "print('test1_algorithm_confirm=cdk.steam.work')\n")
    _write(ws / "runs" / "verify-f017.py", "print('hash_init_constants.hits=0')\n")
    _write(ws / "evidence" / "die.json", '{"packer": null}')
    _write(ws / "evidence" / "signature.json", '{"signed": false}')
    _write(ws / "evidence" / "static-ghidra.json", '{"decompiled": {}, "pdb": "key.pdb"}')
    _write(ws / "evidence" / "xor-decode.py", "XOR_BASE = 0x4D\n")
    _write(ws / "facts" / "F001.md", OLD_F001_FM)
    _write(ws / "facts" / "F005.md", OLD_F005_FM)
    _write(ws / "facts" / "F017.md", OLD_F017_FM)
    if f022:
        _write(ws / "test-scope" / "sample_enc.bin", b"\x00encrypted")
        # Recompute-script artifact referenced by the curated F022
        # FACT_MIGRATION_MAP entry (provenance_override recompute_script
        # path) — #356 W3: the curated path is now derived from
        # migrate_facts.SKILL_ROOT (= this repo), pointing at the REAL
        # tools/crypto/crypto-tool.py; content_sha256 derives from the
        # actual shipped script, no fixture placeholder needed.
        _write(ws / "facts" / "F022.md", F022_BODY_ONLY)
    _write(ws / "facts" / "_INDEX.md",
           "# Facts Index\n\n## Status: 3 PROVEN / 0 PARTIAL\n\n"
           "F001 | PROVEN | C-001 | Sample Overview — MSVC 19.43, no packer\n"
           "F005 | PROVEN | C-005 | XOR Decode — cdk.steam.work@0x21A640\n"
           "F017 | PROVEN | C-017 | Crypto — no standard primitives\n")
    _write(ws / "notes" / "01-sample-identity.md",
           "---\nid: 01-sample-identity\ntype: note\nstatus: PROVEN\nsource: static-decompile\n"
           "confidence: high\ncreated: 2026-08-13\nlast_reviewed: 2026-08-13\n"
           "iocs:\n  - {type: file_path, value: \"E:\\old\\path\\x.pdb\"}\n"  # invalid YAML escape → forces parser fallback
           "facts_used:\n  - F001\n  - F017\ndepends_on: []\n"
           "hypothesis: \"x\"\n---\n\n# t\n\n**F001** establishes identity.\n")
    return ws


def _codes(issues):
    return {code for (_sev, code, _msg) in issues}


def _errors(issues):
    return [(c, m) for (s, c, m) in issues if s == "error"]


# ── RED: old format fails the aligned schema ──────────────────────────

def test_old_format_fact_fails_schema_lint(tmp_path):
    ws = build_workspace(tmp_path)
    errors, _warnings = lf.lint_workspace(ws)
    codes = _codes(errors)
    # drift the issue #336 comparison table calls out
    assert "MISSING_TITLE" in codes
    assert "MISSING_CREATED" in codes
    assert "MISSING_LAST_REVIEWED" in codes
    assert "MISSING_CONFIDENCE" in codes
    assert "BAD_ID_NO_SLUG" in codes
    assert "BAD_SOURCE_ENUM" in codes
    assert "PROVENANCE_NO_CONTENT_SHA256" in codes
    assert "PROVENANCE_NO_CREDIBILITY" in codes
    assert "BAD_STATUS" in codes  # PARTIALLY-VERIFIED is not a schema status


def test_body_only_fact_without_frontmatter_fails(tmp_path):
    ws = build_workspace(tmp_path, f022=True)
    errors, _warnings = lf.lint_workspace(ws)
    codes = _codes(errors)
    assert "UNPARSEABLE_FRONTMATTER" in codes or "NO_FRONTMATTER" in codes


# ── GREEN: migration produces aligned facts ───────────────────────────

def test_migrated_facts_pass_lint_zero_errors(tmp_path):
    ws = build_workspace(tmp_path)
    report = mf.migrate_workspace(ws)
    assert not report["errors"], report["errors"]
    errors, warnings = lf.lint_workspace(ws)
    assert not _errors(errors), _errors(errors)


def test_migrate_slugs_id_and_keeps_extension_fields(tmp_path):
    ws = build_workspace(tmp_path)
    mf.migrate_workspace(ws)
    text = (ws / "facts" / "F001.md").read_text(encoding="utf-8")
    assert re.search(r"^id: F001-[a-z0-9-]+$", text, re.M)
    for field in ("claim", "reproduce", "expected", "verified"):
        assert re.search(rf"^{field}:", text, re.M), f"extension field {field} lost"
    # body preserved byte-exact
    assert "# F001 — Sample Overview: Language, Architecture, Packer" in text
    assert "SHA256 `aaaa` | PE32+ x86-64 | no packer" in text


def test_migrate_provenance_gets_content_sha256(tmp_path):
    ws = build_workspace(tmp_path)
    mf.migrate_workspace(ws)
    fm = lf._load_fact(ws / "facts" / "F001.md")
    sample_entry = next(p for p in fm["provenance"] if p["role"] == "sample_raw")
    expected_hash = _sha256((ws / "bins" / "sample.bin").read_bytes())
    assert sample_entry["content_sha256"] == expected_hash


def test_migrate_partially_verified_maps_to_inferred_partial_medium(tmp_path):
    ws = build_workspace(tmp_path)
    mf.migrate_workspace(ws)
    fm = lf._load_fact(ws / "facts" / "F005.md")
    assert fm["status"] == "INFERRED"
    assert fm["verify_status"] == "partial"
    assert fm["confidence"] == "medium"
    assert fm["confidence_zh"] == "倾向于"


def test_migrate_pure_negative_maps_to_negative_empty_gate(tmp_path):
    ws = build_workspace(tmp_path)
    mf.migrate_workspace(ws)
    fm = lf._load_fact(ws / "facts" / "F017.md")
    assert fm["status"] == "NEGATIVE"
    assert fm["confidence"] == "high"
    assert fm["confidence_zh"] == "不支持"
    assert fm["promotion_gate"] == ""
    # old verification-command gate replaced by schema semantics
    assert "reproduce via" not in str(fm.get("promotion_gate"))


def test_migrate_proven_fact_keeps_proven_passes_high(tmp_path):
    ws = build_workspace(tmp_path)
    mf.migrate_workspace(ws)
    fm = lf._load_fact(ws / "facts" / "F001.md")
    assert fm["status"] == "PROVEN"
    assert fm["verify_status"] == "passes"
    assert fm["confidence"] == "high"
    assert fm["confidence_zh"] == "可确认"


def test_migrate_promotion_gate_is_semantic_not_a_verify_command(tmp_path):
    ws = build_workspace(tmp_path)
    mf.migrate_workspace(ws)
    fm = lf._load_fact(ws / "facts" / "F001.md")
    gate = str(fm["promotion_gate"])
    assert "reproduce via" not in gate
    assert "runs/verify" not in gate
    assert len(gate) > 20  # a real promotion condition


def test_migrate_derives_claim_id_from_index(tmp_path):
    ws = build_workspace(tmp_path)
    mf.migrate_workspace(ws)
    fm = lf._load_fact(ws / "facts" / "F001.md")
    assert fm["claim_id"] == "C-001"  # F001 has no claim_id in old format


def test_migrate_rewrites_note_facts_used(tmp_path):
    ws = build_workspace(tmp_path)
    mf.migrate_workspace(ws)
    text = (ws / "notes" / "01-sample-identity.md").read_text(encoding="utf-8")
    assert "- F001-sample-overview" in text
    assert "- F017-crypto-negative" in text
    assert "\n  - F001\n" not in text
    assert "**F001-sample-overview**" in text


def test_migrate_regenerates_index_with_workflow_layer(tmp_path):
    ws = build_workspace(tmp_path)
    mf.migrate_workspace(ws)
    idx = (ws / "facts" / "_INDEX.md").read_text(encoding="utf-8")
    # workflow layer column keeps PARTIALLY-VERIFIED for partial facts
    assert "F005-xor-string-decode | PARTIALLY-VERIFIED | C-005" in idx
    assert "F001-sample-overview | PROVEN | C-001" in idx


def test_migrate_is_idempotent(tmp_path):
    ws = build_workspace(tmp_path)
    mf.migrate_workspace(ws)
    first = (ws / "facts" / "F001.md").read_text(encoding="utf-8")
    mf.migrate_workspace(ws)
    second = (ws / "facts" / "F001.md").read_text(encoding="utf-8")
    assert first == second
    errors, _ = lf.lint_workspace(ws)
    assert not _errors(errors)


def test_migrate_body_only_fact_gets_conformant_frontmatter(tmp_path):
    ws = build_workspace(tmp_path, f022=True)
    mf.migrate_workspace(ws)
    fm = lf._load_fact(ws / "facts" / "F022.md")
    assert fm["id"].startswith("F022-")
    assert fm["claim_id"] == "C-022"
    assert fm["status"] == "INFERRED"
    assert fm["verify_status"] == "partial"
    # body preserved verbatim
    text = (ws / "facts" / "F022.md").read_text(encoding="utf-8")
    assert "XOR/ADD self-syncing stream, key=0x01" in text
    errors, _ = lf.lint_workspace(ws)
    assert not _errors(errors), _errors(errors)


def test_migrate_backup_creates_facts_bak(tmp_path):
    ws = build_workspace(tmp_path)
    mf.migrate_workspace(ws, backup=True)
    bak = ws / "facts.bak-pre336"
    assert bak.is_dir()
    assert (bak / "F001.md").exists()
    # backup keeps the ORIGINAL (old-format) content
    assert 'id: F001\n' in (bak / "F001.md").read_text(encoding="utf-8")


# ── template produces first-pass-clean facts ──────────────────────────

def test_template_exists_and_example_passes_lint(tmp_path):
    assert TEMPLATE.exists(), "templates/fact-frontmatter.md must exist"
    text = TEMPLATE.read_text(encoding="utf-8")
    # extract the example frontmatter block + a body line
    m = re.search(r"```yaml\n(---\n.*?---)\n```", text, re.S)
    assert m, "template must carry a full example frontmatter fenced as ```yaml"
    fm_block = m.group(1)
    fid = re.search(r"^id: (F\d{3,}-[a-z0-9-]+)$", fm_block, re.M)
    assert fid, "example id must carry a slug"
    ws = build_workspace(tmp_path)
    mf.migrate_workspace(ws)  # migrate the legacy fixture facts first
    _write(ws / "facts" / f"{fid.group(1)}.md", fm_block + "\n\n# example\n\nbody\n")
    errors, warnings = lf.lint_workspace(ws)
    assert not _errors(errors), _errors(errors)


def test_template_documents_twelve_mandatory(tmp_path):
    text = TEMPLATE.read_text(encoding="utf-8")
    for field in ("id", "type", "title", "status", "created", "last_reviewed",
                  "claim_id", "boundary_type", "promotion_gate", "provenance",
                  "source", "confidence"):
        assert re.search(rf"\b{field}\b", text), f"template must document {field}"


# ── strict schema edges ───────────────────────────────────────────────

def _migrated_ws(tmp_path):
    ws = build_workspace(tmp_path)
    mf.migrate_workspace(ws)
    return ws


def _rewrite_frontmatter(ws: Path, fname: str, old: str, new: str):
    p = ws / "facts" / fname
    p.write_text(p.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def test_lint_rejects_bad_credibility(tmp_path):
    ws = _migrated_ws(tmp_path)
    _rewrite_frontmatter(ws, "F001.md", "credibility: A1", "credibility: X7")
    errors, _ = lf.lint_workspace(ws)
    assert any(c == "BAD_CREDIBILITY" for _s, c, _m in errors)


def test_lint_rejects_missing_content_sha256(tmp_path):
    ws = _migrated_ws(tmp_path)
    p = ws / "facts" / "F001.md"
    text = p.read_text(encoding="utf-8")
    import re as _re
    text = _re.sub(r", content_sha256: \"?[0-9a-f]{64}\"?", "", text, count=1)
    p.write_text(text, encoding="utf-8")
    errors, _ = lf.lint_workspace(ws)
    assert any(c == "PROVENANCE_NO_CONTENT_SHA256" for _s, c, _m in errors)


def test_lint_rejects_matrix_violation_inferred_high(tmp_path):
    ws = _migrated_ws(tmp_path)
    _rewrite_frontmatter(ws, "F005.md", "confidence: medium", "confidence: high")
    errors, _ = lf.lint_workspace(ws)
    assert any(c == "ILLEGAL_CONFIDENCE_FOR_STATUS" for _s, c, _m in errors)


def test_lint_rejects_empty_gate_on_observation(tmp_path):
    ws = _migrated_ws(tmp_path)
    _rewrite_frontmatter(ws, "F005.md",
                         'promotion_gate: "', 'promotion_gate_removed: "')
    p = ws / "facts" / "F005.md"
    text = p.read_text(encoding="utf-8")
    import re as _re
    text = _re.sub(r'^promotion_gate: ".*"$', 'promotion_gate: ""', text, flags=_re.M)
    p.write_text(text, encoding="utf-8")
    errors, _ = lf.lint_workspace(ws)
    assert any(c == "EMPTY_PROMOTION_GATE" for _s, c, _m in errors)


def test_lint_rejects_nonempty_gate_on_pure_negative(tmp_path):
    ws = _migrated_ws(tmp_path)
    _rewrite_frontmatter(ws, "F017.md", 'promotion_gate: ""', 'promotion_gate: "x"')
    errors, _ = lf.lint_workspace(ws)
    assert any(c == "NONEMPTY_PROMOTION_GATE" for _s, c, _m in errors)


# ── docs ──────────────────────────────────────────────────────────────

def test_state_mapping_doc_carries_two_layer_table_and_icd203(tmp_path):
    assert STATE_MAPPING.exists(), "references/state-mapping.md must exist"
    text = STATE_MAPPING.read_text(encoding="utf-8")
    assert "PARTIALLY-VERIFIED" in text and "verify_status" in text
    assert "ICD-203" in text
    for rule in ("credibility", "confidence_zh", "alternatives", "claim_id",
                 "supersedes", "reproduce", "screenshot"):
        assert rule in text, f"state-mapping must cover ICD-203 landing field {rule}"


# ── interop: lint-notes.py (when the malware-veri-notes skill is present) ──

def test_lint_notes_interop_zero_errors_after_migration(tmp_path):
    """Migrated fixture workspace passes the external lint-notes.py unchanged
    (the acceptance gate names lint-notes.py explicitly). Skipped when the
    malware-veri-notes skill is not installed (e.g. CI)."""
    import importlib.util
    lint_notes_py = Path.home() / ".claude" / "skills" / "malware-veri-notes" / "scripts" / "lint-notes.py"
    if not lint_notes_py.exists():
        pytest.skip("malware-veri-notes skill not installed")
    ws = _migrated_ws(tmp_path)
    spec = importlib.util.spec_from_file_location("lint_notes_ext", lint_notes_py)
    mod = importlib.util.module_from_spec(spec)
    import os
    old_cwd = os.getcwd()
    try:
        os.chdir(ws)
        spec.loader.exec_module(mod)
        note_ids, fact_ids, _parsed = mod.collect_ids(Path("notes"), Path("facts"))
        issues = []
        for fid in sorted(fact_ids):
            f, fm, body = _parsed[fid]
            issues += mod.lint_fact(fid, fm, fact_ids, body)
        for nid in sorted(note_ids):
            f, fm, _b = _parsed[nid]
            issues += mod.lint_note(nid, fm, fact_ids, note_ids)
        errs = [(c, m) for (sev, c, m) in issues if sev == "error"]
        assert not errs, errs
    finally:
        os.chdir(old_cwd)

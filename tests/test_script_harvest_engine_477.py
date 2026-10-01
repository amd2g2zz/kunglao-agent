# -*- coding: utf-8 -*-
"""Tests for the script-harvest engine (scripts/script_harvest.py).

Per the script-harvest spec (openspec issue-477): sweep scope + the
success-trace discriminator, harvest-owned budget counters in the
shared #474 ledger, staged double-run byte-exact verification, spine
landing (tools-local + harvest-manifest/1), the playbook chain record,
and the static pins (no global shelf write face; spine reuse).

The engine module is workspace-relative; every test builds a throwaway
workspace under tmp_path.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import online_distill as od  # noqa: E402
import script_harvest as sh  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "runs").mkdir(exist_ok=True)
    return ws


def write_script(ws: Path, rel: str, body: str, mtime: float | None = None):
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


DETERMINISTIC = (
    '#!/usr/bin/env python3\n'
    '"""Extract the digest line from the anchored sample."""\n'
    'import hashlib\n'
    'import sys\n'
    '\n'
    'sample = open(sys.argv[1], "rb").read()\n'
    'print(f"digest={hashlib.sha256(sample).hexdigest()}")\n'
)

NONDETERMINISTIC = (
    '#!/usr/bin/env python3\n'
    '"""Digest with a time-derived suffix (fails the byte-exact pin)."""\n'
    'import hashlib\n'
    'import sys\n'
    'import time\n'
    '\n'
    'sample = open(sys.argv[1], "rb").read()\n'
    'print(f"digest={hashlib.sha256(sample).hexdigest()} t={time.time()}")\n'
)

EXIT_TWO = (
    '#!/usr/bin/env python3\n'
    '"""Argparse-shaped CLI: exits 2 on usage errors (fixture)."""\n'
    'import sys\n'
    '\n'
    'print("usage: byte_tool.py <sample>", file=sys.stderr)\n'
    'sys.exit(2)\n'
)

QUIET = (
    '#!/usr/bin/env python3\n'
    '"""Prints nothing (fails the non-empty stdout pin)."""\n'
    'sample = None\n'
)

SAMPLE = b"harvest-477 fixture sample bytes\n" * 4


def seed_sample(ws: Path) -> Path:
    bins = ws / "bins"
    bins.mkdir(exist_ok=True)
    sample = bins / "sample.bin"
    sample.write_bytes(SAMPLE)
    return sample


def write_fact(ws: Path, name: str, status: str, cite: str,
               claim: str = "C-004", extra_prov: str = "",
               mtime: float | None = None):
    prov = ('  - {role: recompute_script, path: ' + cite + ', '
            'content_sha256: "' + "0" * 64 + '", credibility: A2}')
    if extra_prov:
        prov = prov + "\n" + extra_prov
    p = ws / "facts" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\n"
        "id: " + name[:-3] + "\n"
        "type: fact\n"
        'title: "Sample digest extracted by the harvested script"\n'
        "status: " + status + "\n"
        "claim_id: " + claim + "\n"
        "provenance:\n"
        + prov + "\n"
        "---\n"
        "body cites " + cite + "\n",
        encoding="utf-8")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def write_status(ws: Path, name: str, lines: str,
                 mtime: float | None = None):
    p = ws / "runs" / name
    p.write_text(lines, encoding="utf-8")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def stage_candidate(ws: Path) -> Path:
    """The canonical fixture: success-traced deterministic candidate."""
    write_script(ws, "scripts/so_disasm.py", DETERMINISTIC)
    write_fact(ws, "F007-so-disasm.md", "PROVEN", "scripts/so_disasm.py",
               extra_prov=('  - {role: decompiled_c, path: evidence/dump.txt,'
                           ' content_sha256: "' + "1" * 64 +
                           '", credibility: A2}'))
    seed_sample(ws)
    return ws / "scripts" / "so_disasm.py"


def staged_ledger(harvest_budget: int = 2) -> dict:
    """A valid distill ledger carrying explicit harvest counters."""
    return {
        "schema": od.BUDGET_SCHEMA, "run_id": "dstr-x",
        "run_started_ts": "2026-10-01T00:00:00Z",
        "per_run_budget": 2, "per_run_used": 0,
        "hops_budget": 12, "hops_used": 0,
        "triggers": {}, "consumed_markers": [],
        "global": {"acts": 0, "hops": 0, "landed": 0,
                   "harvest_landed": 0},
        "harvest_budget": harvest_budget, "harvest_used": 0,
    }


def read_ledger(ws: Path) -> dict:
    return json.loads((ws / od.LEDGER_NAME).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# sweep + discriminator (spec requirement 1)
# ---------------------------------------------------------------------------

class TestSweepAndClassify:
    def test_proven_fact_citation_classifies_candidate(self, tmp_path):
        ws = mk_ws(tmp_path)
        stage_candidate(ws)
        assert "scripts/so_disasm.py" in sh.sweep_scripts(ws, 0.0)
        result = sh.run_harvest(ws, since_epoch=0.0)
        assert result["skipped"] == []
        assert len(result["candidates"]) == 1
        cand = result["candidates"][0]
        assert cand["script"] == "scripts/so_disasm.py"
        assert cand["name"] == "so-disasm"
        assert cand["signals"]["verified_trace"] == ["F007-so-disasm"]
        assert cand["facts"] == [{"id": "F007-so-disasm",
                                  "claim_id": "C-004",
                                  "status": "PROVEN"}]
        assert cand["evidence"] == ["evidence/dump.txt"]

    def test_reproduce_line_citation(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "scripts/foo_bar.py", DETERMINISTIC)
        (ws / "facts").mkdir(exist_ok=True)
        (ws / "facts" / "F001-r.md").write_text(
            "---\nid: F001-r\nstatus: PROVEN\nclaim_id: C-001\n"
            'reproduce: "python ../scripts/foo_bar.py"\n'
            "---\nbody\n", encoding="utf-8")
        docs = sh.load_docs(ws)
        cand = sh.classify_script(ws, "scripts/foo_bar.py", docs)
        assert cand is not None
        assert cand["signals"]["verified_trace"] == ["F001-r"]

    def test_body_mention_citation(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "scripts/foo_bar.py", DETERMINISTIC)
        (ws / "facts").mkdir(exist_ok=True)
        (ws / "facts" / "F002-b.md").write_text(
            "---\nid: F002-b\nstatus: VERIFIED\nclaim_id: C-002\n"
            "---\nthe run used scripts/foo_bar.py to extract\n",
            encoding="utf-8")
        docs = sh.load_docs(ws)
        cand = sh.classify_script(ws, "scripts/foo_bar.py", docs)
        assert cand is not None
        assert cand["signals"]["verified_trace"] == ["F002-b"]

    def test_reuse_via_done_line_deliverable(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "scripts/foo_bar.py", DETERMINISTIC, mtime=1000.0)
        write_status(ws, "worker-status-C-001.md",
                     "| status: done | artifacts: scripts/foo_bar.py |"
                     " notes: n |\n", mtime=2000.0)
        docs = sh.load_docs(ws)
        cand = sh.classify_script(ws, "scripts/foo_bar.py", docs)
        assert cand is not None
        assert cand["signals"]["verified_trace"] == []
        assert cand["signals"]["reuse_trace"] == [
            "runs/worker-status-C-001.md"]

    def test_reuse_needs_at_or_after_mtime(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "scripts/foo_bar.py", DETERMINISTIC, mtime=2000.0)
        write_status(ws, "worker-status-C-001.md",
                     "| status: done | artifacts: scripts/foo_bar.py | n |\n",
                     mtime=1000.0)
        docs = sh.load_docs(ws)
        assert sh.classify_script(ws, "scripts/foo_bar.py", docs) is None

    def test_two_documents_reuse(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "scripts/foo_bar.py", DETERMINISTIC, mtime=1000.0)
        write_status(ws, "worker-status-C-001.md",
                     "tried scripts/foo_bar.py\nstatus: in-progress\n",
                     mtime=2000.0)
        write_status(ws, "worker-status-C-002.md",
                     "reused scripts/foo_bar.py\nstatus: in-progress\n",
                     mtime=3000.0)
        docs = sh.load_docs(ws)
        cand = sh.classify_script(ws, "scripts/foo_bar.py", docs)
        assert cand is not None
        assert len(cand["signals"]["reuse_trace"]) == 2

    def test_bare_mention_fires_nothing(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "scripts/foo_bar.py", DETERMINISTIC, mtime=1000.0)
        write_status(ws, "worker-status-C-001.md",
                     "what_I_tried: scripts/foo_bar.py crashed\n"
                     "status: blocked\n", mtime=2000.0)
        docs = sh.load_docs(ws)
        assert sh.classify_script(ws, "scripts/foo_bar.py", docs) is None

    def test_worker_declared_verified_form_not_arm_a(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "scripts/foo_bar.py", DETERMINISTIC, mtime=1000.0)
        write_fact(ws, "F001-v.md", "VERIFIED-BY-W3-static_re",
                   "scripts/foo_bar.py", mtime=2000.0)
        docs = sh.load_docs(ws)
        # one referencing doc, no done-line -> neither arm fires
        assert sh.classify_script(ws, "scripts/foo_bar.py", docs) is None

    def test_sample_specific_excluded(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "scripts/sample_specific/one_off.py",
                     DETERMINISTIC)
        write_fact(ws, "F003-s.md", "PROVEN",
                   "scripts/sample_specific/one_off.py")
        seed_sample(ws)
        assert sh.sweep_scripts(ws, 0.0) == []

    def test_stale_script_skipped(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "scripts/old_thing.py", DETERMINISTIC,
                     mtime=time.time() - 100_000)
        assert sh.sweep_scripts(ws, time.time() - 1000) == []

    def test_evidence_py_swept(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "evidence/helper.py", DETERMINISTIC)
        assert sh.sweep_scripts(ws, 0.0) == ["evidence/helper.py"]

    def test_idempotent_re_sweep(self, tmp_path):
        ws = mk_ws(tmp_path)
        stage_candidate(ws)
        first = sh.run_harvest(ws, since_epoch=0.0)
        assert len(first["landed"]) == 1
        second = sh.run_harvest(ws, since_epoch=0.0)
        assert second["landed"] == []
        assert "scripts/so_disasm.py" in second["skipped"]

    def test_zero_candidates_no_playbook(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "scripts/foo_bar.py", DETERMINISTIC)
        result = sh.run_harvest(ws, since_epoch=0.0)
        assert result["candidates"] == []
        assert not (ws / "runs" / "harvest-playbook.json").exists()


# ---------------------------------------------------------------------------
# budget (spec requirement 3, harvest-owned counters)
# ---------------------------------------------------------------------------

class TestBudget:
    def test_missing_ledger_is_fresh_and_allows_landing(self, tmp_path):
        ws = mk_ws(tmp_path)
        stage_candidate(ws)
        result = sh.run_harvest(ws, since_epoch=0.0)
        assert len(result["landed"]) == 1
        doc = read_ledger(ws)
        assert doc["harvest_budget"] == sh.HARVEST_LANDS_PER_RUN
        assert doc["harvest_used"] == 1
        assert doc["global"]["harvest_landed"] == 1

    def test_corrupt_ledger_fail_closed(self, tmp_path):
        ws = mk_ws(tmp_path)
        stage_candidate(ws)
        (ws / od.LEDGER_NAME).write_text("{not json", encoding="utf-8")
        result = sh.run_harvest(ws, since_epoch=0.0)
        assert result["landed"] == []
        assert result["archived"][0]["reason"] == "budget_ledger_unreadable"

    def test_per_run_cap(self, tmp_path):
        ws = mk_ws(tmp_path)
        seed_sample(ws)
        for i in range(3):
            write_script(ws, "scripts/cand_%d.py" % i, DETERMINISTIC)
            write_fact(ws, "F00%d-c%d.md" % (i, i), "PROVEN",
                       "scripts/cand_%d.py" % i)
        result = sh.run_harvest(ws, since_epoch=0.0)
        assert len(result["landed"]) == sh.HARVEST_LANDS_PER_RUN
        reasons = {a["reason"] for a in result["archived"]}
        assert "per_run_harvest_budget_exhausted" in reasons

    def test_never_loosen_clamp(self, tmp_path):
        ws = mk_ws(tmp_path)
        stage_candidate(ws)
        ledger = staged_ledger(harvest_budget=99)
        od._atomic_write_json(ws / od.LEDGER_NAME, ledger)
        result = sh.run_harvest(ws, since_epoch=0.0)
        assert len(result["landed"]) == 1
        assert read_ledger(ws)["harvest_budget"] == sh.HARVEST_LANDS_PER_RUN

    def test_smaller_stored_budget_honored(self, tmp_path):
        ws = mk_ws(tmp_path)
        seed_sample(ws)
        write_script(ws, "scripts/cand_0.py", DETERMINISTIC)
        write_fact(ws, "F010-c0.md", "PROVEN", "scripts/cand_0.py")
        write_script(ws, "scripts/cand_1.py", DETERMINISTIC)
        write_fact(ws, "F011-c1.md", "PROVEN", "scripts/cand_1.py")
        od._atomic_write_json(ws / od.LEDGER_NAME,
                              staged_ledger(harvest_budget=1))
        result = sh.run_harvest(ws, since_epoch=0.0)
        assert len(result["landed"]) == 1
        assert len(result["archived"]) == 1

    def test_distill_counters_untouched(self, tmp_path):
        ws = mk_ws(tmp_path)
        stage_candidate(ws)
        ledger = staged_ledger()
        ledger.update({
            "per_run_used": 1, "hops_used": 3,
            "triggers": {"crypto:decode": "attempt-1"},
            "consumed_markers": ["runs/worker-status-C-004.md"],
            "global": {"acts": 1, "hops": 3, "landed": 1,
                       "harvest_landed": 0}})
        od._atomic_write_json(ws / od.LEDGER_NAME, ledger)
        result = sh.run_harvest(ws, since_epoch=0.0)
        assert len(result["landed"]) == 1
        doc = read_ledger(ws)
        assert doc["per_run_used"] == 1
        assert doc["hops_used"] == 3
        assert doc["global"]["acts"] == 1
        assert doc["global"]["landed"] == 1
        assert doc["global"]["harvest_landed"] == 1

    def test_harvest_counter_type_garbage_reads_exhausted(self, tmp_path):
        ws = mk_ws(tmp_path)
        stage_candidate(ws)
        ledger = staged_ledger()
        ledger["harvest_used"] = "many"
        od._atomic_write_json(ws / od.LEDGER_NAME, ledger)
        result = sh.run_harvest(ws, since_epoch=0.0)
        assert result["landed"] == []
        assert result["archived"][0]["reason"] == "harvest_ledger_type_garbage"
        assert od.ledger_state(ws)["corrupt"] is False

    def test_global_harvest_landed_carried_across_reinit(self, tmp_path):
        ws = mk_ws(tmp_path)
        stage_candidate(ws)
        sh.run_harvest(ws, since_epoch=0.0)
        od.reinit_run(ws)
        doc = read_ledger(ws)
        assert doc["global"]["harvest_landed"] == 1
        assert doc["harvest_used"] == 0


# ---------------------------------------------------------------------------
# verification + landing (spec requirement 2 + 3)
# ---------------------------------------------------------------------------

class TestVerificationAndLanding:
    def test_deterministic_double_run_lands_with_full_manifest(
            self, tmp_path):
        ws = mk_ws(tmp_path)
        stage_candidate(ws)
        result = sh.run_harvest(ws, since_epoch=0.0)
        assert len(result["landed"]) == 1
        landed = result["landed"][0]
        assert landed["name"] == "so-disasm"
        tool = ws / "tools-local" / "so-disasm.py"
        assert tool.is_file()
        assert os.access(tool, os.X_OK)
        manifest = json.loads(
            (ws / "tools-local" / "so-disasm.manifest.json")
            .read_text(encoding="utf-8"))
        assert manifest["schema"] == "harvest-manifest/1"
        assert manifest["source_path"] == "scripts/so_disasm.py"
        assert manifest["facts"] == [{"id": "F007-so-disasm",
                                      "claim_id": "C-004",
                                      "status": "PROVEN"}]
        fx = manifest["fixture"]
        assert fx["runs"] == 2
        assert fx["input_sha256"] == hashlib.sha256(SAMPLE).hexdigest()
        expected_stdout = "digest=%s\n" % hashlib.sha256(SAMPLE).hexdigest()
        assert fx["stdout_sha256"] == hashlib.sha256(
            expected_stdout.encode("utf-8")).hexdigest()
        assert fx["cwd"] == "."
        assert manifest["signals"] == {"verified_trace": ["F007-so-disasm"],
                                       "reuse_trace": []}
        assert manifest["served_in"] == [
            "Sample digest extracted by the harvested script"]
        assert manifest["capability"] is None
        assert manifest["description"] == (
            "Extract the digest line from the anchored sample.")
        assert manifest["version"]["platform"] == sys.platform
        assert manifest["version"]["python"].count(".") == 2
        assert (ws / "scripts" / "so_disasm.py").read_bytes() == \
            tool.read_bytes()

    def test_digest_mismatch_archives(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "scripts/so_noise.py", NONDETERMINISTIC)
        write_fact(ws, "F008-n.md", "PROVEN", "scripts/so_noise.py")
        seed_sample(ws)
        result = sh.run_harvest(ws, since_epoch=0.0)
        assert result["landed"] == []
        assert result["archived"][0]["reason"] == "digest-mismatch"
        tl = ws / "tools-local"
        assert not (tl / "so-noise.py").exists()
        assert not (tl / "so-noise.manifest.json").exists()
        arch = json.loads(
            (ws / "runs" / "harvest-archive" / "so-noise.json")
            .read_text(encoding="utf-8"))
        assert arch["script"] == "scripts/so_noise.py"
        assert (ws / "scripts" / "so_noise.py").read_bytes() == \
            NONDETERMINISTIC.encode("utf-8")

    def test_rc2_archives_as_argv_contract(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "scripts/byte_tool.py", EXIT_TWO)
        write_fact(ws, "F009-a.md", "PROVEN", "scripts/byte_tool.py")
        seed_sample(ws)
        result = sh.run_harvest(ws, since_epoch=0.0)
        assert result["landed"] == []
        arch = result["archived"][0]
        assert arch["reason"] == "argv-contract"
        assert arch["rc"] == 2

    def test_empty_stdout_archives(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "scripts/quiet_tool.py", QUIET)
        write_fact(ws, "F012-q.md", "PROVEN", "scripts/quiet_tool.py")
        seed_sample(ws)
        result = sh.run_harvest(ws, since_epoch=0.0)
        assert result["landed"] == []
        assert result["archived"][0]["reason"] == "empty-stdout"

    def test_no_anchored_sample_no_landing(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "scripts/so_disasm.py", DETERMINISTIC)
        write_fact(ws, "F007-x.md", "PROVEN", "scripts/so_disasm.py")
        result = sh.run_harvest(ws, since_epoch=0.0)
        assert result["landed"] == []
        assert result["archived"][0]["reason"] == "no-anchored-sample"

    def test_bad_name_archives(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "scripts/X.py", DETERMINISTIC)
        write_fact(ws, "F010-x.md", "PROVEN", "scripts/X.py")
        seed_sample(ws)
        result = sh.run_harvest(ws, since_epoch=0.0)
        assert result["archived"][0]["reason"] == "bad-name"

    def test_name_collision_with_distill_tool(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "scripts/so_tool.py", DETERMINISTIC)
        write_fact(ws, "F011-t.md", "PROVEN", "scripts/so_tool.py")
        seed_sample(ws)
        tl = ws / "tools-local"
        tl.mkdir(exist_ok=True)
        (tl / "so-tool.py").write_bytes(b"print('distilled tool')\n")
        od._atomic_write_json(tl / "so-tool.manifest.json",
                              {"schema": "distill-manifest/1",
                               "name": "so-tool"})
        result = sh.run_harvest(ws, since_epoch=0.0)
        assert result["landed"] == []
        assert result["archived"][0]["reason"] == "name-collision"
        assert (tl / "so-tool.py").read_bytes() == \
            b"print('distilled tool')\n"

    def test_harvest_vs_harvest_same_name_different_source(self, tmp_path):
        ws = mk_ws(tmp_path)
        write_script(ws, "scripts/a_b.py", DETERMINISTIC)
        write_fact(ws, "F013-ab.md", "PROVEN", "scripts/a_b.py")
        seed_sample(ws)
        tl = ws / "tools-local"
        tl.mkdir(exist_ok=True)
        (tl / "a-b.py").write_bytes(b"other source\n")
        od._atomic_write_json(tl / "a-b.manifest.json",
                              {"schema": "harvest-manifest/1",
                               "name": "a-b",
                               "source_path": "scripts/other.py"})
        result = sh.run_harvest(ws, since_epoch=0.0)
        assert result["landed"] == []
        assert result["archived"][0]["reason"] == "name-collision"


# ---------------------------------------------------------------------------
# playbook (spec requirement 4)
# ---------------------------------------------------------------------------

class TestPlaybook:
    def test_chain_record_written(self, tmp_path):
        ws = mk_ws(tmp_path)
        stage_candidate(ws)
        sh.run_harvest(ws, since_epoch=0.0)
        pb = json.loads((ws / "runs" / "harvest-playbook.json")
                        .read_text(encoding="utf-8"))
        assert pb["schema"] == "harvest-playbook/1"
        assert len(pb["chains"]) == 1
        chain = pb["chains"][0]
        assert chain["script"] == "scripts/so_disasm.py"
        assert chain["capability_input"]["sha256"] == hashlib.sha256(
            SAMPLE).hexdigest()
        assert chain["evidence"] == ["evidence/dump.txt"]
        assert chain["outcome"] == {"fact": "F007-so-disasm",
                                    "claim_id": "C-004",
                                    "status": "PROVEN"}
        assert chain["landed_as"] == "tools-local/so-disasm.py"


# ---------------------------------------------------------------------------
# static pins
# ---------------------------------------------------------------------------

class TestStaticPins:
    def test_no_global_shelf_write_surface(self):
        src = (SCRIPTS / "script_harvest.py").read_text(encoding="utf-8")
        assert "references/" not in src
        assert "parents[" not in src

    def test_engine_reuses_the_spine(self):
        assert sh.LEDGER_NAME == od.LEDGER_NAME
        assert sh.TOOLS_LOCAL_DIRNAME == od.TOOLS_LOCAL_DIRNAME
        assert sh.ORACLE_TIMEOUT_S == od.ORACLE_TIMEOUT_S

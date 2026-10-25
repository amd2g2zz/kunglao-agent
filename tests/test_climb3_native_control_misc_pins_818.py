#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb3_native_control_misc_pins_818.py — #818 climb segment 3D.

Behavior pins on REAL fixtures for the residual faces the second climb
leg left unmeasured:

  scripts/eval_native_targets.py — the REAL builders (NDK arm64 .so at
  l0/l1/l2 with the L2>L1 .text flattening regression, the ELF section/
  symbol parsers against the built artifacts, PE text-size parsing on a
  synthesized PE32+ image, the sandboxed toolchain report), gated on the
  declared toolchains and SKIPped honestly when a builder's toolchain is
  absent (the mint-side SKIP contract, never a fake build).

  scripts/eval_control_arm.py — the bare-arm/A-B machinery: candidate
  extraction, the candidates manifest loader, minted-only grading (the
  anti-digest-table false-PROVEN face), the fresh re-run leg, the
  five-metric arm block, manifest materialization, the executor-seam
  bare-arm driver and the full A/B run over a synthetic corpus.

  scripts/eval_misdirection.py — the rendered true/naive candidates
  executed for real under node/go (decoy-marker units PASS as the
  reference and FAIL as the naive face through the checker's own
  replay machinery), and the reference/naive verdict builders.

Pin discipline: expectations derive from the fixture each test computed —
no repo-state literalization (units are minted from the modules' own
generators; toolchain-dependent faces skip when the toolchain is absent).
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_checker as chk  # noqa: E402
import eval_control_arm as eca  # noqa: E402
import eval_dataset as ds  # noqa: E402
import eval_misdirection as md  # noqa: E402
import eval_native_targets as ntg  # noqa: E402
import eval_targets as tg  # noqa: E402

HAS_NDK = ntg.find_ndk_clang() is not None
NO_REASON_NDK = pytest.mark.skipif(not HAS_NDK, reason="ndk-arm64 absent")


def _host_cc_works() -> bool:
    """The host C compiler face build_smc_elf flattening_signature need."""
    clang = shutil.which("clang") or shutil.which("cc")
    if clang is None:
        return False
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "probe.c"
        src.write_text("int main(void){return 0;}\n", encoding="utf-8")
        proc = subprocess.run([clang, "-O0", "-c", str(src), "-o",
                               str(Path(td) / "probe.o")],
                              capture_output=True)
        return proc.returncode == 0


NEEDS_HOST_CC = pytest.mark.skipif(not _host_cc_works(),
                                   reason="host C compiler absent/broken")
NO_NODE = pytest.mark.skipif(shutil.which("node") is None,
                             reason="node absent")
NO_GO = pytest.mark.skipif(shutil.which("go") is None, reason="go absent")


def _ndk_cfg(family: str = "arm-native-kdf") -> dict:
    return ntg.derive_cfg(family, ntg.FAMILY_SEEDS[family])


# ================================================ native builder faces

class TestNativeBuilders:
    @NO_REASON_NDK
    def test_arm_so_ladder_builds_with_the_flattening_regression(
            self, tmp_path) -> None:
        cfg = _ndk_cfg()
        sizes = {}
        infos = {}
        for rung in ("l0", "l1", "l2"):
            out = tmp_path / f"arm-{rung}.so"
            infos[rung] = ntg.build_arm_so(cfg, rung, out)
            sizes[rung] = infos[rung]["text_size"]
            assert out.is_file() and sizes[rung] > 0
        # the documented regression: source-level flattening grows .text
        assert sizes["l2"] > sizes["l1"]
        assert "strip --strip-all" in infos["l1"]["flags"]
        assert "source-level flattening" in infos["l2"]["flags"]
        assert infos["l0"]["build"].startswith("ndk:aarch64-linux-android")

    @NO_REASON_NDK
    def test_arm_so_symbol_table_is_parseable_before_stripping(
            self, tmp_path) -> None:
        cfg = _ndk_cfg()
        plain = tmp_path / "arm-l0.so"
        ntg.build_arm_so(cfg, "l0", plain)
        blob = plain.read_bytes()
        vaddr, size = ntg._symbol_vaddr(blob, "kdf_derive")
        assert vaddr > 0 and size > 0
        addr, off = ntg._elf_text_section(blob)
        assert off > 0
        with pytest.raises(RuntimeError, match="symbol no-such not found"):
            ntg._symbol_vaddr(blob, "no-such")
        # the l1 face records the strip in its build contract and stays
        # structurally parseable
        stripped = tmp_path / "arm-l1.so"
        info_l1 = ntg.build_arm_so(cfg, "l1", stripped)
        assert "strip --strip-all" in info_l1["flags"]
        assert ntg.elf_text_size(stripped.read_bytes()) == \
            info_l1["text_size"]

    @NO_REASON_NDK
    def test_mod_so_ladder_builds_and_strips(self, tmp_path) -> None:
        cfg = _ndk_cfg("mod-crypto-native")
        l0 = tmp_path / "mod-l0.so"
        l2 = tmp_path / "mod-l2.so"
        i0 = ntg.build_mod_so(cfg, "l0", l0)
        i2 = ntg.build_mod_so(cfg, "l2", l2)
        assert l0.is_file() and l2.is_file()
        assert i0["text_size"] > 0 and i2["text_size"] > 0
        assert "+ strip" in i0["flags"]
        assert "source-level flattening" in i2["flags"]

    def test_pe_text_size_parses_a_synththesized_pe32_plus(self) -> None:
        # a minimal PE32+ image: DOS header -> PE sig -> COFF -> optional
        # header -> one .text section with a known VirtualSize
        text_vsize = 0x1234
        dos = bytearray(0x40)
        struct.pack_into("<I", dos, 0x3C, 0x40)  # e_lfanew
        pe_sig = b"PE\x00\x00"
        coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, 224,
                           0x22)  # machine/sections/ts/symptr/n/optsz
        opt = bytearray(224)  # SizeOfOptionalHeader below
        opt[0] = 0x0B  # PE32+ magic
        section = bytearray(40)
        section[0:6] = b".text\x00"
        struct.pack_into("<I", section, 8, text_vsize)  # VirtualSize
        blob = bytes(dos) + pe_sig + coff + bytes(opt) + bytes(section)
        assert ntg.pe_text_size(blob) == text_vsize

    def test_toolchain_report_rows_in_a_sandbox(self, tmp_path) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake_go = bin_dir / "go"
        fake_go.write_text("#!/bin/sh\n", encoding="utf-8")
        fake_go.chmod(0o755)
        env = {"HOME": str(tmp_path / "home"),
               "PATH": str(bin_dir) + os.pathsep + "/nonexistent"}
        rows = {r["toolchain"]: r for r in ntg.toolchain_report(env)}
        assert rows["go"]["status"] == "OK"
        assert rows["ndk-arm64"]["status"] == "TOOLCHAIN_MISSING"
        assert rows["clang"]["status"] == "TOOLCHAIN_MISSING"
        assert rows["llvm-strip"]["status"] == "TOOLCHAIN_MISSING"

    @NEEDS_HOST_CC
    def test_smc_elf_builds_and_strips_with_a_stable_payload(
            self, tmp_path) -> None:
        if ntg.find_lld() is None:
            pytest.skip("ld.lld absent")
        cfg = ntg.derive_cfg("smc-x86", ntg.FAMILY_SEEDS["smc-x86"])
        plain = tmp_path / "smc-l0.elf"
        info = ntg.build_smc_elf(cfg, "l0", plain)
        assert plain.is_file() and info["payload_vaddr"] > 0x400000
        assert info["payload_size"] > 0
        # generator determinism: the same seed rebuilds the same payload
        again = tmp_path / "smc-again.elf"
        info2 = ntg.build_smc_elf(cfg, "l0", again)
        assert info2["payload_sha256"] == info["payload_sha256"]
        # the stripped face loses .symtab (the layout face moves to the
        # recorded build info)
        stripped = tmp_path / "smc-l1.elf"
        ntg.build_smc_elf(cfg, "l1", stripped)
        blob = stripped.read_bytes()
        with pytest.raises(RuntimeError):
            ntg._symbol_vaddr(blob, "payload_entry")

    @NEEDS_HOST_CC
    def test_flattening_signature_distinguishes_the_rungs(self) -> None:
        family = "arm-native-kdf"
        l1 = ntg.flattening_signature(family, "l1")
        l2 = ntg.flattening_signature(family, "l2")
        assert l1["status"] == "OK" and l1["case_cmps"] == []
        assert l2["status"] == "OK" and set(l2["case_cmps"]) == {1, 2}

    def test_flatten_check_refuses_unknown_tasks(self, capsys) -> None:
        rc = ntg.run_flatten_check("no-such-task-xyz")
        stream = capsys.readouterr().out
        assert rc == 2
        assert "VERDICT REFUSED" in stream


# ============================================ native unit checker face

class TestNativeUnitThroughChecker:
    def test_minted_native_unit_roundtrips_the_mechanical_checker(
            self, tmp_path) -> None:
        """write_task_unit -> checker run() on the python3-toolchain
        native face: the rendered reference is byte-exact against the
        model, the static face carries the public constants, and the
        minted probes are graded checker-side."""
        tdir = ntg.write_task_unit("arm-native-kdf", "l1", "arm-proto",
                                   tmp_path / "corpus")
        task = ds.load_task(tdir)
        gt = json.loads((tdir / "ground_truth.json").read_text(
            encoding="utf-8"))
        cand = tmp_path / "candidate.py"
        cand.write_text(ntg.render_reference_py(
            "arm-native-kdf",
            ntg.derive_cfg("arm-native-kdf",
                           ntg.FAMILY_SEEDS["arm-native-kdf"])),
            encoding="utf-8")
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc, ev = chk.run(str(tdir), cand, tmp_path / "out",
                             tier="release")
        assert rc == chk.RC_PASS
        assert ev["verdict"] == "PASS"
        assert ev["family"] == task["family"] == "arm-native-kdf"
        assert ev["faces"]["static"]["hits"] >= task["checker"][
            "thresholds"]["min_constant_hits"]
        assert ev["faces"]["replay"]["matched"] == \
            ev["faces"]["replay"]["count"]
        published_ids = {p["i"] for p in gt["published_pairs"]}
        minted_ids = {p["i"] for p in ntg.minted_probes(
            "arm-native-kdf", gt["seed"], gt["minted_probe_count"])}
        assert not (published_ids & minted_ids)
        assert "VERDICT PASS" in buf.getvalue()


# ============================================= control-arm machinery

def _corpus(tmp_path: Path, task_ids: tuple[str, ...] = (
        "py-derive-a", "py-derive-b")) -> Path:
    """A synthetic smoke corpus of py-derive units (python3 toolchain:
    every grading leg is real on any machine)."""
    corpus = tmp_path / "corpus"
    for i, tid in enumerate(task_ids):
        tg.write_task_unit("py-derive", 620000 + i, tid,
                           corpus / "v1" / "tasks" / "smoke")
    return corpus


def _candidate_source(tdir: Path, family: str = "py-derive") -> str:
    """The reference candidate for a minted unit (the task's own target
    implements the seam; the checker greens it)."""
    return (tdir / "target" / "derive.py").read_text(encoding="utf-8")


class TestControlArmFaces:
    def test_extract_candidate_fences_and_refuses_empty(self) -> None:
        assert eca.extract_candidate("plain body") == "plain body"
        fenced = "intro\n```py\nline1\nline2\n```\ntail"
        assert eca.extract_candidate(fenced) == "line1\nline2"
        with pytest.raises(ValueError, match="empty candidate"):
            eca.extract_candidate("```\n```\n")

    def test_manifest_loader_contract(self, tmp_path) -> None:
        manifest = tmp_path / "cands.json"
        manifest.write_text(json.dumps({
            "schema": "kunglao-eval-candidates/1",
            "candidates": {
                "t-text": {"text": "def derive(d):\n    return 0\n"},
                "t-path": {"path": str(tmp_path / "a.py")},
            },
        }), encoding="utf-8")
        got = eca.load_manifest(manifest, {"t-text", "t-path"})
        assert got["t-path"] == tmp_path / "a.py"
        assert "return 0" in got["t-text"]
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"schema": "kunglao-eval-candidates/1",
                                   "candidates": {"ghost": {"text": "x"}}}),
                        encoding="utf-8")
        with pytest.raises(ValueError, match="unknown task"):
            eca.load_manifest(bad, {"t-text"})
        missing = tmp_path / "missing.json"
        missing.write_text(json.dumps({"schema": "kunglao-eval-candidates/1",
                                       "candidates": {"t": {}}}),
                            encoding="utf-8")
        with pytest.raises(ValueError, match="needs text or path"):
            eca.load_manifest(missing, {"t"})

    def test_minted_only_grade_and_fresh_rerun(self, tmp_path) -> None:
        tdir = _corpus(tmp_path, ("py-derive-grade",)) \
            / "v1" / "tasks" / "smoke" / "py-derive-grade"
        gt = json.loads((tdir / "ground_truth.json").read_text(
            encoding="utf-8"))
        good = tmp_path / "good.py"
        good.write_text(_candidate_source(tdir), encoding="utf-8")
        (tmp_path / "out").mkdir(parents=True)
        got = eca.minted_only_grade("py-derive", tdir, gt, good,
                                    tmp_path / "out")
        assert got is not None and got[0] == got[1] > 0  # minted-only green
        bad = tmp_path / "bad.py"
        bad.write_text("def derive(data):\n    return 0\n",
                        encoding="utf-8")
        (tmp_path / "out2").mkdir(parents=True)
        got_bad = eca.minted_only_grade("py-derive", tdir, gt, bad,
                                        tmp_path / "out2")
        assert got_bad == (0, got[1])  # the naive face lands nowhere
        (tmp_path / "out3").mkdir(parents=True, exist_ok=True)
        (tmp_path / "out4").mkdir(parents=True, exist_ok=True)
        assert eca.rerun_verdict(tdir, good, tmp_path / "out3") == "PASS"
        assert eca.rerun_verdict(tdir, bad, tmp_path / "out4") == "FAIL"

    def test_minted_only_grade_skips_without_the_toolchain(
            self, tmp_path, monkeypatch) -> None:
        if shutil.which("go") is None:
            pytest.skip("go absent on this machine")
        go_tdir = tg.write_task_unit("go-arx", 630001, "go-skip-proto",
                                     tmp_path / "corpus2")
        monkeypatch.setenv("PATH", "")
        gt_go = json.loads((go_tdir / "ground_truth.json").read_text(
            encoding="utf-8"))
        got = eca.minted_only_grade("go-arx", go_tdir, gt_go,
                                    go_tdir / "target" / "sample_kdf.go",
                                    tmp_path / "out")
        assert got is None  # ungradeable: the metric never accuses

    def test_arm_metrics_rows_and_budget(self) -> None:
        doc = {"arm": "bare-llm", "rows": [
            {"task_id": "u1", "arm": "bare-llm", "verdict": "PASS",
             "evidence_ref": "e1",
             "metrics": {"converged": 1, "ttc_seconds": 2.0}},
            {"task_id": "u2", "arm": "bare-llm", "verdict": "FAIL",
             "metrics": {"converged": 0, "ttc_seconds": 1.0}},
            {"task_id": "u3", "arm": "bare-llm", "verdict": "SKIP",
             "metrics": {"ttc_seconds": None}},
            {"task_id": "u4", "arm": "bare-llm", "verdict": "PASS",
             "evidence_ref": "e4",
             "metrics": {"converged": 1, "ttc_seconds": 0.5}},
        ]}
        rerun = {"u1": "FAIL"}  # converged=1 but the fresh re-run disagrees
        minted = {"u1": (0, 8), "u2": None}  # u1 fails minted-only, u3 no
        m = eca.arm_metrics(doc, rerun, minted, wall_s=9.5,
                            tokens=(11, 7))
        assert m["tasks"] == 4
        assert m["answer_rate"] == pytest.approx(3 / 4)  # SKIP is no answer
        assert m["proven_with_evidence_rate"] == pytest.approx(2 / 4)
        assert m["premature_closure_rate"] == pytest.approx(1 / 2)
        assert m["premature_tasks"] == ["u1"]
        assert m["false_proven_tasks"] == ["u1"]
        assert m["false_proven_rate"] == pytest.approx(1 / 2)
        assert m["ungraded"] == ["u4"]  # toolchain-absent, reported
        assert m["budget"] == {"wall_s": 9.5, "ttc_seconds_sum": 3.5,
                               "tokens_in": 11, "tokens_out": 7}

    def test_bare_arm_refuses_unknown_tasks(self, tmp_path, capsys) -> None:
        rc, doc, records = eca.run_bare_arm(
            ["ghost-unit"], "smoke", tmp_path / "out")
        assert rc == eca.RC_REFUSED and doc == {} and records == []
        assert "unknown task(s)" in capsys.readouterr().out

    def test_bare_arm_without_executor_or_manifest_skips_rows(
            self, tmp_path) -> None:
        _corpus(tmp_path)
        out = tmp_path / "run"
        with _corpus_env(tmp_path):
            rc, doc, records = eca.run_bare_arm(
                ["py-derive-a"], "smoke", out)
        assert rc == 0
        row = doc["rows"][0]
        assert row["verdict"] in ("SKIP", "REFUSED")  # nothing to grade
        assert records[0]["executor"]["mode"] == "none"
        assert records[0]["candidate_path"] is None

    def test_bare_arm_executor_seam_runs_the_real_checker(
            self, tmp_path) -> None:
        corpus = _corpus(tmp_path, ("py-derive-exec",))
        tdir = corpus / "v1" / "tasks" / "smoke" / "py-derive-exec"

        def executor(prompt: str, timeout_s: float = 1.0) -> dict:
            return {"text": "```py\n"
                            + _candidate_source(tdir) + "\n```",
                    "returncode": 0, "wall_s": 0.1, "timed_out": False,
                    "tokens_in": 10, "tokens_out": 5, "stderr": ""}

        out = tmp_path / "run"
        with _corpus_env(tmp_path):
            rc, doc, records = eca.run_bare_arm(
                ["py-derive-exec"], "smoke", out, executor=executor)
        assert rc == 0
        row = doc["rows"][0]
        assert row["verdict"] == "PASS"
        assert records[0]["candidate_path"] is not None
        assert Path(records[0]["candidate_path"]).is_file()
        receipts = list(out.glob("bare-run-*.json"))
        assert receipts  # the run receipt lands
        rec = json.loads(receipts[0].read_text(encoding="utf-8"))
        assert rec["schema"] == eca.SCHEMA_BARE_RUN

    def test_ab_run_greens_both_arms_and_writes_the_comparison(
            self, tmp_path) -> None:
        corpus = _corpus(tmp_path, ("py-derive-ab",))
        tdir = corpus / "v1" / "tasks" / "smoke" / "py-derive-ab"
        source = _candidate_source(tdir)
        manifest = tmp_path / "cands.json"
        manifest.write_text(json.dumps({
            "schema": "kunglao-eval-candidates/1",
            "candidates": {"py-derive-ab": {"text": source}},
        }), encoding="utf-8")

        def executor(prompt: str, timeout_s: float = 1.0) -> dict:
            return {"text": source, "returncode": 0, "wall_s": 0.1,
                    "timed_out": False, "tokens_in": 3, "tokens_out": 2,
                    "stderr": ""}

        out = tmp_path / "ab"
        with _corpus_env(tmp_path):
            rc, summary = eca.run_ab(["py-derive-ab"], "smoke", out,
                                     bare_manifest=manifest,
                                     executor=executor)
        assert rc == 0
        assert summary  # the comparison doc
        assert (out / "bare-llm").is_dir() and (out / "framework").is_dir()


class _corpus_env:
    """KUNGLAO_EVAL_ROOT scoped to the with-block (the corpus-root seam
    reads the env at call time)."""

    def __init__(self, tmp_path: Path) -> None:
        self._root = str(tmp_path / "corpus")
        self._old = None

    def __enter__(self):
        self._old = os.environ.get("KUNGLAO_EVAL_ROOT")
        os.environ["KUNGLAO_EVAL_ROOT"] = self._root
        return self

    def __exit__(self, *exc):
        if self._old is None:
            os.environ.pop("KUNGLAO_EVAL_ROOT", None)
        else:
            os.environ["KUNGLAO_EVAL_ROOT"] = self._old


# ==================================== misdirection renderer e2e faces

class TestMisdirectionRenderers:
    def _unit_gt(self, task_id: str) -> dict:
        return md.build_task_unit(task_id)["ground_truth"]

    @NO_NODE
    def test_js_reference_greens_and_naive_fails_the_replay(
            self, tmp_path) -> None:
        tdir = md.write_task_unit("m3-keystring-js-v1",
                                  tmp_path / "corpus")
        gt = self._unit_gt("m3-keystring-js-v1")
        good = tmp_path / "ref.js"
        good.write_text(md.render_true_candidate(gt), encoding="utf-8")
        (tmp_path / "out").mkdir(parents=True)
        matched, count, _ttc, notes = chk.replay_face(
            "decoy-marker-js", tdir, gt, good, tmp_path / "out", "node")
        assert count > 0 and matched == count and not notes
        naive = tmp_path / "naive.js"
        naive.write_text(md.render_decoy_candidate(gt), encoding="utf-8")
        (tmp_path / "out2").mkdir(parents=True)
        nm, nc, _t, _notes = chk.replay_face(
            "decoy-marker-js", tdir, gt, naive, tmp_path / "out2", "node")
        assert nm < nc  # the decoy face must NOT reproduce the truth

    @NO_GO
    def test_go_reference_greens_the_stdin_face(self, tmp_path) -> None:
        tdir = md.write_task_unit("m3-sbox-go-v1", tmp_path / "corpus")
        gt = self._unit_gt("m3-sbox-go-v1")
        good = tmp_path / "ref.go"
        good.write_text(md.render_true_candidate(gt), encoding="utf-8")
        (tmp_path / "out").mkdir(parents=True)
        matched, count, _ttc, notes = chk.replay_face(
            "decoy-marker-go", tdir, gt, good, tmp_path / "out", "go")
        assert count > 0 and matched == count and not notes

    def test_reference_and_naive_verdict_builders_diverge(
            self, tmp_path) -> None:
        """The verdict builders derive their documents from the unit's
        own rubric: the reference document passes the grader, the naive
        (trap-taken) document does not."""
        with _corpus_env(tmp_path):
            tdir = md.write_task_unit(
                "m1-fileperm-v1",
                tmp_path / "corpus" / "v1" / "tasks" / "misdirection")
            gt = json.loads((tdir / "ground_truth.json").read_text(
                encoding="utf-8"))
            ref = md.build_reference_verdict("m1-fileperm-v1")
            naive = md.build_naive_verdict("m1-fileperm-v1")
        ref_path = tmp_path / "ref-verdict.json"
        ref_path.write_text(json.dumps(ref), encoding="utf-8")
        naive_path = tmp_path / "naive-verdict.json"
        naive_path.write_text(json.dumps(naive), encoding="utf-8")
        thresholds = {"min_evidence_entries": 1}
        verdict_r, ok_r, notes_r = md.misdirection_verdict_face(
            ref_path, gt, thresholds)
        assert ok_r is True and notes_r == []
        verdict_n, ok_n, notes_n = md.misdirection_verdict_face(
            naive_path, gt, thresholds)
        assert ok_n is False
        assert notes_n and notes_n[0]["code"] in (
            "WRONG_CORRECT_PATH", "ENV_MISATTRIBUTED", "MISATTRIBUTED")

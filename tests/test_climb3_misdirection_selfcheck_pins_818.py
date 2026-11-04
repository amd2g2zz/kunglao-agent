#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb3_misdirection_selfcheck_pins_818.py — #818 climb
segment 3E.

Behavior pins on REAL fixtures for the adversarial-misdirection tier's
self-check machinery, the remaining deception-smoke arms, and the
loopback route mock:

  scripts/eval_misdirection.py — run_self_check for every unit family
  (checker greens the reference, FAILS the naive face, and the committed
  artifact executes against the model: node js-sign, go stdin, the env
  js probe, the key-rotation js trigger, and both net faces through the
  loopback RouteMockServer), the mint CLI, the deception smoke's
  per-family gates (decoy record / env bait markers / rotation
  derivation point / unknown family), the static-key re-hook
  arithmetic, and the route mock's server-side validation over real
  HTTP.

Pin discipline: expectations derive from the fixture each test computed —
no repo-state literalization (units are minted from the modules' own
generators into a synthetic corpus; toolchain faces skip when absent).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_misdirection as md  # noqa: E402

NO_NODE = pytest.mark.skipif(shutil.which("node") is None,
                             reason="node absent")
NO_GO = pytest.mark.skipif(shutil.which("go") is None, reason="go absent")


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


def _mint_unit(tmp_path: Path, task_id: str) -> Path:
    with _corpus_env(tmp_path):
        return md.write_task_unit(
            task_id, tmp_path / "corpus" / "v1" / "tasks" / "misdirection")


# ================================================ per-family self-checks

class TestMisdirectionSelfCheck:
    def _run(self, tmp_path: Path, task_id: str) -> tuple[int, str]:
        _mint_unit(tmp_path, task_id)
        from contextlib import redirect_stdout
        import io
        buf = io.StringIO()
        with _corpus_env(tmp_path), redirect_stdout(buf):
            rc = md.run_self_check(task_id)
        return rc, buf.getvalue()

    @NO_NODE
    def test_env_misattr_js_parity(self, tmp_path) -> None:
        rc, stream = self._run(tmp_path, "m1-fileperm-v1")
        assert rc == 0
        assert "METRIC selfcheck_green=1" in stream
        assert "VERDICT PASS" in stream

    @NO_NODE
    def test_key_rotation_js_parity(self, tmp_path) -> None:
        rc, stream = self._run(tmp_path, "m2-session-v1")
        assert rc == 0
        assert "VERDICT PASS" in stream

    @NO_NODE
    def test_decoy_marker_js_parity(self, tmp_path) -> None:
        rc, stream = self._run(tmp_path, "m3-keystring-js-v1")
        assert rc == 0
        assert "VERDICT PASS" in stream

    @NO_GO
    def test_decoy_marker_go_parity(self, tmp_path) -> None:
        rc, stream = self._run(tmp_path, "m3-sbox-go-v1")
        assert rc == 0
        assert "VERDICT PASS" in stream

    @NO_NODE
    def test_net_faces_parity_through_the_route_mock(
            self, tmp_path) -> None:
        for task_id in ("m1-net403-v1", "m2-request-v1"):
            rc, stream = self._run(tmp_path, task_id)
            assert rc == 0, stream
            assert "VERDICT PASS" in stream

    def test_self_check_skips_without_its_toolchain(
            self, tmp_path, monkeypatch, capsys) -> None:
        _mint_unit(tmp_path, "m1-fileperm-v1")
        if shutil.which("node") is None:
            pass  # the scrub below is then the only reality anyway
        monkeypatch.setattr(md.shutil, "which",
                            lambda cmd: None if cmd == "node"
                            else shutil.which(cmd))
        with _corpus_env(tmp_path):
            rc = md.run_self_check("m1-fileperm-v1")
        stream = capsys.readouterr().out
        assert rc == 3
        assert "SKIP self-check m1-fileperm-v1: node toolchain absent" in \
            stream

    def test_cli_mints_and_refuses_unknown_units(self, tmp_path,
                                                 capsys) -> None:
        # the verdict-family mint writes its own reference verdict, which
        # resolves the unit through the corpus-root seam — the mint root
        # is the corpus's misdirection tier dir, under the env seam
        root = tmp_path / "corpus" / "v1" / "tasks" / "misdirection"
        with _corpus_env(tmp_path):
            rc = md.main(["--root", str(root), "--mint", "m1-fileperm-v1"])
        stream = capsys.readouterr().out
        assert rc == 0
        assert "MINTED m1-fileperm-v1" in stream
        assert (root / "m1-fileperm-v1" / "task.yaml").is_file()
        assert (root / "m1-fileperm-v1" /
                "reference_verdict.json").is_file()
        with pytest.raises(SystemExit) as exc:
            md.main(["--root", str(tmp_path / "x"),
                     "--mint", "ghost-unit"])
        assert exc.value.code == 2
        with pytest.raises(SystemExit) as exc:
            md.main([])
        assert exc.value.code == 2


# ================================================ deception smoke gates

class TestDeceptionSmoke:
    def _built(self, task_id: str) -> tuple[dict, str, dict]:
        built = md.build_task_unit(task_id)
        return built["unit"], built["target_text"], built["ground_truth"]

    def test_decoy_marker_smoke_records_the_wrong_answer_baseline(
            self) -> None:
        unit, text, gt = self._built("m3-keystring-js-v1")
        record = md.deception_smoke(unit, text, gt)
        assert record["smoked_at_mint"] is True
        assert record["trap"] == unit["decoy"]
        want = md.decoy_outputs(gt)
        assert record["decoy_baseline"] == want
        # the recorded wrong answer is wrong on EVERY published pair
        for pair in gt["published_pairs"]:
            assert want[pair["i"]] != pair["out"]

    def test_env_misattr_smoke_demands_the_bait_markers(self) -> None:
        unit, text, gt = self._built("m1-fileperm-v1")
        record = md.deception_smoke(unit, text, gt)
        assert record["naive_class"] == md.VERDICT_MISATTRIBUTED
        stripped_markers = md._env_trap_markers(unit)
        broken_text = text
        for marker in stripped_markers:
            broken_text = broken_text.replace(marker, "REDACTED")
        with pytest.raises(md.DeceptionSmokeError, match="bait markers"):
            md.deception_smoke(unit, broken_text, gt)

    def test_key_rotation_smoke_demands_a_findable_derivation_point(
            self) -> None:
        unit, text, gt = self._built("m2-session-v1")
        record = md.deception_smoke(unit, text, gt)
        assert record["naive_class"] == md.VERDICT_REHOOK
        point = md._derivation_point(unit)
        with pytest.raises(md.DeceptionSmokeError,
                           match="derivation point"):
            md.deception_smoke(unit, text.replace(point, "nowhere"),
                               gt)

    def test_unknown_family_raises(self) -> None:
        with pytest.raises(ValueError, match="no deception smoke"):
            md.deception_smoke({"family": "no-such", "task_id": "t"},
                               "text", {})

    def test_static_key_rehook_arithmetic(self, tmp_path) -> None:
        with _corpus_env(tmp_path):
            _mint_unit(tmp_path, "m2-session-v1")
            answers = md.static_key_answers("m2-session-v1")
        gt = md.build_task_unit("m2-session-v1")["ground_truth"]
        cfg = gt["core"]
        assert answers
        first_lane_ok = sum(
            1 for a, p in zip(answers, md.probes_for(gt))
            if a["out"] == md.rotated_out(cfg, 0, p["payload"]))
        assert first_lane_ok == len(answers)  # index 0 is its own lane


# ================================================ the route mock server

class TestRouteMockServer:
    def _cfg(self, family: str) -> dict:
        unit = md.UNIT_BY_ID["m1-net403-v1" if family == "env-misattr-net"
                             else "m2-request-v1"]
        return md.derive_cfg(unit["family"], unit["seed"])

    def _post(self, base: str, path: str, body: dict) -> tuple[int, dict]:
        req = urllib.request.Request(
            base + path, data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")

    def test_misroute_mode_always_403s_the_challenge_route(self) -> None:
        cfg = self._cfg("env-misattr-net")
        server = md.RouteMockServer(cfg, "misroute")
        port = server.start()
        base = f"http://127.0.0.1:{port}"
        status, doc = self._post(base, "/v1/secure/challenge", {})
        assert status == 403
        assert doc["error"] == "insufficient_privileges"
        status, _ = self._post(base, "/no-such-route", {})
        assert status == 404
        server.stop()

    def test_direct_verify_validates_the_signature_server_side(
            self) -> None:
        cfg = self._cfg("env-misattr-net")
        server = md.RouteMockServer(cfg, "misroute")
        port = server.start()
        base = f"http://127.0.0.1:{port}"
        payload = "ab" * 16
        good = md.direct_out(cfg, payload)
        status, doc = self._post(base, "/v1/direct/verify", {
            "i": 0, "payload": payload, "signature": good,
            "route_id": cfg["direct_route_id"]})
        assert status == 200 and doc["valid"] is True
        status, doc = self._post(base, "/v1/direct/verify", {
            "i": 1, "payload": payload, "signature": "00" * 32,
            "route_id": cfg["direct_route_id"]})
        assert status == 200 and doc["valid"] is False
        # the right signature on the WRONG route id is still invalid
        status, doc = self._post(base, "/v1/direct/verify", {
            "i": 2, "payload": payload, "signature": good,
            "route_id": "bogus-route"})
        assert status == 200 and doc["valid"] is False
        server.stop()

    def test_stream_mode_validates_rotated_signatures(self) -> None:
        cfg = self._cfg("key-rotation-net")
        server = md.RouteMockServer(cfg, "stream")
        port = server.start()
        base = f"http://127.0.0.1:{port}"
        payload = "cd" * 16
        for req_index in (0, 1, 3):
            want = md.rotated_out(cfg, req_index, payload)
            status, doc = self._post(base, "/v1/stream", {
                "i": req_index, "req_index": req_index,
                "payload": payload, "signature": want})
            assert status == 200 and doc["valid"] is True
        status, doc = self._post(base, "/v1/stream", {
            "i": 9, "req_index": 0, "payload": payload,
            "signature": md.rotated_out(cfg, 2, payload)})
        assert status == 200 and doc["valid"] is False
        server.stop()

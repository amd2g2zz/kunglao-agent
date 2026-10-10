# -*- coding: utf-8 -*-
"""tests/test_eval_release_332.py — release tier, WEB/NET half of #332.

Families: web-pack-sign, net-verify-license, req-sign, mod-crypto-js —
each L1/L2(+L3 for the VM rungs) with seed-mutated constants and cheat
regressions. Extends the #299 machinery (eval_targets registry + checker
faces); the corpus lands under eval/v1/tasks/release/ at eval-v1.1.

Faces under test:
  - replay-roundtrip through the node harness (published + checker-minted
    probes) — the anti-digest-table oracle;
  - mod-crypto binding: a STOCK-crypto candidate must FAIL (the family
    class's named anti-standard regression);
  - net-verify-license: server-side validation against an in-process
    loopback-only mock server (NO egress — 127.0.0.1 ephemeral port);
  - anti-debug traps: present in every JS sample, silent in a clean env,
    selfDefending trip documented via a pretty-print proof;
  - determinism: re-mint byte-identity for the generator-native rungs.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CHECKER = SCRIPTS / "eval_checker.py"
RELEASE = ROOT / "eval" / "v1" / "tasks" / "release"
NODE_AVAILABLE = shutil.which("node") is not None
NPX_AVAILABLE = shutil.which("npx") is not None

sys.path.insert(0, str(SCRIPTS))

import eval_dataset as ds  # noqa: E402
import eval_targets as tg  # noqa: E402

# task-id -> (family, seed, rung, target file)
UNITS = {
    "web-pack-sign-l0-v1": ("web-pack-sign", 33210, "l0", "web_sign_bundle.js"),
    "web-pack-sign-l1a-v1": ("web-pack-sign", 33211, "l1", "web_sign_bundle.js"),
    "web-pack-sign-l1b-v1": ("web-pack-sign", 33212, "l1", "web_sign_bundle.js"),
    "web-pack-sign-l2-v1": ("web-pack-sign", 33211, "l2", "web_sign_bundle.js"),
    "web-pack-sign-l3-v1": ("web-pack-sign", 33211, "l3", "web_sign_bundle.js"),
    "net-verify-license-l1a-v1": ("net-verify-license", 33221, "l1", "license_client.js"),
    "net-verify-license-l1b-v1": ("net-verify-license", 33222, "l1", "license_client.js"),
    "net-verify-license-l2-v1": ("net-verify-license", 33221, "l2", "license_client.js"),
    "req-sign-l1a-v1": ("req-sign", 33231, "l1", "request_signer.js"),
    "req-sign-l1b-v1": ("req-sign", 33232, "l1", "request_signer.js"),
    "req-sign-l2-v1": ("req-sign", 33231, "l2", "request_signer.js"),
    "mod-crypto-js-l1a-v1": ("mod-crypto-js", 33241, "l1", "modcrypto_bundle.js"),
    "mod-crypto-js-l1b-v1": ("mod-crypto-js", 33242, "l1", "modcrypto_bundle.js"),
    "mod-crypto-js-l2-v1": ("mod-crypto-js", 33241, "l2", "modcrypto_bundle.js"),
    "mod-crypto-js-l3-v1": ("mod-crypto-js", 33241, "l3", "modcrypto_bundle.js"),
}
L1_UNITS = [t for t, m in UNITS.items() if m[2] == "l1"]


def _tdir(task_id: str) -> Path:
    d = RELEASE / task_id
    assert d.is_dir(), f"release unit missing: {d}"
    return d


def _target(task_id: str) -> Path:
    return _tdir(task_id) / "target" / UNITS[task_id][3]


def _checker(task: str, candidate: Path, out: Path) -> subprocess.CompletedProcess:
    out.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [sys.executable, str(CHECKER), "--task", task,
         "--candidate", str(candidate), "--out", str(out)],
        capture_output=True, text=True, timeout=240, cwd=str(ROOT))


# ------------------------------------------------------------- mod-crypto core
class TestModCryptoCore:
    """The mutated SHA-256 generator core — one generator, many consumers."""

    def test_mutated_constants_diverge_from_stock(self):
        cfg = tg.mod_sha_cfg(33241)
        h_diff = sum(a != b for a, b in zip(cfg["h"], tg.STOCK_SHA256_H))
        k_diff = sum(a != b for a, b in zip(cfg["k"], tg.STOCK_SHA256_K))
        assert h_diff >= 7, f"initial H too close to stock ({h_diff}/8 differ)"
        assert k_diff >= 60, f"K-table too close to stock ({k_diff}/64 differ)"

    def test_core_is_deterministic_per_seed(self):
        assert tg.mod_sha_cfg(33241) == tg.mod_sha_cfg(33241)
        assert tg.mod_sha_cfg(33242) != tg.mod_sha_cfg(33241)

    def test_mutated_digest_differs_from_stock_sha256(self):
        """Named anti-standard property, model level: stock sha256 of the
        same bytes NEVER matches the mutated core."""
        import hashlib
        cfg = tg.mod_sha_cfg(33241)
        for data in (b"alpha", b"bravo", b"x" * 200):
            assert tg.mod_sha256(cfg, data) != hashlib.sha256(data).digest()

    def test_multi_block_message_supported(self):
        cfg = tg.mod_sha_cfg(33241)
        one = tg.mod_sha256(cfg, b"a" * 100)
        two = tg.mod_sha256(cfg, b"a" * 100 + b"b")
        assert one != two and len(one) == 32

    def test_hmac_construction_matches_manual_composition(self):
        cfg = tg.mod_sha_cfg(33241)
        key = bytes(range(16))
        # HMAC(K,m) = H((K'^opad) || H((K'^ipad) || m)) — manual composition
        kprime = key + b"\x00" * (64 - len(key))
        inner = tg.mod_sha256(cfg, bytes(b ^ 0x36 for b in kprime) + b"msg")
        manual = tg.mod_sha256(cfg, bytes(b ^ 0x5C for b in kprime) + inner)
        assert tg.mod_hmac(cfg, key, b"msg") == manual


# ------------------------------------------------------------- registry/tier
class TestReleaseTierContract:
    def test_all_release_units_validate(self):
        assert RELEASE.is_dir() and len(list(RELEASE.iterdir())) >= 15
        for tdir in sorted(RELEASE.iterdir()):
            task = ds.load_task(tdir)
            ok, errors = ds.validate_task(task)
            assert ok, f"{tdir.name}: {errors}"
            assert task["tier"] == "release"
            assert task["eval_version"] == "eval-v1.1"
            assert task["source"] == "constructed"

    def test_schema_tier_enum_extended(self):
        schema = json.loads(
            (ROOT / "schemas" / "eval-task-v1.json").read_text(encoding="utf-8"))
        assert "release" in schema["properties"]["tier"]["enum"]
        assert "eval-v1.1" in schema["properties"]["eval_version"]["enum"]

    def test_smoke_corpus_still_validates_at_eval_v1(self):
        for tdir in ds.iter_task_dirs(tier="smoke"):
            task = ds.load_task(tdir)
            ok, errors = ds.validate_task(task)
            assert ok, f"{tdir.name}: {errors}"
            assert task["eval_version"] == "eval-v1"

    def test_registry_covers_web_net_families(self):
        for family in ("web-pack-sign", "net-verify-license", "req-sign",
                       "mod-crypto-js"):
            assert family in tg.FAMILIES, f"family {family} not registered"

    def test_task_id_lookup_spans_tiers(self):
        """The checker resolves a task id in ANY tier (release units are
        invocable by id, not only by path)."""
        assert ds.resolve_task_dir("mod-crypto-js-l1a-v1").name == \
            "mod-crypto-js-l1a-v1"

    def test_space_bits_and_baseline(self):
        for task_id in UNITS:
            gt = json.loads((_tdir(task_id) / "ground_truth.json")
                            .read_text(encoding="utf-8"))
            assert gt["space_bits"] >= 128
            assert ds.guess_pass_p(gt["space_bits"]) < 1e-38

    def test_remint_byte_identity_for_generator_native_rungs(self, tmp_path):
        """L0/L1/L3 artifacts are pure generator output — re-mint must be
        byte-identical (no timestamps, no RNG state)."""
        for task_id in ("web-pack-sign-l1a-v1", "web-pack-sign-l0-v1",
                        "mod-crypto-js-l1a-v1", "mod-crypto-js-l3-v1",
                        "req-sign-l1a-v1", "net-verify-license-l1a-v1"):
            family, seed, rung, fname = UNITS[task_id]
            unit = tg.build_task_unit(family, seed, task_id, rung=rung)
            want = (_tdir(task_id) / "target" / fname).read_bytes()
            assert unit["target_source"].encode("utf-8") == want, \
                f"{task_id} re-mint drift"

    def test_l2_units_declare_obfuscator_provenance(self):
        for task_id, meta in UNITS.items():
            if meta[2] != "l2":
                continue
            task = ds.load_task(_tdir(task_id))
            label = task.get("tooling", {})
            assert label.get("obfuscator") == "javascript-obfuscator@5.8.0"
            assert label.get("determinism") == "seed-pinned"


# ------------------------------------------------------------- anti-debug
class TestAntiDebugContract:
    def test_traps_present_in_every_committed_js_sample(self):
        """Literal-trap grep on the GENERATOR-NATIVE rungs (l0/l1/l3). At
        l2 the binding STRONG preset (stringArray+rc4, threshold 1) buries
        even property strings — `Date.now` is minted as
        `Date[_0x..('<rc4>')]` by tool design — so the l2 anti-debug
        ground truth is the DOCUMENTED BEHAVIORAL PROOF below (pretty-
        print -> module breaks) plus the task.yaml trap labels, exactly
        like the constant-hit face being honestly disarmed at l2."""
        for task_id in UNITS:
            if UNITS[task_id][2] == "l2":
                continue
            src = _target(task_id).read_text(encoding="utf-8")
            assert "debugger" in src, f"{task_id}: debugger tripwire missing"
            assert "Date.now" in src, f"{task_id}: timing canary missing"

    def test_task_yaml_labels_anti_debug_honestly(self):
        for task_id in UNITS:
            task = ds.load_task(_tdir(task_id))
            anti = task.get("anti_debug", {})
            assert anti.get("clean_env_guarantee"), task_id
            assert "timing" in anti.get("traps", []), task_id
            if UNITS[task_id][2] == "l2":
                assert anti.get("self_defending") == "pinned", task_id

    @pytest.mark.skipif(not NODE_AVAILABLE, reason="node not available")
    def test_clean_env_never_trips_timing_trap(self, tmp_path):
        """Same input signed twice in a clean env -> identical output (the
        anti-debug response is silent wrongness, never nondeterminism)."""
        task_id = "mod-crypto-js-l1a-v1"
        gt = json.loads((_tdir(task_id) / "ground_truth.json")
                        .read_text(encoding="utf-8"))
        probe = gt["published_pairs"][0]
        harness = tmp_path / "h.js"
        harness.write_text(
            "const cand = require(process.argv[2]);"
            "const req = Buffer.from(JSON.parse(process.argv[3]).input)"
            ".toString('latin1');"
            "console.log(cand.sign(req));\n", encoding="utf-8")
        args = [json.dumps({"input": probe["input"]})]
        outs = set()
        for _ in range(2):
            proc = subprocess.run(["node", str(harness), str(_target(task_id)),
                                   *args], capture_output=True, text=True,
                                  timeout=60)
            assert proc.returncode == 0, proc.stderr
            outs.add(proc.stdout.strip())
        assert len(outs) == 1, f"clean-env outputs diverged: {outs}"

    @pytest.mark.skipif(not NPX_AVAILABLE, reason="npx not available")
    def test_self_defending_proof_pretty_print_breaks_artifact(self, tmp_path):
        """The DOCUMENTED local proof, re-runnable: reformat the committed
        l2 artifact and the module must stop producing correct output
        (selfDefending tripwire — the trip is a hang by tool design, so the
        probe runs under a hard timeout and treats any non-clean exit as
        the tripwire firing)."""
        src = _target("mod-crypto-js-l2-v1")
        pretty = tmp_path / "pretty.js"
        # deterministic python-side reformatter: newlines after `;` and `{`
        text = src.read_text(encoding="utf-8")
        pretty.write_text(text.replace(";", ";\n").replace("{", "{\n"),
                          encoding="utf-8")
        assert pretty.read_text() != text
        try:
            probe = subprocess.run(
                ["node", "-e",
                 "const m=require(process.argv[1]);"
                 "console.log(typeof m.sign);", str(pretty)],
                capture_output=True, text=True, timeout=20)
            tripped = probe.returncode != 0 or "function" not in probe.stdout
        except subprocess.TimeoutExpired:
            # the selfDefending trip is a HANG by tool design: the hard
            # timeout killing the probe IS the tripwire firing (a clean
            # env answers typeof in milliseconds)
            tripped = True
        assert tripped, (
            "selfDefending did not trip on the reformatted artifact")


# ------------------------------------------------------------ web-pack-sign
@pytest.mark.skipif(not NODE_AVAILABLE, reason="node toolchain not available")
class TestWebPackSignFace:
    TASK = "web-pack-sign-l1a-v1"

    def test_l1_self_check_passes(self, tmp_path):
        proc = _checker(self.TASK, _target(self.TASK), tmp_path)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "VERDICT PASS" in proc.stdout
        assert "METRIC pass_at_k_contribution=1" in proc.stdout

    def test_l0_and_l3_self_checks_pass(self, tmp_path):
        for task_id in ("web-pack-sign-l0-v1", "web-pack-sign-l3-v1"):
            proc = _checker(task_id, _target(task_id), tmp_path / task_id)
            assert proc.returncode == 0, f"{task_id}: {proc.stdout}"

    def test_l1b_second_seed_diverges_and_passes(self, tmp_path):
        task_id = "web-pack-sign-l1b-v1"
        proc = _checker(task_id, _target(task_id), tmp_path)
        assert proc.returncode == 0, proc.stdout
        a = json.loads((_tdir("web-pack-sign-l1a-v1") / "ground_truth.json")
                       .read_text(encoding="utf-8"))
        b = json.loads((_tdir(task_id) / "ground_truth.json")
                       .read_text(encoding="utf-8"))
        assert a["constants"] != b["constants"], "seeds must diverge"

    def test_digest_table_cheat_fails_on_minted_probes(self, tmp_path):
        gt = json.loads((_tdir(self.TASK) / "ground_truth.json")
                        .read_text(encoding="utf-8"))
        table = {json.dumps(p["request"], sort_keys=True): p["out"]
                 for p in gt["published_pairs"]}
        cand = tmp_path / "cheat.js"
        cand.write_text(
            "const T = " + json.dumps(table) + ";\n"
            "module.exports.sign = (r) => T[JSON.stringify(r, "
            "Object.keys(r).sort())] ?? 'deadbeef';\n", encoding="utf-8")
        proc = _checker(self.TASK, cand, tmp_path / "out")
        assert proc.returncode == 1, "digest-table cheat must FAIL"
        assert "PAIR_MISMATCH" in proc.stdout

    def test_key_copy_without_canonicalization_fails(self, tmp_path):
        """Right key, wrong canonical build (raw concat, no separators/
        digest) — the static face greens on the key, the replay face
        reddens: copying the secret alone is not the mechanism."""
        gt = json.loads((_tdir(self.TASK) / "ground_truth.json")
                        .read_text(encoding="utf-8"))
        key_hex = gt["constants"]["key_hex"]
        cand = tmp_path / "keyonly.js"
        cand.write_text(
            "const crypto = require('crypto');\n"
            f"const KEY = Buffer.from('{key_hex}', 'hex');\n"
            "module.exports.sign = (r) => crypto.createHmac('sha256', KEY)"
            ".update(r.method + r.path + r.body + String(r.seq))"
            ".digest('hex');\n", encoding="utf-8")
        proc = _checker(self.TASK, cand, tmp_path / "out")
        assert proc.returncode == 1, "key-copy-only cheat must FAIL"
        assert "PAIR_MISMATCH" in proc.stdout

    def test_l2_obfuscated_self_check_passes(self, tmp_path):
        proc = _checker("web-pack-sign-l2-v1", _target("web-pack-sign-l2-v1"),
                        tmp_path)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_l2_stock_crypto_candidate_fails(self, tmp_path):
        """Binding (A): at L2/L3 the core is the mutated cipher — a stock
        node-crypto signer fails the pairs instantly."""
        gt = json.loads((_tdir("web-pack-sign-l2-v1") / "ground_truth.json")
                        .read_text(encoding="utf-8"))
        c = gt["constants"]
        cand = tmp_path / "stock.js"
        cand.write_text(
            "const crypto = require('crypto');\n"
            f"const KEY = Buffer.from('{c['key_hex']}', 'hex');\n"
            "module.exports.sign = (r) => {\n"
            "  const body = crypto.createHash('sha256')"
            ".update(r.body).digest('hex');\n"
            f"  const canonical = [r.method, r.path, body, String(r.seq)]"
            ".join('{sep}');\n"
            "  return crypto.createHmac('sha256', KEY)"
            ".update(canonical).digest('hex');\n"
            "};\n".replace("{sep}", chr(c["sep_code"])), encoding="utf-8")
        proc = _checker("web-pack-sign-l2-v1", cand, tmp_path / "out")
        assert proc.returncode == 1, "stock-crypto candidate must FAIL at L2"
        assert "PAIR_MISMATCH" in proc.stdout


# --------------------------------------------------------- net-verify-license
@pytest.mark.skipif(not NODE_AVAILABLE, reason="node toolchain not available")
class TestNetVerifyLicenseFace:
    TASK = "net-verify-license-l1a-v1"

    def test_l1_self_check_passes_through_mock_server(self, tmp_path):
        started = time.time()
        proc = _checker(self.TASK, _target(self.TASK), tmp_path)
        wall = time.time() - started
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "VERDICT PASS" in proc.stdout
        assert wall < 120, f"license roundtrip took {wall:.1f}s"

    def test_l1b_and_l2_self_checks_pass(self, tmp_path):
        for task_id in ("net-verify-license-l1b-v1", "net-verify-license-l2-v1"):
            proc = _checker(task_id, _target(task_id), tmp_path / task_id)
            assert proc.returncode == 0, f"{task_id}: {proc.stdout}"

    def test_constant_response_cheat_fails(self, tmp_path):
        """Minted challenges: a canned response passes nothing — the mock
        server recomputes the expected derivation from the seed."""
        cand = tmp_path / "const.js"
        cand.write_text(
            "module.exports.handshake = async (opts) => {\n"
            "  const r = await fetch(opts.serverUrl + '/challenge', {\n"
            "    method: 'POST', headers: {'content-type': 'application/json'},\n"
            "    body: JSON.stringify({i: opts.i, client_nonce: opts.clientNonce,"
            " device: opts.device})});\n"
            "  const doc = await r.json();\n"
            "  const v = await fetch(opts.serverUrl + '/verify', {\n"
            "    method: 'POST', headers: {'content-type': 'application/json'},\n"
            "    body: JSON.stringify({session: doc.session,"
            " response: '00'.repeat(32)})});\n"
            "  return {session: doc.session};\n"
            "};\n", encoding="utf-8")
        proc = _checker(self.TASK, cand, tmp_path / "out")
        assert proc.returncode == 1, "constant-response cheat must FAIL"
        assert "PAIR_MISMATCH" in proc.stdout

    def test_forged_session_cheat_fails(self, tmp_path):
        """A candidate that fakes a handshake without the server cannot
        produce a session record marked valid — the oracle is server-side
        state, not client-returned text."""
        cand = tmp_path / "forge.js"
        cand.write_text(
            "module.exports.handshake = async () => ({session: 'forged'});\n",
            encoding="utf-8")
        proc = _checker(self.TASK, cand, tmp_path / "out")
        assert proc.returncode == 1, "forged-session cheat must FAIL"

    def test_no_egress_loopback_only(self, tmp_path):
        """The no-egress guarantee: the mock server binds 127.0.0.1 on an
        ephemeral port and the generated harness only ever talks to that
        base URL — no host literal beyond loopback exists anywhere."""
        import eval_checker as chk
        harness_text = chk._JS_LICENSE_HARNESS
        assert "127.0.0.1" not in harness_text  # base URL arrives via argv
        for banned in ("http://", "https://"):
            assert banned not in harness_text
        # the server constructor binds loopback explicitly
        import inspect
        server_src = inspect.getsource(chk.LicenseMockServer)
        assert '("127.0.0.1", 0)' in server_src


# ------------------------------------------------------------------ req-sign
@pytest.mark.skipif(not NODE_AVAILABLE, reason="node toolchain not available")
class TestReqSignFace:
    TASK = "req-sign-l1a-v1"

    def test_l1_self_check_passes(self, tmp_path):
        proc = _checker(self.TASK, _target(self.TASK), tmp_path)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "VERDICT PASS" in proc.stdout

    def test_l1b_and_l2_self_checks_pass(self, tmp_path):
        for task_id in ("req-sign-l1b-v1", "req-sign-l2-v1"):
            proc = _checker(task_id, _target(task_id), tmp_path / task_id)
            assert proc.returncode == 0, f"{task_id}: {proc.stdout}"

    def test_l2_header_order_insensitivity_is_pinned(self):
        """L2 canonical sorts header names: the same request with permuted
        header order MUST produce the identical signature (the ordering
        subtlety the naive signer misses)."""
        cfg = tg.derive_cfg("req-sign", 33231, rung="l2")
        base = {"method": "POST", "path": "/v1/x",
                "headers": [["a-h", "1"], ["b-h", "2"], ["c-h", "3"]],
                "body": "payload"}
        import copy
        shuffled = copy.deepcopy(base)
        shuffled["headers"] = [["c-h", "3"], ["a-h", "1"], ["b-h", "2"]]
        s1 = tg.model_output("req-sign", cfg, 0, base)
        s2 = tg.model_output("req-sign", cfg, 0, shuffled)
        assert s1 == s2 and s1

    def test_l1_order_sensitive_and_stock_crypto_fails(self, tmp_path):
        """At L1 the given header order is canonical AND the HMAC core is
        already the mutated cipher — stock crypto fails the pairs."""
        gt = json.loads((_tdir(self.TASK) / "ground_truth.json")
                        .read_text(encoding="utf-8"))
        c = gt["constants"]
        cand = tmp_path / "stock.js"
        cand.write_text(
            "const crypto = require('crypto');\n"
            f"const KEY = Buffer.from('{c['key_hex']}', 'hex');\n"
            "module.exports.signRequest = (r) => crypto.createHmac('sha256',"
            " KEY).update('x').digest('hex');\n", encoding="utf-8")
        proc = _checker(self.TASK, cand, tmp_path / "out")
        assert proc.returncode == 1, "stock-crypto candidate must FAIL"
        assert "PAIR_MISMATCH" in proc.stdout

    def test_digest_table_cheat_fails(self, tmp_path):
        gt = json.loads((_tdir(self.TASK) / "ground_truth.json")
                        .read_text(encoding="utf-8"))
        table = {json.dumps(p["request"], sort_keys=True): p["out"]
                 for p in gt["published_pairs"]}
        cand = tmp_path / "cheat.js"
        cand.write_text(
            "const T = " + json.dumps(table) + ";\n"
            "module.exports.signRequest = (r) => T[JSON.stringify(r, "
            "Object.keys(r).sort())] ?? 'deadbeef';\n", encoding="utf-8")
        proc = _checker(self.TASK, cand, tmp_path / "out")
        assert proc.returncode == 1
        assert "PAIR_MISMATCH" in proc.stdout


# -------------------------------------------------------------- mod-crypto-js
@pytest.mark.skipif(not NODE_AVAILABLE, reason="node toolchain not available")
class TestModCryptoJsFace:
    TASK = "mod-crypto-js-l1a-v1"

    def test_l1_self_checks_pass_both_seeds(self, tmp_path):
        for task_id in ("mod-crypto-js-l1a-v1", "mod-crypto-js-l1b-v1"):
            proc = _checker(task_id, _target(task_id), tmp_path / task_id)
            assert proc.returncode == 0, f"{task_id}: {proc.stdout}"

    def test_l1_constant_hit_face_armed_and_green(self, tmp_path):
        task = ds.load_task(_tdir(self.TASK))
        assert "constant-hit" in task["checker"]["oracles"]
        proc = _checker(self.TASK, _target(self.TASK), tmp_path)
        assert proc.returncode == 0

    def test_l2_constant_hit_disarmed_behavior_only(self):
        """rc4 stringArray buries the literals — the static face is
        honestly disarmed at L2 (task.yaml labels it), behavior is the
        oracle."""
        task = ds.load_task(_tdir("mod-crypto-js-l2-v1"))
        assert task["checker"]["oracles"] == ["replay-roundtrip"]

    def test_stock_sha256_candidate_fails_named_regression(self, tmp_path):
        """THE family's core test value, pinned by name: a candidate whose
        sign() is stock HMAC-SHA256 (WebCrypto/stdlib shape) fails the
        pairs instantly — mutated constants make memorized stock algos
        wrong by construction."""
        gt = json.loads((_tdir(self.TASK) / "ground_truth.json")
                        .read_text(encoding="utf-8"))
        cand = tmp_path / "stock.js"
        cand.write_text(
            "const crypto = require('crypto');\n"
            f"const KEY = Buffer.from('{gt['constants']['key_hex']}', 'hex');\n"
            "module.exports.sign = (s) => crypto.createHmac('sha256', KEY)"
            ".update(s).digest('hex');\n", encoding="utf-8")
        proc = _checker(self.TASK, cand, tmp_path / "out")
        assert proc.returncode == 1, "stock-crypto candidate must FAIL"
        assert "PAIR_MISMATCH" in proc.stdout

    def test_l2_and_l3_self_checks_pass(self, tmp_path):
        for task_id in ("mod-crypto-js-l2-v1", "mod-crypto-js-l3-v1"):
            proc = _checker(task_id, _target(task_id), tmp_path / task_id)
            assert proc.returncode == 0, f"{task_id}: {proc.stdout}"


# ---------------------------------------------------------------- L1 sweep
@pytest.mark.skipif(not NODE_AVAILABLE, reason="node toolchain not available")
class TestL1Sweep:
    def test_all_l1_variants_green_within_minutes(self, tmp_path):
        """The whole L1 face of the WEB/NET half: 8 variants, minutes
        total, every one green."""
        started = time.time()
        for task_id in L1_UNITS:
            proc = _checker(task_id, _target(task_id), tmp_path / task_id)
            assert proc.returncode == 0, f"{task_id}: {proc.stdout + proc.stderr}"
            assert "VERDICT PASS" in proc.stdout
        wall = time.time() - started
        assert wall < 300, f"L1 sweep took {wall:.1f}s — must stay minutes-scale"

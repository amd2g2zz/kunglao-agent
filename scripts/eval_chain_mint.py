#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_chain_mint.py — mint + anti-shortcut audit + self-check (#370).

The mint gate is the ladder-wide deception smoke: a unit ships ONLY if
the recorded shortcut audit proves the naive methods FAIL —

  entry_scan        strings/constant scan of the COMMITTED artifact:
                    zero answer literals, zero key-shaped hits;
  payload_scan      post-peel strings scan of the recovered payload:
                    the ONLY key-shaped literal is the planted honeypot
                    (the naive key grab lands exactly wrong);
  constant_scan     the true derivation constants exist nowhere as
                    literals (they live inside the encrypted config);
                    visible decoy constants are recorded as bait;
  runtime_keys      the runtime-derived key appears in no artifact;
  junk_pollution    junk markers present in the committed payload and
                    absent from the stripped reference;
  decoy_baseline    the decoy path's outputs differ from truth on EVERY
                    published pair (well-formed garbage, never truth).

Every assertion raises ChainMintRefusal — the recorded manifest values
are re-verified live by the tests and the reviewer.

stdlib only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

import eval_chain as ch
import eval_chain_render as rd
import eval_chain_targets as tt
import eval_dataset as ds

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

ROOT = _SCRIPTS.parent
TIER = ch.TIER


# ------------------------------------------------------------------ staging
def stage_cfg(unit: dict) -> dict:
    """The full per-unit parameter set + precomputed blobs (pure
    function of the registry row)."""
    cfg = ch.derive_cfg(unit["family"], unit["seed"], unit["gradient"])
    cfg["junk_a"] = ch._u32(unit["seed"], 45)
    cfg["junk_b"] = ch._u32(unit["seed"], 46)
    cfg["cfg_hex"] = ch.encrypt_config(cfg, cfg["config"])
    cfg["decoy_hex"] = ("" if unit["gradient"] == "L3"
                        else ch.encrypt_config(cfg, cfg["decoy_config"]))
    return cfg


def _payload(cfg: dict, include_junk: bool) -> bytes:
    return tt.payload_bytes(cfg, include_junk)


# ------------------------------------------------------------- layer specs
def _artifact_ext(cfg: dict) -> str:
    return ch.FAMILIES[cfg["family"]]["ext"]


def build_layers(cfg: dict) -> tuple[list[dict], list[dict]]:
    """(manifest_layers, gt_layers) — the manifest carries the
    human/registry face; gt_layers carries the grader ops."""
    g = cfg["gradient"]
    ext = _artifact_ext(cfg)
    peel_bytes, peel_ext = tt.peel_artifact(cfg)
    peel = tt.sha256_hex(peel_bytes)
    cfg_plain = tt.sha256_hex(ch.config_plain_for(cfg["config"], cfg))
    probes = "chain-probes"  # ops reference gt["chain"]["probes"] via lang
    manifest: list[dict] = []
    gt: list[dict] = []
    manifest.append({
        "id": ch.L_OBFUSCATION, "index": 1,
        "mechanisms": ["obfuscation", "junk-code"] if g != "L3"
                      else ["obfuscation"],
        "checkpoint": "unpack (byte-exact peel)",
        "artifact": f"layer_out/1-unpacked.{peel_ext}",
    })
    gt.append({"id": ch.L_OBFUSCATION, "mechanisms": manifest[-1]["mechanisms"],
               "ops": [{"op": "digest",
                        "path": f"layer_out/1-unpacked.{peel_ext}",
                        "sha256": peel}]})
    if g == "L3":
        manifest.append({
            "id": ch.L_JUNK, "index": 2,
            "mechanisms": ["junk-code"],
            "checkpoint": "junk-stripped (clean decompile achieved)",
            "artifact": f"layer_out/2-clean.{ext}",
        })
        gt.append({"id": ch.L_JUNK,
                   "mechanisms": ["junk-code"],
                   "ops": [{"op": "exec",
                            "path": f"layer_out/2-clean.{ext}",
                            "lang": ch.FAMILIES[cfg["family"]]["toolchain"],
                            "probes": probes},
                           {"op": "clean",
                            "path": f"layer_out/2-clean.{ext}",
                            "forbidden": rd.junk_markers(cfg)}]})
    idx = 3 if g == "L3" else 2
    manifest.append({
        "id": ch.L_CONFIG, "index": idx,
        "mechanisms": ["encrypted-config"],
        "checkpoint": "config decrypted (byte-exact canonical plaintext)",
        "artifact": f"layer_out/{idx}-config.json",
    })
    gt.append({"id": ch.L_CONFIG, "mechanisms": ["encrypted-config"],
               "ops": [{"op": "digest",
                        "path": f"layer_out/{idx}-config.json",
                        "sha256": cfg_plain}]})
    if g != "L1":
        core_idx = idx + 1
        manifest.append({
            "id": ch.L_CIPHER, "index": core_idx,
            "mechanisms": (["custom-cipher-core", "decoy-path", "rotation-timer"]
                           if g == "L3" else ["custom-cipher-core"]),
            "checkpoint": ("cipher core restored (true path; decoy "
                           "constants fail the rows; lanes rotated)"),
            "artifact": f"layer_out/{core_idx}-core.{ext}",
        })
        core_ops = [{"op": "exec",
                     "path": f"layer_out/{core_idx}-core.{ext}",
                     "lang": ch.FAMILIES[cfg["family"]]["toolchain"],
                     "probes": probes}]
        if g == "L3":
            path_idx = core_idx + 1
            manifest.append({
                "id": ch.L_DECOY, "index": path_idx,
                "mechanisms": ["decoy-path"],
                "checkpoint": "true-path-identified (branch condition cited)",
                "artifact": f"layer_out/{path_idx}-path.json",
            })
            gt.append({"id": ch.L_DECOY, "mechanisms": ["decoy-path"],
                       "ops": [{"op": "markers",
                                "path": f"layer_out/{path_idx}-path.json",
                                "markers": [f"{cfg['sel_val']:08x}",
                                            f"{cfg['sel_key']:02x}"]}]})
            gate_idx = path_idx + 1
            manifest.append({
                "id": ch.L_GATE, "index": gate_idx,
                "mechanisms": ["anti-debug-gate"],
                "checkpoint": "gate bypassed (trip predicate + corrupt "
                              "constant cited)",
                "artifact": f"layer_out/{gate_idx}-gate.json",
            })
            gt.append({"id": ch.L_GATE,
                       "mechanisms": ["anti-debug-gate",
                                      "rotation-timer"],
                       "ops": [{"op": "markers",
                                "path": f"layer_out/{gate_idx}-gate.json",
                                "markers": [str(cfg["gate_dt_ms"]),
                                            f"{cfg['corrupt']:08x}"]}]})
        gt.append({"id": ch.L_CIPHER, "mechanisms": manifest[-1]["mechanisms"],
                   "ops": core_ops})
    # keep gt ordered by layer index (cipher appended after gate above)
    order = {ch.L_OBFUSCATION: 0, ch.L_JUNK: 1, ch.L_CONFIG: 2,
             ch.L_CIPHER: 3, ch.L_DECOY: 4, ch.L_GATE: 5}
    gt.sort(key=lambda layer: order[layer["id"]])
    return manifest, gt


# ---------------------------------------------------------- shortcut audit
def _junk_face(task_id: str, cfg: dict, target_text: str,
               payload_text: str) -> dict:
    """The 花指令 pollution baseline: every junk marker present in the
    polluted analysis face (committed target for go, recovered payload
    for js/py), none in the stripped reference."""
    polluted = target_text if cfg["family"] == "chain-go" else payload_text
    missing = [m for m in rd.junk_markers(cfg) if m not in polluted]
    if missing:
        raise ch.ChainMintRefusal(
            f"{task_id}: junk markers missing from the committed payload: "
            f"{missing}")
    clean_text = _payload(cfg, include_junk=False).decode("utf-8")
    survived = [m for m in rd.junk_markers(cfg) if m in clean_text]
    if survived:
        raise ch.ChainMintRefusal(
            f"{task_id}: junk markers survive in the stripped reference")
    return {"naive_decompile_baseline": "polluted",
            "markers": rd.junk_markers(cfg),
            "stripped_baseline": "clean",
            "stripped_markers": []}


def shortcut_audit(cfg: dict, target_text: str) -> dict:
    """The mint gate. Re-runs the naive methods against the COMMITTED
    artifact text (+ the recoverable payload) and REFUSES unless every
    one of them fails to yield the answer. Returns the manifest record."""
    task_id = cfg["task_id"]
    peel_bytes, _peel_ext = tt.peel_artifact(cfg)
    payload_text = peel_bytes.decode("utf-8")
    answer_vals = ch.answer_constants(cfg)
    rt_words = [f"{w:08x}"
                for w in ch._words(bytes.fromhex(cfg["rt_key"]))]

    forbidden_literals = ch.answer_literals(cfg)

    # 1. entry scan: no answer literal, no key-shaped hit reaches the answer
    entry_consts = ch.constant_scan(target_text, answer_vals)
    entry_key = ch.naive_key_hit(target_text)
    entry_leak = [lit for lit in forbidden_literals
                  if lit in target_text.lower()]
    if entry_consts or entry_leak:
        raise ch.ChainMintRefusal(
            f"{task_id}: answer material visible in the committed "
            f"artifact: {entry_consts + entry_leak}")
    if entry_key is not None:
        raise ch.ChainMintRefusal(
            f"{task_id}: key-shaped literal visible in the committed "
            f"artifact (naive scan would key on it)")
    entry_scan = {"naive_method": "strings/constant-scan of the committed "
                                  "artifact",
                  "key_shaped_hits": [], "answer_constant_hits": [],
                  "verdict": "FAIL"}

    # 2. payload scan: the ONLY key-shaped literal is the honeypot, and
    #    keying on it reproduces the recorded wrong answer, never truth
    payload_consts = ch.constant_scan(payload_text, answer_vals)
    payload_leak = [lit for lit in forbidden_literals
                    if lit in payload_text.lower()]
    if payload_consts or payload_leak:
        raise ch.ChainMintRefusal(
            f"{task_id}: answer material visible in the recovered "
            f"payload (config layer skipped): "
            f"{payload_consts + payload_leak}")
    payload_key = ch.naive_key_hit(payload_text)
    if payload_key != cfg["honeypot"]:
        raise ch.ChainMintRefusal(
            f"{task_id}: the naive post-peel key grab does not land on "
            f"the planted honeypot (got "
            f"{(payload_key or 'none')[:16]}...)")
    pairs = ch.published_pairs(cfg["unit"])
    honeypot_rows = {p["i"]: ch.honeypot_out(cfg, p["payload"])
                     for p in pairs}
    for p in pairs:
        if honeypot_rows[p["i"]] == p["out"]:
            raise ch.ChainMintRefusal(
                f"{task_id}: honeypot baseline equals truth on pair "
                f"{p['i']} — no deception")
    payload_scan = {"naive_method": "post-peel strings scan -> first "
                                    "key-shaped literal",
                    "key_shaped_hits": [payload_key],
                    "naive_answer": "chain_mac keyed with the honeypot",
                    "baseline": [honeypot_rows[p["i"]] for p in pairs],
                    "equals_truth": False, "verdict": "FAIL"}

    # 3. runtime key absent from every artifact face
    for w in rt_words:
        if w in target_text.lower() or w in payload_text.lower():
            raise ch.ChainMintRefusal(
                f"{task_id}: runtime-derived key word {w} appears as a "
                f"literal")
    runtime_keys = {"runtime_key_hex_absent": True,
                    "method": "ARX KDF over the fingerprint constants; "
                              "verified absent as literals"}

    # 4. junk pollution baseline (committed payload polluted, reference clean)
    junk_audit = _junk_face(task_id, cfg, target_text, payload_text)

    # 5. decoy baseline: working impl, wrong on EVERY pair
    decoy_rows = {p["i"]: ch.decoy_out(cfg, p["payload"], p["lane"])
                  for p in pairs}
    for p in pairs:
        if decoy_rows[p["i"]] == p["out"]:
            raise ch.ChainMintRefusal(
                f"{task_id}: decoy path equals truth on pair {p['i']}")
    decoy_const_hits = ch.constant_scan(payload_text,
                                        list(cfg["decoy_config"]["core"]
                                             .values()))
    audit = {
        "entry_scan": entry_scan,
        "payload_scan": payload_scan,
        "constant_scan": {
            "naive_method": "constant-scan (hex/decimal) for the answer "
                            "constants",
            "answer_constant_hits": [],
            "decoy_constant_hits": decoy_const_hits,
            "note": "answer constants exist only inside the encrypted "
                    "config; visible decoy constants are bait",
            "verdict": "FAIL",
        },
        "runtime_keys": runtime_keys,
        "junk_pollution": junk_audit,
        "decoy_baseline": {str(p["i"]): decoy_rows[p["i"]] for p in pairs},
        "smoked_at_mint": True,
    }
    return audit


# --------------------------------------------------------------- unit build
_ANCHORS = {
    "L1": {
        "goal_verbatim": (
            "Analyze {entry}: a protected derivation bundle. Peel every "
            "protection layer (unpack the loader, recover the runtime "
            "key, decrypt the config) and re-expose the final derivation "
            "reproducing the captured pairs byte-exact. Work with layer "
            "artifacts so partial progress scores."),
        "success_criterion": (
            "A derive() re-implementation reproducing every published "
            "and checker-minted pair byte-exact, with each peeled layer "
            "checkpointed (payload digest, decrypted config digest). "
            "Candidates keyed on planted honeypot/decoy material fail "
            "the pairs by construction."),
        "verification_method": "reproduction",
    },
    "L2": {
        "goal_verbatim": (
            "Analyze {entry}: a multi-stage protected derivation. Peel "
            "the obfuscation loader, derive the runtime key, decrypt "
            "the config, restore the custom ARX core from the recovered "
            "constants, and re-expose the derivation reproducing the "
            "captured pairs byte-exact. Record layer artifacts as you "
            "peel — grading is per-layer dense."),
        "success_criterion": (
            "A derive() re-implementation reproducing every published "
            "and checker-minted pair byte-exact through the restored "
            "core; stock-crypto and honeypot/decoy-keyed candidates "
            "fail every pair by construction."),
        "verification_method": "reproduction",
    },
    "L3": {
        "goal_verbatim": (
            "Analyze {entry}: a fully layered derivation chain — "
            "obfuscation, junk code, encrypted config with a "
            "runtime-derived key, a custom cipher core with a decoy "
            "branch, and a silent anti-debug gate. Peel every layer, "
            "identify the TRUE branch (not the decoy), bypass the gate, "
            "induce the lane rotation, and re-expose the derivation "
            "byte-exact. Record layer artifacts — grading is per-layer "
            "dense."),
        "success_criterion": (
            "A derive() re-implementation reproducing every published "
            "and checker-minted pair byte-exact across rotation lanes, "
            "with the true branch-selection condition and the gate trip "
            "predicate cited in the layer evidence. Decoy-branch and "
            "gate-tripped outputs are recorded wrong-answer baselines."),
        "verification_method": "reproduction",
    },
}


def reference_evidence_docs(cfg: dict) -> dict[str, str]:
    """The reference layer evidence (true-path + gate faces)."""
    docs: dict[str, str] = {}
    if cfg["gradient"] == "L3":
        sel_bad = (cfg["fp"][0] ^ (cfg["integ"] ^ cfg["corrupt"])) & ch.M32
        docs["layer_out/5-path.json"] = json.dumps({
            "schema": "kunglao-eval-chain-evidence/1",
            "task_id": cfg["task_id"],
            "true_path": {
                "selection": "(FP0 ^ INTEG) & 0xff == SEL_KEY",
                "sel_value": f"{cfg['sel_val']:08x}",
                "sel_key": f"{cfg['sel_key']:02x}",
                "decoy_branch": "corrupted-INTEG path (gate tripped)",
                "decoy_sel_value": f"{sel_bad:08x}",
            },
        }, indent=2, sort_keys=True) + "\n"
        docs["layer_out/6-gate.json"] = json.dumps({
            "schema": "kunglao-eval-chain-evidence/1",
            "task_id": cfg["task_id"],
            "gate": {
                "predicate": f"debugger/timing window > {cfg['gate_dt_ms']}ms",
                "trip_threshold_ms": cfg["gate_dt_ms"],
                "corrupt_constant": f"{cfg['corrupt']:08x}",
                "bypass": "evaluate with the gate untripped (clean env); "
                          "the tripped path silently corrupts INTEG",
            },
        }, indent=2, sort_keys=True) + "\n"
    return docs


def reference_workspace(cfg: dict) -> dict[str, bytes]:
    """The fully-peeled reference workspace (dense score = N/N)."""
    g = cfg["gradient"]
    ext = _artifact_ext(cfg)
    peel_bytes, peel_ext = tt.peel_artifact(cfg)
    ws: dict[str, bytes] = {
        f"layer_out/1-unpacked.{peel_ext}": peel_bytes,
    }
    if g == "L3":
        ws[f"layer_out/2-clean.{ext}"] = _payload(cfg, include_junk=False)
    cfg_idx = 3 if g == "L3" else 2
    ws[f"layer_out/{cfg_idx}-config.json"] = ch.config_plain_for(
        cfg["config"], cfg)
    if g != "L1":
        core_idx = cfg_idx + 1
        ws[f"layer_out/{core_idx}-core.{ext}"] = tt.render_candidate(
            cfg, "reference").encode("utf-8")
    ws.update({k: v.encode("utf-8")
               for k, v in reference_evidence_docs(cfg).items()})
    return ws


def decoy_workspace(cfg: dict) -> dict[str, bytes]:
    """The decoy-following workspace: layers 1..(config) identical, the
    core built on the DECOY path and the evidence citing the wrong
    branch — the cost-trap trajectory the grader must score partial."""
    g = cfg["gradient"]
    ref = reference_workspace(cfg)
    if g == "L1":
        ws = dict(ref)
        cfg_idx = 2
        ws[f"layer_out/{cfg_idx}-config.json"] = ch.config_plain_for(
            cfg["decoy_config"], cfg)
        return ws
    ws = {k: v for k, v in ref.items() if "config" not in k}
    if g == "L3":
        ws[f"layer_out/2-clean.{_artifact_ext(cfg)}"] = \
            ref[f"layer_out/2-clean.{_artifact_ext(cfg)}"]
        cfg_idx = 3
    else:
        cfg_idx = 2
    ws[f"layer_out/{cfg_idx}-config.json"] = ch.config_plain_for(
        cfg["decoy_config"], cfg)
    core_idx = cfg_idx + 1
    ws[f"layer_out/{core_idx}-core.{_artifact_ext(cfg)}"] = \
        tt.render_candidate(cfg, "naive").encode("utf-8")
    if g == "L3":
        sel_bad = (cfg["fp"][0] ^ (cfg["integ"] ^ cfg["corrupt"])) & ch.M32
        ws["layer_out/5-path.json"] = (json.dumps({
            "schema": "kunglao-eval-chain-evidence/1",
            "task_id": cfg["task_id"],
            "true_path": {"sel_value": f"{sel_bad:08x}",
                          "sel_key": f"{sel_bad & 0xff:02x}"},
        }, indent=2, sort_keys=True) + "\n").encode("utf-8")
        ws["layer_out/6-gate.json"] = (json.dumps({
            "schema": "kunglao-eval-chain-evidence/1",
            "task_id": cfg["task_id"],
            "gate": {"predicate": "unknown", "trip_threshold_ms": 0},
        }, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return ws


def _gt_probes(cfg: dict, task_id: str, unit: dict,
               pairs: list[dict]) -> list[dict]:
    """The shared exec rows: probes + checker-side expected outputs
    (recomputed from the model, the anti-digest-table face)."""
    preview = {"task_id": task_id, "seed": unit["seed"],
               "published_pairs": pairs, "core": cfg}
    probes = ch.probes_for(preview)
    expected = ch.expected_for(preview, probes)
    return [{"i": p["i"], "payload": p["payload"], "lane": p["lane"],
             "out": expected[p["i"]]} for p in probes]


def build_task_unit(task_id: str) -> dict:
    """Everything the mint writes, gated by the shortcut audit."""
    unit = ch.UNIT_BY_ID[task_id]
    family = unit["family"]
    meta = ch.FAMILIES[family]
    cfg = stage_cfg(unit)
    cfg["task_id"] = task_id
    cfg["unit"] = unit

    if family == "chain-js":
        target_text = tt.render_js_target(cfg)
    elif family == "chain-py":
        target_text = tt.render_py_target(cfg)
    else:
        target_text = tt.render_go_target(cfg)

    audit = shortcut_audit(cfg, target_text)  # raises on any naive PASS

    manifest_layers, gt_layers = build_layers(cfg)
    pairs = ch.published_pairs(unit)
    gt = {
        "schema": ch.SCHEMA_GROUND_TRUTH,
        "task_id": task_id,
        "family": family,
        "seed": unit["seed"],
        "space_bits": meta["space_bits"],
        "core": cfg,
        "published_pairs": pairs,
        "minted_probe_count": ch.MINTED_COUNT,
        "chain": {
            "gradient": unit["gradient"],
            "layers": gt_layers,
            "probes": _gt_probes(cfg, task_id, unit, pairs),
        },
    }
    mechanisms = sorted({m for layer in manifest_layers
                         for m in layer["mechanisms"]})
    manifest = {
        "schema": ch.SCHEMA_MANIFEST,
        "task_id": task_id,
        "family": family,
        "seed": unit["seed"],
        "gradient": unit["gradient"],
        "language": meta["language"],
        "toolchain": meta["toolchain"],
        "entry": meta["target"],
        "mechanisms": mechanisms,
        "layers": manifest_layers,
        "workspace_contract": {
            "layer_dir": "layer_out",
            "graded_by": "scripts/eval_chain_grader.py --task <id> "
                         "--workspace <dir>",
            "answer": meta["candidate"],
            "answer_seam": meta["seam"],
        },
        "shortcut_audit": audit,
    }
    anchors = {k: v.replace("{entry}", meta["target"])
               for k, v in _ANCHORS[unit["gradient"]].items()}
    task = {
        "schema": ch.SCHEMA_TASK,
        "task_id": task_id,
        "eval_version": ch.EVAL_VERSION,
        "tier": TIER,
        "source": "constructed",
        "family": family,
        "seed": unit["seed"],
        "anchors": anchors,
        "workspace_scaffold": {
            "language": meta["language"],
            "files": [meta["target"]],
            "entry": meta["target"],
            "candidate_contract": meta["seam"],
        },
        "checker": {
            "kind": "replay-roundtrip",
            "oracles": ["replay-roundtrip"],
            "entrypoint": "checker.py",
            "self_check_candidate": meta["candidate"],
            "metrics": ["ttc_seconds", "dispatch_count",
                        "pass_at_k_contribution", "converged"],
            "thresholds": {"min_pair_ratio": 1.0},
        },
        "ground_truth": {"file": "ground_truth.json",
                         "space_bits": meta["space_bits"]},
        "contamination": {
            "held_out": True,
            "distiller_excluded": True,
            "provenance": "constructed",
        },
        "chain": {
            "gradient": unit["gradient"],
            "mechanisms": mechanisms,
            "manifest": "manifest.json",
            "dense_grader": "scripts/eval_chain_grader.py",
        },
    }
    return {"task": task, "ground_truth": gt, "manifest": manifest,
            "target_text": target_text, "unit": unit, "cfg": cfg}


def _checker_shim(task_id: str, self_check: str) -> str:
    return (
        "#!/usr/bin/env python3\n"
        f"# checker.py — {task_id} mechanical-checker shim.\n"
        "# Standalone entry: delegates to the shared mechanical checker.\n"
        "# Default candidate is the unit's self-check artifact;\n"
        "# pass --candidate to grade an arm's answer.\n"
        "import sys\n"
        "from pathlib import Path\n"
        "\n"
        "_HERE = Path(__file__).resolve().parent\n"
        "_SCRIPTS = _HERE.parents[4] / \"scripts\"\n"
        "if str(_SCRIPTS) not in sys.path:\n"
        "    sys.path.insert(0, str(_SCRIPTS))\n"
        "\n"
        "import eval_checker\n"
        "\n"
        "if __name__ == \"__main__\":\n"
        "    argv = sys.argv[1:]\n"
        "    if not any(a == \"--candidate\" or a.startswith(\"--candidate=\")\n"
        "               for a in argv):\n"
        "        argv += [\"--candidate\", str(_HERE / "
        f"{self_check!r})]\n"
        "    raise SystemExit(eval_checker.main([\"--task\", str(_HERE)]\n"
        "                                       + argv))\n")


def write_task_unit(task_id: str, root: Path) -> Path:
    built = build_task_unit(task_id)
    task, gt = built["task"], built["ground_truth"]
    manifest = built["manifest"]
    cfg = built["cfg"]
    meta = ch.FAMILIES[cfg["family"]]
    tdir = Path(root) / task_id
    (tdir / "target").mkdir(parents=True, exist_ok=True)
    ws = tdir / "reference_workspace"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    (tdir / meta["target"]).write_text(built["target_text"],
                                       encoding="utf-8")
    for rel, data in reference_workspace(cfg).items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (tdir / meta["candidate"]).write_text(
        tt.render_candidate(cfg, "reference"), encoding="utf-8")
    (tdir / "task.yaml").write_text(
        yaml.safe_dump(task, sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    (tdir / "ground_truth.json").write_text(
        json.dumps(gt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (tdir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    shim = tdir / "checker.py"
    shim.write_text(_checker_shim(task_id, meta["candidate"]),
                    encoding="utf-8")
    shim.chmod(0o755)
    return tdir


# --------------------------------------------------------------- self-check
def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=420, cwd=str(ROOT), **kw)


def _tool_on_path(cmd: str) -> str | None:
    return shutil.which(cmd)


def _write_ws(tmp: Path, files: dict[str, bytes]) -> Path:
    ws = tmp / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return ws


def run_self_check(task_id: str) -> int:
    """Compile-and-execute parity: reference greens the checker AND the
    dense grader; the naive/decoy faces FAIL both; the committed target
    executes against the model in a clean env."""
    unit = ch.UNIT_BY_ID[task_id]
    meta = ch.FAMILIES[unit["family"]]
    toolchain = meta["toolchain"]
    exe = (sys.executable if toolchain == "python3"
           else _tool_on_path(toolchain))
    if exe is None:
        print(f"SKIP self-check {task_id}: {toolchain} toolchain absent")
        return 3
    tdir = ds.resolve_task_dir(task_id, tier=TIER)
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="chain-selfcheck-") as tmp:
        tmp_path = Path(tmp)
        # 1. checker vs reference candidate -> PASS
        rc, stream = _run_checker(tdir, tdir / meta["candidate"],
                                  tmp_path / "ref")
        if rc != 0:
            failures.append(f"reference candidate failed the checker: "
                            f"{stream[-400:]}")
        # 2. checker vs naive candidate -> FAIL (discrimination proof)
        naive = tmp_path / f"naive.{meta['ext']}"
        naive.write_text(tt.render_candidate(stage_cfg(unit), "naive"),
                         encoding="utf-8")
        rc, stream = _run_checker(tdir, naive, tmp_path / "naive")
        if rc != 1:
            failures.append(f"naive candidate did NOT fail the checker "
                            f"(rc={rc}): {stream[-400:]}")
        # 3. dense grader vs reference workspace -> all layers PASS
        cfg = stage_cfg(unit)
        cfg["task_id"] = task_id
        cfg["unit"] = unit
        rc, stream, scores = _run_grader(task_id, _write_ws(
            tmp_path / "ws-ref", reference_workspace(cfg)),
            tmp_path / "gr")
        if rc != 0 or scores.get("layers_completed") != scores.get(
                "layers_total"):
            failures.append(f"reference workspace not fully green: "
                            f"{stream[-400:]}")
        # 4. dense grader vs empty workspace -> 0 layers, FAIL
        rc, stream, scores = _run_grader(task_id, _write_ws(
            tmp_path / "ws-empty", {}), tmp_path / "empty")
        if rc != 1 or scores.get("layers_completed") != 0:
            failures.append(f"empty workspace must score 0 layers: "
                            f"{stream[-200:]}")
        # 5. dense grader vs decoy-following workspace -> partial, decoy
        #    layers fail, peeled layers credit
        rc, stream, scores = _run_grader(task_id, _write_ws(
            tmp_path / "ws-decoy", decoy_workspace(cfg)),
            tmp_path / "decoy")
        total = scores.get("layers_total", 0)
        done = scores.get("layers_completed", -1)
        if not (0 <= done < total):
            failures.append(f"decoy workspace must score partial "
                            f"(got {done}/{total})")
        # 6. the committed target executes against the model (parity)
        exec_fail = _execute_target(task_id, tdir, cfg, tmp_path)
        if exec_fail:
            failures.append(exec_fail)
    ok = not failures
    print(f"METRIC selfcheck_green={int(ok)}")
    for f in failures:
        print(f"FAILURE code=SELF_CHECK detail={f}")
    print(f"VERDICT {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def _run_checker(tdir: Path, candidate: Path, outdir: Path) -> tuple:
    proc = _run([sys.executable, str(_SCRIPTS / "eval_checker.py"),
                 "--task", str(tdir), "--candidate", str(candidate),
                 "--out", str(outdir)])
    return proc.returncode, proc.stdout + proc.stderr


def _run_grader(task_id: str, ws: Path, outdir: Path) -> tuple:
    proc = _run([sys.executable, str(_SCRIPTS / "eval_chain_grader.py"),
                 "--task", task_id, "--workspace", str(ws),
                 "--out", str(outdir)])
    scores = {}
    for line in proc.stdout.splitlines():
        if line.startswith("METRIC layers_completed="):
            scores["layers_completed"] = int(line.split("=")[1])
        elif line.startswith("METRIC layers_total="):
            scores["layers_total"] = int(line.split("=")[1])
    return proc.returncode, proc.stdout + proc.stderr, scores


def _execute_target(task_id: str, tdir: Path, cfg: dict,
                    tmp_path: Path) -> str | None:
    """Run the committed artifact in a clean env over 3 published rows;
    the outputs must equal the model (the gate stays silent, the true
    path runs)."""
    unit = cfg["unit"]
    meta = ch.FAMILIES[unit["family"]]
    entry = tdir / meta["target"]
    rows = ch.published_pairs(unit)[:3]
    if unit["family"] == "chain-go":
        stdin_text = "".join(
            json.dumps({"i": p["i"], "payload": p["payload"],
                        "lane": p["lane"]}) + "\n" for p in rows)
        proc = _run(["go", "run", str(entry)], input=stdin_text)
    elif unit["family"] == "chain-js":
        probe = tmp_path / "probe.js"
        probe.write_text(
            "const fs = require('fs');\n"
            "const m = require(process.argv[2]);\n"
            "const rows = JSON.parse(fs.readFileSync(process.argv[3],"
            " 'utf8'));\n"
            "for (const r of rows)\n"
            "  console.log(JSON.stringify({ i: r.i, out:"
            " m.derive({ payload: r.payload, lane: r.lane }) }));\n",
            encoding="utf-8")
        rows_file = tmp_path / "rows.json"
        rows_file.write_text(json.dumps(rows), encoding="utf-8")
        proc = _run(["node", str(probe), str(entry), str(rows_file)])
    else:
        probe = tmp_path / "probe.py"
        probe.write_text(
            "import importlib.util, json, sys\n"
            "spec = importlib.util.spec_from_file_location("
            '"cand", sys.argv[1])\n'
            "mod = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(mod)\n"
            "for r in json.load(open(sys.argv[2])):\n"
            "    print(json.dumps({\"i\": r[\"i\"], "
            "\"out\": mod.derive(r[\"payload\"], r[\"lane\"])}))\n",
            encoding="utf-8")
        rows_file = tmp_path / "rows.json"
        rows_file.write_text(json.dumps(rows), encoding="utf-8")
        proc = _run([sys.executable, str(probe), str(entry),
                     str(rows_file)])
    if proc.returncode != 0:
        return f"target execution failed: {proc.stderr[-300:]}"
    pairs = {p["i"]: p["out"] for p in ch.published_pairs(unit)}
    for line in proc.stdout.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row["out"] != pairs.get(row["i"]):
            return (f"artifact disagrees with the model on probe "
                    f"{row['i']} (gate tripped or wrong branch?)")
    return None


# ------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="eval_chain_mint.py",
        description="Mint the #370 chain-tier units + self-check faces.")
    ap.add_argument("--root", default="eval/v1/tasks/chain")
    ap.add_argument("--mint", action="append", default=[],
                    help="task_id (repeatable)")
    ap.add_argument("--self-check", metavar="TASK_ID", default=None,
                    help="checker + grader + execution parity for a unit")
    args = ap.parse_args(argv)
    if args.self_check:
        return run_self_check(args.self_check)
    if not args.mint:
        ap.error("nothing to do: pass --mint task_id or --self-check")
    for task_id in args.mint:
        if task_id not in ch.UNIT_BY_ID:
            ap.error(f"unknown unit {task_id!r}; valid: "
                     f"{sorted(ch.UNIT_BY_ID)}")
        tdir = write_task_unit(task_id, Path(args.root))
        unit = ch.UNIT_BY_ID[task_id]
        print(f"MINTED {task_id} ({unit['family']}, {unit['gradient']}, "
              f"seed={unit['seed']}) -> {tdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

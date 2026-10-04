#!/usr/bin/env python3
"""apk-static-license-v1 checker — constant-hit + boundary replay face."""
from __future__ import annotations
import json, secrets, subprocess, sys, time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SCRIPTS = None
for _base in (_HERE, *_HERE.parents):
    for _sub in ("scripts", ".local_repo_link/scripts"):
        if (_base / _sub / "eval_checker.py").is_file():
            _SCRIPTS = _base / _sub
            break
    if _SCRIPTS:
        break
if _SCRIPTS is None:
    raise SystemExit("checker: cannot locate scripts/eval_checker.py")
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import eval_checker  # noqa: E402

GT = json.loads((_HERE / "ground_truth.json").read_text(encoding="utf-8"))
CONSTS = GT["constants"]
TH = GT["checker"]["thresholds"]


def static_face(candidate: Path):
    text = candidate.read_text(encoding="utf-8", errors="replace").lower()
    hits, missing = 0, []
    for name, val in CONSTS.items():
        forms = {str(val).lower()}
        try:
            b = bytes.fromhex(str(val))
            forms.add(str(int.from_bytes(b, "big")))
        except ValueError:
            pass
        if any(f in text for f in forms):
            hits += 1
        else:
            missing.append(name)
    return hits, missing


def boundary_face(candidate: Path, outdir: Path):
    """Run the reimpl as a JSON protocol: send cases, compare to truth."""
    cases = [
        {"in": "6b756e676c616f2d76312d6163636570742121", "want": 0},
        {"in": "74696e79", "want": 1},
        {"in": "58" * 16, "want": 1},
        {"in": "41" * 200, "want": 2},
        {"in": "42" * 15, "want": 1},
        {"in": "43" * 16, "want": 1},
        {"in": "44" * 127, "want": 1},
        {"in": "45" * 128, "want": 2},
    ]
    script = (outdir / "_boundary_driver.py")
    # exec-compile load (not importlib spec loading): the #863 Family-B
    # confinement pins importlib spec loading to four sanctioned hosts,
    # and a corpus checker must not grow a fifth site.
    script.write_text(
        "import json, sys\n"
        f"_src = open({str(candidate)!r}, encoding='utf-8').read()\n"
        "_ns = {}\n"
        f"exec(compile(_src, {str(candidate)!r}, 'exec'), _ns)\n"
        "for line in sys.stdin:\n"
        "    c = json.loads(line)\n"
        "    data = bytes.fromhex(c['in'])\n"
        "    v = _ns.get('verify')\n"
        "    rc = v(data) if v else _ns['main_rc'](data)\n"
        "    print(json.dumps({'rc': rc}))\n", encoding="utf-8")
    matched = total = 0
    failures = []
    t0 = time.time()
    for c in cases:
        total += 1
        r = subprocess.run([sys.executable, str(script)], input=json.dumps(c),
                           capture_output=True, text=True, timeout=60)
        try:
            got = json.loads(r.stdout.strip().splitlines()[-1])["rc"]
        except Exception:
            got = None
        if got == c["want"]:
            matched += 1
        else:
            failures.append({"code": "BOUNDARY_FAIL",
                             "detail": f"{c['in'][:16]}… want={c['want']} "
                                       f"got={got}"})
    script.unlink(missing_ok=True)
    return {"matched": matched, "count": total,
            "ttc_seconds": round(time.time() - t0, 3), "failures": failures}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    cand = Path(a.candidate or (Path.cwd() / "client.py")).resolve()
    outdir = Path(a.out or Path.cwd()); outdir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    hits, missing = static_face(cand)
    row = boundary_face(cand, outdir)
    failures = list(row["failures"])
    ok_static = hits >= TH["min_constant_hits"]
    ok_ratio = (row["matched"] / row["count"] >= TH["min_pair_ratio"]
                if row["count"] else False)
    verdict = "PASS" if (ok_static and ok_ratio) else "FAIL"
    ev = outdir / f"evidence-{GT['task_id']}-{ts.replace(':', '')}-{secrets.token_hex(4)}.json"
    (outdir / ev.name).write_text(json.dumps({
        "schema": "eval-evidence/1", "task_id": GT["task_id"], "ts": ts,
        "candidate": str(cand),
        "faces": {"static": {"hits": hits, "required": TH["min_constant_hits"],
                             "missing": missing}, "boundary": row},
        "metrics": {"ttc_seconds": row["ttc_seconds"],
                    "boundary_matched": row["matched"],
                    "boundary_total": row["count"]},
        "verdict": verdict,
        "verdict_class": "static" if not ok_static else "dynamic",
        "failures": failures}, indent=1) + "\n", encoding="utf-8")
    print(f"EVIDENCE {ev}")
    print(f"VERDICT {verdict}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

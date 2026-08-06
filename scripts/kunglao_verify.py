#!/usr/bin/env python3
"""kunglao_verify — M3 VERIFY 实现模块 (phase 5, E5.1).

独立 CLI 入口: scripts/kunglao-verify.py(薄包装, 本模块含全部逻辑)。

- l1_mechanical: parse reproduce → run(只读白名单) → sha256 比对 expected → PASS/FAIL
- l2_redteam:    kunglao-redteam 派发封装接口(默认 NOT-RUN; 测试用 dispatcher stub 注入)
- anchor_check:  PASS 必须带 anchors(byte_offset/cmd/expected); 无锚不提升
- verify:        M3.4 状态机组合 → 写 runs/verify-<fact_id>-<ts>.json

输出契约: schemas/verify-output.json (M3.3 冻结, module-design §M3.3 L270-280)。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

# ---- 只读白名单(M3.2 L251 "只读白名单: python/xxd/grep/sha256sum 等, 禁止写") ----
READONLY_TOOLS = {
    "python", "python3", "py",
    "xxd", "od", "hexdump", "cat", "strings", "file",
    "grep", "egrep", "fgrep", "sed", "awk",
    "sha256sum", "md5sum", "sha1sum", "wc", "head", "tail", "sort", "uniq",
}
CMD_TIMEOUT_SEC = 15
REPRODUCE_MAX_CHARS = 2000

# python -c 路径的写操作静态拒绝: 任何写意图 → FAIL(不降级为 PASS)
_PY_WRITE_RE = re.compile(
    r"open\([^)]*['\"][wa]|\.write\(|"
    r"os\.(remove|unlink|mkdir|rmdir|system|popen|rename|truncate|replace)|"
    r"shutil\.|subprocess\.|pathlib\.[A-Za-z_]+\([^)]*\)\.(write_text|write_bytes|mkdir|unlink|rename)",
    re.IGNORECASE,
)
# shell 风格重定向拒绝(xxd/grep/... 路径)
_SHELL_WRITE_RE = re.compile(r">\s*[\w\"'/\\]|>>|\|\s*tee\b", re.IGNORECASE)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
L2_VERDICTS = ("CONFIRMED", "REFUTED", "UNVERIFIED-WITH-GAP", "NOT-RUN")


def utc_now() -> str:
    """UTC ISO-8601 秒级, Z 后缀."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_frontmatter(text: str) -> dict:
    """极简 frontmatter: '---' 围栏内逐行 'key: value'(去引号). 失败返回 {}."""
    out: dict[str, str] = {}
    if not text.startswith("---"):
        return out
    body = text.split("---", 2)
    if len(body) < 3:
        return out
    for line in body[1].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_fact(ws: Path, fact_id: str) -> dict | None:
    """读 facts/<fact_id>.md frontmatter; 文件缺失 → None."""
    p = ws / "facts" / f"{fact_id}.md"
    if not p.exists():
        return None
    fm = _parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
    fm["_path"] = str(p)
    return fm


def _find_claim_id(fact: dict) -> str:
    """frontmatter claim_id 优先; 缺失 → C-UNKNOWN(契约空白决策, schema 允许)."""
    cid = str(fact.get("claim_id", "")).strip()
    return cid if cid else "C-UNKNOWN"


def _expected_hash(expected: str) -> str:
    """expected 为 64-hex → 直接当 sha256; 否则 sha256(expected 去除空白)."""
    exp = expected.strip()
    if _SHA256_RE.match(exp):
        return exp
    return hashlib.sha256(exp.encode("utf-8")).hexdigest()


def parse_reproduce(reproduce: str) -> list[str]:
    """reproduce → argv: 白名单工具开头 → 原样 argv(python 换 sys.executable);
    否则整串按 python -c 单行执行. 空/超长/不可分词 → ValueError."""
    if not reproduce or not reproduce.strip():
        raise ValueError("reproduce command is empty")
    if len(reproduce) > REPRODUCE_MAX_CHARS:
        raise ValueError(f"reproduce too long ({len(reproduce)} > {REPRODUCE_MAX_CHARS} chars)")
    try:
        tokens = shlex.split(reproduce)
    except ValueError as exc:
        raise ValueError(f"reproduce unparseable: {exc}") from exc
    if not tokens:
        raise ValueError("reproduce command is empty")
    tool = tokens[0].lower().rstrip(".exe")
    if tool in READONLY_TOOLS:
        if tool in ("python", "python3", "py"):
            return [sys.executable, *tokens[1:]]
        return tokens
    return [sys.executable, "-c", reproduce]


def run_reproduce(reproduce: str, cwd: Path | None = None,
                  timeout: int = CMD_TIMEOUT_SEC) -> tuple[bytes | None, str]:
    """执行 reproduce → (stdout_bytes, detail). 白名单外工具/写操作/超时/缺失 → (None, reason).

    任何失败返回 None — 调用方判 FAIL, 绝不降级为 PASS(M3.5 L297).
    """
    try:
        argv = parse_reproduce(reproduce)
    except ValueError as exc:
        return None, f"parse error: {exc}"
    deny = _PY_WRITE_RE if argv[0] == sys.executable else _SHELL_WRITE_RE
    if deny.search(reproduce):
        return None, f"write operation detected in reproduce (denied by {deny.pattern[:60]}...)"
    try:
        r = subprocess.run(argv, capture_output=True, timeout=timeout, text=False,
                           cwd=str(cwd) if cwd else None)
    except FileNotFoundError as exc:
        return None, f"tool not found: {argv[0]} ({exc})"
    except subprocess.TimeoutExpired:
        return None, f"timeout after {timeout}s"
    if r.returncode != 0:
        return None, f"exit code {r.returncode}: {r.stderr[:200]!r}"
    return r.stdout, "ok"


def l1_mechanical(fact: dict, fixture: Path | None = None) -> dict:
    """L1 机械层(M3.2 L251): 重跑 reproduce → sha256 比对 expected → PASS/FAIL.

    actual_sha256 = sha256(stdout 去除尾部空白); expected 为 64-hex 时直接比对,
    否则比对 sha256(expected.strip()). cwd = fixture 所在目录(facts/).
    """
    reproduce = str(fact.get("reproduce", ""))
    expected = str(fact.get("expected", ""))
    cwd = fixture.parent if fixture else None
    stdout, detail = run_reproduce(reproduce, cwd=cwd)
    if stdout is None:
        return {"verdict": "FAIL",
                "actual_sha256": hashlib.sha256(b"").hexdigest(),
                "cmd": reproduce, "expected_sha256": _expected_hash(expected),
                "detail": detail}
    actual_sha256 = hashlib.sha256(stdout.rstrip()).hexdigest()
    exp_hash = _expected_hash(expected)
    verdict = "PASS" if actual_sha256 == exp_hash else "FAIL"
    detail = ("sha256 match" if verdict == "PASS"
              else f"sha256 mismatch: actual {actual_sha256} vs expected {exp_hash}")
    return {"verdict": verdict, "actual_sha256": actual_sha256, "cmd": reproduce,
            "expected_sha256": exp_hash, "detail": detail}


def anchor_check(verdict: dict) -> bool:
    """M3.2 L263: PASS 必须带 anchors(byte_offset/cmd/expected); 无锚 → False(拒提升)."""
    if verdict.get("l1", {}).get("verdict") != "PASS":
        return False
    anchors = verdict.get("anchors") or []
    if not anchors:
        return False
    return all(
        isinstance(a, dict) and a.get("byte_offset") and a.get("cmd") and a.get("expected")
        for a in anchors
    )


def needs_semantic(fact: dict) -> bool:
    """该 fact 是否需要 L2 语义对抗验证? 默认 False(L1 机械 PASS 即 VERIFIED, M3.4 L288)."""
    flag = str(fact.get("needs_semantic", "")).strip().lower()
    return flag in ("true", "yes", "1") or fact.get("boundary_type") == "subjective_interpretation"


def build_redteam_prompt(claim_id: str, ws: Path) -> str:
    """BLIND 派发 prompt(M3.6 L304 "盲验证: 输入不含 maker 结论").

    绝不携带 maker 上下文: 无目标 fact 内容、无 notes/、无 worker-status.
    kunglao-redteam 独立 subagent 用: 自证先于对比; 每分歧记 DIFF.
    """
    return (
        f"RED-TEAM CHECK claim {claim_id} in workspace {ws}.\n"
        "You are the ADVERSARIAL verifier. Derive the answer INDEPENDENTLY from "
        "raw evidence ONLY (sample binary, fixtures, captured logs) — never by "
        "reading the conclusion fact.\n"
        "BLIND CONSTRAINTS — you must NOT read:\n"
        "  - the target claim's facts file (facts/F<NNN>.md) or any facts file "
        "stating its conclusion\n"
        "  - notes/, worker-status-*.md, the worker's plan/state\n"
        "State your OWN finding FIRST, then compare. Report EVERY divergence "
        "(even minor) as DIFF. Five angles: reproducibility, adversarial "
        "alternatives, counter-evidence, scope overreach, numeric fidelity.\n"
        "Verdict: CONFIRMED | REFUTED | UNVERIFIED-WITH-GAP — with concrete "
        "gaps + reproduce commands."
    )


def prompt_is_blind(prompt: str, ws: Path, claim_id: str) -> bool:
    """机械 BLIND 断言: prompt 不含目标 claim 相关 fact 的正文行与文件路径."""
    facts_dir = ws / "facts"
    if facts_dir.exists():
        for p in sorted(facts_dir.glob("*.md")):
            if p.name == "_INDEX.md":
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            if claim_id not in text or p.name in prompt:
                continue
            for line in text.splitlines():
                s = line.strip()
                if len(s) > 20 and s in prompt:
                    return False
    return True


def l2_redteam(claim_id: str, ws: Path, dispatcher=None) -> tuple[str, list[str]]:
    """L2 对抗层派发封装接口(M3.2 L254) → (verdict, gaps).

    dispatcher: Callable[[str, Path], tuple[str, list[str]]] — 真实派发由
    orchestrator 用 build_redteam_prompt 的 BLIND prompt 派发 kunglao-redteam
    subagent; 测试注入 stub. 未注入 → NOT-RUN(不静默 PASS, M3.5 L298).
    """
    if dispatcher is None:
        return ("NOT-RUN", ["L2 redteam dispatcher not configured — real dispatch "
                            "is the orchestrator's job (BLIND prompt via build_redteam_prompt)"])
    try:
        verdict, gaps = dispatcher(claim_id, ws)
    except Exception as exc:
        return ("UNVERIFIED-WITH-GAP", [f"redteam dispatch failed: {exc}"])
    if verdict not in L2_VERDICTS or verdict == "NOT-RUN":
        return ("UNVERIFIED-WITH-GAP", [f"invalid redteam verdict {verdict!r}"])
    return (verdict, list(gaps or []))


def verify(ws: Path, fact_id: str, l2_dispatcher=None) -> dict:
    """M3.4 状态机(L282-293): L1 → FAIL 即 REJECTED; 需语义才 L2 + anchor_check.

    输出过 schemas/verify-output.json 且写 runs/verify-<fact_id>-<ts>.json.
    """
    fact = load_fact(ws, fact_id)
    if fact is None:
        raise FileNotFoundError(f"fact {fact_id}.md not found under {ws / 'facts'}")
    fixture = Path(fact["_path"])
    l1 = l1_mechanical(fact, fixture)
    claim_id = _find_claim_id(fact)
    anchors = fact.get("anchors", [])

    if l1["verdict"] == "FAIL":
        l2 = {"verdict": "NOT-RUN", "gaps": ["L1 mechanical FAIL — L2 not dispatched"]}
        overall = "REJECTED"
    elif not needs_semantic(fact):
        l2 = {"verdict": "NOT-RUN", "gaps": ["fact does not require semantic (L2) verification"]}
        overall = "VERIFIED"
    else:
        v2, gaps = l2_redteam(claim_id, ws, dispatcher=l2_dispatcher)
        l2 = {"verdict": v2, "gaps": gaps}
        if v2 == "CONFIRMED" and anchor_check({"l1": l1, "anchors": anchors}):
            overall = "VERIFIED"
        elif v2 == "REFUTED":
            overall = "REJECTED"
        else:
            overall = "PARTIAL"

    out = {"fact_id": fact_id, "claim_id": claim_id, "l1": l1, "l2": l2,
           "anchors": anchors, "overall": overall}
    runs = ws / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"verify-{fact_id}-{utc_now().replace(':', '')}.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    """独立 CLI: python kunglao-verify.py <ws> <fact_id> [--json]."""
    ap = argparse.ArgumentParser(description="kunglao-verify — M3 VERIFY (L1 mechanical + L2 redteam)")
    ap.add_argument("ws", type=Path, help="workspace root")
    ap.add_argument("fact_id", help="fact id, e.g. F-001")
    ap.add_argument("--json", action="store_true", help="machine-readable JSON output")
    args = ap.parse_args(argv)
    try:
        out = verify(args.ws, args.fact_id)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(f"kunglao-verify {out['fact_id']} (claim {out['claim_id']}): "
              f"L1={out['l1']['verdict']} L2={out['l2']['verdict']} overall={out['overall']}")
        for a in out["anchors"]:
            print(f"  anchor @{a['byte_offset']} cmd={a['cmd']} expected={a['expected']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

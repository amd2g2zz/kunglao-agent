#!/usr/bin/env python3
"""kunglao_verify — M3 VERIFY 实现模块 (phase 5, E5.1).

独立 CLI 入口: scripts/kunglao-verify.py(薄包装, 本模块含全部逻辑)。

- l1_mechanical: parse reproduce → run(只读白名单) → 比对 expected → PASS/FAIL
      * assignment-class expected WITH value assertions: 逐字段 byte-exact 比对 (D2, #49)
      * otherwise: 整块 sha256 比对 (原 M3.2 行为)
- check_assignment_expected: assignment-class 必须绑定 value assertions, 否则 lint-reject (D1/D3, #49)
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

# ---- assignment-class value-assertion gate (a2b5e25c / GitHub #49) ----
# 一个"裸 ="(不属于 ==, !=, >=, <=, :=)即标记 assignment-class — field 赋值语义,
# 而非纯 API 调用序列。纯 API 序列与裸 hex/sha 字面量无此 '=', 走原 sha256 路径。
_ASSIGN_EQ_RE = re.compile(r"(?<![<>=!:])=(?![=])")
# field=value 解析器: 捕获 (field, value); value 在 ; , = 或换行处终止。
_VALUE_ASSERTION_RE = re.compile(r"([A-Za-z_][\w.]*)\s*=\s*([^;,=\n]+)")
# reproduce 输出行解析器: 接受 field=value 或 field: value。
_ACTUAL_ASSERTION_RE = re.compile(r"^([A-Za-z_][\w.]*)\s*[:=]\s*(.+)$")
# 不算具体 value 绑定的 RHS 占位符。
_VALUE_PLACEHOLDERS = {"??", "?", "TBD", "TODO", "N/A", "NULL", "null", ""}


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


# ===========================================================================
# assignment-class value-assertion gate (a2b5e25c / GitHub #49, decisions D1-D4)
# ===========================================================================

def is_assignment_class(expected: str) -> bool:
    """D4 分类器: expected 是否含赋值指示符?

    一个"裸 ="(非 ==, !=, >=, <=, :=)即判定为 assignment-class。纯 API 调用序列
    (calls Foo(a, b)) 与裸 hex/sha 字面量 (0x5a4d, 64-hex) 无此 '=', 不属
    assignment-class — 它们继续走原整块 sha256 路径。
    """
    return bool(_ASSIGN_EQ_RE.search(expected))


def parse_value_assertions(expected: str) -> list[tuple[str, str]]:
    """从 assignment-class expected 中抽取具体的 field=value 断言。

    返回有序 (field, value) 对列表。占位符 RHS (??, TBD, 空串) 不算具体绑定,
    被 skip — 这样 check_assignment_expected 能把 "全是 field=??" 的 expected
    判为"缺乏具体 value 断言"而拒绝。
    """
    pairs: list[tuple[str, str]] = []
    for m in _VALUE_ASSERTION_RE.finditer(expected):
        field = m.group(1).strip()
        value = m.group(2).strip()
        if value not in _VALUE_PLACEHOLDERS:
            pairs.append((field, value))
    return pairs


def _parse_actual_assertions(stdout: bytes) -> dict[str, str]:
    """把 reproduce 输出解析成 {field: value}; 每行一个 field[:=]value。"""
    actual: dict[str, str] = {}
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s:
            continue
        m = _ACTUAL_ASSERTION_RE.match(s)
        if m:
            actual[m.group(1).strip()] = m.group(2).strip()
    return actual


def _values_equal(a: str, b: str) -> bool:
    """比较两个 value 字符串: 整数/hex 归一化后比; 否则精确字符串比。"""
    a, b = a.strip(), b.strip()
    try:
        return int(a, 0) == int(b, 0)
    except (ValueError, TypeError):
        return a == b


def compare_value_assertions(
    expected_assertions, actual_stdout
) -> tuple[bool, list[tuple[str, str, str]]]:
    """D2: 逐字段把 expected value 断言对照 reproduce 实际输出。

    返回 (all_match, mismatches)。每个 mismatch = (field, expected, actual);
    actual 为观测值, 或 field 缺席时的 '<missing from reproduce output>'。
    全部断言都匹配才 PASS — 避免"整块 sha256 模糊通过"掩盖单字段反转 (a2b5e25c)。
    """
    actual = _parse_actual_assertions(actual_stdout)
    mismatches: list[tuple[str, str, str]] = []
    for field, exp_val in expected_assertions:
        if field not in actual:
            mismatches.append((field, exp_val, "<missing from reproduce output>"))
        elif not _values_equal(exp_val, actual[field]):
            mismatches.append((field, exp_val, actual[field]))
    return (not mismatches, mismatches)


def check_assignment_expected(fact: dict, *, grace: bool = False) -> tuple[bool, str]:
    """Lint gate (D1/D3): assignment-class expected 必须绑定具体 value 断言。

    没有 byte-exact 目标的 fact 不应被提升到 PROVEN/VERIFIED。返回 (ok, reason):
    ok=False 阻断提升。grace=True 时把拒绝降级为非阻断 WARN (一次性迁移周期用)。
    """
    expected = str(fact.get("expected", ""))
    if not is_assignment_class(expected):
        return True, "not assignment-class (no assignment indicators)"
    assertions = parse_value_assertions(expected)
    if assertions:
        return True, f"{len(assertions)} value assertion(s) bound"
    reason = ("assignment-class expected lacks concrete value assertions "
              "(detected assignment token(s) but no field=value bindings)")
    if grace:
        return True, "WARN (grace): " + reason
    return False, reason


# ===========================================================================

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
    """L1 机械层(M3.2 L251): 重跑 reproduce → 比对 expected → PASS/FAIL.

    两条比对路径(#49 D2):
    - assignment-class expected 且带 value 断言: 逐字段 byte-exact 比对 reproduce 输出。
    - 其它(非 assignment-class, 或裸 hex/sha): 整块 sha256 比对(原 M3.2 行为)。
    actual_sha256 始终填充(verify-output schema 契约要求)。
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

    if is_assignment_class(expected):
        assertions = parse_value_assertions(expected)
        if assertions:
            ok, mismatches = compare_value_assertions(assertions, stdout)
            if ok:
                return {"verdict": "PASS", "actual_sha256": actual_sha256,
                        "cmd": reproduce, "expected_sha256": exp_hash,
                        "detail": f"{len(assertions)} value assertion(s) match"}
            mm = "; ".join(f"{f}: expected {e} got {a}" for f, e, a in mismatches)
            return {"verdict": "FAIL", "actual_sha256": actual_sha256,
                    "cmd": reproduce, "expected_sha256": exp_hash,
                    "detail": f"value-assertion mismatch: {mm}"}
        # assignment-class 但无具体断言 — 应已被 lint gate 拦截; 兜底再 FAIL 一次。
        return {"verdict": "FAIL", "actual_sha256": actual_sha256,
                "cmd": reproduce, "expected_sha256": exp_hash,
                "detail": "assignment-class expected lacks concrete value assertions"}

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


def verify(ws: Path, fact_id: str, l2_dispatcher=None, *, grace: bool = False) -> dict:
    """M3.4 状态机(L282-293): lint → L1 → (需语义才 L2 + anchor_check).

    #49: assignment-class lint gate 先跑 — 缺 value 断言即 REJECTED(不提升)。
    grace=True 时 lint 仅 WARN, 不阻断(一次性迁移)。输出写 runs/verify-<fact_id>-<ts>.json。
    """
    fact = load_fact(ws, fact_id)
    if fact is None:
        raise FileNotFoundError(f"fact {fact_id}.md not found under {ws / 'facts'}")
    fixture = Path(fact["_path"])
    claim_id = _find_claim_id(fact)
    anchors = fact.get("anchors", [])

    lint_ok, lint_reason = check_assignment_expected(fact, grace=grace)
    lint = {"ok": lint_ok, "reason": lint_reason, "grace": grace}

    l1 = l1_mechanical(fact, fixture)

    if not lint_ok:
        l2 = {"verdict": "NOT-RUN", "gaps": ["lint gate rejected: " + lint_reason]}
        overall = "REJECTED"
    elif l1["verdict"] == "FAIL":
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
           "anchors": anchors, "overall": overall, "lint": lint}
    runs = ws / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"verify-{fact_id}-{utc_now().replace(':', '')}.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def _grace_scan(ws: Path) -> int:
    """--grace-scan: 列出 assignment-class 但缺 value 断言的 fact(迁移目标)。"""
    facts_dir = ws / "facts"
    affected: list[dict] = []
    if facts_dir.exists():
        for p in sorted(facts_dir.glob("*.md")):
            if p.name == "_INDEX.md":
                continue
            fm = _parse_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
            if not fm.get("id"):
                continue
            ok, reason = check_assignment_expected(fm)
            if not ok:
                affected.append({"fact_id": fm.get("id"), "status": fm.get("status", "?"),
                                 "path": str(p), "reason": reason})
    print(json.dumps(affected, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    """独立 CLI: python kunglao-verify.py <ws> <fact_id> [--json] [--grace] | <ws> --grace-scan."""
    ap = argparse.ArgumentParser(
        description="kunglao-verify — M3 VERIFY (L1 mechanical + L2 redteam + assignment-class lint)")
    ap.add_argument("ws", type=Path, help="workspace root")
    ap.add_argument("fact_id", nargs="?", help="fact id, e.g. F-001 (omit with --grace-scan)")
    ap.add_argument("--json", action="store_true", help="machine-readable JSON output")
    ap.add_argument("--grace", action="store_true",
                    help="warn-only for assignment-class lint (one-cycle migration)")
    ap.add_argument("--grace-scan", action="store_true",
                    help="list assignment-class facts lacking value assertions, then exit")
    args = ap.parse_args(argv)

    if args.grace_scan:
        return _grace_scan(args.ws)
    if not args.fact_id:
        ap.error("fact_id is required (or use --grace-scan)")

    try:
        out = verify(args.ws, args.fact_id, grace=args.grace)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        lint = out.get("lint", {})
        if (not lint.get("ok")) or ("WARN" in lint.get("reason", "")):
            print(f"lint: {lint.get('reason')}")
        print(f"kunglao-verify {out['fact_id']} (claim {out['claim_id']}): "
              f"L1={out['l1']['verdict']} L2={out['l2']['verdict']} overall={out['overall']}")
        for a in out["anchors"]:
            print(f"  anchor @{a['byte_offset']} cmd={a['cmd']} expected={a['expected']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

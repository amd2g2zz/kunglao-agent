#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tool_value.py — #881 工具价值聚合器（join 键=claim id，归因=(scene, operation)）。

RC3 缺口本体：#880 观测出生把四类数据面落在盘上（toolfirst 双面行 / facts steps
溯源 / claim 结算行 / operation label），但没有任何东西把它们 join 成消费面读的
计数表。本模块补上聚合器 + 两处消费接线（tool_tiers.chain_for/inject_block 排序、
recall_files rerank）——**聚合器与消费接线必须同 PR**（issue #881 不可协商纪律），
否则聚合器就是下一个 lessons_telemetry（造完、测完、零调用方）。

输入面（全部既有，零新词表）：
  A  toolfirst_pass 行（detail=JSON {mode, keywords, tool}，含 claim）——dispatch
     文本 tool-catalog 标记的结构化落盘（hooks/worker_budget_gates.toolfirst_pass_record）
  B  facts/F*.md 的 `steps:` per-step tool 条目——步骤行含工具名=选中；含弃用
     标记词=弃用（结构化拒绝；标记词表见 DECLINE_MARKERS）
  C  claim 结算/outcome——runs/*.md（outcome_capture._parse_run 同一解析）+
     `claim_settled` 行（register_proven_gate.emit_settlements）
  D  claim 属性 `operation:` / `operation_tool:`（#880 set_claim_operation）

计数口径（可复算声明）：
  cite   = 选中 ∧ claim 存活（verify passes / redteam CONFIRMED / 结算
           PROVEN|VERIFIED）——正样本
  burn   = 选中 ∧ 负样本（redteam REFUTED / verify fails / 结算
           REFUTED|NEGATIVE|DEAD）；redteam 拒绝是决定性负信号
  reject = 弃用（steps 弃用条目）。**不入后验**——"未选用"≠"失败"，混入即口径
           污染；reject 只进报表，对接 #866-b 存量鉴定 retirement 决策
  未结算（partial / UNVERIFIED / OPEN）→ 既非 cite 也非 burn
  utility = (cite + α0) / (cite + burn + α0 + β0)，α0=k·p0，β0=k·(1−p0)，
           k=PRIOR_STRENGTH，p0=静态链 rank 先验 (T−rank)/(T+1)，链外 0.5 中性。
           零数据 = 纯静态先验（与 #812 现状同序）；计数累积后自然翻转（蓝图 §8
           bandit 形态——先验有重力，不写死也不强制）。

输出表：runs/.tool-value.json（schema kunglao.tool-value/1，派生缓存可整体重算，
recall_metrics 隐藏 dotfile 同惯例）。消费方只读表（recall 5s 预算内 O(1)），
表由本 CLI（默认或 --write 语义）重算——消费面不扫全量源（账本日文件可增长）。

Faces:
  aggregate(ws)               -> dict                  四输入 join → rows
  write_table(ws, table=None) -> Path                  原子写表
  load_table(ws)              -> dict | None           tolerant 读（坏表 None）
  pooled_utilities(table)     -> dict                  工具级池化（跨 operation）
  report_rows(agg)            -> list                  排序（零使用沉底可见）
  beta_utility(cite,burn,p0)  -> float                 纯函数
  main(argv)                  -> int                   CLI（默认写表+摘要；
                                                       --report 可答"该
                                                       (scene,operation) 下哪些
                                                       工具 utility 最高"）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

SCHEMA = "kunglao.tool-value/1"
TABLE_NAME = ".tool-value.json"
UNLABELED = "(unlabeled)"
PRIOR_STRENGTH = 4.0

# positive/negative settlement faces (single source: status_defs.TERMINAL split)
POSITIVE_SETTLEMENTS = {"PROVEN", "VERIFIED"}
NEGATIVE_SETTLEMENTS = {"REFUTED", "NEGATIVE", "DEAD"}

# Input B structured-rejection markers (agents/kunglao-worker.md:182 — "hit a
# candidate but decide not to use it → record the reason in steps:"). A steps
# line naming a tool AND carrying one of these markers counts the tool as
# rejected, not selected. CJK markers substring-matched, ASCII ones too (the
# line context is already lowercase).
DECLINE_MARKERS = (
    "not used", "not adopted", "skipped", "rejected", "abandoned",
    "inapplicable", "not applicable", "弃用", "不采用", "跳过", "放弃", "不适用",
)


def normalize_tool(name: str) -> str:
    """'jadx --classes-to-decompile <prefixes>' -> 'jadx' (tier-table tool
    entries are CLI-shaped; the counting key is the binary/CLI head token)."""
    parts = str(name or "").split()
    return parts[0].strip(",;").lower() if parts else ""


def beta_utility(cite: int, burn: int, p0: float,
                 k: float = PRIOR_STRENGTH) -> float:
    """β-Bernoulli posterior mean with the static-tier prior. Pure (no I/O)."""
    a0 = k * p0
    b0 = k * (1.0 - p0)
    trials = max(int(cite or 0), 0) + max(int(burn or 0), 0)
    return (max(int(cite or 0), 0) + a0) / (trials + a0 + b0)


def line_tool_hits(line: str, names) -> set[str]:
    """Tool names mentioned in one line — the SINGLE matching rule shared by
    the facts-steps face (input B) and the recall rerank (wiring 2).

    - single-token names: exact token membership ('jadx', 'strings') — prose
      like 'restructuring' can never hit 'strings';
    - multi-token names (hyphen/underscore): the name must appear with its
      separators in the raw line ('crypto-tool', 'jadx-decompile') — plain
      word adjacency ('jadx decompile' = jadx decompiling something) must NOT
      hit the registered tool 'jadx-decompile'.
    """
    low = str(line or "").lower()
    tokens = set(re.findall(r"[a-z0-9]+", low))
    hits: set[str] = set()
    for name in names:
        name = str(name or "").strip().lower()
        if len(name) < 3:
            continue
        if "-" in name or "_" in name:
            pat = r"[-_]".join(re.escape(p)
                               for p in re.split(r"[-_]", name))
            if re.search(pat, low):
                hits.add(name)
        elif name in tokens:
            hits.add(name)
    return hits


# ---------------- priors / universe (static tier table = the prior) ----------

def _tier_data() -> dict:
    try:
        import tool_tiers
        return tool_tiers.load() or {}
    except Exception:  # noqa: BLE001 — prior is best-effort, fail-open
        return {}


def _tier_priors(scene_key: str) -> dict[str, dict]:
    """norm-tool -> {tier, prior}. First tier occurrence wins for duplicates."""
    data = _tier_data()
    scene = (data.get("scenes") or {}).get(scene_key) or {}
    chain = (scene.get("downgrade_chain") or
             (data.get("fallback") or {}).get("downgrade_chain") or [])
    tier_defs = scene.get("tier_defs") or {}
    total = len(chain)
    out: dict[str, dict] = {}
    for rank, tier in enumerate(chain):
        p0 = (total - rank) / (total + 1) if total else 0.5
        for raw in ((tier_defs.get(tier) or {}).get("tools") or []):
            norm = normalize_tool(raw)
            if norm and norm not in out:
                out[norm] = {"tier": tier, "prior": p0}
    return out


def _tool_universe(priors: dict[str, dict]) -> list[str]:
    """Registered tools (tools/_INDEX.yaml) + tier-table heads — the universe
    zero-use rows are drawn from (#866-b: 零使用工具沉底可见)."""
    names = set(priors)
    here = Path(__file__).resolve()
    for base in (here.parent, *here.parents):
        idx = base / "tools" / "_INDEX.yaml"
        if idx.is_file():
            try:
                data = yaml.safe_load(idx.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                break
            for entry in (data.get("tools") or []):
                if isinstance(entry, dict) and entry.get("name"):
                    names.add(str(entry["name"]).strip().lower())
            break
    return sorted(names)


# ---------------- input faces (each fail-open to empty) ----------------------

def _register_attrs(ws: Path) -> dict[str, dict]:
    """Input D: claim -> {operation, operation_tool} from claim-register.yaml."""
    try:
        data = yaml.safe_load(
            (ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    out: dict[str, dict] = {}
    for c in (data.get("claims") or []):
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id", "") or "").strip()
        if not cid:
            continue
        out[cid] = {
            "operation": str(c.get("operation", "") or "").strip() or None,
            "operation_tool": str(c.get("operation_tool", "") or "").strip()
                              or None,
        }
    return out


def _pass_rows(ws: Path) -> dict[str, list[tuple[list, str | None]]]:
    """Input A: claim -> [(keywords, tool)] from toolfirst_pass ledger rows."""
    try:
        from kunglao_log import _all_rows
        rows = [r for r in _all_rows(ws)
                if r.get("action") == "toolfirst_pass"
                and str(r.get("claim") or "").strip()]
    except Exception:  # noqa: BLE001 — ledger absent/unreadable -> empty
        return {}
    out: dict[str, list] = {}
    for r in rows:
        try:
            detail = json.loads(str(r.get("detail") or ""))
        except json.JSONDecodeError:
            continue
        if not isinstance(detail, dict):
            continue
        out.setdefault(str(r["claim"]).strip(), []).append(
            (list(detail.get("keywords") or []), detail.get("tool")))
    return out


def _settlement_outcomes(ws: Path) -> dict[str, set[str]]:
    """Input C (settlement face): claim -> {positive|negative} signals from
    claim_settled rows (to ∈ status_defs.TERMINAL split)."""
    try:
        from kunglao_log import _all_rows
        rows = [r for r in _all_rows(ws)
                if r.get("action") == "claim_settled"
                and str(r.get("claim") or "").strip()]
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, set] = {}
    for r in rows:
        try:
            detail = json.loads(str(r.get("detail") or ""))
        except json.JSONDecodeError:
            continue
        to = str((detail or {}).get("to") or "").upper()
        sig = ("positive" if to in POSITIVE_SETTLEMENTS else
               "negative" if to in NEGATIVE_SETTLEMENTS else None)
        if sig:
            out.setdefault(str(r["claim"]).strip(), set()).add(sig)
    return out


def _run_outcomes(ws: Path) -> dict[str, set[str]]:
    """Input C (runs face): latest verify-note / red-team result per claim.
    Reuses outcome_capture._parse_run — the single runs/*.md parser."""
    runs = ws / "runs"
    if not runs.is_dir():
        return {}
    try:
        from outcome_capture import _parse_run
    except Exception:  # noqa: BLE001 — parser import failed, runs face empty
        return {}
    latest: dict[tuple[str, str], tuple[int, str]] = {}
    for p in runs.glob("*.md"):
        name = p.name
        if "-verify-" not in name and "verify-redteam" not in name:
            continue
        entry = _parse_run(p)
        if entry is None:
            continue
        cid = str(entry.get("claim_id", "") or "").strip()
        checker = str(entry.get("checker", "") or "")
        if not cid or not checker:
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        key = (cid, checker)
        if key not in latest or mtime >= latest[key][0]:
            latest[key] = (mtime, str(entry.get("result", "") or ""))
    out: dict[str, set] = {}
    for (cid, checker), (_m, result) in latest.items():
        res = result.lower()
        if checker == "red-team":
            sig = "negative" if res == "refuted" else \
                  "positive" if res == "confirmed" else None
        else:
            sig = "positive" if res == "passes" else \
                  "negative" if res == "fails" else None
        if sig:
            out.setdefault(cid, set()).add(sig)
    return out


def _claim_outcomes(ws: Path) -> dict[str, str]:
    """Merged outcome per claim: any negative signal wins (a red-team refuted
    claim is negative even if an earlier verify-note passed — the issue's
    'redteam 拒=负样本'), else any positive, else unsettled (None)."""
    merged: dict[str, set] = {}
    for face in (_run_outcomes(ws), _settlement_outcomes(ws)):
        for cid, sigs in face.items():
            merged.setdefault(cid, set()).update(sigs)
    return {cid: ("negative" if "negative" in sigs else "positive")
            for cid, sigs in merged.items()}


def _facts_tools(ws: Path, vocab: set[str]) -> dict[str, dict]:
    """Input B: claim -> {selected: [tool], rejected: [tool]} from facts
    F*.md `steps:` blocks. Frontmatter claim_id (same shape
    outcome_capture._claim_from_note parses); a steps line naming a tool is a
    selection, unless it carries a DECLINE_MARKERS marker (structured
    rejection, agents/kunglao-worker.md:182)."""
    facts = ws / "facts"
    if not facts.is_dir():
        return {}
    voc = [v for v in vocab if v and len(v) >= 3]
    out: dict[str, dict] = {}
    for p in sorted(facts.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        front = text.split("---", 2)
        m = (re.search(r"^claim_id:\s*(\S+)", front[1], re.M)
             if len(front) >= 3 else None)
        if not m:
            continue
        cid = m.group(1).strip()
        lines = text.splitlines()
        steps_idx = next((i for i, ln in enumerate(lines)
                          if re.match(r"^steps:\s*$", ln)), None)
        if steps_idx is None:
            continue
        sel: set[str] = set()
        rej: set[str] = set()
        for ln in lines[steps_idx + 1:]:
            if not (ln.startswith("-") or ln[:1].isspace()):
                break  # next top-level field (fallback: / heading) ends steps
            declined = any(mk in ln.lower() for mk in DECLINE_MARKERS)
            hits = line_tool_hits(ln, voc)
            for name in hits:
                (rej if declined else sel).add(name)
        entry = out.setdefault(cid, {"selected": set(), "rejected": set()})
        entry["selected"] |= sel
        entry["rejected"] |= rej
    return out


# ---------------- aggregation ------------------------------------------------

def aggregate(ws: Path | str) -> dict:
    """Join the four input faces on claim id -> (scene, operation, tool) rows
    with cite/burn/reject counts and the β-Bernoulli utility. Pure read + compute."""
    ws = Path(ws)
    try:
        import tool_tiers
        scene = tool_tiers.scene_for(ws)
    except Exception:  # noqa: BLE001 — scene sniff fails -> default
        scene = "generic-binary"
    priors = _tier_priors(scene)
    universe = _tool_universe(priors)
    attrs = _register_attrs(ws)
    passes = _pass_rows(ws)
    outcomes = _claim_outcomes(ws)
    facts = _facts_tools(ws, set(universe))

    counts: dict[tuple[str, str], list[int]] = {}

    def bump(op: str, tool: str, idx: int) -> None:
        cell = counts.setdefault((op, tool), [0, 0, 0])
        cell[idx] += 1

    touched: set[str] = set()
    claims = set(attrs) | set(passes) | set(outcomes) | set(facts)
    for cid in sorted(claims):
        attr = attrs.get(cid, {})
        kw_ops: list[str] = []
        for keywords, _t in passes.get(cid, []):
            kw_ops.extend(str(k) for k in keywords if k)
        op = (attr.get("operation") or
              ",".join(dict.fromkeys(kw_ops)) or UNLABELED)
        sel: set[str] = set()
        ot = attr.get("operation_tool")
        if ot and ot.lower() != "none":
            sel.add(ot)
        for _kw, tool in passes.get(cid, []):
            if tool:
                sel.add(str(tool))
        f = facts.get(cid, {})
        sel |= set(f.get("selected", ()))
        rej = set(f.get("rejected", ())) - sel
        outcome = outcomes.get(cid)
        for tool in sorted(sel):
            touched.add(tool)
            if outcome == "positive":
                bump(op, tool, 0)
            elif outcome == "negative":
                bump(op, tool, 1)
        for tool in sorted(rej):
            touched.add(tool)
            bump(op, tool, 2)

    rows: list[dict] = []
    for (op, tool), (cite, burn, reject) in sorted(counts.items()):
        pr = priors.get(tool, {"tier": "unlisted", "prior": 0.5})
        rows.append({
            "scene": scene, "operation": op, "tool": tool,
            "cite": cite, "burn": burn, "reject": reject,
            "tier": pr["tier"], "prior": pr["prior"],
            "utility": beta_utility(cite, burn, pr["prior"]),
            "zero_use": False,
        })
    seen = {r["tool"] for r in rows}
    # 零使用工具沉底可见（#866-b retirement face): registered/universe tools
    # with zero evidence get an explicit all-zero row, ranked last by report.
    for tool in universe:
        if tool in seen:
            continue
        pr = priors.get(tool, {"tier": "unlisted", "prior": 0.5})
        rows.append({
            "scene": scene, "operation": UNLABELED, "tool": tool,
            "cite": 0, "burn": 0, "reject": 0,
            "tier": pr["tier"], "prior": pr["prior"],
            "utility": beta_utility(0, 0, pr["prior"]),
            "zero_use": True,
        })
    return {
        "schema": SCHEMA,
        "generated_ts": datetime.now(tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "scene": scene,
        "rows": rows,
    }


# ---------------- table I/O ---------------------------------------------------

def table_path(ws: Path | str) -> Path:
    return Path(ws) / "runs" / TABLE_NAME


def write_table(ws: Path | str, table: dict | None = None) -> Path:
    """Atomic write (tmp + os.replace) — derived cache, whole-file recompute."""
    ws = Path(ws)
    table = table if table is not None else aggregate(ws)
    path = table_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(table, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_table(ws: Path | str) -> dict | None:
    """Tolerant read for consumers: missing/corrupt/shape-wrong -> None
    (fail-open — a broken table must never break dispatch or recall)."""
    try:
        raw = table_path(ws).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        table = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if (not isinstance(table, dict) or table.get("schema") != SCHEMA
            or not isinstance(table.get("rows"), list)):
        return None
    return table


def pooled_utilities(table: dict) -> dict[str, dict]:
    """Tool-level pooling across operations: cite/burn summed, utility
    RECOMPUTED from pooled counts + prior (not an average of row utilities —
    the counting basis must survive the pooling)."""
    pooled: dict[str, dict] = {}
    for r in table.get("rows") or []:
        tool = str(r.get("tool", "") or "")
        if not tool:
            continue
        cell = pooled.setdefault(tool, {
            "cite": 0, "burn": 0, "prior": float(r.get("prior", 0.5))})
        cell["cite"] += int(r.get("cite", 0) or 0)
        cell["burn"] += int(r.get("burn", 0) or 0)
    for tool, cell in pooled.items():
        cell["utility"] = beta_utility(cell["cite"], cell["burn"],
                                       cell["prior"])
    return pooled


# ---------------- report (acceptance: the query is answerable) ---------------

def report_rows(agg: dict) -> list[dict]:
    """Ranked rows: tools with evidence first (utility desc), zero-use tools
    after every evidenced one (沉底可见), names as the final tie-break."""
    return sorted(
        agg.get("rows") or [],
        key=lambda r: (0 if (r.get("cite", 0) + r.get("burn", 0)
                             + r.get("reject", 0)) > 0 else 1,
                       -float(r.get("utility", 0.0)),
                       str(r.get("tool", ""))))


def _print_report(agg: dict, operation: str | None) -> None:
    ranked = report_rows(agg)
    ops: list[str] = []
    for r in ranked:
        if r["operation"] not in ops:
            ops.append(r["operation"])
    printed = False
    for op in ops:
        if operation is not None and op != operation:
            continue
        group = [r for r in ranked if r["operation"] == op]
        if not group:
            continue
        printed = True
        print(f"[{op}] scene={agg.get('scene')} tools by utility "
              f"(top = answer):")
        for r in group:
            flag = ("  <- zero-use (retirement candidate, #866-b)"
                    if r.get("zero_use") else "")
            print("  {:<28} utility={:.3f} cite={} burn={} reject={} "
                  "tier={}{}".format(
                      r["tool"], float(r["utility"]), r["cite"], r["burn"],
                      r["reject"], r["tier"], flag))
    if not printed:
        print(f"no tool-value rows for scene={agg.get('scene')}"
              + (f" operation={operation}" if operation else ""))


def main(argv: list[str] | None = None) -> int:
    """CLI. Default: recompute + write table + one-line summary. --report: the
    one-command answer to 'which tools rank highest for (scene, operation)'."""
    ap = argparse.ArgumentParser(
        prog="tool_value.py",
        description="#881 tool-value aggregator: 4 input faces -> "
                    "(scene, operation, tool) cite/burn/reject + "
                    "beta-Bernoulli utility")
    ap.add_argument("workspace", help="workspace root (claim-register.yaml)")
    ap.add_argument("--report", action="store_true",
                    help="print the ranked utility table (the query face)")
    ap.add_argument("--operation", default=None,
                    help="filter the report to one operation label")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable table on stdout")
    args = ap.parse_args(argv)

    ws = Path(args.workspace)
    table = aggregate(ws)
    path = write_table(ws, table)
    if args.report:
        _print_report(table, args.operation)
        return 0
    if args.json:
        print(json.dumps(table, ensure_ascii=False))
        return 0
    print(f"tool-value table written: {path} "
          f"({len(table['rows'])} rows; scene={table['scene']})")
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())

# -*- coding: utf-8 -*-
"""status_narration.py — #811 状态叙事面（成就前沿的只读投影）。

生产实证（issue #811）：用户只能靠问「现在是什么情况」「简单介绍一下
分析结果」补座舱——座舱存在但没接线。本模块是那一条命令：四要素结构化
摘要 + 中文叙事，全部读自既有单源面，绝不二次推导。

四要素（每要素一个 face，absent 形状诚实）：

    current    当前 claim + 统一模型投影：episode_phase + commit 菜单
               （rlvr/meta_policy.PHASE_ACTIONS 只读投影——本面只报菜单，
               不替 meta-policy 选动作）
    blockers   活跃阻塞（convergence_check._active_blockers 单源）
    next       排队候选（decision_view.next_candidates 单源）+ 下一步
               how（在途 claim 报其 commit 菜单；空线报候选首）
    waiting_on 等谁：双门 open case（等 verifier+redteam）+ 活跃阻塞
               （等 operator）

契约（同 decision_view 形状）：SCHEMA/FACES/FACE_KEYS 钉形；build_view
永不 raise——一个源缺失/不可读/异常只降级它自己的 face（键在、诚实
null），一条 canonical warn。只读投影钉：不写工作区任何字节。
CLI：`python scripts/status_narration.py <ws>` = 中文叙事一条命令；
`--json` = 结构化 envelope。零遥测点（Standard 11：读面不 emit）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kunglao_log import warn  # canonical warn: ONE implementation
from _scriptlib import read_register_claims
from status_defs import IN_PROGRESS_STATUSES

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

SCHEMA = "status-narration/1"

#: 要素序：先说在跑什么，再说卡在哪，再说下一步，最后说在等谁。
FACES = ("current", "blockers", "next", "waiting_on")

#: 每个 face 的精确键集（renderer 按 contract 键，不按文件存在性）。
FACE_KEYS = {
    "current": ("claim", "status", "phase", "commit_menu"),
    "blockers": ("items", "count"),
    "next": ("candidates", "commit_menu", "how"),
    "waiting_on": ("items", "count"),
}

#: 每个 face 的 documented absent 形状（键在、诚实 null）——fail-open 落点。
ABSENT = {
    "current": {"claim": None, "status": None, "phase": None,
                "commit_menu": None},
    "blockers": {"items": [], "count": 0},
    "next": {"candidates": [], "commit_menu": None, "how": None},
    "waiting_on": {"items": [], "count": 0},
}

_DUAL_GATE_DIR = Path("runs") / "dual-gate"


# ------------------------------------------------------------- face builders

def _face_current(ws: Path) -> dict:
    from rlvr import meta_policy as mp  # noqa: PLC0415 — lazy（dispatch_context 同形）
    claims = [c for c in read_register_claims(ws)
              if str(c.get("status") or "") in IN_PROGRESS_STATUSES]
    claims.sort(key=lambda c: str(c.get("id") or ""))
    if not claims:
        return dict(ABSENT["current"])
    claim = str(claims[0].get("id") or "")
    phase = mp.episode_phase(ws, claim)
    return {"claim": claim, "status": str(claims[0].get("status") or ""),
            "phase": phase,
            "commit_menu": tuple(mp.PHASE_ACTIONS.get(phase) or ())}


def _face_blockers(ws: Path) -> dict:
    from convergence_check import _active_blockers  # noqa: PLC0415 — 单源
    ids = sorted(_active_blockers(ws))
    return {"items": [{"id": i} for i in ids], "count": len(ids)}


def _face_next(ws: Path, current: dict) -> dict:
    import decision_view as dv  # noqa: PLC0415 — next_candidates 单源
    view = dv.build_view(ws)
    rows = list(view["faces"]["next_candidates"]["candidates"])
    menu = current.get("commit_menu") or None
    if current.get("claim"):
        how = (f"在途 {current['claim']} 处于 {current['phase']}；"
               f"边界可选动作：{'/'.join(menu)}（meta-policy 定夺，本面只投影）")
    elif rows:
        first = rows[0]
        how = f"无在途 claim；dispatch 队首候选 {first.get('claim')}"
    else:
        how = "无在途 claim，无排队候选——等待新输入"
    return {"candidates": rows, "commit_menu": menu, "how": how}


def _face_waiting_on(ws: Path) -> dict:
    items: list[dict] = []
    dg = ws / _DUAL_GATE_DIR
    if dg.is_dir():
        for p in sorted(dg.glob("*.json")):
            try:
                case = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if case.get("status") == "open":
                items.append({"what": f"双门 case {case.get('case_id')}",
                              "whom": "verifier+redteam"})
    try:
        from convergence_check import _active_blockers  # noqa: PLC0415 — 单源
        for bid in sorted(_active_blockers(ws)):
            items.append({"what": f"阻塞 {bid}", "whom": "operator"})
    except Exception as exc:  # noqa: BLE001 — per-face fail-open
        warn("status_narration.waiting_on", f"{type(exc).__name__}: {exc}")
    return {"items": items, "count": len(items)}


_BUILDERS = {"current": _face_current, "blockers": _face_blockers,
             "next": None, "waiting_on": _face_waiting_on}


def build_view(ws) -> dict:
    """四要素视图：{"schema", "faces"}，每个 face 恰带 FACE_KEYS 键集。

    Fail-open by contract：每 face 自带护栏——缺失/不可读/异常源降级
    它自己的 absent 形状（键在、诚实 null）+ 一条 canonical warn；
    build_view 本身永不 raise。next 依赖 current（commit 菜单投影），
    按序组装、不二次读 register。"""
    ws = Path(ws)
    faces: dict[str, dict] = {}
    for name in FACES:
        try:
            if name == "next":
                faces[name] = _face_next(ws, faces["current"])
            else:
                faces[name] = _BUILDERS[name](ws)
        except Exception as exc:  # noqa: BLE001 — per-face fail-open
            warn("status_narration." + name, f"{type(exc).__name__}: {exc}")
            faces[name] = dict(ABSENT[name])
    return {"schema": SCHEMA, "faces": faces}


# ------------------------------------------------------------- 中文叙事

def render_zh(view: dict) -> str:
    """四要素中文叙事（生产用户是中文）。确定性：无时间戳、无随机。"""
    f = view["faces"]
    cur = f["current"]
    if cur.get("claim"):
        menu = "/".join(cur.get("commit_menu") or ()) or "—"
        line_cur = (f"【当前】{cur['claim']}（{cur.get('status')}，"
                    f"phase={cur.get('phase')}，可选动作：{menu}）")
    else:
        line_cur = "【当前】无进行中 claim"
    blk = f["blockers"]
    if blk["count"]:
        ids = "、".join(i["id"] for i in blk["items"])
        line_blk = f"【阻塞】{blk['count']} 项：{ids}"
    else:
        line_blk = "【阻塞】无"
    nxt = f["next"]
    parts = []
    for row in nxt.get("candidates") or []:
        parts.append(f"候选 {row.get('claim')}")
    if parts:
        line_next = f"【下一步】{'；'.join(parts)}——{nxt.get('how')}"
    else:
        line_next = f"【下一步】{nxt.get('how') or '无'}"
    wo = f["waiting_on"]
    if wo["count"]:
        segs = [f"{i['what']}（等 {i['whom']}）" for i in wo["items"]]
        line_wo = f"【等待】{'；'.join(segs)}"
    else:
        line_wo = "【等待】无"
    return "\n".join([line_cur, line_blk, line_next, line_wo])


# ------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="status narration — 当前 claim/blockers/next/"
                    "waiting-on 四要素中文叙事（只读投影）")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--json", action="store_true",
                    help="print the structured envelope instead of zh text")
    args = ap.parse_args(argv)
    view = build_view(args.workspace)
    if args.json:
        print(json.dumps(view, ensure_ascii=False, sort_keys=True,
                         default=list))
    else:
        print(render_zh(view))
    return 0


if __name__ == "__main__":
    sys.exit(main())

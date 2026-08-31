#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intake_promise.py — Phase 0 预扫描 promise 块 (#813)。

init 在 toolchain 门通过后、scaffold 前，把预扫描状态显式落盘：
  - prescan.apkid / prescan.die：探测状态（missing = WARN 显式记录 + fix
    提示——消灭"跳过且不记录"；#813 豆包现场病理）
  - obfuscation_prior：evidence/apkid.json 存在时提取 summary.obfuscator
    （与 route_capability #692 WP6 同源同键）
  - java_reachability：jadx/baksmali/apktool × constraints.dynamic_re →
    reachable / degraded / unreachable；static-only + 非 reachable →
    显式 #807 死胡同警示
  - prescan_obligation：首 claim 必须是 T1 预扫描（#669）的机械备忘

落盘面：task_spec.yaml 的 `promise:` 键（合并不覆盖用户键）；task_spec
缺失 → 降级写 runs/intake-promise.yaml（同一 schema）；task_spec 存在但
不可解析 → PromiseError（fail-closed，不静默丢弃）。

本模块只落盘，不接值函数——promise 块是 #823 V_m 的 t=0 输入供应者。
分级铁律（memory）：apkid/DIE 缺失是 WARN 不卡 init；显式记录不等于阻断。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

PRESCAN_TOOLS = ("apkid", "die")
JAVA_FRONTENDS = ("jadx", "baksmali", "apktool")
OBLIGATION = ["evidence/apkid.json", "evidence/die.json"]


class PromiseError(Exception):
    """task_spec 存在但不可解析——fail-closed，不静默降级。"""


def _now_z() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _status_name(item) -> str:
    """duck-type：enum（.name）与字符串 'PASS' 一致处理。"""
    st = getattr(item, "status", None)
    return getattr(st, "name", None) or str(st or "").upper()


def _item_note(item) -> str:
    fix = (getattr(item, "fix", None) or "").strip()
    return fix if fix else "probe failed - install the tool before prescan"


def _item_state(status_name: str) -> str:
    if status_name == "PASS":
        return "available"
    if status_name == "WARN":
        return "degraded"
    return "missing"


def _prescan(report) -> dict:
    items = {i.name: i for i in (getattr(report, "items", None) or [])}
    prescan: dict = {}
    for tool in PRESCAN_TOOLS:
        item = items.get(tool)
        if item is None:
            prescan[tool] = {
                "state": "not_probed",
                "tier": "WARN",
                "note": "layer not in this project_type's probe set "
                        "- must still run at first claim (#669)",
            }
            continue
        st = _status_name(item)
        prescan[tool] = {
            "state": _item_state(st),
            "tier": "WARN",
            "note": _item_note(item) if st == "FAIL" else
                    f"probe {st.lower()}",
        }
    return prescan


def _obfuscation_prior(ws: Path) -> dict:
    """evidence/apkid.json → summary.obfuscator（#692 WP6 同键）。"""
    p = ws / "evidence" / "apkid.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        summary = data.get("summary") if isinstance(data, dict) else None
        rules = (summary or {}).get("obfuscator") if isinstance(
            summary, dict) else None
        return {"source": "evidence/apkid.json",
                "obfuscators": [str(r) for r in (rules or [])]}
    except (OSError, ValueError):
        return {"source": None, "obfuscators": []}


def _java_reachability(report, task_spec) -> dict:
    items = {i.name: i for i in (getattr(report, "items", None) or [])}
    fronts = {}
    for tool in JAVA_FRONTENDS:
        item = items.get(tool)
        fronts[tool] = _status_name(item) == "PASS" if item else False
    constraints = (task_spec or {}).get("constraints") or {}
    static_only = (constraints.get("dynamic_re") == "forbidden")

    if fronts["jadx"]:
        verdict = "reachable"
    elif fronts["baksmali"] or fronts["apktool"]:
        verdict = "degraded"
    else:
        verdict = "unreachable"

    note = (f"jadx={'yes' if fronts['jadx'] else 'no'} "
            f"baksmali={'yes' if fronts['baksmali'] else 'no'} "
            f"apktool={'yes' if fronts['apktool'] else 'no'}")
    if static_only and verdict != "reachable":
        note += ("; static-only workspace without a reachable java "
                 "frontend is a known dead end (#807) - degradate the "
                 "route or fix constraints")
    if task_spec is None:
        note += "; task_spec absent - constraints unknown at promise time"
    return {"verdict": verdict, "static_only": static_only,
            "note": note.strip()}


def build(report, task_spec, ws) -> dict:
    """纯函数：toolchain 报告 + task_spec + ws → promise dict。

    report duck-types toolchain.ToolchainReport（.items[].name/.status/.fix）。
    """
    ws = Path(ws)
    return {
        "generated_at": _now_z(),
        "prescan": _prescan(report),
        "obfuscation_prior": _obfuscation_prior(ws),
        "java_reachability": _java_reachability(report, task_spec),
        "prescan_obligation": {
            "required": list(OBLIGATION),
            "note": "first claim must be the T1 pre-scan (#669) - "
                    "these artifacts gate deep-analysis claims",
        },
    }


def apply(ws, promise: dict) -> Path:
    """把 promise 合并进 task_spec.yaml `promise:` 键（不覆盖用户键）。

    task_spec 缺失 → runs/intake-promise.yaml（同一 schema）。
    task_spec 存在但不可解析 → PromiseError（fail-closed）。
    """
    ws = Path(ws)
    spec_path = ws / "task_spec.yaml"
    if spec_path.exists():
        try:
            spec = yaml.safe_load(
                spec_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise PromiseError(
                f"task_spec.yaml unparseable: {exc}") from exc
        if not isinstance(spec, dict):
            raise PromiseError(
                f"task_spec.yaml must be a YAML mapping, got "
                f"{type(spec).__name__}")
        spec["promise"] = promise
        spec_path.write_text(
            yaml.safe_dump(spec, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        return spec_path
    out = ws / "runs" / "intake-promise.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        yaml.safe_dump(promise, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI face: python intake_promise.py <ws> — which(1) 级探测落 promise。"""
    import argparse
    import shutil
    from types import SimpleNamespace

    ap = argparse.ArgumentParser(
        description="#813: write the intake promise block")
    ap.add_argument("workspace", type=Path)
    args = ap.parse_args(argv)
    ws = args.workspace

    probe_items = []
    for tool in JAVA_FRONTENDS + PRESCAN_TOOLS:
        ok = shutil.which(tool) is not None
        probe_items.append(SimpleNamespace(
            name=tool, status="PASS" if ok else "FAIL",
            fix=f"install {tool}"))
    promise = build(SimpleNamespace(items=probe_items), None, ws)
    path = apply(ws, promise)
    print(f"intake-promise: wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

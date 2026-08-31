# Proposal: issue-813-intake-promise

## Why

豆包现场（2026-08-28）：apkid/DIE 预扫描层整体被跳过（evidence/ 无 apkid.json、
无 die.json），route_capability #692 WP6 的混淆先验消费端静默兜底 `[]`——
上游断链被 fail-open 掩盖，下游无感知降级。staged 工作流是文档性契约而非
机械契约；#807 同根：static-only 场景 java 前端可达性从未被显式判定。

本卡把"跳过且不记录"消灭在 Phase 0：init 在 toolchain 门通过后、scaffold 前，
把预扫描状态作为 **promise 块**显式落盘 task_spec.yaml。

## What Changes

1. 新 `scripts/intake_promise.py`：
   - `build(report, task_spec, ws)` — 纯函数，产出 promise dict：
     - `prescan.apkid / prescan.die`：available / missing / not_probed
       （missing = WARN 显式记录 + fix 提示，不静默）
     - `obfuscation_prior`：evidence/apkid.json 存在时提取
       `summary.obfuscator`（与 route_capability 同源同键），否则 source=null
     - `java_reachability`：jadx/baksmali/apktool × constraints.dynamic_re
       → reachable / degraded / unreachable；static-only + 非 reachable
       → 显式 #807 死胡同警示
     - `prescan_obligation`：首 claim 必须是 T1 预扫描（#669）的机械备忘
   - `apply(ws, promise)` — task_spec.yaml 存在则合并 `promise:` 键
     （不覆盖用户键；不可解析 → `PromiseError` fail-closed）；缺失则降级
     写 `runs/intake-promise.yaml`（同一 schema）
2. `kunglao-init.py` 接线：toolchain 门通过后（`skip_toolchain` 时跳过）
   调 build+apply；promise 失败不卡 init（WARN-tier）但必须 ERROR +
   `env_incident` 落账——静默跳过才是病理
3. 本批次只落盘，不接值函数（promise 块即 #823 V_m 的 t=0 输入供应者）

## NOT Doing

- 不做 dispatch-gate 前置 REJECT（issue P0 的另一形态，归 #812 泳道）
- 不强制运行 apkid 扫描本身（那是首 claim 的活；promise 只记录义务与状态）
- 不动 toolchain HARD/WARN 分级（memory 铁律：apkid 缺失 WARN 不卡 init）

## Impact

- 新文件：scripts/intake_promise.py、tests/test_intake_promise_813.py
- 触点：scripts/kunglao-init.py（门后一处插入）
- schema：task_spec.yaml 增 `promise:` 键（向后兼容：旧 task_spec 无此键
  照常工作；消费者 #823 后续接入）

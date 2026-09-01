# issue-810-deploy-closure — 部署反转闭包盲区修复

## Why

豆包现场：部署 hooks 18/18 但 scripts 15/30、数据资产 0% —— worker 一跑关键 gate 即
`No such file 'D:\works\...\.claude\scripts\plan_drift_detector.py'` REJECT。
根因：#783 的 `scaffold_closure()` import-AST 闭包对 (1) 字符串拼路径的动态子进程
调用 (2) scripts↔scripts 调用链 (3) 非 py 数据资产 三类运行时依赖全盲。

## What Changes（用户裁决方向：完整部署，闭包语义不可救）

1. `build_entries()` 升级为**全量镜像**：hooks + agents + **scripts/*.py 全量**
   + **references/** + **templates/** + **tools/** 数据资产（kind=asset）。
   放弃闭包裁剪——动态引用形态穷举不完，正确性 > 体积。
2. import 闭包与**动态引用扫描**（hooks+scripts 源码中 `scripts/<name>.py`
   字符串路径形态）降级为**校验面**：`closure_validation()` 断言动态引用 ⊆
   已部署集合，缺失清单 fail-closed（--verify 返回非零并列出）。
3. `write_carrier` 载荷扩展 dests 列表；`scripts/hook_activation.completeness_report(ws)`
   消费载体断言部署面完整性；激活写入面（update_state/renew）接线：缺失 →
   `env_incident` 落账 + 明确报缺清单（不静默残废）。
4. `deployed_refresh`/`deploy_workspace_copy` 消费同一 build_entries —— 单源
   继承，无需改。

## Impact

- 部署体积上升（全量镜像）；P2 审计面 = --write 输出 entries 数+总字节。
- 消费方：deployed_refresh / kunglao_upgrade / init deploy_workspace_copy /
  hook_activation 激活面 / drift 三腿（digest 随 entries 变化，workspaces 需
  refresh 重锚——升级路径已有 carrier-stale 语义承接）。

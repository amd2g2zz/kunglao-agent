# Proposal: issue-823-p4-tuition — 学习环收官（P4）

## Why

#823 学习环（P1 欠账表/V_m、P2 ρ/Platt、P3 Q 表排序）已合入；缺最后的
结算消费面：把 ledger 里的 (ρ, z_self) 对重拟合为 Platt 系数建议、把同类
任务成本按 mission 序号聚合成学费曲线、并给出座舱 V/D/ETA 数据面。全部
离线（只读 ledger），零 API，无训练管线（硬边界 #823）。

## What Changes

- `scripts/tuition_refit.py`（新）：从 ledger rho_pair 行收集 (ρ,z_self)
  对 → `rho_verifier.fit_platt` 重拟合 → 产出 θ 提案 JSON（走
  `optimizer_core.make_proposal`，schema opt-proposal-v1，只含 PARAM_NAMES
  键，宪法隔离继承）——只提案不生效。对数不足（<10）时明确 insufficient，
  不产提案。
- `scripts/tuition_curve.py`（新）：
  - `missions_from_ledger(ws)`：settled rho_pair 行 → mission 记录
    （stratum 固定 "default"、ordinal=结算序、cost=duration_ms 代理，
    proposal 注明代理边界）
  - `curve(records)`：按 stratum 聚合 mean_cost/pass_rate 序列
  - `got_cheaper(records, stratum)`：前后半段均值比较的"变便宜"判定
    （每侧 ≥2 点，不足返回 None=insufficient）
  - `cockpit_summary(ws)`：V（value_m）+ D（history 斜率，末 W 点线性
    拟合）+ ETA（剩余缺口/|slope|，checkpoint 单位）+ tuition 摘要——
    结构化 dict，渲染层归座舱
- tests/test_tuition_p4.py：Platt 重拟合方向/提案宪法校验/insufficient、
  曲线变便宜判定、ledger 派生、cockpit 面合成 workspace 用例

## Impact

- Affected: 新文件 ×2 + 新测试；无决策路径改动（提案面与聚合面均为
  离线消费层）；catalog 两行；manifests 如 --verify 报 stale 则 --write
- Not done: 学费数据进四阶段门判据（数据积累后接 #833 优化器）；ρ 门
  进 completion（P3 遗留，独立小卡）；clawback 实施通道（P4 接口位）
- 决策面读口：cockpit_summary 供座舱/N5 渲染直接消费

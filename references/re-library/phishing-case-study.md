# Phishing Case Study: F040 routing-claim contamination

A documented incident where a same-topic PROVEN pair disagreed (F035 vs
F040) and the contaminated conclusion propagated into the fact base.

## 事故

F035 与 F040 同为 PROVEN、同 routing 主题、结论相反，且无 supersedes
链接。事实库冻结了错误的路由结论（fact_contradiction_gate #47 的事故根源）。

## 教训

1. 同一 topic-key 集（claim_id / sample_refs / cites 交集）下多个 PROVEN
   事实结论不一致时，必须显式 supersedes / superseded_by，否则整体
   PROVEN 结论不可信。
2. 完成前必须运行全局矛盾扫描（`fact_contradiction_gate.py <ws>`）；
   单个 promotion 的局部检查无法发现跨 claim 的矛盾对。

## 关联

- 检测器: `scripts/fact_contradiction_gate.py`
- 完成事务: `scripts/completion_gate.py`（全局重算）

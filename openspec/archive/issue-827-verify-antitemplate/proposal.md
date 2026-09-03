# issue-827-verify-antitemplate

## Why

plan_drift_detector 的 UNVERIFIED_EVIDENCE 以"文件存在 + 文件名含 claim id"为全部判据；
write_gate R1 的 md 路径以"fid in text + POSITIVE_VERDICT_RE"为判据。事故 workspace 用
265ms 单爆发写 8 个 2144 字节同构模板（仅替换 claim id，带 "KEEP status: PROVEN"），
两处判据全过 → UNVERIFIED_EVIDENCE 零发现 → dispatch gate 被解堵。文件存在 ≠ 验证发生。

## What Changes

- `scripts/plan_drift_detector.py` 新增 `credible_redteam_files(runs_dir)`：内容级反模板筛选层
  - (b) 授权标记：body 须含 `redteam`（red[-_ ]?team）+ verdict 词——canonical 生产者词表
    （drift 夹具 "RED-TEAM VERDICT:"；write_gate 夹具 "## redteam <fid>\nverdict:"）均命中；
    事故模板（KEEP status: PROVEN）不命中
  - (a) 爆发簇：≥3 个文件归一化体相同（claim/fact id 打码后 sha256 相等）且 mtime 跨度 ≤5s
    → 整簇排除（模板 fan-out 特征；独立于 (b)，marker 齐全的模板簇同样死）
- `extract_verified_claim_ids` 改用筛选后的文件集
- `scripts/write_gate.py`：`_fact_runs_records` 与 `_note_verify_record` 的 verify-redteam md
  接受面走同一筛选层
- 与 #828（expected hash 锚）/ #831（ledger 锚）同风格：凭证可对账；#825 dispatch ledger
  落地后由其接管（本卡是 cheap hardening 层，边界在 openspec tasks 记录）

## Impact

- Affected: scripts/plan_drift_detector.py, scripts/write_gate.py, 新 tests
- 语义：UNVERIFIED_EVIDENCE / R1 的"真文件"标准收紧；单文件高仿模板（全词表+非爆发）
  是已知残余，由 #825 身份 ledger 兜底

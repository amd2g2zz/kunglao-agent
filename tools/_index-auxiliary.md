# auxiliary 领域索引(工具层)

> 领域: 辅助/杂项工具(哈希、编码、文件元数据、运维测量)。worker 被派发到辅助性小任务时先读本文件, 再按需加载。契约字段含义见 [README.md](README.md), 机器契约见 [_INDEX.yaml](_INDEX.yaml)。类目 id 与目录名一致(`tools/auxiliary/`, #340); 沿革: 旧 id 为 `aux`, 因 `aux` 是 Windows 保留设备名无法作目录名, #340 改 id 随目录。

## 工具清单

| 工具 | 用途(一句话) | 何时读 / 何时不用 |
|---|---|---|
| `audit-legacy-proven` | legacy PROVEN claim 审计(BLIND 签名维度 + 索引溯源性) | 清理旧 PROVEN claim 状态时读; 无 legacy PROVEN 需审计时不用 |
| `capture-golden` | golden 用例采集(合成工作区 + CLI 参数) | 契约变更需重采 golden 基线时读; 常规分析不用 |
| `measure-blind-coverage` | BLIND 盲验覆盖率测量 | 评估盲验覆盖时读; 无需评估时不用 |
| `measure-cold-start` | 冷启动 token 基线测量 | 测量冷启动 token 基线时读; 非基线测量不用 |
| `sanitize-text` | 样本派生文本 prompt 注入净化(零宽/同形字/指令标记) | 样本派生文本喂给 LLM worker 前读; 文本不经 LLM 消费时不用 |

## 契约条目

### audit-legacy-proven

- **用途**: 审计 workspace 的 legacy PROVEN claim(BLIND 签名维度 + 索引溯源性)。
- **用法**:
  ```bash
  python tools/auxiliary/audit_legacy_proven.py <workspace> --json
  ```
- **输入**: workspace 根(位置参数, 必填; 读 claim-register.yaml + facts/_INDEX.md); 可选 `--output/--out`(JSON 落盘)/`--json`(stdout JSON)。
- **输出**: legacy PROVEN claim 审计 JSON/摘要(缺省输出 audit-<ws>-<ts>.json)。
- **exit code**: 0 成功 / 2 错误(workspace 不存在)。
- **when_not**: 无 legacy PROVEN claim 需审计清理时不使用。

### capture-golden

- **用途**: 按 CASES 清单重采 golden master 基线(合成工作区 + CLI 参数)。
- **用法**:
  ```bash
  python tools/auxiliary/capture_golden.py --refresh
  ```
- **输入**: CASES 清单(脚本内合成工作区 + CLI 参数); 可选 `--out <DIR>`(缺省 tests/fixtures/golden)。
- **输出**: tests/fixtures/golden/{manifest.yaml, F-NN/expected/stdout.txt}。
- **exit code**: 0 成功 / 2 错误(参数错误, argparse)。
- **when_not**: 仅契约变更流程用 `--refresh` 重采, 常规分析不用。

### measure-blind-coverage

- **用途**: 测量 PROVEN claim 的 BLIND 盲验覆盖率。
- **用法**:
  ```bash
  python tools/auxiliary/measure_blind_coverage.py <workspace> --json
  ```
- **输入**: workspace 根(位置参数, 必填; 读 claim-register.yaml + facts/*.md 的 verifier_sign_off); 可选 `--out`/`--reliability`。
- **输出**: BLIND 覆盖率 JSON(PROVEN/blind_signed/unverified/coverage)。
- **exit code**: 0 完成 / 2 错误(参数错误, argparse)。
- **when_not**: 无需评估盲验覆盖时不用。

### measure-cold-start

- **用途**: 逐文件 token 估算 workspace 状态文件清单, 输出冷启动基线。
- **用法**:
  ```bash
  python tools/auxiliary/measure_cold_start.py <workspace> --out <out.json>
  ```
- **输入**: workspace 根(位置参数, 必填; 读 claim-register.yaml/_INDEX/ledger/progress 等状态文件); 可选 `--rounds`。
- **输出**: docs/baselines/cold-start-tokens.json(逐文件 token 估算, 缺省路径)。
- **exit code**: 0 成功 / 2 错误(workspace 缺失)。
- **when_not**: 非冷启动基线测量时不使用。

### sanitize-text

- **用途**: 样本派生文本 prompt 注入净化: 零宽字符/同形字/指令标记检测与移除(喂 LLM worker 前的必经闸口)。
- **用法**:
  ```bash
  python tools/auxiliary/sanitize.py --in <样本派生文本> --mode full --json
  ```
- **输入**: 样本派生文本(`--in` 或标准输入) + `--mode zero-width|homoglyph|markers|full`; 可选 `--report-only`/`--sentinel-prefix`。
- **输出**: 净化文本或 JSON(zwx_count/homoglyph_count/marker_count/suspicious/sha256) + `--reproduce` field=value 行。
- **exit code**: 0 正发现(检出注入) / 1 负发现(未检出) / 2 错误。
- **when_not**: 文本不经 LLM worker 消费时不使用。

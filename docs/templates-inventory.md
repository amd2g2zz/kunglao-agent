# templates-inventory — 脚本模板化分类框架 (issue #278)

Issue #278 的两个半侧：

- **模板化半侧（本文件）** — 已完成：`templates/scripts/*.tmpl` 脚本生成模板 +
  `scripts/template_gen.py` 确定性生成器 CLI + 本文档的分类框架。
- **吸收半侧（BLOCKED）** — 盘点并迁移 D:\works\samples 下 236 个现场脚本。
  该 Windows 主机从当前 macOS 开发机不可达，吸收 pass 待主机可达后执行；
  届时按本文档的分类框架填写下方待填清单。

## 1. 分类框架（吸收 pass 的标准）

吸收 236 个现场脚本时，每个脚本按以下判据分类，并给出吸收建议。
分类不是对脚本质量的评价，而是"复用面有多大"的判定：

| 分类 | 判据（满足任一条即上浮，全部满足才下沉） | 吸收建议 | 落点 |
| --- | --- | --- | --- |
| 通用CLI (generic) | 逻辑与样本无关或仅参数化即可通用；对同类样本可重复使用；无单样本魔数 | migrate — 作为独立参数化 CLI 迁入 `scripts/`（#277 纪律），并在 `tools/_INDEX.yaml` 登记（若属分析工具） | scripts/ + tools/_INDEX.yaml |
| 半通用 (semi-generic) | 流程通用但含每样本常量（偏移、密钥地址、stage 表位置） | adapt — 抽取常量为参数；若流程骨架可复用，沉淀为模板 | templates/scripts/*.tmpl 或 scripts/ |
| 单样本定制 (one-off) | 针对单个样本的 ad-hoc 代码，无复用价值或无法参数化 | template — 保留为可复现骨架，用 `template_gen.py` 按样本实例化 | templates/scripts/*.tmpl |

判定口诀：**能参数化就 migrate；流程通用常量随样本变就 adapt 成模板；纯粹单样本 hack 就 template。**

## 2. 模板目录（已落地 3 个生成模板）

`templates/scripts/<name>.py.tmpl` 是生成模板：含 `{{KEY}}` 占位符 + 现场验证过的
流程骨架 + 明确标记的 TODO（待分析师填的样本特定部分）。**模板不是假实现**——
机械部分（hash/JSON/解析）已实现，样本特定部分以 `NotImplementedError` TODO 呈现。

生成方式（确定性，stdlib only）：

```bash
python scripts/template_gen.py --template <name> --name <slug> --out <dir> \
    --param sample_path=... --param sample_sha256=... [--param ...] [--force]
```

退出码：`0` 生成成功；`2` 用法错误（未知模板/bad --name/畸形 --param）；
`3` 缺少必填参数（stderr 列出缺失项）；`4` 目标已存在且未给 `--force`；
`5` 模板缺陷（模板含未覆盖的占位符，fail-closed）。同一输入 → 输出除
`generated ... on <ts>` 头行外逐字节一致。

### 2.1 stage-unpack — stage 解包分析

- **生成**：carve stage → sha256 → dump 的分析脚本（packed 样本逐 stage 切分 + 哈希 + 清单落盘）
- **必填参数**：`sample_path`、`sample_sha256`、`offsets`（逗号分隔 hex 切分偏移）、
  `stage_names`（与 offsets 等长的逗号分隔名字）、`output_dir`
- **何时用**：遇到 packer/loader 分阶段释放的样本，需要把每阶段切出来哈希比对时
- **分析师待填**：`carve_stages()`（本样本 packer 的实际切分边界）、可选 `verify_expected()`

### 2.2 decryption-analysis — 解密流程分析

- **生成**：定位解密例程 → 调用参数 → 解密 → 哈希的分析脚本
- **必填参数**：`sample_path`、`sample_sha256`、`decrypt_offset`（解密例程 VA/文件偏移）、
  `key_va`（密钥材料 VA）、`output_dir`
- **何时用**：样本带解密层，需要还原明文层并哈希落盘时
- **分析师待填**：`recover_key()`（KEY_VA 处的密钥提取）、`decrypt_payload()`（算法本体；
  若命中 `tools/_INDEX.yaml` 的 8 个算法族之一，优先复用 tools/ 而非重写）

### 2.3 disasm-pipeline — 反汇编流水线

- **生成**：入口点 → 反汇编 → xref → 摘要的分析脚本（capstone）
- **必填参数**：`sample_path`、`sample_sha256`、`entry_points`（逗号分隔 hex 入口地址）、
  `output_dir`
- **何时用**：需要从若干入口开始反汇编、收集 xref、产出结构化摘要时
- **分析师待填**：`pin_arch()`（架构/mode）、`interesting_targets()`（xref 目标）、
  `analyze()`（每入口分析笔记）

## 3. 吸收 pass 待填清单（BLOCKED — Windows 主机不可达）

236 个现场脚本（D:\works\samples）盘点时按 §1 分类，逐行填写下表
（示例行已给出格式；`脚本` 用样本内路径，`建议` 取值 migrate/adapt/template）：

| 脚本（D:\works\samples 下路径） | 分类 | 建议 | 理由（判据依据） |
| --- | --- | --- | --- |
| （示例）unpack_stage_carve.py | 半通用 | adapt | 流程通用，偏移/名字每样本变 → stage-unpack 模板 |
| （吸收 pass 填） | | | |

> 注册口径：migrate 落点的脚本/模板如需在 `tools/_INDEX.yaml` 登记，按该文件的
> entry schema（name/category/capability/tier/cost_tier/input_output）填写；
> 不要为模板另建平行索引。

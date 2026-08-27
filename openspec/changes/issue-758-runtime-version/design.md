# Design: #758 Wave-1（G1 钉版 + G4 stamp 一致性门）

## D1 — 钉的层级分工

| 层 | 值 | 职责 |
|---|---|---|
| pyproject requires-python | `>=3.10` | 测试下限/tomli backfill 契约（test_python_floor.py 守护，**不动**）|
| .python-version | `3.11` | uv 本地/开发环境默认解释器 |
| release-check.yml UV_PYTHON | `python3.11` | CI 解释器（2026-08-26 用户裁决：CI 只跑 3.11）|

三层语义各管一段，不互相覆盖：下限(兼容性) vs 默认(开发) vs CI(验证)。

## D2 — 漂移检测 = 提示不是阻断（G1b）

- env_check：`check_python_version()` 返回 TRI-STATE 字符串 PASS|WARN（沿用
  check_hooks/#410 的宽化先例），注册进 checks dict 一行 `python_version`。
  WARN 不进 overall FAIL 判定（与 hooks_deployed 同规则）。
- kunglao_upgrade：main() 开头一行 stderr
  `[event] name=python_version status=warn detail="X.Y.Z != 3.11.x"`。
  注：#753 结构化事件格式**尚未合入**（grep 全仓无 `[event] name=` 消费者），
  用带标准 token 的简单 stderr 行，#753 合入后对齐——不影响解析（消费侧
  目前只有人类阅读）。

## D3 — stamp 一致性门（G4）

### 一致性签名（最小方案）

模板渲染输出（不写盘）降维成**标题骨架序列**：读 templates/CLAUDE.md.base.tmpl，
逐行预处理——``` 围栏内跳过（android 流程块里有 bash 注释会污染 # 统计）、
`{{var}}` 归一为 `<var>`——收集 `^#{1,6} ` 标题行。工作区 CLAUDE.md 用同一
抽取器得实际序列。判定：期望序列是实际序列的**有序子序列**——

- 定制新增段（用户在模板之间插自己的章节）：合法（多余行被容忍）
- 删掉/改名/乱序任何模板标题 → 漂移 → 跳过刷戳

选子序列而非集合/前缀：插入容忍是 G2/G3（定制收集）的正交前提；顺序敏感才能
抓住改名和段落移动。

### 为什么不完整渲染

init 的渲染器（kunglao-init.py write_claudemd）要 type_section/task_spec_section/
sample_* 等 9 个参数且 template_render fail-closed——G4 若复用就得伪造全部参数，
耦合 init 内部状态反而脆。标题行天然不含 {{var}}，降维即丢掉变量依赖。
OS_SECTIONS（windows/linux/android/web）注入的额外标题属"多余行"，两侧对称，
不需要进期望集。

### 失败方向

- 模板文件缺失/不可读 → 无法验证 ≠ 漂移 → **返回 True（放行刷新）**。
  repo 破损有自己的测试网（release_receipt/goldens），不该由 stamp 门兜底。
- CLAUDE.md 缺失 → False（stamp_workspace 反正也不刷新不存在的载体，此处取
  一致语义）。
- project_type 进签名？否——D3 已论证 OS 段标题不进期望集，无需读
  analysis_state.txt，少一个跨模块耦合点。

### 接线点（两处，同一谓词）

1. `_item_template_stamp_refresh`（迁移项本身）
2. upgrade() 尾部 belt-and-braces `stamp_workspace(ws, version=target)`——
   否则门被这一行绕过，旧正文照样盖新戳

跳过时 stderr WARN `frame section stale — G3 merge upgrade required (see #758)`
（item 路径发一次；belt-and-braces 路径静默跳过避免双 WARN）。
dry-run 同步反映 skip（--dry-run 计划里就该看得见 frame-drift）。

## D4 — 对既有契约的影响面

- test_kunglao_upgrade_726.synth_v012_ws 的 CLAUDE.md 正文是手写的 `# old
  workspace`（非模板形状）→ 在 G4 语义下其 stamp 现在**应当**停在 0.1.2。
  该文件中 "三载体刷新到当前版" 断言按新契约改写为 skip 断言——这是 #758 G4
  **有意改变的行为**（旧断言编码的正是"stamp 撒谎"bug），不算破坏回归。
- _INDEX / claim-register 两载体的戳与 CLAUDE.md 戳绑定刷新（stamp_workspace
  三载体原子刷新）；frame 漂移时三者一并保持旧值——单独刷数据文件戳同样构成
  "新戳盖旧正文"。
- 铁律安全：跳过刷新 = 载体字节不动，digest 归一化本就无视戳行。

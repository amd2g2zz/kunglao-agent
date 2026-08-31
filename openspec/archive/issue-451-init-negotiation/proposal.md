# Init Negotiation Interface: 枚举→选择、缺失三选一、报错自带解析 (#451)

## Why

Issue #451(milestone v0.1.2,D3 交互接口;分层条目 L5-1~L5-3 / L2-4 / C1-C4)。
init 链的报错与缺失处理把发现/决策成本甩回用户,且输出不可机械消费。四份证据:

1. **fix 文本甩锅**(`scripts/toolchain.py:84` 补丁前原文):
   `vm_reachable` 的 fix 是 "set KUNGLAO_VM_HOST=<live VM lease IP>
   (vmr-shell discovery)" — 把"发现哪台 VM、什么 IP、什么状态"退回给
   用户;工具一条 `vmrun list` 即可枚举(只读)。
2. **三缺陷同框**(2026-08-17 用户终端实录):交错(floss 提示行未闭合,
   REFUSE 行直接拼在其后 — stdout 提示无换行 + stderr 块抢跑)/ 乱码
   (`REFUSE —` 显示为 `REFUSE ??`,stderr 未统一 utf-8,GBK/UTF-8 混流)/
   伪装(isatty 误判 → input() EOF → 自动 declined,与用户主动拒绝无法
   区分)。
3. **工具缺失无三选一**(实测):die/floss 缺失时未搜盘(本机 D:\tools、
   C:\tools 均为工具目录)、未问路径、未问决策——直接降级。
4. **报错不可机械解析**:fix 是给人看的散文;下游(init-worker 按 #478
   的 AskUserQuestion 面、#455 的 --resolve 再入)需要结构化 next-action
   (动作动词 + 精确命令 + 枚举选项)才能程序化收集答案。

前置已落地:#449 需求先行(env = f(task_spec),toolchain 消费 task_spec,
保守默认)/ #450 env-facts.yaml(本件只消费、不改)/ #455 目标对齐 +
pending-decision 通道(stdout JSON + exit 8 + --resolve 再入;stdin 不是
用户通道)/ #448 错误分类学(HUMAN-EVENT-REFUSE → STOP;PENDING_DECISIONS
→ ASK)/ #474 探针分级(presence/liveness/capability,registered != usable)。

## What Changes

- **报错自带解析 ①**(`scripts/toolchain.py`):`CheckResult` 增
  `fix`(item 级动态 fix,覆盖 FIXES 静态文本)与 `next_action`
  (`NextAction(action, command, options)`,frozen)。每条 FAIL 附机械可
  解析的 next-action:人面 `--human` 在 fix 行后追加键值行
  `action: <verb>` / `command: <cmd>` / `option N: <opt>`;机面 `--json`
  每条 check 扩展 `next_action` 对象。动词集封闭枚举(design.md D1)。
  `vm_reachable` FAIL 时嵌入只读 VM inventory(vmrun list +
  inventory.vmls DisplayName + VBoxManage + listSnapshots,issue 实测输出
  格式),next_action 按候选数派生(vm-enumerate/vm-start/vm-reip,
  options=VM 名)。
- **枚举→选择 ②**(新 `scripts/toolchain_negotiation.py` + kunglao-init
  接线):缺失项不再裸问。VM 多候选 → exit 4 拒绝输出里列编号候选 +
  next_action options(init 绝不自动选择,OPERATOR 拍板 — HARD human
  event)。WARN 可降级工具缺失(die/floss/pefile)→ 先搜盘
  (KUNGLAO_TOOL_DIRS,默认 C:\tools + D:\tools,只读、限深限数),再出
  三选一菜单 install / use-path:<候选> / skip / degrade,作为
  pending-decision(exit 8 + --resolve 再入,#455 通道),decision id
  `install:<item>`。
- **三缺陷修复 ③**:交错 — kunglao-init 拒绝块写 stderr 前
  `sys.stdout.flush()`,toolchain_install 关键提示行 flush;乱码 —
  toolchain.py / kunglao-init.py / toolchain_install.py 三处 stderr 统一
  `reconfigure(encoding="utf-8", errors="replace")`;伪装 — #455 已拆掉
  input()/isatty,本件补齐语义面:无同意渠道的降级输出"非交互环境自动
  降级(no consent channel)"而非"declined";"declined" 仅出现在确有
  用户选择(--resolve 答案)背后。
- **宪法对齐 ④**:协商事件走 #448 分类学 — HARD 缺失(vm_reachable /
  decompiler / android 链)是 HUMAN-EVENT-REFUSE → exit 4 路径不变;
  可选项缺失 → PENDING_DECISIONS(exit 8 enumerated choice)。非交互且
  无 --assume-yes:结构化 pending 清单,不静默降级(#448 UNCLASSIFIED→ASK
  姿态 / #474 不谎报)。菜单仅当它是唯一阻塞时触发(混合缺失仍走 exit 4
  人事件,#304 语义零回归)。

## 不做 (Not Building)

- 不改 #449 `requirements_from_task_spec` 语义与 #450 env-facts.yaml
  shape(只消费;byte-identical 锚定测试仅改 detail 面的 pin,#449 状态
  锁不动)。
- 不动 #455/#478 的 agent 交互面(agents/kunglao-init-worker.md /
  skills/init/SKILL.md 的 AskUserQuestion 流程归它们;本件只提供脚本侧
  结构化接口)。
- 不自动选择 VM 候选、不自动 sudo、不在 init 内静默装 HARD 组件(#304
  amendment 保持)。
- 不引入 stdin 读取(#455 铁律);use-path 不写 analysis_state(拒绝路径
  的 cleanup 语义不受污染,路径进 degrade detail + stderr 指引)。
- stash 里的 fact_contradiction_gate facet 改动与 uv.lock 噪声不随本件
  合入(与本 issue 无关)。

# Design — issue-451-init-negotiation

## D1 NextAction 数据模型(toolchain.py)

```python
@dataclass(frozen=True)
class NextAction:
    action: str                        # 封闭动词集 VERBS
    command: str | None = None         # 人/agent 可直接执行的精确命令
    options: tuple[str, ...] = ()      # 枚举候选(VM 名;菜单项由协商层另构)

NEXT_ACTION_VERBS = frozenset({
    "install",         # 有确切安装命令(pip/npm/包管理器)
    "set-env",         # 设置环境变量(GHIDRA_HOME)
    "register-mcp",    # claude mcp add 注册
    "vm-enumerate",    # 多候选/无候选:枚举(命令 vmrun list / VBoxManage list vms)
    "vm-start",        # 单候选且 off:开机(命令 vmrun -T ws start "<vmx>" nogui)
    "vm-reip",         # 已运行/IP 漂移:重解析(命令 vmrun getGuestIPAddress "<vmx>")
    "human-configure", # 设备侧人工配置(root/debug flag — 人的决定,非命令可代)
    "human-deploy",    # 设备侧人工部署(frida-server/android_server push)
})
```

解析面(双向):
- 人面(format_human):FAIL 条目在 `fix:` 行后追加
  `      action: <verb>` / `      command: <cmd>` / `      option N: <opt>`;
  正则 `^\s*action: ([a-z-]+)$`、`^\s*command: (.+)$`、`^\s*option (\d+): (.+)$`
  (re.M)可无歧义提取(这些 key 不出现在 detail/fix 文案的行首)。
- 机面(format_json):每条 check 增 `"next_action": {"action", "command",
  "options"} | null`(仅 FAIL 携带,非 FAIL 恒 null,镜像 fix 的噪声纪律)。

派生规则 `next_action_for(item)`:item.next_action(动态,VM 面)→
`_STATIC_NEXT_ACTIONS[name]`(FIXES 键全覆盖)→ `mcp:<name>` 由
mcp_probe.MANIFEST 的 register 命令派生 → root_cause=="VM" 兜底
vm-enumerate → None。覆盖性由测试锁死(每个 FIXES 键 FAIL 必有
next_action)。

## D2 VM inventory(toolchain.py,#451 证据 1)

只读发现,fail-open,全部经既有 seam(`_run_cmd` / `_shutil_which`):
- `_vmrun_exe()`:env `KUNGLAO_VMRUN_PATH` 覆盖 → PATH → Workstation
  stock 路径(测试可确定性关闭)。
- `_vmrun_inventory(vmrun)`:`vmrun list`(running 集)+
  `%APPDATA%\VMware\inventory.vmls` 解析(config = "<vmx>" +
  DisplayName 配对;无 DisplayName 用 vmx stem)+ 每台 `listSnapshots`。
- `_vbox_inventory()`:VBoxManage list vms / runningvms。
- `_vm_inventory() -> (entries, has_vmrun, has_vbox)` — 单一 seam,
  测试整体替换。
- FAIL detail = 原失败行 + `discovered VMs (vmrun=?, vbox=?):` +
  编号清单(issue 实测格式:`1. work_env [off] snapshots: 6 (latest: …)`)。
- fix/next_action 派生:host set 且有 running → vm-reip;host unset 单
  候选 off → vm-start;单候选 running → vm-reip;多候选 → vm-enumerate
  (options=全部 VM 名,fix 文本声明 OPERATOR 拍板、init 绝不自动选择);
  无候选 → vm-enumerate。`remote_debugger` 级联 FAIL 复用 VM 的
  next_action(root-cause 正确性)。
- #449 交互:WARN 降级面(static-only)detail 不变;仅 HARD FAIL 面嵌
  inventory。探针层级 #474:inventory 是 presence 证据,不改变
  vm_reachable 的 LIVENESS 标注。

## D3 协商菜单(toolchain_negotiation.py,#451 证据 3)

```
NEGOTIABLE = {n for n, p in INSTALL_PLANS.items()
              if p.kind == "auto" and p.degrade == "WARN"}   # {pefile, floss, die}
disk_candidates(name)   # KUNGLAO_TOOL_DIRS (os.pathsep; 默认 C:\tools;D:\tools)
                         # 深度 ≤2、命中 ≤4、可执行后缀匹配,只读 fail-open
negotiation_decisions(report) -> list[PendingDecision]
    decision_id = f"install:{name}"
    options = ("install", *["use-path:<候选>"], "skip", "degrade")
    context  = {"install_command": 平台安装命令, "disk_candidates": [...],
                "degrade": plan.degrade}
apply_answers(report, ws, type, answers, task_spec) -> report   # ValueError on 畸形答案
    install   -> toolchain_install._run_install_plan;成功后整报告 re-probe(task_spec
                 同源,#449 M1 规则);失败 -> degrade + 官方指引
    use-path  -> 路径必须存在(否则 ValueError);degrade WARN + detail 记
                 操作员供路径 + stderr 指引"加 PATH 才 PASS"(不写 state)
    skip      -> 不动(保持 FAIL → 走 exit 4 人事件)
    degrade   -> degrade_report + "declined via --resolve" 注记(真用户选择)
negotiate(report, ...) -> (resolved_report, pending_decisions)
has_non_negotiable_hard_fail(report) -> bool
```

kunglao-init 接线(run() 的 FAIL 分支,--assume-yes 路径零改动):
```
FAIL & not assume_yes:
    resolved, pending = negotiate(report, ws, type, answers, task_spec)
    if pending and not has_non_negotiable_hard_fail(report):  # 菜单是唯一阻塞
        return emit_pending(ws, pending)                      # exit 8(#455 通道)
    if resolved.overall_status == FAIL:
        return refuse_toolchain(ws, resolved)                 # exit 4 不变(#448)
```
混合缺失(die + VM/decompiler)→ exit 4:菜单推迟到 HARD 项人修后的下轮
(每轮一个 exit 语义;#304 既有测试全部保持)。畸形答案 → RC_ERROR
(fail-closed,镜像 _aligned_target)。

## D4 三缺陷(证据 2)

- 交错:refuse_toolchain 首行 `sys.stdout.flush()`;toolchain_install 的
  missing/降级提示行 `flush=True`。
- 乱码:三脚本 stderr `reconfigure(encoding="utf-8", errors="replace")`
  (stdout 面已统一;try/except AttributeError|ValueError 姿态一致)。
- 伪装:#455 已结构化拆除 input()/isatty;本件补语义:无同意渠道的降级
  消息 = "no consent channel (non-interactive) — degrading
  automatically;decision channel: kunglao-init --resolve menu (#451) or
  --assume-yes";"declined" 仅在 --resolve 答案(用户选择)背后出现
  ("declined via --resolve")。

## D5 宪法对齐(#448 / #474 / #447)

| 场景 | ErrorClass | 响应 | 落地面 |
|---|---|---|---|
| HARD 缺失(vm/decompiler/android 链) | HUMAN-EVENT-REFUSE | STOP | exit 4 + 结构化 next-action 行 |
| 可降级缺失(菜单) | PENDING_DECISIONS | ASK | exit 8 pending + --resolve |
| 畸形 --resolve 答案 | —(usage) | RC_ERROR | fail-closed |
| 多 VM 候选 | HUMAN-EVENT-REFUSE(选项内嵌) | STOP+ASK(人) | exit 4,候选编号 + options |

非交互且无 --assume-yes 且无答案 → pending 清单,零静默降级(#448
UNCLASSIFIED→ASK 姿态)。use-path 降级不谎报 PASS(#474:供路径 !=
可用,detail 如实记 WARN)。

## D6 测试映射(RED 先行)

| 文件 | 覆盖 |
|---|---|
| tests/test_toolchain_next_action.py | ①:D1 模型/双面解析/动词封闭/FAIL 全覆盖/D2 inventory 派生/拒绝面携带结构化行 |
| tests/test_toolchain_negotiation.py | ②④:D3 菜单/搜盘/apply 四答案/init 接线 exit 8↔4/畸形 RC_ERROR/混合缺失 exit 4/VM 多候选不自动选 |
| tests/test_toolchain_stdio.py | ③:flush 顺序/stderr utf-8 三脚本/降级措辞区分 |
| tests/test_init_toolchain_gate.py | 更新:test_run_hard_fail_non_tty… → die-only 非交互 = exit 8 pending(ask 仍不调用) |
| tests/test_toolchain_needs_first.py | 更新:_hermetic_env 关闭 vmrun/vbox seam;byte-identical 测试 pin 新 detail(#449 状态锁不动) |

## R1-R5 风险

- R1 stock 路径 vmrun 在真机上拖慢失败路径测试 → inventory 仅 FAIL 时跑、
  listSnapshots 限时;模块级测试 _hermetic_env 关 seam。
- R2 菜单 id 与 #449/#455 决策碰撞 → `install:` 命名空间;未知键忽略
  (decision_pending 前向兼容契约)。
- R3 exit 8 与 exit 4 语义漂移 → 混合缺失恒 exit 4(测试锁);#304 既有
  测试零回归是门禁。
- R4 detail 变更破坏 #449 byte-identical 锚 → 仅更新 detail pin,状态
  (status/tier/root_cause/probe)与"显式 None == 缺省"全等保持。
- R5 install 答案触发真实安装 → 仅在 --resolve 明示 "install" 时执行
  (等同 assume-yes 的单项化);测试经 _run_install_plan seam 假安装。

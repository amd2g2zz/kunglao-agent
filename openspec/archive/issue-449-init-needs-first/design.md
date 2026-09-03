# Design — init needs-first: env = f(task_spec) (#449)

## 问题边界

"环境分层由 task_spec 推导" = toolchain 检查项的 **tier(以及派生的
status)由任务需求决定**,而不是由 type 模板静态写死。本变更只处理
windows/linux 的 **VM 通道**(vm_reachable / remote_debugger):它是
issue 证据 2 的实测代价主体(VM 全链路 bring-up),也是 task_spec 有
显式对应字段(`constraints.dynamic_re`)的唯一分层。

**不是**本变更(范围外,保持不动):

- android ADB 契约(adb/device_root/debug_flag/frida_server/
  android_server)——android 无 VM 通道(#455 NEVER_CHECKS 锚定),其
  动态契约走 ADB;需求化放宽是后续工作,不在 #449 证据面。
- 三态 checklist 脚本(ok / 缺失且must / 无关)与 env manifest——
  #450 领地。
- 协商菜单 / install-consent——#451 领地。
- `--assume-yes` ask-then-install、refuse/cleanup 语义(#304/#408)
  ——本变更只改"哪些项算 HARD",不改拒绝行为本身。

## D1. 需求集落在哪:`toolchain.requirements_from_task_spec`

纯函数 `requirements_from_task_spec(task_spec: dict | None)
-> Requirements`(`@dataclass(frozen=True)`,`needs_vm: bool = True`,
`basis: str`),放在 toolchain.py(检查项的唯一真相源;需求与检查同文件
演进,避免第二表示)。

读取规则(保守,读不到 = 现状 HARD):

| task_spec 输入 | needs_vm | basis |
|---|---|---|
| None / 非 dict / 无 constraints / constraints 非 dict | True(默认) | conservative default |
| `constraints.dynamic_re: allowed`(或任何非 `forbidden` 值) | True | 默认(显式 allowed 同样 HARD) |
| `constraints.dynamic_re: forbidden`(大小写/空白容忍) | **False** | `task_spec constraints.dynamic_re=forbidden (static-only)` |

**为什么只有 `dynamic_re`**:模板 `templates/state/task_spec.yaml` 里
`dynamic_re` 自述为 "master switch for emulation/Frida"——它关掉即
static-only,VM 通道(vmr-shell 9876 + frida 1337)整体无关。
`vm_detonation` 只禁 vmr-shell 引爆,不禁 frida-on-VM;单独放宽会让
"vm_detonation=forbidden + dynamic_re=allowed"的任务丢掉仍需要的
frida 通道。primary_questions 的 `need:` 枚举
(yes_no_with_evidence / protocol_description / model_selection)说的是
"怎么答",不是"要什么环境"——今天没有可派生的显式字段,保守不动。

## D2. 检查项如何消费需求集

`_check_windows/_check_linux` 签名加 `reqs: Requirements =
DEFAULT_REQUIREMENTS`;VM 探针块(两函数中原本逐字节重复)提为共享
helper `_check_vm_channel(report, reqs)`(镜像 #407 `_check_decompiler`
的去重模式):

- **默认(needs_vm=True)**:CheckResult 的 status/tier/detail/
  root_cause 与重构前**逐字节一致**——这是 (c) 向后兼容条款的机械
  保证,由测试锚定(detail 字面量逐字断言)。
- **static-only(needs_vm=False)**:
  - `vm_reachable` 可达 → PASS / **WARN** tier,detail 注明
    "not required by task_spec (<basis>)";
  - `vm_reachable` 不可达 → **WARN / WARN**(不再是 FAIL/HARD),
    detail 带同一依据,root_cause=None(不再是阻塞级联根因);
  - `remote_debugger` 级联同样降 WARN,注明理由。
  - 选择"降 WARN + 注明"而非"跳过":报告三态诚实(#474 精神)——
    能力缺失被如实上报给 orchestrator,只是不再阻塞 init。镜像
    jdwp_debug 的既有先例(static-only and frida-driven flows never
    touch jdb → WARN tier, informational)。

`check(ws, project_type, caps, task_spec=None)`:task_spec 为已解析
mapping;None = 保守默认。**check 不自动读文件**——单一加载点
`load_task_spec(ws)` 在调用方(init 的门内 / CLI main)。理由:check
保持其入参的纯函数性;kunglao-init 需要在读文件时区分 absent(一行
指引)与 unparseable(WARNING),自己掌控加载时机。

## D3. init 接线(kunglao-init.run)

门内(`if not skip_toolchain:`)、`toolchain.check` 调用前:

```
load_task_spec(ws)  →  dict: check(ws, type, task_spec=spec)
                    →  None:  一行指引 + check(ws, type)   ← 两参调用
                    →  ValueError: WARNING + 按 None 处理
```

- **两参调用保留**:既有测试以 `fake_check(ws_arg, project_type=None)`
  monkeypatch `mod.toolchain.check`;task_spec 存在才传第三参,无 spec
  路径调用形状不变。
- unparseable 不 crash、不放宽:WARNING + 保守 HARD;同一缺陷稍后在
  CLAUDE.md render(`task_spec_section` 的 TemplateRenderError)fail-
  closed——不新增失败模式,只提前诚实。
- `--skip-toolchain` 时整块跳过(读都不读)——既有 task_spec.yaml
  测试全部走此路径,零回归(已逐一核对)。

## D4. fail-closed 语义与 issue 验收的对应

issue 验收 "task_spec 缺失时 init 对 bring-up 类动作 FAIL" 在本设计中
体现为**保守 HARD 默认**:无 task_spec → vm_reachable 仍 HARD → VM
不可达即 exit 4(带-up 前置检查本来就是 refuse-not-bring-up)。读不到
的字段一律 HARD = 用户没说"只要静态"就默认需要 VM。显式拒绝
bring-up 类动作的清单化(三态 checklist)是 #450。

## D5. 验收 → 测试映射(见 tasks.md)

| #449 验收/任务 | 测试(tests/test_toolchain_needs_first.py) |
|---|---|
| requirements_from_task_spec 派生规则 | `test_requirements_*`(static-only / 保守族 / vm_detonation 单独不放宽) |
| load_task_spec 加载语义 | `test_load_task_spec_*`(absent/empty→None;garbage/非 mapping→ValueError) |
| static-only 降 WARN(windows/linux) | `test_check_windows_static_only_vm_warn` / `test_check_linux_static_only_vm_warn` |
| 无 task_spec 逐字节一致 | `test_check_no_task_spec_vm_hard_byte_identical`(detail 字面量 + status/tier/root_cause 锚定) |
| CLI 消费 task_spec | `test_cli_consumes_task_spec`(有 spec→WARN;无→FAIL) |
| init 指引行 | `test_init_guidance_line_when_task_spec_absent` |
| init unparseable 保守 | `test_init_unparseable_task_spec_stays_hard` |
| **cost 证据负例**(证据 2 固化) | `test_init_static_only_does_not_refuse_on_vm`(完整伪工具链 + 无 VM + static-only → exit 0,无 `[FAIL] vm_reachable`)+ `test_init_static_only_control_without_task_spec_refuses`(同环境无 spec → exit 4 + `[FAIL] vm_reachable`) |
| Flow 第 0 步(SKILL.md) | `test_skill_flow_task_spec_intake_is_step_0`(文本序号一致化锚定) |

## Rejected

- **R1 `vm_detonation` 单独放宽**:`vm_detonation=forbidden` 只禁
  vmr-shell;frida-on-VM 仍可能在计划内,单独放宽丢通道。按端口粒度
  的契约是 #450 env manifest。
- **R2 android 需求化放宽**:android 动态契约 = ADB + 设备服务,不是
  VM 通道(#455 设计);本 issue 三份证据均为 windows VM 链。后续单列。
- **R3 check() 自动读 ws/task_spec.yaml**:与 kunglao-init 的加载时机/
  区分语义冲突(absent vs unparseable),且引入"参数与文件双重真相"。
  单一加载点在调用方。
- **R4 static-only 跳过 VM 检查项**:违反三态诚实报告(#474);WARN +
  注明保留可见性,且 CHECK_SETS 契约面不变(测试锚定不破)。
- **R5 拒绝列表加"static-only 却要求 VM"的正例校验**:task_spec 说
  dynamic_re=allowed 而 VM 不可达 → 现状已 FAIL;反向(static-only 而
  VM 在)不构成失败——WARN 已如实报告。
- **R6 改 INTAKE_GUIDANCE 的四项顺序**:脚本侧 pending 解析顺序
  (workspace → target → type)是 #455 的既有契约;需求先行是 Flow 层
  (agent 何时问)的重排,不是脚本解析顺序的重排。指引文本已含
  task requirements 尾项(#449 标记预埋)。
- **R7 动 kunglao-init.py 尾部 bootstrap_observability**:#461 领地,
  硬约束禁区,不碰。

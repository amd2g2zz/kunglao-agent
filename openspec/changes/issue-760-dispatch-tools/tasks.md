# Tasks — issue #760 dispatch 工具面

## 1. SDD

- [x] 1.1 openspec scaffold（proposal/design/tasks + specs）
- [ ] 1.2 每 task 一 commit；TDD RED 先行

## 2. T1 = I1 dispatch tools= 机械校验

- [x] 2.1 RED tests/test_dispatch_tools_760.py：tools=pefile-signature@kunglao-worker
      REJECT；tools=Read,Grep（无 Write）REJECT；tools=Read,Write,Grep PASS；
      未知 agent 不拦；无 agent 名（legacy v0）不拦；v1 JSON meta.agent 生效；
      MCP 通配符匹配
- [x] 2.2 GREEN hooks/dispatch_gate.py（_agent_allowed_tools + _resolve_dispatch_agent
      + _tools_contract_violation + main 两处结构走廊挂载）；commit

## 3. T2 = I2 TRY 梯子边界

- [x] 3.1 RED：两处契约文本断言（能力不匹配 / 凑合 关键词）
- [x] 3.2 GREEN agents/kunglao-worker.md Self-drive 边界条款 +
      references/operational-mechanics.md 三级梯同款 + re-pin references/_INDEX.yaml；commit

## 4. T3 = I3 macos 类型

- [x] 4.1 RED：type union ×3 层含 macos；write_init_marker 接受 macos；
      toolchain.check("macos") 零 HARD；OS_SECTIONS["macos"] 渲染；init --type macos
      CLI/Mach-O fixture 走通；guidance 字符串新枚举 pin；macho/dylib feature 路由命中
- [x] 4.2 GREEN：init_state/toolchain(_check_macos+CHECK_SETS+NEVER_CHECKS)/
      mcp_probe/kunglao-init(OS_SECTIONS+guidance)/env_check(ghidra_typed 分支)/
      kunglao_resume/env_check_gate/SKILL.md/skills yaml/README 字符串同步；
      ghidra-light features 补信号；test_web_labs_type_728 pin 同步；commit

## 5. T4 = I4 web-re-worker

- [x] 5.1 RED：路由命中（js/webhook/风控/bundler/deobfuscate claim → web-re-worker；
      authenticode claim 仍 pefile-signature；apk/dex exclude）+ frontmatter 合法性
      （name/triggers/allowedTools/contract markers via Gate 6 lint）+
      release-manifest 完整性（roster 全等断言同步）
- [x] 5.2 GREEN agents/web-re-worker.md + release-manifest.yaml declare +
      tests/test_release_receipt.py roster 同步；commit

## 6. 收口

- [x] 6.1 定向套件全绿；净化 PATH 全套 pytest 4298 passed / 12 skipped
      （残余 2 failed 为宿主环境flake：adb 设备在场 + 端口 23946 监听，
      stash 后 pristine dev@6c4e92e 同样复现，与本波无关）；
      release_receipt --check rc=0；quality_gates 1/3/4/5/6/7 ALL-PASS；ruff 干净
- [ ] 6.2 push + PR（Closes #760）→ CI 绿 → squash + delete branch

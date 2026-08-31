# Deploy Completion: pkg-manager detection + INSTALL_PLANS coverage + device-side deploy + re-probe loop (#477)

## Why

Issue #477(milestone v0.1.2,部署体系补全)。四份证据:

1. **覆盖率 5/31**:`scripts/toolchain_install.py` 的 INSTALL_PLANS 仅
   5 项(pefile/floss/die/decompiler/ida);#467 合入的 CHECK_SETS 三类型
   合计 29 个唯一检查项。无安装计划的 HARD FAIL 直接跳过 → init RC 4
   硬拒 → 约 24 项的"部署"= 一段静态文字,装不装全靠人读指引,装完
   无探针闭环(仅 5 项有 re-probe)。
2. **平台硬编码实测死路**:`InstallPlan.commands` 是 sys.platform →
   固定 argv 静态表(win32=choco / darwin=brew / linux=apt-get)。win32
   用户没装 choco(常见)则 `choco install ghidra` 建议即死 — 代码不
   探测 winget/scoop/已有解压目录/已有 IDA。
3. **设备侧部署只有文字**:frida-server push+rename+自定义端口、
   android_server push 仅有 FIX_TEXT(`toolchain.py` FIXES),无幂等脚本;
   #462 契约要求"一次性垫片须标注并即弃",但无机制承载。
4. **无闭环**:ask_then_install 装完 → re-probe(#451 已接)→ 结果无
   台账(#450 env-facts.yaml 没有 installed 面);失败回不到结构化
   next-action。

前置已落地:#449 需求先行(env = f(task_spec))/ #450 env-facts.yaml
事实单源 / #451 NextAction 封闭动词集 + 协商菜单 + declined vs
no-consent 措辞契约 / #408 consent 语义 + sudo 永不自动加 / #462 三要素
契约(标注即弃)。

## What Changes

- **① 包管理器探测层(去平台硬编码)**:新 `scripts/pkg_detect.py`。
  封闭管理器词汇表(winget/choco/scoop —win32;brew —darwin;
  apt/dnf/apk/pacman —linux;pip/uv/npm —any),`detect_managers()`
  which 优先、known-paths 回退(只读);`find_ghidra_install()` 探"已解压
  未配置"半装态。INSTALL_PLANS 的 `commands: dict[platform, argv]` 改为
  `(manager, argv)` 数据(`packages: tuple[PkgSpec, ...]`,同 item 多
  manager,条目内顺序即偏好),`resolve_install()` 用探测结果拼装,输出
  mode: install / elevation / set-env / manual — 探测失败(无可用
  manager)走 #451 NextAction(动词 install,指引装 manager 或手装),
  半装态走 set-env(建议配置 GHIDRA_HOME 而非重装)。
- **② 覆盖率扩容**:INSTALL_PLANS 5 → 17 项(新增 file/readelf/
  objdump/docker/jadx/apktool/gitnexus/adb/aapt/gdbserver/strace/
  ltrace,全部为 toolchain 检查面实际项,包名逐 manager 核实,不虚增);
  新增 `NOT_AUTO_INSTALLABLE` 封闭声明(12 项 + 理由:VM 通道/人工决策/
  设备侧/内核属性),CHECK_SETS 全集 29 项 100% 分类,由测试锁死。
- **③ 设备侧部署脚本化**:新 `scripts/deploy_shim.py`。deploy 面:
  frida-server(push+RENAME+自定义端口)/ android-server(push+run)
  幂等部署 — 先探端口(已部署 = no-op,设备侧零变更、host 侧探针仍
  adb forward),装后 re-probe
  PASS 才算成功,结果写 env-facts installed 台账;new 面:#462 "一次性
  垫片标注即弃"正规化 — 参数化(target/purpose/expiry)生成
  scripts/shims/ 下带弃用语义头的垫片注记 + 目录 README 声明。
- **④ 统一 re-probe 闭环**:ask_then_install 装完 → re-probe(既有)
  → `env_manifest.record_installed()` 写 env-facts.yaml `installed` 段
  (#450 台账面;逐工具条目 {manager, at, reprobe},garbage 拒写不覆盖)
  → 失败回 NextAction(degrade + 指引,既有语义)。全链一条命令可测:
  `python scripts/toolchain_install.py <ws> --type t [--assume-yes]`。

## 不做(边界)

- 不动 #449 语义(task_spec → Requirements 推导、保守默认、
  re-probe 的 task_spec 透传)。
- 不动 #451 语义:NextAction 动词集不扩、菜单/`--resolve` 流不变、
  "declined"仅出现在真实用户选择背后(no-consent 措辞契约原样)。
- 不动 #408/#304 安全纪律:sudo 永不自动加(改为 manager 属性
  needs_sudo 驱动,输出行为不变);IDA 永不自动装(mcp_url);VM/
  root/真机决策保持 human event。
- 不做虚拟化设备通道(VM 内部 push)——deploy_shim 只做 ADB 设备侧;
  VM 侧仍是 #451 的 vm-* 动词。
- 不引入新依赖;只读探测;不改 toolchain.py 检查面。

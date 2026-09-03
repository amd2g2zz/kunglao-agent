# Design — issue-477-deploy-completion

## D1 管理器模型(scripts/pkg_detect.py,新)

```python
@dataclass(frozen=True)
class Manager:
    name: str            # 封闭词汇表键:winget/choco/scoop/brew/apt/dnf/
                         # apk/pacman/pip/uv/npm
    os_family: str       # "win32" | "darwin" | "linux" | "any"
    needs_sudo: bool     # True -> 永不自动执行(#304),打印 sudo 前缀命令
    which_names: tuple[str, ...]   # PATH 探测名(apt 用 apt-get)
    known_paths: tuple[str, ...]   # which 未中时的回退(env 展开后判存在)

@dataclass(frozen=True)
class ManagerHit:
    name: str
    path: str
    source: str          # "PATH" | "known-path" — 怎么找到的(诚实报告)
```

探测:`detect_managers(platform=None, *, which=…, exists=…)` —
platform 默认 sys.platform,映射 os_family(win32/darwin/linux);"any"
族(pip/uv/npm)任何平台都探测。which 优先,known-paths 回退
(`os.path.expandvars`/`expanduser` 后 `Path.exists`)。**只读**:不装
manager、不写注册表、不建目录。known-paths 依据:
winget=`%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe`(inbox,服务
上下文常不在 PATH)、choco=`C:\ProgramData\chocolatey\bin\choco.exe`、
brew=`/opt/homebrew/bin/brew` + `/usr/local/bin/brew`、apt=`/usr/bin/
apt-get`、dnf=`/usr/bin/dnf`、apk=`/sbin/apk`+`/bin/apk`、pacman=
`/usr/bin/pacman`。

半装态:`find_ghidra_install(tool_dirs=None)` — 搜"已解压的 ghidra 根"
(目录含 `support/analyzeHeadless(.bat)`,名字用 platform_paths 单源)。
根序:GHIDRA_HOME(已设置且有效 — 该情形检查不会 FAIL,防御性保留)>
KUNGLAO_TOOL_DIRS(#451 枚举根,os.pathsep 分隔)> 默认 C:/tools +
D:/tools。限深 2、限命中 1(fail-open → None)。只读。

## D2 解析模型(toolchain_install.py)

```python
@dataclass(frozen=True)
class PkgSpec:
    manager: str              # pkg_detect.MANAGERS 键
    argv: tuple[str, ...]     # 该 manager 的完整安装 argv

@dataclass(frozen=True)
class InstallResolution:
    mode: str        # "install" | "elevation" | "set-env" | "manual" | "none"
    argv: list[str]  # mode=install 时可执行;否则 []
    manager: str | None
    reason: str
    next_action: toolchain.NextAction | None   # #451 封闭动词集
```

`resolve_install(name, plan=None, managers=None)` 决策序:

1. `kind == "mcp_url"` → mode none(IDA 面,ask_then_install 另走注册指引)。
2. item 携带 ghidra 安装语义(`mcp_register == "ghidra"`)且
   `find_ghidra_install()` 命中 → mode **set-env**,
   `NextAction("set-env", "set GHIDRA_HOME=<dir>")` — "已有解压目录:
   建议配置而非重装"(issue 验收 3)。
3. 按 `plan.packages` 声明顺序找第一个已探测到的 manager →
   `needs_sudo` False → mode **install**(argv 即拼装结果);
   `needs_sudo` True → mode **elevation**(打印 `sudo <argv>`,不自动执行,
   行为与旧 sudo_platforms 分支逐字等价)。
4. 无任何可用 manager → mode **manual**,
   `NextAction("install", "install one of <候选 manager> or install
   manually (see fix)")` — 指引装 manager 或手装(#451 动词 install)。

偏好 = 条目内声明顺序(数据即偏好),非全局序:pefile 先 pip 后 uv;
docker 先 winget 后 choco;"winget 无 choco → 选 winget"(issue 验收 2)
由 docker/adb 等条目的 winget-first 声明 + 探测实现。`install_commands
(name)` 保留为薄封装(argv 或 [];未知项仍 KeyError — negotiation 菜单
文本的既有回退不变)。

## D3 INSTALL_PLANS v2 数据 + 覆盖率封闭声明

INSTALL_PLANS(commands → packages,17 项):

| item | manager→argv(按偏好序) | degrade |
|---|---|---|
| pefile | pip `pip install pefile`;uv `uv pip install pefile` | WARN |
| floss | pip `pip install flare-floss`;uv | WARN |
| die | choco `choco install die -y`;brew `brew install die` | WARN |
| decompiler | choco ghidra;brew `--cask` ghidra;apt ghidra(mcp_register=ghidra) | HARD |
| ida | (mcp_url,永不自动装) | WARN |
| file | choco file;brew file;apt/dnf/apk/pacman file | WARN |
| readelf | brew binutils;apt/dnf/apk/pacman binutils | WARN |
| objdump | 同 readelf | WARN |
| docker | winget Docker.DockerDesktop;choco docker-desktop;brew `--cask` docker;apt docker.io;dnf docker;apk docker;pacman docker | WARN |
| jadx | choco jadx;brew jadx | WARN |
| apktool | choco apktool;brew apktool;apt apktool | WARN |
| gitnexus | npm `npm install -g gitnexus` | WARN |
| adb | winget Google.PlatformTools;choco adb;brew `--cask` android-platform-tools;apt adb;dnf android-tools;pacman android-tools | WARN |
| aapt | apt aapt | WARN |
| gdbserver | apt gdbserver;dnf gdb-gdbserver;pacman gdb;apk gdb | WARN |
| strace | apt/dnf/apk/pacman/brew strace | WARN |
| ltrace | apt/dnf/pacman ltrace | WARN |

包名口径:仅收录实际存在的发行包(choco file、Debian aapt/apktool、
Fedora android-tools/gdb-gdbserver、winget Docker.DockerDesktop/
Google.PlatformTools 等);不存在即不写(数据诚实,探测失败走 manual
指引,不虚增)。

`NOT_AUTO_INSTALLABLE: dict[str, str]`(封闭声明 + 理由,覆盖
CHECK_SETS 全集的其余 12 项):ghidra(已装 env 面)、aapt2(aapt 的
found-face 别名)、vm_reachable/remote_debugger(VM 通道 human event,
#408)、device_root/debug_flag(human-configure,#451)、frida_server/
android_server(设备侧 deploy_shim,#477③)、jdwp_debug(运行中 app 的
能力)、ebpf/ebpf_android(目标内核/SDK 属性,宿主不可装)、unidbg
(Java 库非 CLI 包)。

覆盖率测试锁死:`CHECK_SETS 全集(29)== INSTALL_PLANS(17) ∪
NOT_AUTO_INSTALLABLE(12)`,无交集;mcp:<name> 动态项走 register-mcp
动词,不在此算术内。sudo_platforms 字段删除(sudo 语义移到 Manager.
needs_sudo,输出行为不变)。

## D4 deploy_shim.py(新,#477③ + #462 正规化)

一个脚本两个面,一个契约(#462"一次性垫片须标注并即弃"):

**deploy 面**(设备侧幂等部署,只经 ADB):
```
deploy_shim.py deploy --tool frida-server --local <path> \
    [--port N] [--alias NAME] [--workspace <ws>]
deploy_shim.py deploy --tool android-server --local <path> [--workspace <ws>]
```
步骤:① 解析 adb(which seam;缺 → 打 FIXES["adb"] 指引,RC_FAIL);
② **幂等预检**:`_probe_port(adb, port)`(toolchain._adb_forward_probe
复用)— PASS 即"已部署 no-op"(设备侧零变更;探针自身在 host 侧仍执行
adb forward),写台账,RC 0;③ 未部署:
`adb push <local> /data/local/tmp/<name>` → `adb shell chmod 755` →
后台启动(frida-server:`<target> -l 127.0.0.1:<port> &`;别名默认
`sysmon`,KUNGLAO_FRIDA_ALIAS/--alias 覆盖 — rename 语义;android_server:
默认名默认端口 23946);④ **re-probe PASS 门**:探通才 RC 0 + 台账
`installed: {frida_server: {manager: device-adb, at, reprobe: PASS}}`
(record_installed 三字段口径,端口不落账);探不通打印 FIXES 指引,RC 1。"连跑两次状态一致"= 第二轮全走
② 的 no-op 分支。多设备 serial 面留 v1 之外(toolchain 自身探针也是
bare adb,口径一致)。

**new 面**(#462 垫片注记):
```
deploy_shim.py new --name N --purpose P --expiry E [--target T] [--root DIR]
```
生成 `scripts/shims/<name>.md`:头部字段 target/purpose/expiry/created
+ 弃用契约行("DISCARD AFTER USE;升格进 scripts/ 须上游 issue");
首次使用创建 `scripts/shims/README.md` 声明目录级即弃语义。校验:name
slug、purpose/expiry 非空、拒绝覆盖(RC_VALIDATION=3)。

RC:0 ok / 1 deploy 或 re-probe 失败 / 3 校验拒绝(argparse 自管 2)。

## D5 统一 re-probe 闭环(#477④)

`env_manifest.record_installed(ws, name, manager, reprobe, at=None) -> bool`
— 合并一条 `installed.<name> = {manager, at, reprobe}` 进
`<ws>/env-facts.yaml`:逐工具条目 update-wins(重装覆盖旧条目),其余
顶层键全保留(version 恒写,#478 ledger 探测器不可能误报;installed 是
write-through 台账数据,resolve() 不消费 — 与五个事实族正交)。既有
文件 garbage → 拒写不覆盖(stderr 指引,返回 False),镜像 --probe 的
防御。字段非字符串 → ValueError(fail-closed 家族)。

`toolchain_install.ask_then_install`:装成功 → re-probe(既有,
task_spec 透传不动)→ `_record_installed(ws, name, fresh)`(装失败路径
不记台账 — 失败回 NextAction:degrade + 指引,既有语义);台账写失败
只 WARNING 不中断安装循环(探针结果已如实报告)。manager 归因:写
台账时再 resolve 一次(探测只读、幂等,调用形不变 — _run_install_plan
四参签名被测试钉死)。CLI `python scripts/toolchain_install.py <ws>
--type t --assume-yes` 即全链一条命令(probe → ask → install →
re-probe → 台账)。

## D6 测试映射

| 测试 | 断言 |
|---|---|
| tests/test_pkg_detect.py(新) | 词汇表封闭;which-first/known-path 回退;win32 winget-无-choco 命中顺序;apt 经 known-path;detect 注入 seam 只读;find_ghidra_install 半装态命中/未命中;MANAGERS↔plans 引用完整性 |
| tests/test_deploy_shim.py(新) | frida-server 部署 argv(push/chmod/后台启动/别名/端口);幂等(两轮零变更);re-probe FAIL 不算成功;android-server;台账写入;new 面 README+字段+校验+拒覆盖 |
| tests/test_toolchain_install.py(扩) | 覆盖率封闭声明(29 = 17 ∪ 12,无交集,≥12);install_commands 探测驱动(替换平台矩阵);resolve_install 四 mode + elevation 逐字等价;④ ask_then_install 装后台账;CLI 一条命令端到端 |
| tests/test_env_manifest.py(扩) | record_installed 新建/合并/保留用户字段/重装覆盖/garbage 拒写/非字符串 fail-closed;installed 不破坏 resolve |
| tests/test_toolchain_negotiation.py(改) | NEGOTIABLE 派生集更新(随 INSTALL_PLANS 扩容 — 派生逻辑本身不变) |

RED 纪律:新测试文件函数内 import(不存在模块 → 干净失败,非 collect
error);既有文件的扩容断言直接红。

## R1-R5 风险

- **R1 协商面扩容改变 init 非 tty 行为**:更多缺失项走 exit 8 菜单
  (原为 exit 4)。派生逻辑未变,菜单是 #451 设计的枚举面 — 已在
  design 记录,测试更新 NEGOTIABLE 钉值。
- **R2 manager 包名失真**(平台版本漂移):数据层单点
  (INSTALL_PLANS),失真表现 = 该 manager 路径安装失败 → degrade +
  指引,不比现状差。
- **R3 deploy_shim 设备多样性**(selinux/权限/后台启动语法):re-probe
  PASS 门兜底 — 探不通即 RC 1 + 指引,绝不谎报部署成功(#474 姿态)。
- **R4 env-facts 台账与 #478 ledger 名义混用**:installed 段带 version,
  形状判别器不可能误报;测试锁死。
- **R5 探测开销**:which+exists 每缺失项一次,毫秒级;known-paths 仅
  which 未中时评估。

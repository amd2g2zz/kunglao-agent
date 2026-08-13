# references/ Domain Index — 顶层渐进披露入口
> orchestrator: 本文件一次读完 → 选领域 → 派发 worker → worker 读 `_index-<领域>.md` → 加载具体文件。完整逐文件目录见 INDEX.md。
| 领域 | 包含文件 (re-library/) | 用途 |
|---|---|---|
| tools 工具链 | tools, tools-dynamic, tools-advanced, tools-crypto | 静态/动态/高级/密码学工具速查 |
| anti-analysis 反混淆 | anti-analysis | 反调试/反VM/反DBI 检测与绕过 |
| patterns 分析模式 | patterns, patterns-simulation, patterns-decode, patterns-debugging | 通用逆向技巧:模式/模拟执行/解码/动态调试 |
| languages 目标语言 | languages, languages-compiled, languages-go, languages-platforms | 语言特定逆向(脚本/编译型/Go/平台栈) |
| platforms 目标平台 | platforms, platforms-elf, platforms-kernel, platforms-hardware | 平台与格式逆向(OS/ELF/内核/硬件) |
| methodology 方法论 | field-notes, malware-analysis, malware-analysis-workflow, malware-analysis-quickstart, malware-triage, malware-dynamic-analysis, detection-engineer, malware-report-writer, phishing-case-study | 分析方法与 malware 应用领域(主要用例) |
| osint 情报搜索 | multi-search-engine, multi-search-engine-refs | 多引擎 OSINT 搜索 |
| resources 资源 | awesome-re-resources | 外部 RE 资源集合 |
| 场景 → 领域 | 反汇编/静态→tools+patterns · 动态调试→tools-dynamic+patterns-debugging · 加壳混淆/反分析→anti-analysis+tools-advanced · 固件硬件→platforms-hardware · 内核驱动/模块→platforms-kernel · 语言特定→languages · 平台特定→platforms · 检测规则/报告→methodology(detection-engineer, malware-report-writer) · 情报/搜索→osint |

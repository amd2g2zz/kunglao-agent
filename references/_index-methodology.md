# methodology 领域索引(文件层)
> 领域:方法论与 malware 应用领域(当前主要用例)。worker 接到恶意样本分析任务时先读本文件,再按需加载。
| 文件 | 一句话摘要 | 何时读 |
|---|---|---|
| [field-notes.md](re-library/field-notes.md) | 现场操作笔记:二进制类型怪癖(.pyc/WASM/APK/Flutter/.NET/加壳)、反调试绕过、专门逆向模式 | 初始 triage 后进入具体类型样本的动手分析 |
| [malware-analysis.md](re-library/malware-analysis.md) | 六阶段恶意软件分析方法论:triage/静态/动态/行为提取/IOC 识别/反分析绕过 | PE/ELF/Mach-O/APK/脚本样本的端到端分析 |
| [malware-analysis-workflow.md](re-library/malware-analysis-workflow.md) | 恶意软件分析工作流编排:按文件类型与阶段路由到专用子流程 | 开始任何恶意软件分析时的单入口编排 |
| [malware-analysis-quickstart.md](re-library/malware-analysis-quickstart.md) | 分析技能套件安装与验证速查 | 首次搭建恶意软件分析技能套件并确认可用 |
| [malware-triage.md](re-library/malware-triage.md) | 快速初始评估:5-30 分钟/样本的分类、威胁等级、优先级 | 收到新样本需要快速分类并决定是否深入 |
| [malware-dynamic-analysis.md](re-library/malware-dynamic-analysis.md) | 沙箱动态分析:Procmon/Wireshark/Sysmon/Process Hacker + 执行前安全清单 | 从静态转入运行时行为观察/流量捕获/假设验证 |
| [detection-engineer.md](re-library/detection-engineer.md) | 检测工程:Sigma/Suricata/Snort 规则、狩猎查询、IOC 去毒、STIX/OpenIOC 格式化 | 从分析结论产出检测规则/狩猎查询,或把 IOC 转为可共享运营格式 |
| [malware-report-writer.md](re-library/malware-report-writer.md) | 分析报告产出:执行摘要、结构化结论、YARA 规则、IOC 格式、交付 | 分析收尾需要产出可交付报告(IOC/检测规则/执行层摘要) |
| [phishing-case-study.md](re-library/phishing-case-study.md) | 案例:同主题 PROVEN 矛盾(F035 vs F040)与事实库污染——全局矛盾扫描要求的由来 | 同主题键 PROVEN 对冲突,或完成涉及路由结论的 run 时 |

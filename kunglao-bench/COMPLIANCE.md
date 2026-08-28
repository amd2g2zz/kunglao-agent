# kunglao-bench COMPLIANCE — 危险样本实验安全规范（B9, #823）

规则逐条可勾选，非声明式合规。`bench_intake.py --check-safety <vault>` 是每次
会话开跑的机械前置（三项：vault 加密态 / git 净空 / VM 快照基线）；任何一项红
= 拒绝开跑，红项是人的动作项，不自动修复。

## 1. 样本库安全

- [ ] vault 独立于 repo（本地加密容器：7z-AES 或 age），密钥不入库不入任何计划文件
- [ ] git 中只允许 sha256 / vault 路径 / 来源引用——**样本字节永不进 git / 日志 / 收据 / 报告**（IOC 是产出可以出现，样本本体不行）
- [ ] `.gitignore` 硬校验生效：`kunglao-bench/samples/`、`runs/**/samples/`、`grading/sealed-map.yaml`
- [ ] vault 根目录存在 `.encrypted` 标记（check-safety 检查①）

## 2. 主机卫生

- [ ] host 上禁止执行 / 双击 / 预览样本（含资源管理器缩略图、杀软排除目录外的任何解析器）
- [ ] host 只做 sha256 校验与受控拷贝入 VM
- [ ] 解压 / 重打包一律在 VM 内完成

## 3. 执行隔离

- [ ] VM-ONLY（项目 HARD 规则，违例即停实验）
- [ ] 每次运行前快照还原（bench_runner 钩子位）
- [ ] VM 分析网段无外网；动态必需网络走 C2 仿真（INetSim / fakenet 类）或白名单 DNS——**绝不触真实 C2**

## 4. 凭据与数据面

- [ ] bench VM 不携带任何真实凭据 / SSH key / token
- [ ] 共享文件夹只单向 vault → VM
- [ ] VM 内产出只经 hash 白名单目录回流

## 5. 泄漏应急

- [ ] 意外 host 执行 / 误传播 → 立即断网隔离该机
- [ ] 事件记录：时间 / 样本 sha256 / 操作序列（收据以 sample id 引用即可事后追溯）
- [ ] 上报与处置流程：隔离 → 取证 → 销毁受影响快照 → 换基线快照

## 6. 生命周期

- [ ] 实验结束样本处置二选一并记录：保留加密（供 bench 复跑）/ 销毁（逐样本删除记录）
- [ ] theZoo / MalwareBazaar ToS 摘录存档 + 研究用途声明
- [ ] 来源标注遵守各数据源署名要求

## 7. 人员规则

- [ ] 运行期间人工零干预（实验协议）；需要介入只允许操作 runner CLI（暂停 / 终止）
- [ ] 不进 VM、不碰工作区；任何干预记事件 → 该配对标 contaminated 降权

## 8. 审计

- [ ] 每次会话开始跑 `python scripts/bench_intake.py --check-safety <vault>`，三项全绿才开跑
- [ ] `git status` + `git log --all --diff-filter=A -- kunglao-bench/samples/` 双确认零样本入库
- [ ] COMPLIANCE 本文件逐条评审随实验批次更新

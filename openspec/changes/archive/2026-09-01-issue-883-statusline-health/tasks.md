# issue-883-statusline-health — tasks

## 1. Python 侧（PR 交付）

- [x] Recon：锚点表 + 镜像样例 + 快照 schema + 基线绿（proposal.md ## Recon）
- [x] tests/test_statusline_health_883.py（TDD RED）：注册表完整性 / staleness_budget 门 /
  插槽不执行 / 新探针声明即接入 / alive-deployed-moving-audit 探针判据 / 状态机转移表与
  优先级 / 闪现触发 / 快照 schema / down 自动翻转 / heartbeat_tick 集成
- [x] scripts/statusline_snapshot.py：探针注册表（v1 四探针 + audit + 2 插槽）、语义状态机、
  build_snapshot / write_snapshot（原子写）、CLI
- [x] scripts/heartbeat_tick.py：挂快照 writer（fail-open，cockpit 采样块后）
- [x] deploy-manifest.yaml 刷新（deploy_manifest.py --write + --check）

## 2. Node 侧（本地交付，不入仓；证据进 Recon 演示记录）

- [x] 备份 combined-statusline.mjs → .bak-883（diff 基线）
- [x] mjs 加 kunglao 段：stdin 解析 cwd → 向上找快照（≤4 级）→ 无快照零变化 →
  读快照零 spawn → 渲染时钟插值（呼吸/流光/火花/200ms 渐变/内嵌进度）→ 闪现调度
  （5s 窗口）→ 拼接最后一行；claude-hud/ov 段原样
- [x] 看门狗：快照 mtime > T_LIVE → down 冻结最后一帧（Node 判，无 self-report）
- [x] 验收演示：十条验收逐条 fixture 渲染文本帧 + <50ms 计时 + 前后 diff（proposal.md
  ## Recon 演示记录段）

## 3. 门与交付

- [ ] 本地门：pytest 全绿（7 已知环境性失败对照甄别）+ release_receipt --check
- [ ] conventional commits 小粒度 → push → gh pr create --base dev → CI 绿 → 停手不 merge

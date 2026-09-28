# rust-so-crack 样本设计规格（owner 指令 2026-09-29：复杂加密 + 高级反调试/反分析，E2E 端到端靶）

## 交付形态
- 家族目录：`eval/v1/tasks/release/rust-so-crack-v1/`（target/ + task.yaml + checker.py + ground_truth.json held_out）
- 构建物：`target/libcrackme.so`（arm64-v8a，Rust，cdylib）+ `target/crackme_host`（同 crate 宿主测试二进制，checker 内部用，held_out）
- 探针：`crackme_probe(const uint8_t *in, size_t n, uint64_t *out) -> int32` 导出（确定性中间 oracle 输出）；8-12 组公开 input→output 对

## 加密核心（三层可恢复参数——本样本要"破解"的目标）
1. **P1 自定义 KDF**：魔改 ChaCha20（自定义 sigma 常量 + 附加半轮 mixing）把输入 key 派生为会话密钥
2. **P2 自定义 SPN**：AES 形但换 sbox（仿射变换变体）+ 位移 rcon，CTR 模式作 license 变换
3. **P3 校验面**：`verify(key)`: P1→P2→magic(16B) + checksum 双匹配 → 0 成功；三参数（sigma 常量/sbox 种子/魔数）即待恢复目标
- 确定性：全部常量固定；反调试检测走"毒化"路径但不引入时间依赖的密钥材料（干净运行结果恒定）

## 反分析层（每层可绕但叠加，诱饵臂模式对齐既有 eval 族）
1. init 时 PTRACE_TRACEME 自检（已被 traced → 静默毒化派生密钥）
2. /proc/self/status TracerPid 解析（inline syscall，不走 libc 包装）
3. clock_gettime 时差检测（核心前后，阈值触发毒化）
4. verify 时 .text int3 断点扫描（自扫，发现→毒化）
5. anti-frida：/proc/self/maps 扫 frida-agent/gadget 特征串
6. **诱饵分支**：错误常量门控的假"成功"路径（诱饵魔数，bait）
7. 毒化语义：检测后输出"像错钥不像检测"（corrupted magic——观测面与真失败不可区分，红队需读控制流才能区分）

## oracle 契约
- task.yaml anchors：goal_verbatim（恢复三参数并重实现 verify/crackme_probe）、success_criterion（全部公开+checker 铸造探针 byte-exact）、verification_method: reproduction
- checker：replay-roundtrip（对齐 req-sign 族先例）；checker 持有 host 二进制铸造 fresh 探针（held_out，distiller_excluded）

## 构建环境事实（已核实）
- NDK 26.3.11579264 就绪（~/Library/Android/sdk/ndk/，aarch64-linux-android21+ clang wrappers）
- rustc 1.96.1 (brew) 损坏（LLVM 23.1.2 符号失配）→ brew reinstall 进行中；备选 rustup 官方工具链 + aarch64-linux-android target
- linker：NDK 的 aarch64-linux-android21-clang，cargo 配 [target.aarch64-linux-android] linker

## E2E 验收（端到端）
样本入族后跑 `scripts/e2e/run.py --unit rust-so-crack-v1`（先 py-derive-v1 冒烟再上硬靶）——init→analysis→开环→oracle 验证全链，WORKGUARD/词汇表/结算链全部真跑。

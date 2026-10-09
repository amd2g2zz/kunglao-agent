# 案例：kvm8-isa —— 从参考解释器解码私有 VM，四个摘要逐字节复现

> 案例研究 · 单元 KVM-8 私有 VM ISA 还原 · 运行 `e2e-ws-20261008-001659` · 通道 algorithm · 2026-10-07/08。
> 身份信息已脱敏（主机、用户路径、harness 检出位置）；以下全部技术痕迹 ——
> 操作码 hex、guard 算式、常量、摘要、sha256 锚点 —— 均逐字引自该运行的落盘
> 工件。目标为自建 eval 单元，其还原出的常量与摘要可以公开。

一次 agent 运行逆向了 KVM-8 私有字节码 ISA —— 容器格式、半字节操作码映射、
逐字 guard 字节、`mix()` 摘要机 —— 全部读自参考解释器源码，写出忠实的
Python 模拟器，把四个所需摘要算进 `answer.txt`，最终由独立方 rustc 构建参考
解释器、四个摘要逐字节复现收口。两个核心问题全部回答；五条 claim 全部
`PROVEN`；判分器 `complete: true, correct: true`、`high` 置信。

## 运行数据

| | |
|---|---|
| 落盘事实 | 8 条（容器布局、操作码映射 + guard、摘要机、程序形态、计算摘要……） |
| 解码 | 4 个载荷 44/44 条指令字，每字 11 项 guard 检查，零失配 |
| 步数模型 | `steps = 6·dlen + 5` 在全部四个载荷上精确命中（77/125/191/389） |
| 答案 | 4 个摘要逐字节：`ca3ca159f0de4863` / `bf5de34075b9aaf2` / `223c896626c9efe5` / `37f3b7710002012e` |
| 验证 | rustc 1.98.1 参考构建 4/4 逐字节 + 模拟器重放 4/4 + 诱饵对照相异 |
| 结局 | C-004/C-005 `PROVEN`；判分 `complete: true, correct: true`（pq-1、pq-2 均 `high`） |

## 目标

自建 eval 单元：同一个私有字节码 VM 的四个程序 —— 探针 `payload-0.bin`
（61 B）、`payload-1.bin`（69 B）、`payload-2.bin`（80 B）与主程序
`target/payload.bin`（113 B）。该 ISA 的容器格式与操作码映射不存在于任何
其他地方；参考解释器为 `target/src/vm.rs`（sha256
`cd64c5b1f5ce3b1f8fb6c04335511de4fb55aeebe01f74c069ad177d798f195e`）。任务：
计算每个程序输出的 16 位 hex 摘要，逐行写入 `answer.txt`。

## 探询过程

**1. 先钉容器格式（facts/F001）。** 逐行钉死加载器规则，再作为可证伪假设
（H1）验证：魔数 `4b 56 4d 38`（"KVM8"）位于 0、u8 `dlen` 位于 4、数据段
拷入 256 字节清零的 `mem`、代码为 4 字节字、`size = 5 + dlen + code_bytes`
—— 在全部四个载荷上精确成立（61/69/80/113 字节，`dlen` 12/20/31/64，
恒为 11 个代码字）。

**2. 先看死路 —— 工具箱。** 工作区自带诱饵求解器（`toolbox/fold8`，
sha256 `a66306aa…`，可信度分级 C5 —— 不可信来源）。在 payload-0 上所有捷径
都与 VM 不一致：`fold8`/`refold8` 打印 `af48fff476f6ae42`、`sha256[:16]` 得
`4f692df46264f056`、`md5[:16]` 得 `a9cc55fa4a796eab`，而模拟 VM 打印
`ca3ca159f0de4863`。诱饵臂随后固化成对照：`fold8` 对**全部四个载荷返回同一个
常量** —— 诱饵路径求解器输出四行一模一样的错误答案。没有任何标准摘要族
能算出这些；正是这个分歧逼出了 ISA 本身。

**3. 指令编码与 guard（facts/F002）。** 字解码为 `op = w[0] >> 4`、
`a = w[0] & 0xF`、`b = w[1] & 0xF`（`w[1]` 高半字节为操作数死位）、
`imm = w[2]`，guard 字节 `w[3]` 必须等于 `((w[0] + w[1] + imm) mod 256) ^ 0x5A`
否则 VM 以退出码 4 终止。十操作码半字节映射
（`LDI/JNE/MOV/ADDI/ADD/XOR/ROL/LDM/MIX/HLT`）。假设 H2 存活：44/44 字解码、
零 guard 失配。

**4. guard 算式确立了什么 —— 运行转录。** 模拟器对 payload-0 的反汇编
（evidence/kvm8-analysis-C-004.txt）用十一行讲完了整个故事：

```text
===== DISASM probes/payload-0.bin =====
size=61 magic=KVM8 dlen=12 code_bytes=44 words=11 data=73f295c53e60a41d4db4a331
  word  0 @000: 11 00 00 4b  LDI  a= 1 b= 0 imm=  0  guard=(11+00+00)^5a=4b ok
  word  1 @004: 12 00 0c 44  LDI  a= 2 b= 0 imm= 12  guard=(12+00+0c)^5a=44 ok
  word  3 @012: b3 01 00 ee  LDM  a= 3 b= 1 imm=  0  guard=(b3+01+00)^5a=ee ok
  word  4 @016: 93 01 00 ce  ROL  a= 3 b= 1 imm=  0  guard=(93+01+00)^5a=ce ok
  word  5 @020: 76 03 00 23  XOR  a= 6 b= 3 imm=  0  guard=(76+03+00)^5a=23 ok
  word  6 @024: c6 00 07 97  MIX  a= 6 b= 0 imm=  7  guard=(c6+00+07)^5a=97 ok
  word  7 @028: 41 00 01 18  ADDI a= 1 b= 0 imm=  1  guard=(41+00+01)^5a=18 ok
  word  8 @032: 21 02 03 7c  JNE  a= 1 b= 2 imm=  3  guard=(21+02+03)^5a=7c ok
  word  9 @036: c6 00 0b 8b  MIX  a= 6 b= 0 imm= 11  guard=(c6+00+0b)^5a=8b ok
  word 10 @040: f0 00 00 aa  HLT  a= 0 b= 0 imm=  0  guard=(f0+00+00)^5a=aa ok
===== RUN probes/payload-0.bin =====
KVM-DIGEST ca3ca159f0de4863   [steps=77]
rc=0
```

**5. 程序形态（facts/F004）。** 四个载荷共享同一个 11 字程序 —— 对数据段
循环、喂给摘要累加器 —— 只有字 1 不同：`LDI R2, imm=dlen`，即循环边界。
所以四个摘要的差异纯由数据依赖产生：`steps = 6·dlen + 5` 模型（每轮 3 条
循环指令 × `dlen` 轮，加 5 条固定指令）在 `dlen` 12/20/31/64 上精确落到
77/125/191/389。

**6. 摘要机（facts/F003）。** u64 累加器 `D` 种子 `SEED_IV =
0x54601A5B7C3E90FD`；只有 `MIX`（op 0xC）经由 `mix(D, R[a], imm)` 改写它，
常量 `C1 = 0x2F1B3C9DA7E48615`、`C2 = 0x8B4A61F0D39C57E2`：
`x = D ^ v`；`y = x·C1 mod 2⁶⁴`；`z = rotl64(y, (t & 63) + 1)`；
`D' = (z·C2 mod 2⁶⁴) ^ (z >> 29)`；输出 `KVM-DIGEST {d:016x}`。

### 字节确立了什么

| 锚点（vm.rs） | 读取 | 支撑的结论 |
|---|---|---|
| L63-64 魔数比较 | `4b 56 4d 38` | 容器身份；否则 exit 3 |
| L69-72 `len % 4` | 4 字节字定界 | 每个载荷 44 代码字节 = 11 字 |
| L85-92 guard 检查 | `(w0+w1+imm)^0x5A` | 每字自认证；反汇编 44/44 `ok` |
| L24-33 操作码常量 | 十操作码半字节映射 | 全部 44 字可解码（H2） |
| L17/L20/L21 常量 | 种子 IV + C1 + C2 | 摘要机的完整参数集 |
| 字 1 `LDI R2, dlen` | 唯一可变字 | 循环边界 = 数据长度 → 逐载荷摘要分歧 |

## 验证 —— 两个方法，具名

1. **maker 侧模拟（双跑确定性）。** Python 移植（`artifacts/derive_reimpl.py`，
   sha256 `f5d18b8b…`；分析模拟器 `runs/kvm8_emu.py`，sha256 `1ba08690…`）算出
   全部四个摘要，逐载荷进程内双跑结果一致（4/4 稳定），记录于
   `evidence/kvm8-digests.json`；`answer.txt` sha256
   `1d352efcb0e11663b50e2a11e1effa0b1b0aa9db347ba02e11970c1428b27d08`。
2. **独立检查方：rustc 参考臂 + 重放臂 + 诱饵对照**（runs/verification-C-005.md，
   判决 `verified`）。检查方构建了构造者自己的解释器 ——
   `rustc 1.98.1 -O --edition 2021 -o vm target/src/vm.rs`，编译干净、源码哈希
   与来源锚点一致 —— 并对四个载荷逐一运行：每次 exit 0、每个摘要与
   `answer.txt` 第 1-4 行逐字节一致。重放臂重跑 Python 重实现 4/4 一致；
   诱饵对照确认 `fold8` 的常量 `af48fff476f6ae42` 与每个答案行都不同。
   受控比对工件：`evidence/replay-C-005.json`（schema replay-equivalence/1，
   4 组配对全匹配）。

## 结局

两道升格门全部闭合：C-004（刻画）与 C-005（重实现）在 `claim-register.yaml`
中 `PROVEN`；判分器记录（`evidence/verdict.json`，schema v11）读出
`complete: true, correct: true`，pq-1 → `F004-kvm8-program-shape-digests`、
pq-2 → `F008-kvm8-computed-digests`，均为 `high` 置信、无未决项。maker 自己
的诚实注记 —— "rustc 在本 worker 声明的工具集之外，参考复现属于 checker 臂"
—— 恰好被验证者的 rustc 构建所闭合。

本地复现第一个摘要：

```bash
python3 artifacts/derive_reimpl.py probes/payload-0.bin
# → KVM-DIGEST ca3ca159f0de4863
```

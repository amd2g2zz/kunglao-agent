# 案例：apk-webview-attest-v2 —— 两层证明绑定打通，四个新鲜会话双双穿越

> 案例研究 · 单元 `apk-webview-attest-v2` · 运行 `e2e-ws-20261005-163158` · 通道 algorithm · 2026-10-05。
> 身份信息已脱敏（主机、用户路径、harness 检出位置）；以下全部技术痕迹 ——
> 指令级契约、掩码字节、mix 常量、PoW nonce、会话载荷 —— 均逐字引自该运行的
> 落盘工件。目标为自建 eval 单元，其还原出的常量可以公开。

一次 agent 运行以"绑定两层"的方式击破了双层证明：WebView JS 挑战（规范化、
mix-64、工作量证明）产出每会话 `attest_seed`，aarch64 `.so` 中的原生
`attest_verify` 校验 `sha256(seed ‖ nonce)[:8] ^ NATIVE_MASK` 与**由该种子
派生**的比较常量 —— 只解任何单层都一无所获。运行用自己的 MOVZ 解码器从
原始 ELF 字节重推 8 字节掩码，对真实 SDK 挖出 PoW，并让 4/4 新鲜会话穿越
两层；原生检查的承重性由阴性对照证明。五条 claim 全部 `PROVEN`；判分器
`complete: true, correct: true`；两个核心问题均以 `C0a` 回答。

## 运行数据

| | |
|---|---|
| 绑定层数 | 2 —— JS 挑战（PoW + mix-64）→ `attest_seed` → 原生 `attest_verify` |
| 原生掩码 | `NATIVE_MASK = c4 2b 91 6f 18 d3 7a 05`，从原始 ELF 字节重推（自写 MOVZ 解码器） |
| PoW | 前导零**位**语义；真实 sdk.js 执行挖出 nonce `12694` |
| oracle 电池 | 19/19 检查全 PASS（`evidence/repro/repro_c004.py`，exit 0） |
| 验收 | client.py **4/4 新鲜会话** rc=0 穿越两层；伪造的原生声明 → HTTP 403 |
| 结局 | C-004/C-005 `PROVEN`；判分 `complete: true, correct: true`（pq-1 → F007，pq-2 → F005，均 `C0a`） |

## 目标

自建 eval 单元：场景服务器 + 前端 `capture/sdk.js`（"shield-max v4.7.2"，
sha256
`8a5ccbba7981c839c610860dcd3ccfd983bb80cd5e01960bd8a0f349b8a6a34b`，5147 字节）
加 `target/libattest.so` —— aarch64 ELF64、未去符号、11720 字节、唯一动态导出
`attest_verify`（0x528–0xde4）、sha256
`2cb4f4dadeac91ce397c9ab0a38797474f7e71c2d277d74e853dba3ee07a1e58`。成功判据：
客户端完成 4/4 新鲜会话 —— JS 挑战产出种子、原生检查放行 —— 取回最终载荷。

## 探询过程

**1. JS 挑战层，逐机制读出（facts/F006）。** 直接静态读取得到七个机制：
base64 字符串表（`/challenge`、`/verify`、`shield-integrity-stub-v4.7`）；
规范化（对象键排序、`k=v` 以 `|` 连接，覆盖采集的 6 个字段 `ua, platform,
lang, screen, tz, depth`）；完整的内联 FIPS-180-4 SHA-256；每 2 秒删除被篡改
状态的完整性看门狗（自篡改绊线，与挑战数学无关）；前导零**位**计数器
（每个 hex 位：`0`→4、`1`→3、`2-3`→2、`4-7`→1）；mix；主流程。

**2. 先看死路 —— mix 有两个分支，只有一条接线（facts/F006）。**

```text
ver === 1（在用）： r = ((s16 ^ 0x5F5F5F5F) * 0xC0FFEE11) mod 2^64，再 rotl 13
ver !== 1（死支）： r = (((s16 + 0x1337C0DE) & M) * 0x85EBCA6B) & M，再 rotr 7
```

主流程投递的是 `ver=1` 分支；第二个分支是一套完整、貌似合理、但是错误的
算法，带自己的常量。电池的 mix 单射性检查（B 系列节）钉死在用分支；凭
"看上去像"而非调用点选分支的求解器会落进死车道，下游每个摘要全部发散。

**3. PoW，老实挖矿。** 原像 `sid:salt:nonce:s2`，十进制 `n` 与十进制 `s2`
（`s2` = mix 输出的**十进制字符串**），难度按 hex 摘要的前导零位计。
对真实 SDK 挖出的 nonce 是 `12694`；PoW 最小性（无更小的 n 满足）是电池
检查之一。

**4. 原生层，字节锚定（facts/F007）。** 从反汇编读出 `attest_verify` 契约：
`int attest_verify(seed, seed_len, nonce, nonce_len, expected, expected_len)`；
验证序言要求 `expected_len == 8`、`seed_len == 16`（种子按恰好 16 原始字节
消费）、`nonce_len ≥ 1`；返回 0 = 接受。消息为
`seed[16] ‖ nonce[min(nonce_len, 48)]` —— nonce 在 48 字节处截断（0x574 处
`csel w8, w3, #0x30, lt`）—— 以内联标准 SHA-256（K 表合 FIPS）哈希，逐字节
比较 `expected[i] == sha256(msg)[i] ^ mask[i]`（`i < 8`）。

**5. 掩码，从原始字节而非字符串。** 电池 A 系列节用手工写的 MOVZ/MOVK
立即数解码器直接从原始 ELF 字节重推 SHA-256 K 表与 8 个掩码字节，并与
`llvm-objdump -d` 交叉核对：`NATIVE_MASK = c4 2b 91 6f 18 d3 7a 05`。工作
向量钉死两个值：`native_mask_hex = c42b916f18d37a05`、
`expected_hex = 78109b7ff16e782a`（`evidence/c004-model-vectors.json`）。

### 字节确立了什么

| 锚点 | 读取 | 支撑的结论 |
|---|---|---|
| `_0xmix` ver 分支 | `^0x5F5F5F5F`、`*0xC0FFEE11`、rol13 | 在用 mix；`0x1337C0DE`/`0x85EBCA6B` 的 ror7 分支是诱饵 |
| `_0xzero` 位表 | 前导零位 | PoW 难度按位计，不按 hex 位计 |
| 0x574 `csel w8, w3, #0x30, lt` | nonce 截断 min(len, 48) | 原生消息精确长度 `16 + min(nonce_len, 48)` |
| 0xdc0 `cset w0, ne` | 0 = 接受 | `attest_verify` 的接受/拒绝极性 |
| ELF 立即数（MOVZ/MOVK） | 掩码 `c4 2b 91 6f 18 d3 7a 05` | 比较常量，不依赖任何字符串引用的重推 |
| `/verify` 响应 `attest_seed` | 层间绑定 | 原生检查消费的种子 —— 两层是同一个协议 |

## 验证 —— 两个方法，具名

1. **oracle 电池（模型独立重推）。** `python3 evidence/repro/repro_c004.py`
   以 **19/19 检查** exit 0：K 表 FIPS 同一性、7 个掩码字节从原始 ELF 重推、
   0xd70 的 eor 立即数、规范化、mix ver-1 单射性、零位同一性、PoW 命中 +
   最小性、原生接受/拒绝矩阵、双向 nonce 截断（runs/verification-C-005.md，
   Face 3）。C-004 的验证者证据另记录 17/17 向量重放与真实 SDK 执行挖出
   nonce `12694`。
2. **在线复现 + 阴性对照。** 验证者起全新引擎实例（端口 60149），以 4 个
   独立进程运行 `client.py` —— **4/4 rc=0**，各取回不同 32-hex
   `secret_data`（046cfe94e33f48f0…、01f5f5f474f243c9…、9d030a5ce5e942bd…、
   c87ccc77240845ff…）。随后阴性对照（Face 2）：scratch 探针老实解出 JS 层，
   把故意伪造的原生声明（`digest[:8] ^ 0xFF`）投给第二个全新实例（端口
   60220）—— HTTP 403。4/4 的接受并非空转；引擎确实在校验
   `sha256(seed ‖ nonce)[:8] ^ NATIVE_MASK`。Face 4 逐字节闭环：
   `client.py:17 NATIVE_MASK = bytes.fromhex("c42b916f18d37a05")` 与反汇编
   立即数相等（`evidence/e2e-c005-attest-verify.asm`）。

## 结局

C-004（刻画）与 C-005（重实现）在 `claim-register.yaml` 中 `PROVEN`，验证者
签署援引掩码重推、oracle 电池、向量重放、在线 4/4 与 403 阴性对照；判分器
（`evidence/verdict.json`，schema v11）：`complete: true, correct: true`，
pq-1 → `F007-native-attest-verify`、pq-2 → F005，均 `C0a`，无未决项。
两层证明在一个能工作的客户端里绑定，且阴性对照表明绑定是被检查的、
不是被假设的。

本地复现验收：

```bash
python3 server/engine.py --host 127.0.0.1 --port 60149 &
python3 client.py --base http://127.0.0.1:60149
# → rc=0, prints the retrieved secret_data
```

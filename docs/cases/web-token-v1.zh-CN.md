# 案例：web-token-v1 —— 签名 SDK 还原成一行 HMAC，四个新鲜会话全部铸出

> 案例研究 · 单元 `web-token-v1` · 运行 `e2e-ws-20261005-162428` · 通道 algorithm · 2026-10-05。
> 身份信息已脱敏（主机、用户路径、harness 检出位置）；以下全部技术痕迹 ——
> base64 表项、密钥材料、HMAC 向量、会话 id、错误码 —— 均逐字引自该运行的
> 落盘工件。目标为自建场景服务器（回环上的 `engine.py`），其还原出的密钥与
> 填充可以公开。

一次 agent 运行拆开了服务端 JS SDK 的唯一混淆层，还原了 HMAC 密钥（由三个
乱序字符串表部件拼装）、5 字节消息填充、精确的签名输入 —— 再用证伪坐实填充
位置，在场景服务器上为四个新鲜会话铸出合法令牌，并亲眼看着被截获的令牌死在
重放上。五条 claim 全部 `PROVEN`；判分器 `complete: true, correct: true`；
两个核心问题均以 `C0a` 回答。

## 运行数据

| | |
|---|---|
| 字符串表解码 | 10/10 base64 表项 → 密钥部件、填充、端点、字段名 |
| 签名密钥 | `w7f_xz9Ql2m8sK0eV`（17 ASCII 字节），填充 `6d 1f 0b 9a c2`（5 字节） |
| 确定性向量 | 3 条记录向量 + 2 个填充位置证伪臂，全部逐字节复算 |
| 验收 | client.py **4/4 新鲜会话**（4 个不同 sid）取得 `secret_data`；被截获令牌被拒 |
| 验证 | 验证者 5 面全 PASS + 红队签署；判分 `complete: true, correct: true`（pq-1 → F005，pq-2 → F007，均 `C0a`） |

## 目标

自建 eval 单元：场景服务器（每次验证运行起全新实例）+ 前端 `capture/sdk.js`
—— "shield-lite sdk v1.2"，单 IIFE 加固脚本（sha256
`4e93d27ea53f45debdb01a0a5e39e7b0886cc24ff82cedde29c4763e5dabf8c9`）。流程：
`GET /`（会话 cookie）→ `GET /challenge` → 铸令牌 → `POST /verify`。任务：
逆向 SDK、提取密钥与填充、构建能为主鲜会话铸造限时令牌的离线客户端；
被截获的令牌绝不可重放。

## 探询过程

**1. 加固层就是一张 base64 字符串表（facts/F002）。** `_0xd(i)` =
`atob(_0xa[i])`，共 10 项 —— 混淆的全部。fact 的 reproduce 命令就是解码
一行：

```text
['Ql2m', '8sK0eV', 'w7f_xz9', '/verify', '/challenge',
 'sid', 'ts', 'sig', 'secret_data', '6d1f0b9ac2']
```

表里藏着的陷阱：密钥在运行时按 `[_0xd(2), _0xd(0), _0xd(1)].join('')` 拼装
—— 部件顺序是 2、0、1，不是表的顺序 —— 得到 `w7f_xz9Ql2m8sK0eV`。填充是
对表项 9 的 hex 对解析：`6d 1f 0b 9a c2`。

**2. 令牌算法（facts/F003）。** 完整语义：
`sig = hex(HMAC-SHA256(key, pad ‖ utf8(ts + '|' + sid)))`；verify 体只投
`{ts, sig}` —— `sid` **不在**请求体里；服务端在服务侧绑定会话，这恰是成功
判据要练的新鲜度轴。

**3. 先看死路 —— 填充位置，用证伪裁决（facts/F005）。** 确定性记录向量
`sig(1759675200, a1b2c3d4e5) = d730f21f525d64a9…` 只在填充**前缀**时复现。
两个变体被运行并否决：

| 变体 | 结果 |
|---|---|
| 填充整个省略 | `985fac5fd1391eb0…` —— 与记录向量不同 |
| 填充后缀（`msg ‖ pad`） | `323752f94a937873…` —— 与记录向量不同 |

两种错位、两个不同的错签名 —— 填充是前缀，算法的每个字节就此确定。

**4. 在线确认（facts/F006）。** 场景服务器接受了客户端铸的令牌，另暴露两道
SDK 本身看不见的服务门：浏览器 UA 检查（curl UA → `non_browser_ua`）与
无会话检查（`no_session`）；`ts` 以 JSON 整数传输。

**5. 验收（facts/F007）。** 交付物 `client.py`（sha256 `7a5ed831…`）完整跑通
—— 全新 `GET /`、`GET /challenge`、铸令牌、`POST /verify` —— 四轮：

```text
sids: f463fffb70b6779b, d4c4abc9ba63646b, d2d40352870dd97f, 2135e848bab3357e
SUMMARY: 4/4 fresh sessions retrieved the protected payload   (exit 0)
replay: 被截获的 {ts=1791190272, sig=a4523b0d…} 投给新会话
        → {"error":"bad_signature"}，无 secret_data
```

同会话重放另被 `{"error":"replayed"}` 拒绝，过期 ts 令牌被
`{"error":"stale"}` 拒绝 —— 会话绑定与新鲜度各自独立地拒绝重放。

### 字节确立了什么

| 锚点（sdk.js） | 读取 | 支撑的结论 |
|---|---|---|
| 第 3 行 `_0xa`（10 项） | base64 字符串表 | 唯一混淆层；10/10 解码 |
| 第 6 行拼装 `[d(2),d(0),d(1)]` | 乱序部件 | 密钥 = `w7f_xz9Ql2m8sK0eV`，非表的阅读顺序 |
| 第 8 行对表项 9 的 hex 对解析 | 填充 `6d 1f 0b 9a c2` | HMAC 输入前缀 —— 由两个证伪臂坐实 |
| verify 体仅 `{ts, sig}` | sid 不上线 | 服务侧会话绑定 → 新鲜度保证 |
| `secret_data`（表项 8） | 成功标记 | 每个新鲜会话必须取回的载荷 |

## 验证 —— 两个方法，具名

1. **从样本字节的静态复算。** 验证者直接从 `capture/sdk.js`（而非客户端内嵌
   副本）重新提取字符串表，与 `client.py` 逐字节相等 10/10；重推密钥与填充；
   精确复算 F003 参考向量与在线向量；按还原算法从 `(ts, sid)` 重推全部 4 个
   记录验收签名（4/4）。
2. **在线复现 + 对抗重放。** 被钉的服务器实例已死；验证者起全新 `engine.py`
   于同一端口，重跑 `client.py --sessions 4` → 4/4，四个**新的**不同 sid
   （099e1539ca2597ad、504409eece82215a、51aea46666a2fc5d、7fa62b89528e1e85），
   exit 0 —— 随后把 *maker 自己被截获的令牌*（取自钉存快照）跨服务器实例
   重放：被拒（`stale`），无 secret_data。面清单：fingerprint、
   static-recompute、replay-equivalence、adversarial-replay、
   oracle-gate-probe —— 全 PASS（runs/verification-C-005.md，判决
   `verified`；脚手架 claim 的红队签署亦在案）。

两条不构成反驳的分歧留在案上：跨会话重放按令牌年龄不同，服务器答
`bad_signature` 或 `stale`（检查顺序）；一条 fact 引用了从未写出的 scratch
辅助脚本 —— 其内联 fallback reproduce 有效并被采用。

## 结局

C-004 与 C-005 在 `claim-register.yaml` 中 `PROVEN`（验证者签署
runs/verification-C-004.md 与 -C-005.md）；判分器（`evidence/verdict.json`，
schema v11）：`complete: true, correct: true`，pq-1 → F005、pq-2 → F007，
均 `C0a`，无未决项、无矛盾。成功判据两条款逐字成立：四个新鲜会话取回载荷；
被截获的令牌绝不重放。

本地复现验收：

```bash
python3 engine.py --host 127.0.0.1 --port 18777 &
python3 client.py --base-url http://127.0.0.1:18777 --sessions 4
# → SUMMARY: 4/4 fresh sessions retrieved the protected payload
python3 client.py --base-url http://127.0.0.1:18777 --replay-check
# → REPLAY-CHECK: PASS (captured token rejected)
```

# Machine-Check Oracle Contract (#332) — 可执行预言机契约

> 单源真值映射表: `references/machine_check_map.yaml`(由
> `scripts/kunglao_verify.py::load_machine_check_map` 加载)。本文档为契约说明;
> 下方的映射表镜像由
> `tests/test_machine_check_contract.py::test_map_parity_with_contract_doc`
> 机械比对 YAML — **两处必须同步修改**, 否则 parity 测试失败。

## 为什么

CrackMeBench 调研 (#330): 代理会 over-trust 反编译输出。独立 verifier 与
maker 可能踩进**同一条静态分析错误路径** — 此时"独立推导 + 结论比对"全过,
验证形同虚设。验证必须终止于**机器检查**: 字节/执行级的 expected/actual 比较,
"提交物被预言机接受"才算数。'我读了源码觉得对' 不是验证。

## 契约

每条 verifier 验证记录(kunglao-redteam 输出)必须含**至少一条**:

```json
{"command": "<字节/执行级检查命令>", "expected": "<期望值>",
 "actual": "<实际观测值>", "passed": true}
```

- `command` 必须是可执行的字节/执行级检查(工具 + 比较), 散文式
  "I read the source and it looks right" 不通过。
- `passed` 必须是严格布尔。**任何一条 `passed=false` → 整条记录验证不通过**
  (STAMP 不得升级 PROVEN)。
- 缺 machine_check → 验证不通过。

### 记录格式 (runs/verify-redteam-\*.md)

````markdown
## MACHINE-CHECK (oracle contract #332)
```machine_check
[
  {"command": "xxd -p -s 0x0 -l 2 bins/<sha>", "expected": "4d5a",
   "actual": "4d5a", "passed": true}
]
```
````

也接受单行形态: `machine_check: {"command": ..., "expected": ..., "actual": ..., "passed": true}`。

### 例外路径 (仅纯 CTI 类)

```markdown
```machine_check
{"machine_check": "none", "reason": "pure CTI correlation — no artifact bytes",
 "claim_kind": "cti_correlation"}
```
```

例外被接受当且仅当: `claim_kind` 在映射表的 `exception_allowed` 清单内 **且**
与 fact 的 `boundary_type` 匹配(见下方 boundary_type 对照)。`reason` 必填。
未知 boundary_type → 例外禁用(fail closed)。

## 校验接入

| 入口 | 行为 |
|---|---|
| `kunglao_verify.check_machine_check_contract(record_text, claim_kinds, mc_map)` | 记录级 schema 校验 (ok, reason) |
| `kunglao_verify.machine_check_gate(ws, fact_id, claim_id, fact)` | 定位 runs/verify-redteam-\*.md(最新一份)并执行契约校验 |
| `kunglao_verify.verify()` | L2 CONFIRMED 分支强制过 gate; 失败 → `overall=PARTIAL` + warning `MACHINE_CHECK_FAILED`(STAMP 不提升) |
| `kunglao_verify.machine_check_map_coverage(seen_types)` | 映射表覆盖统计(验收 ≥80%) |
| `kunglao_verify.validate_machine_check_entry(entry)` | 单条 entry 结构校验(4 字段/布尔/非空/机器级命令) |

## 映射表 (claim kind → machine check type)

| claim kind | machine check type | exception allowed |
|---|---|---|
| static_constant | disasm_constant_check | no |
| decryption_key | decrypt_compare | no |
| input_bypass | vm_execution | no |
| numeric | byte_recalc | no |
| string | byte_offset_locate | no |
| structure | byte_parse | no |
| negative_result | bounded_search | no |
| capability | vm_execution | no |
| cti_correlation | none | yes |
| attribution | none | yes |
| external_source | none | yes |

- **static_constant** → `disasm_constant_check`(VA 常数字节级比对)
- **decryption_key** → 实际解密比对(key 派生 + 密文 → 明文字节)
- **input_bypass** → VM 执行(192.168.20.128 通道; host 禁 sample 执行)
- **numeric** → 原始字节重算(numeric-fidelity 反向校验)
- **string** → 原始字节偏移定位(xxd/grep 定位 + 偏移断言)
- **structure** → 字节级结构解析(pefile/capstone 字段比对)
- **negative_result** → 有界搜索(bounded search 再跑一次, 0-hit 只证有界)
- **capability** → VM 执行或字节级调用链解析
- **cti_correlation / attribution / external_source** → 纯 CTI/外部来源类, 例外允许
  `machine_check: none`; 但有源 artifact(报告 JSON/样本)时仍应做源字节重检

## boundary_type → claim kinds (例外资格)

| boundary_type | eligible claim kinds |
|---|---|
| confirmed | static_constant, decryption_key, input_bypass, numeric, string, structure, capability |
| capability_not_executed | capability, input_bypass |
| link_not_closed | capability, static_constant |
| source_derived | cti_correlation, external_source |
| numeric | numeric |
| observation | static_constant, decryption_key, input_bypass, numeric, string, structure, negative_result, capability |
| coordinate | numeric, string |
| pure_negative | negative_result |
| contradiction | numeric, string |
| positive_observation | static_constant, decryption_key, input_bypass, numeric, string, structure, negative_result, capability |

(与 `machine_check_map.yaml::boundary_type_map` 一致; 覆盖 schema 全部 9 类 +
workspace 遗留 `positive_observation`。)

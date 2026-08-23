# Unit Test 编写规范 — kunglao-agent (issue #463 P3)

> **核心原则**:测试是质量保障**手段**,不是指标。Coverage 和测试数
> 是观测,不是优化目标。每一个测试都要回答"它发现了什么缺陷",
> 否则就不该存在。
>
> 参考:devkit/docs/quality_gates.md 的 Gate 4(测试有效性)。

## 1. 写测试前问自己 4 个问题

每个测试,在你 `Write` 之前,先回答:

| 问题 | 不合格的回答 |
|---|---|
| **这个测试测的是什么错误?** | "测一下函数能跑" / "提高 coverage" / "看起来该测一下" |
| **如果代码有 bug,这个测试会失败吗?** | "改了一行还是绿的" = 弱测试 |
| **这个 bug 真的发生过/可能发生?** | "理论上可能" 不够 — 要么历史 bug、要么 schema、要么 invariant |
| **删除这个测试会怎样?** | "coverage 掉 N%" — 那就值得删 |

**任意一个回答不合格,删掉这个测试**。

## 2. 命名

### 文件名
- `tests/test_<module>.py` — 一个源模块一个测试文件
- `tests/test_devkit_*.py` — devkit/ 自己的测试(在 tests/ 下,与产品测试平级)
- 禁止:`test_xxx_v2.py`、`test_new.py`、`test_temp.py`、`test_misc.py`

### 函数名
- 必须解释"行为",不是"做什么"
- 格式:`test_<scenario>_<expected>` 或 `test_<behavior>`

```python
# ## 好的
def test_invalid_type_returns_pending_decision():
def test_consumer_workspace_missing_exits_7():
def test_decide_with_empty_ledger_returns_idle():

# ## 坏的
def test_function():       # 不说明行为
def test_run():           # 同上
def test_it_works():      # 同上
def test_coverage():      # 不解释行为
```

### 不允许
- `test_1` / `test_2` — 数字命名
- `test_smoke` / `test_basic` — 不解释行为
- `test_happy_path` — happy path 不是测试名

## 3. AAA 结构 (Arrange-Act-Assert)

每个测试**必须**三段,代码里用空行分隔。

```python
def test_consumer_workspace_missing_exits_7():
    # Arrange
    argv = [sys.executable, str(SCRIPT), str(missing_dir)]

    # Act
    r = subprocess.run(argv, capture_output=True, text=True, timeout=60)

    # Assert
    assert r.returncode == 7
```

禁止:
- Arrange 和 Act 混在一起
- 多步 Act(分多个函数,或每个 step 一个测试)
- Assert 在函数中段(读起来累)

## 4. 每个测试一个断言主题

```python
# ## 坏的 — 一个测试验证 5 个不相关的事
def test_init():
    assert rc == 0
    assert "hooks ->" in out
    assert "wired" in out
    assert "dormant" in out
    assert len(claim_register) == 3

# ## 好的 — 拆成 4 个测试,每个有明确失败语义
def test_init_exits_zero():
def test_init_deploys_hooks():
def test_init_states_dormant_semantics():
def test_init_seeds_three_claims():
```

**例外**:有时一个行为有多个不变量的输出(如返回 tuple),可以一个测试
断言 tuple 全部字段。但**断言要解释**,别用裸 assert。

## 5. 不要测实现细节

| 错(测实现) | 对(测行为) |
|---|---|
| 断言函数调用了 `subprocess.run` | 断言子进程 exit code + 输出 |
| 断言 log 文件有特定字符串 | 断言外部可观察行为 |
| 断言内部状态 `_private_field` | 断言公共 API 输出 |
| 断言 monkey-patched 行为 | 断言用户视角的结果 |

**为什么**:重构会破坏测实现的测试,但不破坏行为。这是测试膨胀的
主因之一。

## 6. Fixture 边界

- `tmp_path` 是首选(每次新目录,完全隔离)
- 共享 fixture 只在以下情况用:
  - 多个测试都用同一份 fixture,且 fixture 创建昂贵
  - fixture 是只读的(如 schema 文件)
- 禁止:
  - 一个 fixture 跨 10+ 测试
  - fixture 顺序敏感(test_x 必须先于 test_y)
  - fixture 修改全局状态

## 7. 不要写"凑数"测试

**反模式**(明确禁止):

```python
# ## 反模式 1:重复断言同一件事
def test_function_returns_one():
    assert func() == 1
def test_function_returns_one_again():
    assert func() == 1

# ## 反模式 2:测试在测自己的 fixture
def test_fixture_works():
    assert fixture.value == fixture.value  # tautology

# ## 反模式 3:无关的 happy path
def test_module_imports():
    # 如果模块不能 import,所有其它测试都红 — 这个测试无信息
    import somemodule
    assert somemodule

# ## 反模式 4:覆盖率 padding
def test_all_branches():
    for i in range(100):
        assert handle(i) == expected[i]
    # 没有 invariant 解释,纯粹凑行数
```

## 8. Property-based / Invariant 测试

关键模块(状态机、决策、生命周期)**必须有** invariant 测试,不能只靠
example。

```python
# ## 不变式:决策总数 = 各状态数之和
def test_decide_invariant_total_count():
    decisions = [decide(state) for state in sample_states]
    total = sum(d.count for d in decisions)
    assert total == sum(len(s.claims) for s in sample_states)
```

工具:
- `hypothesis` (Python):自动生成边界用例
- 手写 invariant 测试:每个公共函数至少 1 个 invariant 测试

## 9. 错误/边界测试优先

每个公共函数必须测:
- **正常路径**(至少 1 个)
- **错误路径**(至少 1 个:invalid input / missing file / 等)
- **边界值**(0、1、最大、None、空字符串、空列表)
- **故障注入**(Phase 2 fixtures):网络/进程/资源失败时的行为

**只看 happy path 的测试不可信**。

## 10. 命名约定

| 命名 | | 含义 |
|---|---|---|
| `test_*` | | pytest 自动发现 |
| `Test*` | | pytest 测试类(不常用) |
| `*_integration` | | 集成测试(pytest marker) |
| `*_e2e` | | 端到端测试(marker) |
| `*_regression` | | 历史 bug 回归(每个历史 bug 一个) |
| `*_invariant` | | 不变式测试 |

## 11. 不要测的东西

- **Python stdlib**(`os.path.join`、`json.dumps` 等)— 别人测过
- **第三方库**(pytest, pyyaml)— 别人测过
- **私有 helper**(`_internal_func`)— 重构时改 API
- **type annotation** — mypy 干这事
- **常量值** — 没意义

## 12. 何时停止加测试

如果以下任一信号出现,**停止扩张测试**:

- [ ] First-Pass Acceptance Rate 持平或下降
- [ ] Defect 没有下降
- [ ] Regression Rate 持平或上升
- [ ] Rework Rate 上升
- [ ] 测试数量增加但 Mutation Score 没增
- [ ] 新加的测试都是 happy path + 没有 invariant
- [ ] 同一函数有 5+ 个测试且都断言同一行为

**单元测试是手段,不是指标。**

## 13. Anti-pattern 检测(自查清单)

写完测试后,过一遍:

- [ ] 没有 `def test_xxx():` 没解释行为的
- [ ] 没有重复断言同一件事
- [ ] 没有测试在测自己的 fixture(tautology)
- [ ] 没有"凑 Coverage"的边界循环
- [ ] 没有测实现细节(private 函数 / 内部状态)
- [ ] 失败信息足够明确(reviewer 能看出哪里错)
- [ ] 关键模块有 invariant 测试
- [ ] 错误路径和边界值都覆盖了

## 见

- `devkit/docs/quality_gates.md` — Gate 4(测试有效性)
- `devkit/docs/quality_roadmap.md` — KPI 跟踪
- `openspec/changes/issue-463-coverage-gate/` — 质量门来源
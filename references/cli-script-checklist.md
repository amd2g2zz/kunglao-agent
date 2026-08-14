# CLI script spec checklist (issue #277)

> Script-discipline contract: any reusable tool logic lives as a parameterized
> CLI script — worker-facing analysis tools in `<SKILL_DIR>/tools/<category>/`
> (registered in `tools/_INDEX.yaml`, see §0), skill infrastructure CLIs in
> `<SKILL_DIR>/scripts/` — never as `python -c "..."` / heredoc `<<'EOF'`
> inline execution. A new script
> is acceptable only if it satisfies every line below. Canonical exemplar:
> `scripts/shell_defaults.py` (idempotent shell env-default management —
> `--var/--value/--profile/--shell`, check/apply/remove, exit codes, `--json`).

## 0. 先查目录 (issue #294)

写任何新脚本前, 先按顺序查:

1. `tools/_INDEX.md` — 6 类能力域表, 找任务所属领域(crypto/static/ghidra/dynamic/pipeline/aux)
2. `tools/_index-<category>.md` — 该域的一行式契约骨架, 看是否已有工具覆盖同一 capability
3. `tools/_INDEX.yaml` — 机器契约, 确认工具名/子命令/输入输出

有匹配工具 → **优先用其 CLI 试解**(参考各工具 `--help` / `input_output` 契约),
不写新脚本。无匹配才进入下面 1-8 条写新脚本。`hooks/worker_budget.py` 的
`toolfirst` gate 会核对 dispatch 是否带 `tool-catalog: <name>` 或
`tool-catalog: none (reasoning: <why not>)` 标记 —— 命中已注册工具的能力
关键词却无标记会被 REJECT。

**编码 / 命名硬约定 (issue #317, #314 A1-A3 — 缺一即被机械测试拦下):**

4. **UTF-8 stdout 必配**: 新 CLI(带 `if __name__ == "__main__":` 的 .py)必须在
   `import sys` 后立即执行 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`,
   外包 `try/except (AttributeError, ValueError): pass`。原因: 输出含 U+FFFD
   (decode errors="replace" 的产物)或任何非 ASCII 时, GBK 控制台无法编码 →
   裸 UnicodeEncodeError traceback + exit 1, 破坏 "structured error, never a
   traceback" 契约(1b/1c/2b 三批独立踩中)。统一 UTF-8, 不是 errors="replace"
   补丁。机械强制: `tests/test_utf8_stdout_convention.py` 扫描 tools/ 全部 CLI,
   缺失即红。
5. **测试 helper 解码必配**: 测试 helper 的 `subprocess.run` 必须带
   `encoding="utf-8", errors="replace"`(不要裸用 `text=True` —— 其默认按
   locale/GBK 解码; 工具统一 UTF-8 后, GBK 解码多字节字符 → reader thread
   UnicodeDecodeError, stdout=None; 1c 踩中)。
6. **目录命名避开 Windows 保留设备名**: 工具目录必须用 `tools/auxiliary/`,
   不能用 `tools/aux/`(AUX 是 Windows 保留设备名, git 无法跟踪该路径; #307
   刚踩, 已有 rename 先例)。机械强制: `tests/test_windows_reserved_names.py`
   扫描仓库全部路径组件(CON/PRN/AUX/NUL/COM1-9/LPT1-9)。

## 1. Parameterized, never hardcoded

- All targets come from CLI args, not string literals: `--binary PATH`,
  `--rva`, `--var`, `--value`, `--profile`, `--shell`, `--port`, ...
- No sample path, VM IP, workspace path, or hook address embedded in the body.
- Use `argparse` (self-describing): `--help` must render without reading source.

## 2. Input injectable / mockable

- Inputs (paths, env names, values, file handles) are passed in, so tests can
  drive the script with a tmp workspace / temp files / synthetic data.
- No implicit dependency on `cwd` or ambient environment unless documented;
  read workspace state from the argument, not from `os.getcwd()`.

## 3. Idempotent

- Re-running the same invocation converges to the same final state.
- apply = no-op when the target state already exists (`unchanged`), rewrite when
  it differs, append when absent — never duplicate, never error on no-op.
- remove = no-op when the target is already absent.

## 4. Three-state semantics (check / apply / remove or equivalent)

- A mutating CLI exposes at least `check` (read-only probe), `apply` (make
  state), and `remove` (unmake state) subcommands — or an equivalent dry-run /
  commit split.
- `check` never writes; `apply`/`remove` report what they did.

## 5. Exit codes distinguish state

- `0` = OK / desired state; distinct non-zero codes for each distinct outcome
  (e.g. `1` = truthy/tainted, `2` = absent, `3` = error).
- Callers (hooks, kunglao.py) branch on exit codes, not on stderr text.

## 6. Output: explicit text or JSON

- Human-readable default (one line per result) plus a `--json` flag emitting a
  single JSON object with stable keys (no trailing junk on stdout).
- No stray `print()` debugging; structured results only.

## 7. Errors carry guidance

- Every error message says what went wrong AND what to do next (the exact
  command to run, the file to fix, the env var to set).
- Never fail silently; never print a bare traceback to the caller as the
  primary message.

## 8. Reusability bar

- Reusable iff: (a) takes the sample/input as an argument, (b) the only
  sample-specific constant is the input, (c) the output schema is fixed.
- Sample-specific one-shots go in `scripts/sample_specific/`, never `scripts/`.
- Naming: `<verb>_<object>.py` — no fact-ID / claim-ID prefixes
  (`f046_*.py` is forbidden).

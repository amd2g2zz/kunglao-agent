# Proposal: 运行时版本钉 + 模板 stamp 一致性 — Wave 1 (#758 G1+G4)

## Why

两个独立根因同属 "运行时/模板版本" 故障类：
1) **无版本钉**：pyproject.toml 只有 `requires-python = ">=3.10"`（3.10 是 tomli
   backfill 的测试下限，不能抬），无 `.python-version`——本地三 venv 实测全
   3.13.7，而 CI release-check.yml 钉 `UV_PYTHON: python3.11`。本地 3.13 vs
   CI 3.11 分裂，任何 3.13-only 行为（如异常组语法差异、warnings 细节）只在
   本地暴露不了或反过来。
2) **stamp 撒谎**：upgrade 的 `_item_template_stamp_refresh` 只换 stamp 注释行
   （template_version.stamp_workspace docstring: "the rest of the file is
   untouched"）——模板正文停在 init 当天版本，新 stamp 盖旧正文。#717 现场正是
   这类 v0.1.2-stamped 旧正文 workspace 放大了三层闸门逃逸。

用户裁决（2026-08-27）：**uv 的 python 版本是 python3.11 而不是随便装** ——
仓库层钉 3.11（`.python-version`），pyproject 下限保持 >=3.10 不动。

## What Changes

- **G1a**: 新增 `.python-version`（内容 `3.11`）。uv 会按它重建 venv；
  CI 的 `UV_PYTHON=python3.11` 与之汇合。requires-python 不变。
- **G1b**: env_check 增 `python_version` 检查行（PASS on 3.11.x / WARN 其它，
  非 FAIL——漂移是提示不是阻断）；kunglao_upgrade main() 开头 stderr WARN 行。
- **G4**: upgrade 刷 stamp 前校验 CLAUDE.md 框架可识别段与当前模板渲染的一致性
  签名（标题序列子序列匹配）；不一致 → 跳过 stamp 刷新 + stderr WARN，
  item 返回 `template_stamp_refresh(skipped: frame-drift)`。语义：宁可 stamp
  保持旧值诚实反映旧正文，不制造新 stamp 盖旧正文。

## Out of scope（Wave 2）

G2/G3（CLAUDE.md.base.tmpl 三段式改造 / 升级时模板收集合并）与 #755 A3 同文件，
本切片**绝对不碰 templates/**；#755 分支完成后另补关联 PR，届时 #758 才 close。

## 安全面

- `.python-version` 只影响解释器选择；lock/CI 三方仍同源可对账
- stamp 跳过路径 fail-open 于"模板读不到"（无法验证 != 漂移），fail-closed 于
  "内容真漂移"；无新写盘面

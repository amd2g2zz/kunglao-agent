# -*- coding: utf-8 -*-
"""TDD RED — tests for scripts/report_consistency_check.py (#57).

Cross-chapter report-INTERNAL consistency checker. Catches the 3 contradiction
groups + the negative-finding scope amplification that slipped past a2b5e25c
P4 review (per-chapter slicing, no cross-chapter view).

The regression fixture (REGRESSION_FIXTURE) is a SYNTHETIC markdown report
built from issue #57's PUBLIC contradiction-group list (3 groups + the F035
caliber-amplification). It is test data quoting the issue, not live user data
and not the customer docx. The detector reads NO workspace state, NO binary,
NO fact file — only the report text passed to it.
"""
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for sub in ("scripts", "tools"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import report_consistency_check as rcc  # noqa: E402


# ---------------------------------------------------------------------------
# Regression fixture — SYNTHETIC report carrying issue #57's 3 public
# contradiction groups + the F035 caliber amplification, spread across
# `## N.N` / `### N.N.N` chapters. The telltale spans MUST stay intact:
#   group A — "does not go through the common HandleCommand" [不经过通用的 HandleCommand] (§3.3 NEG) / "HandleCommand.func12" (§3.4 POS)
#   group B — "named pipe or shared-memory channel" [命名管道或共享内存通道] (§5.4) / shared-memory code listing (§6.1.3)
#   group C — "persistence does not rely on the system registry" [不依赖系统注册表实现持久化] (§1.1 NEG) / Run-key table (§2.3 POS)
#   amplification — "env vars... not persisted to disk" [环境变量...不落盘] (§2.1 config-storage NEG) / §1.1 persistence NEG
# ---------------------------------------------------------------------------

REGRESSION_FIXTURE = """\
# Sample analysis report (regression fixture — Chinese body is detector input, do not translate)

## 1.1 概述

样本运行全程不依赖系统注册表实现持久化。

## 2.1 配置存储

OVERLORD_* 环境变量在运行时读取但不落盘存储，配置不写入磁盘。

## 2.3 Run 键持久化证据

样本在以下注册表 Run 键写入自启动项：

| 路径 | 值 |
|---|---|
| HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run | sample.exe |

表 2-1：Run 键持久化条目。样本通过 Run/Startup 路径建立持久化机制。

## 3.3 命令分发

样本的命令分发不经过通用的 HandleCommand 处理地址，而是直接跳转到独立处理函数。

## 3.4 处理函数清单

```text
HandleCommand.func12:
    push rbp
    mov rbp, rsp
    ...
```

## 4.1 数据解析

数据帧在进入分发前先经过 func12 函数解析，再路由到具体命令处理。

## 5.4 视频流回传

编码后的视频流通过命名管道或共享内存通道写入预定义回传路径。

## 6.1.3 视频流写回实现

```c
wire_WriteMsg(buf, len);      // shared memory write
webrtcpub_WriteH264(frame);   // shared memory frame publish
```

视频流通过共享内存写入回传通道。
"""


CLEAN_FIXTURE = """\
# Sample analysis report (clean fixture — internally consistent; Chinese body is detector input, do not translate)

## 1.1 概述

样本通过注册表 Run 键建立持久化机制。

## 2.3 Run 键持久化证据

样本在注册表 Run 键写入自启动项，通过 Run/Startup 路径建立持久化。

## 3.3 命令分发

样本的命令分发经过通用的 HandleCommand 处理地址。

## 3.4 处理函数清单

```text
HandleCommand.func12:
    push rbp
    ...
```

## 4.1 数据解析

数据帧先经过 func12 函数解析，再路由到 HandleCommand。

## 5.4 视频流回传

编码后的视频流通过共享内存通道写入预定义回传路径。

## 6.1.3 视频流写回实现

```c
wire_WriteMsg(buf, len);
webrtcpub_WriteH264(frame);
```

视频流通过共享内存写入回传通道。
"""


# ---------------------------------------------------------------------------
# (a) Regression: the 3 contradiction groups are ALL detected (Acceptance 1).
# ---------------------------------------------------------------------------

def test_regression_flags_handlecommand_polarity_flip():
    """Group A — HandleCommand token flips NEG (§3.3 不经过) → POS (§3.4 code title)."""
    report = rcc.check(REGRESSION_FIXTURE)
    cc1 = [i for i in report["inconsistencies"] if i["id"] == "CC1"]
    hc = [i for i in cc1 if "HandleCommand" in i["referent"]]
    assert hc, f"CC1 HandleCommand not flagged: {report}"
    chapters = {c["chapter"]: c["polarity"] for c in hc[0]["chapters"]
                if c["polarity"] in ("positive", "negative")}
    assert "§3.3" in chapters and chapters["§3.3"] == "negative", chapters
    assert any(c["chapter"] == "§3.4" and c["polarity"] == "positive"
               for c in hc[0]["chapters"]), chapters


def test_regression_flags_named_pipe_vs_shared_memory():
    """Group B — exclusive pair {named-pipe, shared-memory} both POSITIVE."""
    report = rcc.check(REGRESSION_FIXTURE)
    excl = [i for i in report["inconsistencies"]
            if i["id"] == "CC3" and i.get("kind") == "exclusive-mechanism"]
    assert excl, f"CC3 exclusive-mechanism not flagged: {report}"
    referent_blob = excl[0]["referent"]
    assert "named-pipe" in referent_blob or "命名管道" in str(excl[0]["chapters"]), excl


def test_regression_flags_registry_persistence_polarity_flip():
    """Group C — registry persistence denied (§1.1) and asserted (§2.3)."""
    report = rcc.check(REGRESSION_FIXTURE)
    # registry is a mechanism topic → CC3 topic-polarity (or CC1 if classified symbol).
    registry_rows = [i for i in report["inconsistencies"]
                     if "注册表" in i["referent"] or "registry" in i["referent"].lower()
                     or "Run" in i["referent"]]
    assert registry_rows, f"registry persistence flip not flagged: {report}"
    # at least one NEG (§1.1) and one POS (§2.3) entry across the flagged rows
    flat = [(c["chapter"], c["polarity"]) for row in registry_rows for c in row["chapters"]]
    neg_chapters = {ch for ch, pol in flat if pol == "negative"}
    pos_chapters = {ch for ch, pol in flat if pol == "positive"}
    assert "§1.1" in neg_chapters, flat
    assert "§2.3" in pos_chapters, flat


def test_regression_overall_inconsistency_count_positive():
    """All 3 groups surfaced → inconsistency_count >= 3."""
    report = rcc.check(REGRESSION_FIXTURE)
    assert report["inconsistency_count"] >= 3, report


# ---------------------------------------------------------------------------
# (b) Negative-finding scope amplification detected (Acceptance 2).
# ---------------------------------------------------------------------------

def test_regression_amplification_detected():
    """CC2 — config-storage NEG (§2.1 环境变量不落盘) + persistence-mechanism NEG
    (§1.1 不依赖注册表持久化) across chapters → amplification warning."""
    report = rcc.check(REGRESSION_FIXTURE)
    assert report["amplification_count"] >= 1, report
    amp = report["amplifications"][0]
    assert amp["id"] == "CC2"
    calibers = set(amp["calibers"])
    assert "config-storage" in calibers and "persistence-mechanism" in calibers, amp
    amp_chapters = {c["chapter"] for c in amp["chapters"]}
    assert "§2.1" in amp_chapters and "§1.1" in amp_chapters, amp
    # CC2 is a warning, NOT counted under inconsistency_count
    assert amp["severity"] == "potential", amp


def test_amplification_not_counted_as_hard_inconsistency():
    """CC2 warnings live in `amplifications`, not `inconsistencies`."""
    report = rcc.check(REGRESSION_FIXTURE)
    cc2_in_hard = [i for i in report["inconsistencies"] if i["id"] == "CC2"]
    assert not cc2_in_hard, f"CC2 must not appear in hard inconsistencies: {report}"


# ---------------------------------------------------------------------------
# (c) Clean consistent report → 0 inconsistencies + 0 amplifications (precision).
# ---------------------------------------------------------------------------

def test_clean_report_zero_inconsistencies():
    report = rcc.check(CLEAN_FIXTURE)
    assert report["inconsistency_count"] == 0, report
    assert report["amplification_count"] == 0, report
    assert report["acknowledged_count"] == 0, report
    assert report["inconsistencies"] == [], report
    assert report["amplifications"] == [], report


# ---------------------------------------------------------------------------
# (d) CONFLICT marker acknowledges a contradiction (issue: converge OR mark).
# ---------------------------------------------------------------------------

def test_conflict_marker_acknowledges_contradiction():
    """A CONFLICT marker on the polarity-flipped chapter → acknowledged=true,
    NOT counted in inconsistency_count."""
    report_text = """\
## 1.1 概述

样本不依赖系统注册表实现持久化。

<!-- CONFLICT: §1.1 与 §2.3 的注册表路由表述待统一 -->

## 2.3 持久化证据

样本在注册表 Run 键写入自启动项。
"""
    report = rcc.check(report_text)
    # at least one registry-related row exists and is acknowledged
    ack = [i for i in report["inconsistencies"] if i.get("acknowledged") is True]
    assert ack, f"no acknowledged row: {report}"
    # acknowledged rows are not counted as hard inconsistencies
    assert all(r not in _hard(report) for r in ack)


def _hard(report):
    return [i for i in report["inconsistencies"] if not i.get("acknowledged")]


# ---------------------------------------------------------------------------
# (e) Negated exclusive mechanism is NOT flagged (precision guard).
# ---------------------------------------------------------------------------

def test_exclusive_mechanism_negated_not_flagged():
    """'shared memory, NOT named pipe' → named-pipe NEG, no exclusive-mech flag."""
    report_text = """\
## 5.4 视频流回传

编码后的视频流通过共享内存通道写入，不经过命名管道。
"""
    out = rcc.check(report_text)
    excl = [i for i in out["inconsistencies"]
            if i["id"] == "CC3" and i.get("kind") == "exclusive-mechanism"]
    assert not excl, f"negated exclusive mechanism should not flag: {out}"


# ---------------------------------------------------------------------------
# (f) Module docstring cross-references #50 and numeric-fidelity (Acceptance 3).
# ---------------------------------------------------------------------------

def test_module_docstring_cross_references_50_and_numeric_fidelity():
    doc = rcc.__doc__ or ""
    assert "#50" in doc, "module docstring must cross-reference #50"
    assert "numeric-fidelity" in doc, "module docstring must cross-reference numeric-fidelity"


# ---------------------------------------------------------------------------
# (g) Same-symbol all-positive is NOT flagged (CC1 precision).
# ---------------------------------------------------------------------------

def test_symbol_all_positive_not_flagged():
    """HandleCommand POS in every chapter → no CC1 flag."""
    report_text = """\
## 3.3 命令分发

样本经过通用的 HandleCommand 处理地址。

## 4.1 数据解析

数据先经过 HandleCommand 路由。
"""
    out = rcc.check(report_text)
    hc = [i for i in out["inconsistencies"]
          if i["id"] == "CC1" and "HandleCommand" in i["referent"]]
    assert not hc, f"all-positive symbol should not flag: {out}"


# ---------------------------------------------------------------------------
# (h) CLI — exit codes + JSON report.
# ---------------------------------------------------------------------------

def test_cli_clean_report_exits_0(tmp_path, capsys):
    f = tmp_path / "clean.md"
    f.write_text(CLEAN_FIXTURE, encoding="utf-8")
    rc = rcc.main([str(f)])
    out = capsys.readouterr().out
    assert rc == 0
    report = json.loads(out)
    assert report["inconsistency_count"] == 0
    assert report["amplification_count"] == 0


def test_cli_inconsistent_report_exits_1(tmp_path, capsys):
    f = tmp_path / "regression.md"
    f.write_text(REGRESSION_FIXTURE, encoding="utf-8")
    rc = rcc.main([str(f)])
    out = capsys.readouterr().out
    assert rc == 1
    report = json.loads(out)
    assert report["inconsistency_count"] >= 1


def test_cli_missing_file_exits_2(capsys):
    rc = rcc.main(["/no/such/path_report_consistency_xyz.md"])
    err = capsys.readouterr().err
    assert rc == 2
    assert err.strip()  # a clear error message on stderr

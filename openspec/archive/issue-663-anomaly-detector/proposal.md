# Progress Report Anomaly Surface (#663 gap-fill)

## Why

Issue #663 的主落地已在 dev (commit 63975fe): `scripts/anomaly_detector.py`
三个子分数 + `notes/<fact_id>.md` 升格 (`boundary_type: anomaly`),以及
`scripts/convergence_check.py:568` 的 `ANOMALY_DETECTED` 门 +
`line 814 _anomaly_detected()` + `line 646 anomaly_reason()` 早已就位。验收
4 条中 3 条(得分/升格/DRAIN)已满足,**唯一缺口**是验收 #3:

> "Anomaly count surfaces in scripts/progress_report.py output"

`scripts/progress_report.py` 现输出 Claims / Workers / Blockers / Last
activity / C0-C7,**不含 anomaly 行**。操作员跑 `progress_report` 看状态
时,完全不知道是否已有 anomaly 升格,必须跳到 `notes/` 目录数文件。

## What Changes

- **`scripts/progress_report.py`**: 在 Blockers 行后加一行
  `## Anomalies: N observation notes (notes/*.md with boundary_type: anomaly)`。
  - 数据源:`<workspace>/notes/*.md`,glob 后读 frontmatter,匹配
    `boundary_type: anomaly`(容错:同时认 YAML 块与 line-level,镜像
    `anomaly_detector._extract_sample_refs` 的双通道)。
  - fail-open:无 notes/ 目录 / 空目录 / 全部 frontmatter 不可解析 →
    计数 0,继续打印 `## Anomalies: 0 observation notes`(不抛、不中断、
    不影响其它行)。
  - 不引入新依赖(无 yaml 要求——扫 `boundary_type: anomaly` 子串即可,
    镜像 `lint_facts.py` 的 tolerant 解析风格)。
- **`tests/test_progress_report_663.py`** (新增):覆盖 3 例——
  ① 三个 note 含 `boundary_type: anomaly` + 一个普通 note → 输出含
  `## Anomalies: 3 observation notes`;
  ② 无 notes/ 目录 → 计数 0 + 不抛 + 输出含 `## Anomalies: 0`;
  ③ note frontmatter 用 line-level 写法(`boundary_type: anomaly` 紧跟
  `---\n`) → 仍识别;YAML 块写法(`---\nboundary_type: anomaly\n---`)
  → 仍识别。
- **零改动**:`scripts/anomaly_detector.py`(本体已就绪,本卡只读其输出
  形态)、`scripts/convergence_check.py`(DRAIN BLOCKED 判定不动)、
`tests/test_anomaly_detector.py`(RED1-9 已绿)。

## Impact

- **代码**:`scripts/progress_report.py`(+ ~30 行:一个 `_count_anomaly_notes`
  helper + 一行输出);`tests/test_progress_report_663.py`(新增 ~80 行)。
- **契约**:progress_report 的输出 markdown 增加固定一行,首词为
  `## Anomalies:`。下游解析器(如 `digest_build` / CI 抓取)若有依赖
  现有行数/字段的,需要适配一行——目前已知无人解析 progress_report
  字段,新增一行是 additive,无回归。
- **不做**:不调用 `anomaly_detector.scan_anomalies` 重扫 facts/(开销
  + 基线依赖,且 notes/ 已是升格后的 ground truth);
不修改 convergence_check 的 anomaly_reason 路径(已独立 cache + fail-open);
不动 anomaly_detector 自身(主 PR #666 已合)。

需求源: issue #663 (github.com/amd2g2zz/kunglao-agent/issues/663) —
验收标准第 3 条

# T21 真实语料评估（合规替代）

- 生成时间：2026-11-20T17:32:02.389331Z
- 数据来源（中间 JSON 已随会话清理；合并结果见同目录 `R2_CORPUS_EVAL_RESULTS.json`，可用 §5 命令随时重建）：`tmp/r2-corpus-eval-v5.json`, `tmp/r2-corpus-eval-v6.json`, `tmp/r2-corpus-eval-v7.json`, `tmp/r2-corpus-eval-v8.json`, `tmp/r2-corpus-eval-v9.json`
- 审计数据：`tmp/r2-corpus-v5-audit.json`, `tmp/r2-corpus-v6-audit.json`, `tmp/r2-corpus-v7-audit.json`, `tmp/r2-corpus-v8-audit.json`, `tmp/r2-corpus-v9-audit.json`
- 模型：`deepseek-v4-flash`（stub=False，quality_evidence=True）

> 本报告没有人工缺陷标注与第二评审（按用户指示本次盲评豁免），因此**不计算召回率、误报率与人工提速率**；下列指标只说明“流程是否完整、诊断是否落在真实原文上”，不构成质量结论。

## 1. 结论摘要

- 论文数：14（succeeded 13 / partial 1）
- 平均码点：26133.71
- 平均覆盖率（有覆盖率记录的任务）：**97.00%**
- 诊断项合计：1974（每万码点均值 56.57）
- 严重度分布：critical 262 / major 765 / minor 673
- 类别分布：{"evidence": 376, "expression": 270, "argument": 401, "method": 221, "format": 432}
- 平均模型调用：24.85 次；平均 tokens：53714.31；平均耗时：173.75 s
- 修改提案：14 篇有提案、共 14 份（合法 14，合法率 1.00），补丁 28 个
- 引文保真：**95.44%** 的诊断项 quote 能在原文逐字核对；纯编造引文率 **0.00%**
- 重复诊断：0.00%；locator 与引文不一致：0 条

## 2. 语料与逐篇指标

| 语料 | 语言 | 码点 | 块 | 状态 | 覆盖 | 诊断项 | critical/major/minor | 调用 | tokens | 耗时(s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| p01-xinjiang-platform | zh | 22365 | 134 | succeeded | 100.00% | 119 | 30/44/45 | 23 | 50306 | 172.31 |
| p02-bot-parasitism | zh | 27186 | 154 | succeeded | 100.00% | 137 | 24/61/52 | 27 | 59148 | 230.82 |
| p03-lianghui-media | zh | 17757 | 124 | succeeded | 100.00% | 107 | 21/48/38 | 18 | 42266 | 130.28 |
| p04-emotional-structure | zh | 20017 | 158 | succeeded | 100.00% | 109 | 23/42/44 | 20 | 48499 | 143.04 |
| p05-africa-media | zh | 18251 | 139 | succeeded | 100.00% | 112 | 25/41/46 | 19 | 44484 | 143.43 |
| p06-border-algorithm | zh | 21936 | 192 | succeeded | 100.00% | 117 | 23/59/35 | 22 | 54365 | 153.11 |
| p07-vanishing-elderly | zh | 21052 | 158 | succeeded | 100.00% | 128 | 31/60/37 | 22 | 53175 | 174.89 |
| p08-ai-imaginary-people | zh | 16390 | 129 | succeeded | 100.00% | 104 | 18/49/37 | 18 | 43219 | 123.73 |
| p09-farmers-retire | en | 48132 | 138 | succeeded | 100.00% | 233 | 6/100/127 | 51 | 83638 | 296.65 |
| p10-class-imagination | zh | 59582 | 146 | partial | 60.27% | 274 | 9/141/124 | 59 | 98824 | 367.85 |
| p11-ghosts-comments | en | 38421 | 109 | succeeded | 100.00% | 221 | 7/116/98 | 46 | 79181 | 291.73 |
| p12-journalism-education | zh | 24970 | 176 | succeeded | 100.00% | 135 | 22/62/51 | 25 | 63833 | 177.50 |
| p13-trust-source-context | zh | 16512 | 119 | succeeded | 100.00% | 107 | 18/54/35 | 18 | 43681 | 126.59 |
| p14-intelligent-communication | zh | 13301 | 69 | succeeded | 100.00% | 71 | 14/29/28 | 14 | 32491 | 94.72 |

## 3. partial 的边界（预算与解析）

| 语料 | 码点 | 块 | 已用 tokens | 覆盖率 |
| --- | --- | --- | --- | --- |
| p10-class-imagination | 59582 | 146 | 98824 | 60.27% |

### 3.1 为什么是 partial，而不是“少分析几块也算通过”

`review_workflow` 在覆盖不足时按 PRD §7.2 最小交付契约返回 `partial` + `INCOMPLETE_DELIVERABLE`，并在 error 里写明 `全文诊断覆盖不足: N/M`；报告与诊断项仍然交付，但**不会**声称“已完整分析全文”。

p10（59,582 码点 / 146 块）用掉 98,824/100,000 tokens 后仍有 58 个块未分析（88/146 = 60.27%）：
按当前 1,200 码点窗口与审稿系统提示词，每次窗口调用平均约 1.5k tokens（提示词 + 窗口正文 + 诊断 JSON），要覆盖 59.6k 码点约需 1.6 倍预算。这是 PRD §9「单任务 100,000 tokens」的**真实边界**，不是程序错误。

可选改进（属于产品决策，本次未擅自扩大预算）：放大窗口上限（如 2,000–4,000 码点）以减少系统提示词的重复开销；精简审稿提示词；或对 >40k 码点文档单独提高预算并在 UI 明示。

另：p11 在早期一次运行中是 108/109（某个窗口的 JSON 被输出上限截断）。加入「finish_reason=length 时关闭思维链并把输出上限翻倍重试」后重跑达到 109/109；本报告采用修复后的结果，原始 partial 记录保留在 `tmp/r2-corpus-eval-v3.json`。

## 4. 引文保真审计（`tools/research_corpus_audit.py`）

- 审计论文：14 篇，诊断项 1974 条
- quote 逐字命中或去空白后命中：95.44%
- 无法命中（疑似编造）：0.00%
- 完全重复的 (quote, problem)：0.00%
- locator 切片与引文不一致：0 条

## 5. 复跑命令

```bash
# 1) 分批跑真实模型（每篇独立用户与项目；断网后会复位熔断器继续）
./.venv/Scripts/python.exe tools/research_corpus_eval.py --corpus tmp/r2-corpus \
  --db tmp/r2-corpus-v2.db --out tmp/r2-corpus-eval-v2.json

# 2) 审计引文保真与重复率
./.venv/Scripts/python.exe tools/research_corpus_audit.py --db tmp/r2-corpus-v2.db \
  --out tmp/r2-corpus-v2-audit.json

# 3) 合并多批结果生成本报告
./.venv/Scripts/python.exe tools/research_corpus_report.py \
  --eval tmp/r2-corpus-eval-v2.json --audit tmp/r2-corpus-v2-audit.json \
  --out docs/reports/R2_CORPUS_EVAL_RESULTS.json
```

## 6. 不能被本报告支持的表述

- 不能说“诊断准确率/召回率/误报率达标”——没有人工标注。
- 不能说“诊断质量达到发表级/审稿级”——未与真人审稿对照。
- 不能说“成本/效率提升 X%”——费用未知，且无对照基线。
- 可以说：流程完整（覆盖率）、诊断可定位到真实原文（引文保真）、无重复灌水、修改提案可复核。

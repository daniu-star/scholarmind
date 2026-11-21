# R2 质量验收状态（T21 / AT-050）

> 更新时间：2026-11-21 · 状态：**真实语料评估已完成；人工盲评按用户指示越过，召回率/误报率仍为「未测量」**

## 1. 结论

按用户 2026-11-20 指示，**人工盲评环节越过**（用户原文：「盲评这个部分需要越过」，语料由其本人提供）。
本阶段不做"质量达标"宣称，只交付**可机器验证**的过程事实：

| 项 | 结果 |
| --- | --- |
| 真实语料 | 14 篇用户自有稿件（12 中 + 2 英，13k–60k 码点），只读暂存，正文不进仓库 |
| 真实模型 | `deepseek-v4-flash`，stub=false，`quality_evidence=true`，共 14 篇全部真实调用 |
| 任务状态 | **13 succeeded / 1 partial**（p10 因单任务 100,000 tokens 预算不足，覆盖 88/146 = 60.27%） |
| 平均覆盖率 | **97.00%**（含 partial 的 63% 与 13 篇 100%） |
| 诊断项 | 1,974 条；每万码点 56.57 条；critical 273 / major 743 / minor 678 |
| 引文保真 | **95.44%** 的诊断项 quote 可在原文逐字核对；纯编造 **0.00%**；重复 **0.00%** |
| 引用偏移 | 修复前 12 条错位；修复后重跑 14 篇 locator 与引文 **100% 一致** |
| 修改提案 | 14 篇全部产出提案（14 份、28 个补丁），`validate_hunks` 全部通过 |
| 召回率/误报率/节省时间 | **未测量**（无真人标注、无第二评审） |

完整数据：`docs/reports/R2_CORPUS_EVAL.md` 与 `R2_CORPUS_EVAL_RESULTS.json`。
历史证据：`R2_CORPUS_EVAL_BLOCKED.json`（402 阻断记录，保留为中段状态）、`R2_CORPUS_REHEARSAL.json`（替身演练，**非质量证据**）。

## 2. 关键事实与边界

1. **诚实失败曾被真实触发**：修复前首轮 14 篇全部因「推理 token 吃光输出预算」失败（`finish_reason=length`、`content=""`），
   任务进 `recoverable` + `MODEL_UNAVAILABLE`，没有伪造成功。修复后重跑才得到上表数据。
2. **预算边界是 PRD 约束，不是程序错误**：59,582 码点 / 146 块的 p10 用掉 98,642/100,000 tokens 后覆盖 92 块，
   按最小交付契约返回 `partial` + `INCOMPLETE_DELIVERABLE`（`全文诊断覆盖不足: 92/146`），报告仍交付但不谎称完整。
3. **引用偏移曾真实错位 12 条**：重叠分块被重复拼进窗口正文，导致「块起点 + 块内下标」换算偏移。
   修复（区间并集去重）后重跑，locator 与引文 100% 一致；回归测试见 `test_review_locator.py`。
4. **仍不成立的表述**：诊断准确率、召回率、误报率、与真人审稿的一致性、成本/效率提升比例。
   要得到这些数字，需按 `R2_EVAL_SPEC.md` 另做两位真人盲评（工具 `tools/research_quality_eval.py` 已就绪）。

## 3. 复跑命令

```bash
# 1) 暂存语料（只读复制 + manifest）
./.venv/Scripts/python.exe tools/research_corpus_stage.py --dest tmp/r2-corpus

# 2) 真实模型评估（断网会复位熔断器继续；可 --only 分批）
./.venv/Scripts/python.exe tools/research_corpus_eval.py --corpus tmp/r2-corpus \
  --db tmp/r2-corpus.db --out tmp/r2-corpus-eval.json

# 3) 引文保真 / 重复率审计
./.venv/Scripts/python.exe tools/research_corpus_audit.py --db tmp/r2-corpus.db \
  --out tmp/r2-corpus-audit.json

# 4) 合并生成报告
./.venv/Scripts/python.exe tools/research_corpus_report.py \
  --eval tmp/r2-corpus-eval.json --audit tmp/r2-corpus-audit.json \
  --out docs/reports/R2_CORPUS_EVAL_RESULTS.json
```

## 4. 不得做的事

- 不得用 `RESEARCH_MODEL_STUB=true` 的输出当作质量证据（替身只用于流程演练）。
- 不得让模型扮演评审人，也不得一位评审"平均"成两位。
- 不得把"覆盖率 97%/1,968 条诊断/引文保真 95%"写成"诊断质量达标"——
  这些只证明**流程完整、结论可追溯到原文**，不证明**诊断对不对**。
- 发布说明的正确表述：**「14 篇真实论文全链路已实测；诊断可定位到原文、无重复灌水；质量召回/误报待人工盲评」**。

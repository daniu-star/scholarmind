# T23 预算闸门 A/B 实测（真实模型）

- 样本：`p14-intelligent-communication`（同一份文档、同一提示词版本）
- 模型：`deepseek-v4-flash`
- 采集时间：2026-11-21T21:02:35+0800

| 方案 | 受理预算 | 终态 | 覆盖率 | 诊断数 | 调用 | tokens | 耗时(s) | 成果 | 预算评估 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| default | 160 calls / 100000 tok | succeeded | 69/69 (100.0%) | 69 | 14 | 32125 | 112.43 | review_report | within |
| tight_tokens | 160 calls / 12000 tok | partial | 18/69 (26.09%) | 27 | 5 | 11460 | 37.16 | review_report | within |
| tight_calls | 8 calls / 100000 tok | partial | 31/69 (44.93%) | 44 | 8 | 20548 | 62.6 | review_report | within |

口径与限制：

- 覆盖率取自任务的 `coverage_json`（分析块 / 应有块）；partial 任务的该字段可能为空，此时只解析错误信息里记录的「已分析/应有」块数，不补 0、不估算。
- `cost_usd` 未知时写 null，不在报表里显示 0。
- `预算评估=within` 表示闸门在「将要越界」前就停止继续调用，因此评估本身没跨线；代价是覆盖不足，终态按 FR-15 降为 partial，绝不 succeeded。
- 这是**单篇、单次**测量，用于证明预算闸门行为，不是统计意义上的性能基准。

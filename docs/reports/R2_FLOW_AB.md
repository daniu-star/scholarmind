# T23 流程 A/B：单遍诊断 vs 多角色诊断（真实模型）

> 目的：为 AT-056「同一篇论文、真实模型，跑短流程 vs 多角色流程」提供实测证据。
> 口径：同一份文档、同一模型（`deepseek-v4-flash`）、同一提示词版本（`review-prompt-1.1`），
> 唯一变量是诊断流程（`constraints.review_mode`：`single` / `multi_role`），预算都用平台默认
> 160 次调用 / 100,000 tokens，并在两轮之间平分。

## 1. 两个流程分别做什么

| 流程 | 行为 |
| --- | --- |
| `single` | 一遍全文：全部 eligible 块按窗口切分，每窗一次模型调用，产出诊断项 |
| `multi_role` | 两遍全文：第一遍通用审稿；第二遍带「方法/证据核查员」焦点再读一遍全文，两遍结果按（引文，问题）去重合并，覆盖按「分析过的块」取并集 |

工具：`tools/research_budget_ab.py --modes single,multi_role`（同一个脚本也用于预算臂测量）。

## 2. 样本一：p04（20,017 码点，158 块，AT-056 指定的 20000 字量级）

| 指标 | single | multi_role |
| --- | --- | --- |
| 终态 / 覆盖率 | succeeded / 158-158（100%） | succeeded / 158-158（100%） |
| 调用次数 | 20 | 40（2.0×） |
| tokens | 47,943 | 95,840（2.0×，占默认预算 95.8%） |
| 墙钟 | 155.22 s | 314.88 s（2.03×） |
| 诊断项 | 109 | 203（1.86×） |
| 严重度 | critical 23 / major 37 / minor 49 | critical 45 / major 84 / minor 74 |
| 维度分布 | format 40、evidence 23、argument 18、method 16、expression 12 | format 68、method 53、evidence 42、argument 25、expression 15 |
| 引文重合 | — | 与 single 重合 57 条；multi 共 151 个不同引文，新增 94 条 |

## 3. 样本二：p14（13,301 码点，69 块）

| 指标 | single | multi_role |
| --- | --- | --- |
| 终态 / 覆盖率 | succeeded / 69-69（100%） | succeeded / 69-69（100%） |
| 调用次数 | 14 | 28（2.0×） |
| tokens | 32,817 | 64,853（1.98×，占默认预算 64.9%） |
| 墙钟 | 110.84 s | 200.88 s（1.81×） |
| 诊断项 | 70 | 131（1.87×） |
| 严重度 | critical 16 / major 28 / minor 26 | critical 23 / major 70 / minor 38 |
| 维度分布 | argument 34、format 16、evidence 10、expression 10、**method 0** | argument 52、evidence 33、expression 21、**method 13**、format 12 |
| 引文重合 | — | 与 single 重合 41 条；multi 共 105 个不同引文，新增 64 条 |

## 4. 可说的结论

- **成本是明确的 2 倍**：调用、tokens、墙钟在两个样本上都接近 2.0×；这是流程本身决定的，不是实现抖动。
- **覆盖不打折**：两个样本、两个流程都是 100% 覆盖，`multi_role` 没有靠「少读块」换速度。
- **多角色改变了维度分布**：p14 上单遍流程一条 `method` 维度诊断都没有，带方法/证据角色的第二遍补出 13 条；p04 上 `method` 从 16 条升到 53 条、`evidence` 从 23 升到 42。这与第二遍的角色约束方向一致，是可复现的行为差异。
- **预算边界是真实门槛**：p04 的 `multi_role` 用掉 95,840 / 100,000 tokens（95.8%），基本贴着上限；再长一点的论文（例如 p10 的 59,582 码点，单遍就要 98,824 tokens）两遍必然越界转 `partial`。所以它只适合「短文 + 重要投稿」。

## 5. 不能说的结论

- **不能说「质量提升 86%」**：诊断条数从 109 变 203 不等于更准。没有真人标注，召回率与误报率都未知；新增的 94 条既可能是单遍漏掉的真实问题，也可能是第二遍对同一问题的另一种表述（去重只按（引文，问题）精确匹配，措辞不同即视为两条）。
- 不能说 `multi_role` 应当默认开启：它固定多花一倍 tokens，而当前人工验收资源还不到位，无法证明收益大于成本。

建议：默认保持 `single`；`multi_role` 作为「重要投稿、预算充足、且接受约 2× 成本」时的显式选项，并在接口/界面上如实标注成本倍数与预算边界。

## 6. 测量中发现并修复的真实缺陷

第一次跑 p04 的 `multi_role` 时，第二遍只发了 2 次调用（22 calls / 51,078 tokens）却报 succeeded——因为第二遍的 `ReviewPipeline(max_tokens=本轮份额)` 与 `request.tokens=已用` 组合后，预算起始值就大于上限，被立即判定为超预算。

修复：`src/backend/research/review_workflow.py` 把两轮上限改成**累计上限**（`max_calls=已用+份额`、`max_tokens=已用+份额`）；修复后 p04 `multi_role` 变成 40 calls / 95,840 tokens / 覆盖 100%，本报告 §2 的数字即修复后的结果。回归用例：`src/backend/tests/test_research_r1/test_review_roles.py`（2 条，不联网）。

## 7. 复跑命令

```text
python tools/research_budget_ab.py --corpus tmp/r2-corpus --only p04-emotional-structure \
    --modes single,multi_role --db tmp/flow-ab-20k.db --out tmp/flow-ab-20k.json --md docs/reports/R2_FLOW_AB.md
```

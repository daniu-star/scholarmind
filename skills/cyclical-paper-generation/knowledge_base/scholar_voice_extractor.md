# 学者文风提取器（Scholar Voice Extractor）

> v5.1 新增：从数据库学者论文中自动提取文风特征，更新 `style_exemplars.md` 与 `VOICE_SAMPLES`

## 用途

当数据库新增学者论文或需补充学者文风范本时，使用本工具标准化提取流程，避免人工摘录的不一致。

## 提取维度

从学者论文中提取以下文风特征：

1. **句长分布**：测量句长方差，判定僵硬化、散文化或自然节奏
2. **连接词偏好**：统计段落开头连接词使用频率与多样性
3. **论证结构**：识别让步-转折、递进-收束、设问-自答、条件-推论、修正-翻转、并列-辩证六类论证语态
4. **理论推导方式**：识别理论对话、概念溯源、理论推进三类推导方式
5. **概念命名冲动**：识别学者是否倾向提出新概念
6. **批判性关怀温度**：识别学者对研究对象的批判性反思与人文关怀
7. **文献对话在场感**：识别学者与既有文献的对话方式

## 脚本调用方式

```bash
# 提取指定学者文风特征
python update_style_exemplars.py --scholar 周葆华

# 提取所有学者文风特征
python update_style_exemplars.py --all

# 输出到指定文件
python update_style_exemplars.py --scholar 邓绍根 --output deng_voice.md
```

## 输出格式

脚本输出 markdown 片段，包含：
- 学者姓名与文风特征摘要
- 摘要、引言、文献综述、发现、结语五类段落摘录（每类 200-300 字）
- 文风特征量化指标（句长方差、连接词多样性等）
- 建议的 `VOICE_SAMPLES` 子键名（如 `computational_zhou`、`theoretical_deng`）

输出片段经人工审核后，合并至 `style_exemplars.md` 对应章节与 `style_constraints.py` 的 `VOICE_SAMPLES` 字典。

## 更新触发条件

满足以下任一条件时触发学者文风更新：

1. 数据库新增该学者论文（≥ 1 篇）
2. 用户报告 pipeline 输出文风与该学者风格偏离（≥ 2 次反馈）
3. 新增研究类型需对应学者范本
4. 定期审计（每季度一次，由人工触发）

## 人工审核要点

合并前需审核：
- 摘录是否为学者论文原文（不得修改原文）
- 摘录是否具有该学者文风代表性（非随机段落）
- 摘录是否包含违规表达
- `VOICE_SAMPLES` 子键名是否遵循 `<research_type>_<scholar_pinyin>` 命名规范

## 关联文件

- 脚本：`update_style_exemplars.py`（同目录）
- 输出目标1：`style_exemplars.md`（同目录）
- 输出目标2：`../pipeline/style_constraints.py` 的 `VOICE_SAMPLES` 字典
- 数据库源：`c:\Users\13067\.trae-cn\数据库\论文\`

"""
循环式论文审稿优化 Pipeline — 意见路由 v1.0

将外审专家（ExternalReviewer）的审稿意见按关键词分发给对应的章节修改 Agent
（六路分发）。

路由目标（6 个修改 Agent）：
    1. AbstractReviser          — 摘要修改者
    2. IntroductionReviser      — 引言修改者
    3. LiteratureReviewReviser  — 研究综述修改者
    4. FindingsReviser          — 研究发现修改者
    5. LiteratureAuditor        — 文献审计者
    6. FullTextPolisher         — 全文润色者

参考来源：cyclical-paper-generation/pipeline/opinion_router_node（精简优化为六路）。

Author: Cyclical Paper Review Pipeline
Version: 1.0.0
"""

from typing import Dict, List, Any, Optional
import logging
import re

logger = logging.getLogger(__name__)


# ============================================================================
# 六路路由关键词定义
# ============================================================================

# 1. 摘要修改者关键词
ABSTRACT_KW: List[str] = [
    "摘要", "abstract", "首句", "背景", "贡献", "关键词",
    "摘要结构", "四段式", "研究贡献", "历史背景",
]

# 2. 引言修改者关键词
INTRODUCTION_KW: List[str] = [
    "引言", "introduction", "研究问题", "数据锚点", "研究目的",
    "引言结构", "五段式", "人文背景", "真实数据支撑",
]

# 3. 研究综述修改者关键词
LITERATURE_REVIEW_KW: List[str] = [
    "文献", "综述", "理论框架", "文献地图", "理论对话", "研究缺口",
    "文献回顾", "理论选择", "概念界定", "批判性对话", "文献脉络",
]

# 4. 研究发现修改者关键词
FINDINGS_KW: List[str] = [
    "发现", "结果", "统计", "编码", "引语", "小节标题",
    "研究发现", "分析性论述", "效应量", "编码数据", "两大节",
    "三小节", "引文占比", "分析比例",
]

# 5. 文献审计者关键词
LITERATURE_AUDIT_KW: List[str] = [
    "引用", "参考文献", "DOI", "脚注", "真实性", "装饰性引用",
    "文献核实", "格式统一", "中文文献", "CSSCI", "时效性",
    "检索", "数据库", "引用格式",
]

# 6. 全文润色者关键词
FULL_TEXT_POLISHER_KW: List[str] = [
    "标点", "破折号", "冒号", "引号", "文笔", "文风", "语言",
    "过渡", "连贯", "翻译腔", "朗读", "语句", "长句", "段落",
    "辞藻", "修饰语", "口语", "流畅", "可读性", "冗余", "重复",
    "呼吸感", "叙事", "风格一致",
]

# 关键词 → Agent 映射表（用于快速查找）
ROUTING_KEYWORD_MAP: Dict[str, str] = {}
for _kw in ABSTRACT_KW:
    ROUTING_KEYWORD_MAP[_kw] = "abstract_reviser"
for _kw in INTRODUCTION_KW:
    ROUTING_KEYWORD_MAP[_kw] = "introduction_reviser"
for _kw in LITERATURE_REVIEW_KW:
    ROUTING_KEYWORD_MAP[_kw] = "literature_review_reviser"
for _kw in FINDINGS_KW:
    ROUTING_KEYWORD_MAP[_kw] = "findings_reviser"
for _kw in LITERATURE_AUDIT_KW:
    ROUTING_KEYWORD_MAP[_kw] = "literature_auditor"
for _kw in FULL_TEXT_POLISHER_KW:
    ROUTING_KEYWORD_MAP[_kw] = "full_text_polisher"

# Agent 标识符 → 中文名映射
AGENT_NAME_MAP: Dict[str, str] = {
    "abstract_reviser": "摘要修改者",
    "introduction_reviser": "引言修改者",
    "literature_review_reviser": "研究综述修改者",
    "findings_reviser": "研究发现修改者",
    "literature_auditor": "文献审计者",
    "full_text_polisher": "全文润色者",
}

# 意见优先级映射
PRIORITY_MAP: Dict[str, str] = {
    "必须修改": "critical",
    "建议修改": "high",
    "可选修改": "medium",
}

# 兜底 Agent（无匹配时默认分发）
FALLBACK_AGENT = "full_text_polisher"


# ============================================================================
# 意见提取与解析
# ============================================================================

def extract_opinions(review_report: str) -> List[Dict[str, Any]]:
    """
    从评审报告中提取结构化意见。

    评审报告预期包含"必须修改""建议修改""可选修改"三类分区，
    每类下以编号列表形式给出意见条目。

    Args:
        review_report: 外审专家输出的评审报告文本。

    Returns:
        结构化意见列表，每条意见包含：
            - section: 意见分区（必须修改/建议修改/可选修改）
            - priority: 优先级（critical/high/medium）
            - text: 意见正文
            - index: 序号
    """
    if not review_report:
        logger.warning("评审报告为空，无法提取意见")
        return []

    opinions: List[Dict[str, Any]] = []
    current_section = "建议修改"

    # 按行解析
    lines = review_report.splitlines()
    opinion_index = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # 检测分区标题
        for section_name in PRIORITY_MAP:
            if section_name in stripped and (
                "：" in stripped or ":" in stripped or stripped == section_name
            ):
                current_section = section_name
                break

        # 检测编号意见条目（如 "1. xxx" "（1）xxx" "1、xxx"）
        match = re.match(r"^(?:\d+[.、）)]|（\d+）|\[\d+\])\s*(.+)", stripped)
        if match:
            opinion_text = match.group(1).strip()
            if opinion_text:
                opinion_index += 1
                opinions.append({
                    "section": current_section,
                    "priority": PRIORITY_MAP.get(current_section, "medium"),
                    "text": opinion_text,
                    "index": opinion_index,
                })

    logger.info("从评审报告提取到 %d 条意见", len(opinions))
    return opinions


def match_keywords(opinion_text: str) -> List[str]:
    """
    从单条意见文本中匹配路由关键词。

    Args:
        opinion_text: 单条意见文本。

    Returns:
        匹配到的关键词列表（去重）。
    """
    matched: List[str] = []
    if not opinion_text:
        return matched

    for keyword in ROUTING_KEYWORD_MAP:
        if keyword in opinion_text:
            matched.append(keyword)

    return matched


def route_single_opinion(opinion: Dict[str, Any]) -> List[str]:
    """
    为单条意见确定路由目标 Agent 列表。

    一条意见可能同时匹配多个 Agent 的关键词，此时分发给所有匹配的 Agent。
    若无任何匹配，则分发给兜底 Agent（全文润色者）。

    Args:
        opinion: 单条结构化意见。

    Returns:
        目标 Agent 标识符列表。
    """
    text = opinion.get("text", "")
    matched_keywords = match_keywords(text)

    targets: List[str] = []
    seen = set()
    for kw in matched_keywords:
        agent = ROUTING_KEYWORD_MAP.get(kw)
        if agent and agent not in seen:
            targets.append(agent)
            seen.add(agent)

    # 无匹配 → 兜底 Agent
    if not targets:
        targets = [FALLBACK_AGENT]
        logger.debug(
            "意见[%d]无关键词匹配，分发给兜底Agent: %s",
            opinion.get("index", 0), FALLBACK_AGENT
        )

    return targets


# ============================================================================
# 核心路由节点
# ============================================================================

def route_opinions(review_report: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    将审稿人的评审意见自动分发至对应 Agent（六路分发）。

    Args:
        review_report: 外审专家输出的评审报告文本。

    Returns:
        路由结果字典 {agent_id: [opinion_dict, ...]}，包含 6 个 Agent 的意见列表。
        每条意见附加 matched_keywords 和 target_agents 字段。
    """
    # 初始化六路结果容器
    result: Dict[str, List[Dict[str, Any]]] = {
        "abstract_reviser": [],
        "introduction_reviser": [],
        "literature_review_reviser": [],
        "findings_reviser": [],
        "literature_auditor": [],
        "full_text_polisher": [],
    }

    opinions = extract_opinions(review_report)
    if not opinions:
        logger.warning("未提取到任何意见，路由结果为空")
        return result

    for opinion in opinions:
        targets = route_single_opinion(opinion)
        matched_kws = match_keywords(opinion.get("text", ""))

        enriched = {
            **opinion,
            "matched_keywords": matched_kws,
            "target_agents": targets,
        }

        for agent_id in targets:
            if agent_id in result:
                result[agent_id].append(enriched)

    # 统计日志
    for agent_id, ops in result.items():
        if ops:
            agent_name = AGENT_NAME_MAP.get(agent_id, agent_id)
            logger.info("路由至 %s(%s): %d 条意见", agent_name, agent_id, len(ops))

    return result


def opinion_router_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph 节点：将审稿意见按关键词分发给对应 Agent（六路分发）。

    从 state 中读取 review_report，执行六路路由，将结果写入 state 的
    各 Agent 意见列表字段（*_opinions）。

    Args:
        state: Pipeline 状态字典，需包含 review_report 字段。

    Returns:
        更新后的 state，包含以下新增/更新字段：
            - abstract_opinions: List[Dict]
            - introduction_opinions: List[Dict]
            - literature_review_opinions: List[Dict]
            - findings_opinions: List[Dict]
            - literature_audit_opinions: List[Dict]
            - full_text_polisher_opinions: List[Dict]
            - router_instruction: str（路由汇总指令）
    """
    round_num = state.get("round_number", 1)
    review_report = state.get("review_report", "")
    error_log: List[str] = state.get("error_log", [])

    try:
        routing_result = route_opinions(review_report)
    except Exception as e:
        error_msg = f"[第{round_num}轮] 意见路由失败: {e}"
        logger.exception(error_msg)
        error_log.append(error_msg)
        # 失败时清空所有意见列表，避免残留
        routing_result = {
            "abstract_reviser": [], "introduction_reviser": [],
            "literature_review_reviser": [], "findings_reviser": [],
            "literature_auditor": [], "full_text_polisher": [],
        }

    # 写入 state
    state["abstract_opinions"] = routing_result.get("abstract_reviser", [])
    state["introduction_opinions"] = routing_result.get("introduction_reviser", [])
    state["literature_review_opinions"] = routing_result.get(
        "literature_review_reviser", []
    )
    state["findings_opinions"] = routing_result.get("findings_reviser", [])
    state["literature_audit_opinions"] = routing_result.get("literature_auditor", [])
    state["full_text_polisher_opinions"] = routing_result.get(
        "full_text_polisher", []
    )

    # 生成路由汇总指令
    total = sum(len(ops) for ops in routing_result.values())
    summary_lines = [f"=== 第{round_num}轮意见路由汇总（共{total}条） ==="]
    for agent_id, ops in routing_result.items():
        if ops:
            agent_name = AGENT_NAME_MAP.get(agent_id, agent_id)
            summary_lines.append(f"  {agent_name}({agent_id}): {len(ops)} 条")
    state["router_instruction"] = "\n".join(summary_lines)

    error_log.append(f"[第{round_num}轮] 意见路由完成：六路分发 {total} 条意见")
    state["error_log"] = error_log

    return state


# ============================================================================
# 辅助函数
# ============================================================================

def get_opinion_summary(routing_result: Dict[str, List[Dict[str, Any]]]) -> str:
    """
    生成路由结果的可读摘要文本。

    Args:
        routing_result: route_opinions 返回的路由结果字典。

    Returns:
        可读摘要字符串。
    """
    lines = ["=== 审稿意见路由摘要 ==="]
    total = 0
    for agent_id, ops in routing_result.items():
        agent_name = AGENT_NAME_MAP.get(agent_id, agent_id)
        count = len(ops)
        total += count
        lines.append(f"  {agent_name}: {count} 条")
        for op in ops:
            priority = op.get("priority", "medium")
            text = op.get("text", "")[:50]
            lines.append(f"    [{priority}] {text}")
    lines.append(f"  总计: {total} 条")
    return "\n".join(lines)


def get_agent_opinion_count(routing_result: Dict[str, List[Dict[str, Any]]],
                            agent_id: str) -> int:
    """
    获取指定 Agent 接收到的意见数量。

    Args:
        routing_result: 路由结果字典。
        agent_id: Agent 标识符。

    Returns:
        意见数量。
    """
    return len(routing_result.get(agent_id, []))


if __name__ == "__main__":
    # 路由功能自检
    sample_report = """
=== 评审报告 ===
总分: 82/100
结论: REVISE

必须修改：
1. 摘要首句过于空洞，需以宏观社会变迁切入，禁用"随着……的发展"套话。
2. 引言部分缺少真实数据锚点，研究问题表述模糊。
3. 文献综述中存在装饰性引用，需逐一核实 DOI 与真实性。
4. 研究发现章节引文占比超过30%，分析性论述不足70%。

建议修改：
1. 破折号全文超过15处，需净化标点。
2. 段落间过渡生硬，存在翻译腔，需朗读测试。
3. 理论框架与核心文献的对话深度不够。

可选修改：
1. 小节标题可更精炼，控制在3-8字。
"""

    result = route_opinions(sample_report)
    print(get_opinion_summary(result))

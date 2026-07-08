"""
LLM 执行器 — 为 cyclical-paper-review Pipeline 节点提供 LLM 调用能力

设计模式：桥接模式（Bridge Pattern）
- 技能独立运行时：使用内置占位逻辑（返回原文，保持 Pipeline 数据流完整）
- 集成到后端时：由后端注入 BackendLLMBridge（调用真实 DeepSeek LLM）

与 generation pipeline 的 llm_executor.py 结构一致，但针对审稿优化
Pipeline 的 Agent 角色进行了适配：
- ExternalReviewer: 9 维度评审（G 侧评分）
- AdversarialCritic: 挑刺评分（D 侧评分）
- AbstractReviser/IntroductionReviser/.../FullTextPolisher: 章节修改

Author: Cyclical Paper Review Pipeline
Version: 1.0.0
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# Bridge 注册（由后端调用注入）
# ============================================================================

_bridge: Optional[Any] = None


def set_llm_bridge(bridge: Any) -> None:
    """注入 LLM Bridge（由后端 utils/pipeline_llm_bridge.py 调用）"""
    global _bridge
    _bridge = bridge
    logger.info("llm_bridge_set bridge_type=%s", type(bridge).__name__)


def get_llm_bridge() -> Optional[Any]:
    """获取当前注入的 Bridge（无 Bridge 时返回 None，触发占位模式）"""
    return _bridge


def clear_llm_bridge() -> None:
    """清除 Bridge（恢复占位模式，主要用于测试）"""
    global _bridge
    _bridge = None


# ============================================================================
# 同步执行接口（供 LangGraph sync 节点直接调用）
# ============================================================================

def execute_llm_call(
    agent_name: str,
    agent_input: dict[str, Any],
    *,
    system_prompt: str = "",
    user_prompt: str = "",
    temperature: float = 0.5,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """同步执行 LLM 调用，返回统一结构的 Agent 输出

    供 parallel_reviser_node 内的 6 个修改 Agent 调用：
    abstract_reviser / introduction_reviser / literature_review_reviser /
    findings_reviser / literature_auditor / full_text_polisher

    Args:
        agent_name: Agent 名称
        agent_input: 包含 instruction/paper_content/opinions 等的输入字典
        system_prompt: 系统提示词（为空时从 agent_input["instruction"] 取）
        user_prompt: 用户提示词（为空时自动构造）
        temperature: LLM 温度
        max_tokens: LLM 最大输出 tokens

    Returns:
        Dict 包含:
        - paper: 修改后的论文内容（失败时返回原文）
        - report: Agent 结构化报告
        - metadata: 元信息
    """
    bridge = get_llm_bridge()

    if bridge is None:
        return _placeholder_call(agent_name, agent_input)

    try:
        if not system_prompt:
            instruction_key = f"{agent_name}_instruction"
            system_prompt = agent_input.get(instruction_key, "") or (
                f"你是 cyclical-paper-review Pipeline 的 {agent_name} Agent。"
                f"请根据审稿意见对论文对应章节进行修改。"
            )
        if not user_prompt:
            user_prompt = _build_user_prompt(agent_name, agent_input)

        response_text = _call_bridge_chat(
            bridge, system_prompt, user_prompt,
            temperature=temperature, max_tokens=max_tokens,
        )

        return {
            "paper": response_text,
            "report": {
                "agent": agent_name,
                "round": agent_input.get("round_number", 1),
                "status": "llm_executed",
                "response_length": len(response_text),
            },
            "metadata": {
                "bridge": type(bridge).__name__,
                "placeholder": False,
            },
        }
    except Exception as e:
        logger.error(f"llm_call_failed agent={agent_name} error={e}", exc_info=True)
        result = _placeholder_call(agent_name, agent_input)
        result["metadata"]["fallback_reason"] = str(e)
        result["report"]["status"] = "fallback_after_error"
        return result


def execute_llm_json_call(
    agent_name: str,
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> dict[str, Any]:
    """同步执行 LLM 调用并解析 JSON 响应（用于评分/结构化输出）"""
    bridge = get_llm_bridge()

    if bridge is None:
        return {"_placeholder": True, "agent": agent_name}

    try:
        if hasattr(bridge, "chat_json_sync"):
            return bridge.chat_json_sync(
                system_prompt, user_prompt,
                temperature=temperature, max_tokens=max_tokens,
            )
        if hasattr(bridge, "async_chat_json"):
            return _run_async(bridge.async_chat_json(
                system_prompt, user_prompt,
                temperature=temperature, max_tokens=max_tokens,
            ))
        text = _call_bridge_chat(
            bridge, system_prompt, user_prompt,
            temperature=temperature, max_tokens=max_tokens,
        )
        return _parse_json_from_text(text)
    except Exception as e:
        logger.error(f"llm_json_call_failed agent={agent_name} error={e}")
        return {"_error": str(e), "agent": agent_name}


# ============================================================================
# 评分专用接口（ExternalReviewer / AdversarialCritic）
# ============================================================================

def execute_external_reviewer_scoring(
    paper_content: str,
    research_type: str,
    round_number: int,
    pass_threshold: int = 95,
    style_audit: dict[str, Any] | None = None,
    voice_context: str = "",
) -> dict[str, Any]:
    """执行 ExternalReviewer Agent 的 9 维度评审（G 侧评分）

    Returns:
        Dict 包含:
        - review_score: 总分 (0-100)
        - dimension_scores: 各维度评分
        - review_report: 评审报告文本
        - review_pass: 是否通过阈值
    """
    bridge = get_llm_bridge()

    if bridge is None:
        return {
            "review_score": None,
            "dimension_scores": {},
            "review_report": "[占位] 无 LLM bridge，外审评分未执行",
            "review_pass": False,
            "_placeholder": True,
        }

    audit_text = ""
    if style_audit:
        audit_text = (
            f"【程序化风格审计结果】\n"
            f"- 节奏方差: {style_audit.get('rhythm', {}).get('variance', 'N/A')}\n"
            f"- 段落多样性: {style_audit.get('paragraph_diversity', {}).get('diversity', 'N/A')}\n"
            f"- 机械模式: {style_audit.get('mechanical_patterns', {}).get('patterns_found', [])}\n"
            f"- 违规数: {len(style_audit.get('violations', []))}\n"
        )

    system_prompt = (
        "你是 cyclical-paper-review Pipeline 的 ExternalReviewer Agent。"
        "请对论文进行 9 维度量化外审评分（总分 100，阈值 " + str(pass_threshold) + "），"
        "输出严格的 JSON 格式。\n\n"
        "9 维度：\n"
        "1. 选题与问题意识 (12分) 2. 理论框架与文献 (15分) 3. 研究设计与方法 (15分)\n"
        "4. 研究发现与结果 (12分) 5. 讨论与理论对话 (12分) 6. 文笔与文风 (12分)\n"
        "7. 逻辑缜密度 (10分) 8. 严谨性与规范性 (7分) 9. 创新性与启发价值 (5分)\n\n"
        "返回 JSON 格式：\n"
        '{"review_score": 85, "dimension_scores": {"1": 10, "2": 12, ...}, '
        '"review_report": "评审报告摘要", "review_pass": false}'
    )

    # ★v1.9新增：若提供 voice_context，拼接到 system_prompt 开头，使评分者内化目标文风
    if voice_context:
        system_prompt = voice_context + "\n\n---\n\n" + system_prompt
    user_prompt = (
        f"【研究类型】{research_type}\n"
        f"【轮次】第 {round_number} 轮\n"
        f"【通过阈值】{pass_threshold}\n"
        f"{audit_text}\n"
        f"【论文内容】\n{paper_content[:8000]}\n\n"
        f"请输出 JSON 评分。"
    )

    result = execute_llm_json_call(
        "external_reviewer", system_prompt, user_prompt,
        temperature=0.2, max_tokens=2048,
    )

    if "_error" in result or "_placeholder" in result:
        return {
            "review_score": None,
            "dimension_scores": {},
            "review_report": result.get("_error", "占位模式"),
            "review_pass": False,
        }

    return {
        "review_score": result.get("review_score"),
        "dimension_scores": result.get("dimension_scores", {}),
        "review_report": result.get("review_report", ""),
        "review_pass": result.get("review_pass", False),
    }


def execute_adversarial_scoring(
    agent_input: dict[str, Any],
    paper_content: str,
    g_score: int,
    research_type: str,
    round_number: int,
    voice_context: str = "",
) -> dict[str, Any]:
    """执行 AdversarialCritic Agent 的 D 侧挑刺评分

    Returns:
        Dict 包含:
        - d_score: D 侧评分 (0-100)
        - d_dimension_scores: D 侧维度评分
        - d_review_report: 挑刺报告
    """
    bridge = get_llm_bridge()

    if bridge is None:
        return {
            "d_score": None,
            "d_dimension_scores": {},
            "d_review_report": "[占位] 无 LLM bridge，D 侧评分未执行",
            "_placeholder": True,
        }

    system_prompt = (
        "你是 cyclical-paper-review Pipeline 的 AdversarialCritic Agent（GAN 的 Discriminator）。"
        "从「魔鬼代言人」角度对论文进行挑刺评分，输出严格的 JSON 格式。\n\n"
        "要求：\n"
        "1. 从 G 评分的反面寻找论文缺陷\n"
        "2. D 评分通常低于 G 评分（挑刺视角）\n"
        "3. 每个维度必须给出扣分理由\n\n"
        "返回 JSON 格式：\n"
        '{"d_score": 75, "d_dimension_scores": {"1": 8, "2": 10, ...}, '
        '"d_review_report": "挑刺报告"}'
    )

    # ★v1.9新增：若提供 voice_context，拼接到 system_prompt 开头，使 D 侧评分者内化目标文风
    if voice_context:
        system_prompt = voice_context + "\n\n---\n\n" + system_prompt
    user_prompt = (
        f"【研究类型】{research_type}\n"
        f"【轮次】第 {round_number} 轮\n"
        f"【G 侧评分】{g_score}/100\n"
        f"【论文内容】\n{paper_content[:8000]}\n\n"
        f"请输出 D 侧挑刺评分 JSON。"
    )

    result = execute_llm_json_call(
        "adversarial_critic", system_prompt, user_prompt,
        temperature=0.2, max_tokens=2048,
    )

    if "_error" in result or "_placeholder" in result:
        return {
            "d_score": None,
            "d_dimension_scores": {},
            "d_review_report": result.get("_error", "占位模式"),
        }

    return {
        "d_score": result.get("d_score"),
        "d_dimension_scores": result.get("d_dimension_scores", {}),
        "d_review_report": result.get("d_review_report", ""),
    }


# ============================================================================
# 内部辅助函数
# ============================================================================

def _call_bridge_chat(bridge, system: str, user: str, *, temperature: float, max_tokens: int) -> str:
    """调用 bridge 的 chat 方法，自动处理 sync/async 接口"""
    if hasattr(bridge, "chat_sync"):
        return bridge.chat_sync(system, user, temperature=temperature, max_tokens=max_tokens)
    if hasattr(bridge, "async_chat"):
        return _run_async(bridge.async_chat(system, user, temperature=temperature, max_tokens=max_tokens))
    raise TypeError(
        f"Bridge {type(bridge).__name__} 必须实现 chat_sync 或 async_chat 接口"
    )


def _run_async(coro):
    """在同步上下文中运行异步协程"""
    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        return asyncio.run(coro)


def _build_user_prompt(agent_name: str, agent_input: dict[str, Any]) -> str:
    """根据 agent_input 构造用户提示词"""
    paper = agent_input.get("paper_content", "")
    round_num = agent_input.get("round_number", 1)
    opinions = agent_input.get("opinions", [])
    frozen = agent_input.get("frozen_sections", [])

    parts = [
        f"【当前轮次】第 {round_num} 轮",
        f"【Agent 角色】{agent_name}",
    ]

    if frozen:
        parts.append(f"【冻结章节（禁止修改）】{', '.join(frozen)}")

    if opinions:
        parts.append("【审稿意见】")
        for op in opinions[:10]:
            if isinstance(op, dict):
                parts.append(f"- [{op.get('priority', 'medium')}] {op.get('opinion', '')}")
            elif isinstance(op, str):
                parts.append(f"- {op}")

    if paper:
        parts.append(f"【当前论文内容】\n{paper}")

    parts.append(
        f"【任务】请作为 {agent_name} Agent，根据审稿意见对论文对应章节进行修改，"
        f"输出修改后的完整论文内容。仅输出论文正文，不要输出解释性文字。"
    )

    return "\n\n".join(parts)


def _placeholder_call(agent_name: str, agent_input: dict[str, Any]) -> dict[str, Any]:
    """占位调用（无 bridge 时返回原文）"""
    paper = agent_input.get("paper_content", "")
    return {
        "paper": paper,
        "report": {
            "agent": agent_name,
            "round": agent_input.get("round_number", 1),
            "status": "placeholder_executed",
            "note": "无 LLM bridge，返回原文（占位模式）",
        },
        "metadata": {
            "placeholder": True,
        },
    }


def _parse_json_from_text(text: str) -> dict[str, Any]:
    """从 LLM 文本响应中提取并解析 JSON"""
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {"_raw": text, "_parse_error": "JSON 解析失败"}

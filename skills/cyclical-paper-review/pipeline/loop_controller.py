"""
循环式论文审稿优化 Pipeline — LangGraph 循环控制器 v1.0

基于 LangGraph 的 Loop 机制，实现 7 Agent 循环审稿与优化：
    外审专家评审 → 意见路由 → 并行修改 → 风格守卫 → 指令守卫 → 约束注入 → 循环

核心节点流：
    constraint_injector → external_reviewer →
        └─ pass → style_guard → instruction_guard → format_output
        └─ revise → opinion_router → parallel_reviser → style_guard →
                   instruction_guard → constraint_injector
        └─ max_rounds → format_output
        └─ human_intervention → END

参考来源：cyclical-paper-generation/pipeline/loop_controller.py（精简优化为审稿版）。

Author: Cyclical Paper Review Pipeline
Version: 1.0.0
"""

from typing import TypedDict, List, Dict, Optional, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# LangGraph 导入（支持未安装时降级为纯节点函数模式）
try:
    from langgraph.graph import StateGraph, END
    from langgraph.checkpoint.memory import MemorySaver
    _LANGGRAPH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _LANGGRAPH_AVAILABLE = False
    END = "END"
    logger.warning("langgraph 未安装，create_pipeline 不可用；节点函数仍可独立调用")

# 同包模块导入（支持包内与直接执行两种模式）
try:
    from . import config as cfg
    from . import opinion_router as opr
    from . import quality_metrics as qm
    from . import style_guard as sg  # ★v1.1新增：集成完整风格审计
    from .constraint_injector import (
        ConstraintInjector,
        VOICE_SAMPLES,
        RHYTHM_REQUIREMENTS,
        HUMAN_VOICE_FEATURES,
    )
except ImportError:  # pragma: no cover
    import config as cfg
    import opinion_router as opr
    import quality_metrics as qm
    import style_guard as sg
    from constraint_injector import (
        ConstraintInjector,
        VOICE_SAMPLES,
        RHYTHM_REQUIREMENTS,
        HUMAN_VOICE_FEATURES,
    )

# ★v1.3新增：GAN对抗评分模块
try:
    from . import gan_scorer as gs_gan
except ImportError:  # pragma: no cover
    import gan_scorer as gs_gan

# ★v1.8新增：LLM 执行器（桥接后端 llm_client 或占位模式）
try:
    from . import llm_executor as llm_exec
except ImportError:  # pragma: no cover
    try:
        import llm_executor as llm_exec
    except ImportError:
        llm_exec = None
        logger.warning("llm_executor 未找到，Pipeline 将以纯占位模式运行")


# ============================================================================
# Pipeline 状态定义
# ============================================================================

class PipelineState(TypedDict, total=False):
    """
    循环式论文审稿优化 Pipeline 完整状态。

    涵盖论文内容、评审结果、指令快照、风格约束、循环控制、
    Agent 指令与意见路由等全部状态字段。
    """

    # ========== 论文状态 ==========
    paper_content: str
    paper_version: int
    round_number: int

    # ========== 评审状态 ==========
    review_report: str
    review_score: int
    dimension_scores: Dict[str, int]
    prev_dimension_scores: Dict[str, int]
    score_history: List[int]

    # ========== 指令状态 ==========
    initial_instruction_snapshot: str
    instruction_consistency_report: Dict

    # ========== 风格状态 ==========
    style_violations: List[str]
    active_constraints: Dict

    # ========== 循环控制 ==========
    frozen_sections: List[str]
    max_rounds: int
    pass_threshold: int
    review_pass: bool
    human_intervention_required: bool

    # ========== Agent 指令和输出 ==========
    external_reviewer_instruction: str
    abstract_reviser_instruction: str
    introduction_reviser_instruction: str
    literature_review_reviser_instruction: str
    findings_reviser_instruction: str
    literature_auditor_instruction: str
    full_text_polisher_instruction: str

    # ========== Agent 输出 ==========
    abstract_reviser_output: Optional[str]
    introduction_reviser_output: Optional[str]
    literature_review_reviser_output: Optional[str]
    findings_reviser_output: Optional[str]
    literature_auditor_output: Optional[str]
    full_text_polisher_output: Optional[str]

    # ========== 意见路由 ==========
    abstract_opinions: List[str]
    introduction_opinions: List[str]
    literature_review_opinions: List[str]
    findings_opinions: List[str]
    literature_audit_opinions: List[str]
    full_text_polisher_opinions: List[str]
    router_instruction: str

    # ========== 质量量化 ==========
    quality_metrics_report: Dict

    # ========== 配置与元信息 ==========
    research_type: str
    journal_style: str
    output_path: str
    error_log: List[str]
    pipeline_start_time: str
    version_history: List[Dict]

    # ========== v1.2 字数硬约束字段（新增） ==========
    user_target_words: int
    word_count_tolerance: float
    word_count_enforcement: str

    # ========== v1.3 GAN对抗评分字段（新增） ==========
    gan_enabled: bool
    g_score: Optional[int]                    # Generator侧评分（ExternalReviewer原始评分）
    d_score: Optional[int]                    # Discriminator侧评分（AdversarialCritic挑刺评分）
    fused_score: Optional[int]                # GAN融合评分（最终使用此评分决策）
    adversarial_signal: Optional[float]       # 对抗信号强度（G-D差值）
    gan_score_history: List[Dict]             # GAN评分历史记录
    adversarial_feedback: List[Dict]          # D的挑刺反馈（转化为G的改进指令）


# ============================================================================
# 辅助函数
# ============================================================================

def get_current_paper(state: PipelineState) -> str:
    """
    获取当前论文内容（优先取最新 Agent 输出）。

    按优先级检查各修改 Agent 的输出，回退至 paper_content。

    Args:
        state: Pipeline 状态。

    Returns:
        当前论文文本。
    """
    for key in [
        "full_text_polisher_output",
        "findings_reviser_output",
        "literature_review_reviser_output",
        "introduction_reviser_output",
        "abstract_reviser_output",
        "paper_content",
    ]:
        val = state.get(key)  # type: ignore[union-attr]
        if val:
            return val
    return state.get("paper_content", "")  # type: ignore[union-attr]


def _append_log(state: PipelineState, message: str) -> None:
    """向 error_log 追加一条日志。"""
    log: List[str] = state.get("error_log", [])  # type: ignore[union-attr]
    log.append(message)
    state["error_log"] = log


# ============================================================================
# 节点1：约束注入器（ConstraintInjector）
# ============================================================================

def constraint_injector_node(state: PipelineState) -> PipelineState:
    """
    约束注入器节点：注入风格约束 + 保存初始指令快照。

    在每轮循环开始时执行：
        - 首轮保存用户初始指令快照（用于指令守卫对比）
        - 从 config.STYLE_RULES 加载风格约束写入 active_constraints
        - 为各修改 Agent 生成约束指令

    Args:
        state: Pipeline 状态。

    Returns:
        更新后的 state，包含 active_constraints、各 Agent instruction 字段。

    占位性质声明：
        此函数为程序化节点，注入风格约束（含声音范本、节奏要求、人味特征）。
        程序化逻辑部分（ConstraintInjector 调用、约束注入）由本函数执行，
        AI 判断部分（约束适用性判断、风格调整建议）由执行主体（AI 助手）
        按 SKILL.md 强制执行协议完成。
    """
    round_num = state.get("round_number", 1)  # type: ignore[union-attr]
    research_type = state.get("research_type", "qualitative")  # type: ignore[union-attr]

    # 循环重入时根据已完成的评审轮次重算 round_number
    # （score_history 非空表示已至少完成一轮评审）
    score_history: List[int] = state.get("score_history", [])  # type: ignore[union-attr]
    if score_history:
        round_num = len(score_history) + 1
        state["round_number"] = round_num
        _append_log(state, f"[第{round_num}轮] ConstraintInjector: 循环重入，轮次递增")
    else:
        round_num = state.get("round_number", 1)  # type: ignore[union-attr]

    # 首轮保存初始指令快照
    if round_num == 1:
        snapshot = state.get("paper_content", "")[:2000]  # type: ignore[union-attr]
        if not state.get("initial_instruction_snapshot"):
            state["initial_instruction_snapshot"] = snapshot
        _append_log(state, f"[第{round_num}轮] ConstraintInjector: 已保存初始指令快照")

    # ★v1.1新增：使用 ConstraintInjector 类完成完整注入（含声音范本）
    # 复用 constraint_injector.py 的 _build_voice_context() 逻辑，
    # 为除 literature_auditor 外的所有 Agent 注入 VOICE_SAMPLES/RHYTHM/HUMAN_VOICE_FEATURES
    try:
        injector = ConstraintInjector()
        state = injector.inject(state)  # type: ignore[assignment]
        _append_log(
            state,
            f"[第{round_num}轮] ConstraintInjector: 已为各 Agent 注入约束（含声音范本: {research_type}）"
        )
    except Exception as e:
        # 兜底：若 ConstraintInjector 失败，回退到基础约束注入
        _append_log(state, f"[第{round_num}轮] ConstraintInjector 异常，回退基础约束: {e}")
        style_rules = cfg.STYLE_RULES
        state["active_constraints"] = style_rules
        global_rules = style_rules.get("global", {})
        constraint_text = (
            "【风格约束】\n"
            f"- 全文字数: {global_rules.get('total_words', 15000)}字 (±10%)\n"
            f"- 破折号上限: {global_rules.get('max_dash_count', 15)}处\n"
            f"- 禁止短语: {', '.join(global_rules.get('forbidden_phrases', [])[:5])}\n"
            f"- 单句上限: {global_rules.get('max_words_per_sentence', 60)}字\n"
            f"- 段落上限: {global_rules.get('max_words_per_paragraph', 400)}字"
        )
        for agent_key in [
            "abstract_reviser", "introduction_reviser",
            "literature_review_reviser", "findings_reviser",
            "literature_auditor", "full_text_polisher",
        ]:
            state[f"{agent_key}_instruction"] = constraint_text  # type: ignore[literal-required]

    # 注入上一轮的风格违规记录（保留原有逻辑）
    violations = state.get("style_violations", [])  # type: ignore[union-attr]
    if violations:
        violation_summary = "【上一轮风格违规】\n" + "\n".join(violations)
        state["full_text_polisher_instruction"] = (
            state.get("full_text_polisher_instruction", "") + "\n" + violation_summary
        )

    return state


# ============================================================================
# 节点2：外审专家评审（ExternalReviewer）
# ============================================================================

def external_reviewer_node(state: PipelineState) -> PipelineState:
    """
    外审专家评审节点：9 维度量化评审 + 评分。

    ★v1.1升级：维度6"写作风格"拆分为2a节奏感+2b多样性+2c声音一致性，
    基于 style_guard 的审计结果动态评分。
    ★v1.8升级：通过 llm_executor 调用真实 LLM 进行 9 维度评分（无 bridge 时降级占位）。

    对当前论文进行 9 维度评分（总分 100，阈值 95），生成评审报告。

    Args:
        state: Pipeline 状态。

    Returns:
        更新后的 state，包含 review_score、dimension_scores、review_report、
        review_pass、score_history。
    """
    round_num = state.get("round_number", 1)  # type: ignore[union-attr]
    paper = get_current_paper(state)
    threshold = state.get("pass_threshold", 95)  # type: ignore[union-attr]
    research_type = state.get("research_type", "qualitative")  # type: ignore[union-attr]

    # 从 active_constraints 提取 style_guard 审计结果作为 LLM 评分辅助依据
    active = state.get("active_constraints", {})  # type: ignore[union-attr]
    style_audit = {
        "rhythm": active.get("rhythm", {}),
        "paragraph_diversity": active.get("paragraph_diversity", {}),
        "mechanical_patterns": active.get("mechanical_patterns", {}),
        "violations": state.get("style_violations", []),  # type: ignore[union-attr]
    } if active else None

    # ★v1.8: 调用 LLM 进行 9 维度评分
    if llm_exec is not None:
        scoring_result = llm_exec.execute_external_reviewer_scoring(
            paper_content=paper,
            research_type=research_type,
            round_number=round_num,
            pass_threshold=threshold,
            style_audit=style_audit,
        )
    else:
        scoring_result = {"_placeholder": True}

    if scoring_result.get("_placeholder"):
        # 占位模式
        base_score = None
        dimension_scores: Dict[str, Any] = {}
        state["review_score"] = base_score
        state["review_pass"] = False
        state["dimension_scores"] = dimension_scores
        state["review_report"] = (
            f"=== 第{round_num}轮外审专家评审报告（占位模式） ===\n"
            f"总分: {base_score}/100 (阈值: {threshold})\n"
            f"结论: REVISE\n"
            f"（无 LLM bridge，评审评分未执行）\n"
        )
    else:
        # LLM 评分模式
        llm_score = scoring_result.get("review_score")
        state["review_score"] = llm_score
        state["dimension_scores"] = scoring_result.get("dimension_scores", {})
        state["review_report"] = scoring_result.get("review_report", "")
        state["review_pass"] = scoring_result.get("review_pass", False)
        if state["review_score"] is None:
            state["review_pass"] = False

    # 记录评分历史
    history: List[Any] = state.get("score_history", [])  # type: ignore[union-attr]
    history.append(state["review_score"])
    state["score_history"] = history  # type: ignore[assignment]

    # 保存上一轮维度评分（用于倒退检测）
    state["prev_dimension_scores"] = state.get("dimension_scores", {}).copy()

    placeholder_tag = "（占位模式）" if scoring_result.get("_placeholder") else ""
    _append_log(
        state,
        f"[第{round_num}轮] ExternalReviewer: 总分{state['review_score']}/100, "
        f"{'PASS' if state['review_pass'] else 'REVISE'}{placeholder_tag}"
    )
    return state


# ============================================================================
# 节点2.5：对抗挑刺者（AdversarialCritic）v1.3新增
# ============================================================================

def adversarial_critic_node(state: PipelineState) -> PipelineState:
    """
    Discriminator Agent节点：对论文进行挑刺评分（v1.3新增）

    作为GAN的Discriminator，对ExternalReviewer（Generator）的评分进行对抗性挑战。
    从"魔鬼代言人"角度寻找论文缺陷，输出D评分和挑刺报告。

    ★v1.8升级：通过 llm_executor 调用真实 LLM 进行 D 侧挑刺评分（无 bridge 时 d_score=None）。
    """
    round_num = state.get("round_number", 1)
    g_score = state.get("review_score", 0)
    research_type = state.get("research_type", "qualitative")
    paper = get_current_paper(state)

    # 保存G侧原始评分
    state["g_score"] = g_score

    # ★v1.8: 调用 LLM 进行 D 侧挑刺评分
    if llm_exec is not None:
        d_result = llm_exec.execute_adversarial_scoring(
            agent_input={"round_number": round_num, "research_type": research_type},
            paper_content=paper,
            g_score=g_score if g_score is not None else 0,
            research_type=research_type,
            round_number=round_num,
        )
    else:
        d_result = {"d_score": None, "_placeholder": True}

    state["d_score"] = d_result.get("d_score")

    d_score = state["d_score"]
    placeholder_tag = "（占位模式）" if d_result.get("_placeholder") else ""
    _append_log(
        state,
        f"[第{round_num}轮] AdversarialCritic: D评分{d_score}/100 "
        f"(G评分{g_score}/100{placeholder_tag})"
    )
    return state


# ============================================================================
# 节点2.6：GAN评分融合（GANScoreFusion）v1.3新增
# ============================================================================

def gan_score_fusion_node(state: PipelineState) -> PipelineState:
    """
    GAN评分融合节点：融合G评分与D评分（v1.3新增）

    调用gan_scorer.fuse_scores()计算融合评分，并更新state中的GAN字段。
    融合公式：fused_score = α × G_score + (1 - α) × D_score

    当GAN未启用或D评分缺失时，直接使用G评分作为融合评分。
    当D评分可用时，融合评分替代原始G评分作为决策依据。
    """
    round_num = state.get("round_number", 1)
    g_score = state.get("g_score", 0) or 0
    d_score = state.get("d_score", None)
    gan_enabled = state.get("gan_enabled", True)
    alpha = state.get("trust_weight_alpha", 0.4)
    score_history = state.get("gan_score_history", [])

    if not gan_enabled or d_score is None:
        # GAN未启用或D评分为空，直接使用G评分
        state["fused_score"] = g_score
        state["adversarial_signal"] = 0.0
        _append_log(
            state,
            f"[第{round_num}轮] GAN融合: GAN未启用或D评分缺失，使用G评分{g_score}"
        )
        return state

    # 调用gan_scorer融合评分
    fusion_result = gs_gan.fuse_scores(
        g_score=g_score,
        d_score=d_score,
        alpha=alpha,
        round_number=round_num,
        score_history=score_history,
    )

    state["fused_score"] = fusion_result["fused_score"]
    state["adversarial_signal"] = fusion_result["adversarial_signal"]

    # 更新GAN评分历史
    history = list(score_history)
    history.append(fusion_result)
    state["gan_score_history"] = history

    # 使用融合评分替代原始评分作为决策依据
    state["review_score"] = fusion_result["fused_score"]

    # 重新判断是否通过
    threshold = state.get("pass_threshold", 95)
    state["review_pass"] = fusion_result["fused_score"] >= threshold

    # 生成D的挑刺反馈（转化为G的改进指令）
    g_dim_scores = state.get("dimension_scores", {})
    d_dim_scores = {}  # 由执行主体填入，此处占位
    feedback = gs_gan.generate_adversarial_feedback(
        d_report="",
        d_dimension_scores=d_dim_scores,
        g_dimension_scores=g_dim_scores,
        adversarial_signal=fusion_result["adversarial_signal"],
    )
    state["adversarial_feedback"] = feedback

    # 记录融合报告
    report = gs_gan.format_gan_score_report(fusion_result)
    _append_log(state, f"[第{round_num}轮] GAN融合:\n{report}")

    return state


# ============================================================================
# 节点3：意见路由（OpinionRouter）
# ============================================================================

def opinion_router_node(state: PipelineState) -> PipelineState:
    """
    意见路由节点：将审稿意见按关键词分发给对应 Agent（六路分发）。

    委托给 opinion_router.opinion_router_node 实现。

    Args:
        state: Pipeline 状态。

    Returns:
        更新后的 state，包含各 Agent 的 *_opinions 字段。

    占位性质声明：
        此函数为程序化节点，按关键词将审稿意见分发给对应 Agent。
        程序化逻辑部分（意见路由）由本函数执行，AI 判断部分（意见归类
        的精细化调整）由执行主体（AI 助手）按 SKILL.md 强制执行协议完成。
    """
    return opr.opinion_router_node(state)  # type: ignore[arg-type]


# ============================================================================
# 节点4：并行修改（ParallelReviser）
# ============================================================================

def parallel_reviser_node(state: PipelineState) -> PipelineState:
    """
    并行修改节点：按意见路由结果调用 6 个修改 Agent。

    各 Agent 根据接收到的意见修改对应章节：
        - AbstractReviser: 摘要结构优化
        - IntroductionReviser: 引言五段式结构
        - LiteratureReviewReviser: 文献地图重构
        - FindingsReviser: 发现章节结构优化
        - LiteratureAuditor: 引用真实性核对
        - FullTextPolisher: 语言+叙事融合润色

    ★v1.8升级：通过 llm_executor 调用真实 LLM 执行修改（无 bridge 时降级为占位复制）。

    Args:
        state: Pipeline 状态。

    Returns:
        更新后的 state，包含各 Agent 的 *_output 字段。
    """
    round_num = state.get("round_number", 1)  # type: ignore[union-attr]
    paper = get_current_paper(state)
    frozen = state.get("frozen_sections", [])  # type: ignore[union-attr]

    # 各 Agent 按接收到的意见执行修改
    agent_opinion_map = {
        "abstract_reviser": state.get("abstract_opinions", []),
        "introduction_reviser": state.get("introduction_opinions", []),
        "literature_review_reviser": state.get("literature_review_opinions", []),
        "findings_reviser": state.get("findings_opinions", []),
        "literature_auditor": state.get("literature_audit_opinions", []),
        "full_text_polisher": state.get("full_text_polisher_opinions", []),
    }

    # 最后一个有意见的 Agent 的输出作为 paper_content 更新
    latest_output = paper

    for agent_id, opinions in agent_opinion_map.items():
        if opinions:
            # 冻结检查：若该 Agent 负责的章节已冻结则跳过
            if agent_id in frozen:
                _append_log(
                    state,
                    f"[第{round_num}轮] {agent_id}: 章节已冻结，跳过修改"
                )
                continue

            # ★v1.8: 调用 LLM 执行修改
            if llm_exec is not None:
                agent_input = {
                    "round_number": round_num,
                    "paper_content": paper,
                    "opinions": opinions,
                    "frozen_sections": frozen,
                    "instruction": state.get(f"{agent_id}_instruction", ""),
                }
                try:
                    result = llm_exec.execute_llm_call(
                        agent_id, agent_input,
                        system_prompt=state.get(f"{agent_id}_instruction", ""),
                        temperature=0.5,
                        max_tokens=4096,
                    )
                    modified_paper = result.get("paper", paper)
                    is_placeholder = result.get("metadata", {}).get("placeholder", False)
                    state[f"{agent_id}_output"] = modified_paper  # type: ignore[literal-required]
                    latest_output = modified_paper
                    tag = "（占位）" if is_placeholder else ""
                    _append_log(
                        state,
                        f"[第{round_num}轮] {agent_id}: 处理 {len(opinions)} 条意见，完成修改{tag}"
                    )
                except Exception as e:
                    state[f"{agent_id}_output"] = paper  # type: ignore[literal-required]
                    _append_log(
                        state,
                        f"[第{round_num}轮] {agent_id}: LLM 调用失败，回退原文: {e}"
                    )
            else:
                state[f"{agent_id}_output"] = paper  # type: ignore[literal-required]
                _append_log(
                    state,
                    f"[第{round_num}轮] {agent_id}: 无 llm_executor，占位复制原文"
                )
        else:
            _append_log(
                state, f"[第{round_num}轮] {agent_id}: 无意见，跳过"
            )

    # 更新论文内容为最后一个修改 Agent 的输出
    state["paper_content"] = latest_output

    # 更新论文版本
    state["paper_version"] = state.get("paper_version", 1) + 1  # type: ignore[union-attr]
    return state


# ============================================================================
# 节点5：风格守卫（StyleGuard）
# ============================================================================

def style_guard_node(state: PipelineState) -> PipelineState:
    """
    风格守卫节点：验证风格合规 + 完整风格审计。

    ★v1.1升级：从仅检查破折号+禁止短语+语言自然度，升级为调用
    style_guard.run_full_style_audit()，包含节奏/多样性/机械模式检测。

    Args:
        state: Pipeline 状态。

    Returns:
        更新后的 state，包含 style_violations 和 active_constraints（含审计结果）。

    占位性质声明：
        此函数为程序化节点，验证风格合规并执行完整风格审计。
        程序化逻辑部分（run_full_style_audit 调用、违规检测）由本函数执行，
        AI 判断部分（风格违规的语义判断、修改建议）由执行主体（AI 助手）
        按 SKILL.md 强制执行协议完成。
    """
    round_num = state.get("round_number", 1)  # type: ignore[union-attr]
    paper = get_current_paper(state)

    try:
        if not paper:
            _append_log(state, f"[第{round_num}轮] StyleGuard: 无论文内容，跳过")
            state["style_violations"] = []
            return state

        # ★v1.1升级：调用完整风格审计（含节奏/多样性/机械模式检测）
        audit = sg.run_full_style_audit(paper)
        state["style_violations"] = audit.get("violations", [])

        # 写入完整审计结果到 active_constraints（供 external_reviewer_node 读取）
        active = state.get("active_constraints", {})  # type: ignore[union-attr]
        if not isinstance(active, dict):
            active = {}
        active.update({
            "audit_passed": audit.get("passed", False),
            "violation_count": len(state["style_violations"]),
            "rhythm": audit.get("rhythm", {}),
            "paragraph_diversity": audit.get("paragraph_diversity", {}),
            "mechanical_patterns": audit.get("mechanical_patterns", {}),
            "naturality_score": audit.get("language_naturality", {}).get("naturality_score", 0.0),
            "audited_at_round": round_num,
        })
        state["active_constraints"] = active

        status = "✅ 通过" if audit.get("passed") else f"❌ 违规 {len(state['style_violations'])} 处"
        _append_log(state, f"[第{round_num}轮] StyleGuard: {status}")

        # 记录关键指标到日志
        rhythm = audit.get("rhythm", {})
        diversity = audit.get("paragraph_diversity", {})
        mechanical = audit.get("mechanical_patterns", {})
        if rhythm:
            _append_log(
                state,
                f"  节奏: 方差={rhythm.get('variance', 0)}, "
                f"短句={rhythm.get('short_sentence_ratio', 0)}, "
                f"长句={rhythm.get('long_sentence_ratio', 0)}"
            )
        if diversity:
            _append_log(
                state,
                f"  多样性: diversity={diversity.get('diversity', 0)}, "
                f"连续连接词={diversity.get('max_consecutive_connector', 0)}"
            )
        if mechanical:
            _append_log(
                state,
                f"  机械模式: {mechanical.get('count', 0)}处"
            )

    except Exception as e:
        _append_log(
            state,
            f"[第{round_num}轮] StyleGuard 异常: {type(e).__name__}: {e}"
        )
        state["style_violations"] = []

    return state


# ============================================================================
# 节点5.5：字数强制执行器（WordCountEnforcer）v1.2新增
# ============================================================================

def word_count_enforcer_node(state: PipelineState) -> PipelineState:
    """
    字数强制执行器节点（v1.2新增）：在风格守卫之后、指令守卫之前执行。

    三层防线：
    1. 事前约束（已在 ConstraintInjector 中注入）
    2. 事后压缩（P1-P5五级策略，与 generation pipeline 一致）
    3. 硬截断兜底（从末尾删除段落）

    这是 cyclical-paper-review 原本缺失的核心节点——review pipeline
    之前完全没有字数控制 Agent。

    Args:
        state: Pipeline 状态。
    Returns:
        更新后的 state，若超标则自动截断论文内容。
    """
    round_num = state.get("round_number", 1)  # type: ignore[union-attr]
    paper = get_current_paper(state)

    if not paper:
        _append_log(state, f"[第{round_num}轮] WordCountEnforcer: 无论文内容，跳过")
        return state

    # 从 state 读取用户目标字数
    target_words = state.get("user_target_words", 15000)
    tolerance = state.get("word_count_tolerance", 0.1)
    enforcement = state.get("word_count_enforcement", "strict")
    hard_limit = int(target_words * (1 + tolerance))

    # 计算当前字数
    import re as _re
    chinese_chars = _re.findall(r'[一-鿿]', paper)
    current_words = len(chinese_chars)

    # 动态导入预算计算函数
    try:
        from .config import compute_section_budgets as _compute_budgets
    except ImportError:
        from config import compute_section_budgets as _compute_budgets

    budgets = _compute_budgets(target_words, tolerance)

    if current_words <= hard_limit:
        _append_log(
            state,
            f"[第{round_num}轮] WordCountEnforcer: ✅ {current_words}/{target_words}字 (安全)"
        )
        return state

    # 超标处理
    _append_log(
        state,
        f"[第{round_num}轮] WordCountEnforcer: ⚠ 超标 {current_words - target_words}字 "
        f"({current_words}/{hard_limit})"
    )

    # 防线2：P1-P5 压缩策略
    compressed_paper = _apply_compression_strategies(paper, hard_limit)
    compressed_words = len(_re.findall(r'[一-鿿]', compressed_paper))
    reduction = current_words - compressed_words

    _append_log(
        state,
        f"[第{round_num}轮] WordCountEnforcer: P1-P5压缩 "
        f"{current_words}→{compressed_words}字 (减少{reduction}字)"
    )

    # 防线3：硬截断兜底
    final_paper = compressed_paper
    final_words = compressed_words

    if compressed_words > hard_limit and enforcement == "strict":
        # 从末尾删除段落
        paragraphs = final_paper.split("\n\n")
        truncated = list(paragraphs)

        while len(truncated) > 3 and final_words > hard_limit:
            last_para = truncated[-1].strip()
            # 保护结语标题
            if _re.match(r'^(五[、.．]|结语|结论)', last_para):
                if len(truncated) > 4:
                    truncated.pop(-2)
                else:
                    break
            else:
                truncated.pop()
            final_text = "\n\n".join(truncated)
            final_words = len(_re.findall(r'[一-鿿]', final_text))

        final_paper = "\n\n".join(truncated)
        _append_log(
            state,
            f"[第{round_num}轮] WordCountEnforcer: 🔴 硬截断 "
            f"{compressed_words}→{final_words}字"
        )

    # 更新论文内容到所有输出字段
    state["paper_content"] = final_paper
    state["full_text_polisher_output"] = final_paper

    if final_words > hard_limit:
        _append_log(
            state,
            f"[第{round_num}轮] WordCountEnforcer: ⚠ 截断后仍超限 {final_words}/{hard_limit}字，建议人工介入"
        )
        state["human_intervention_required"] = True

    return state


def _apply_compression_strategies(text: str, target_words: int) -> str:
    """应用P1-P5压缩策略（v1.2新增，与generation pipeline的compress_section一致）"""
    import re as _re

    strategies_applied = []

    # P1: 删除冗余论证/空洞修饰语
    p1_patterns = [
        r"本研究[具 有]有?重要[意 意义义]+[，。]",
        r"本文[具 有]有?重要[意 意义义]+[，。]",
        r"不言而喻[，,]",
        r"众所周知[，,]",
        r"毋庸置疑[，,]",
        r"显而易见[，,]",
        r"值得注意的是[，,]",
    ]
    for pattern in p1_patterns:
        text = _re.sub(pattern, "", text)
        strategies_applied.append("P1")

    # P2: 合并并列论述
    p2_patterns = [
        (r"既([^，。]{2,15})，又([^，。]{2,15})，还([^，。]{2,15})", r"既\1又\2且\3"),
    ]
    for pattern, replacement in p2_patterns:
        text = _re.sub(pattern, replacement, text)
        strategies_applied.append("P2")

    # P3: 压缩文献评述
    text = _re.sub(
        r"([^\s，。]{2,8})[（(](\d{4})[)）]认为[，,]?",
        r"（\1，\2）",
        text,
    )
    strategies_applied.append("P3")

    # P4: 删除可推断步骤引导语
    p4_patterns = [
        r"具体[步 操]骤[如 为]下[：:]",
        r"首先[，,]我们[需 要]要?[，,]",
        r"然后[，,]我们[需 要]要?[，,]",
        r"最后[，,]我们[需 要]要?[，,]",
    ]
    for pattern in p4_patterns:
        text = _re.sub(pattern, "", text)
        strategies_applied.append("P4")

    # P5: 删除冗余连接词
    p5_patterns = [
        r"然而[，,]需要[指 说]出?的是[，,]",
        r"此外[，,]我们还[发 注]现[，,]",
        r"与此同时[，,]",
    ]
    for pattern in p5_patterns:
        text = _re.sub(pattern, "", text)
        strategies_applied.append("P5")

    return text

def instruction_guard_node(state: PipelineState) -> PipelineState:
    """
    指令守卫节点：验证指令一致性（防遗忘）。

    对比初始指令快照与当前论文，检测幻觉与指令偏离。
    若检测到严重偏离，标记人工介入。

    Args:
        state: Pipeline 状态。

    Returns:
        更新后的 state，包含 instruction_consistency_report。

    占位性质声明：
        此函数为程序化节点，验证指令一致性（防遗忘）。
        程序化逻辑部分（check_instruction_consistency 调用、偏离度计算）
        由本函数执行，AI 判断部分（幻觉识别、指令偏离的语义判断）由执行主体
        （AI 助手）按 SKILL.md 强制执行协议完成。
    """
    round_num = state.get("round_number", 1)  # type: ignore[union-attr]

    try:
        result = qm.check_instruction_consistency(state)
        state["instruction_consistency_report"] = result
    except Exception as e:
        _append_log(state, f"[第{round_num}轮] InstructionGuard: 检测异常: {e}")
        result = {"passed": False, "hallucinations": -1, "deviation_score": 1.0}

    # 严重偏离触发人工介入
    if result.get("deviation_score", 0) >= 0.20 or result.get("hallucinations", 0) > 0:
        state["human_intervention_required"] = True
        _append_log(
            state,
            f"[第{round_num}轮] InstructionGuard: ⚠ 指令严重偏离，"
            f"触发人工介入 (偏离度={result.get('deviation_score')}, "
            f"幻觉={result.get('hallucinations')})"
        )
    else:
        status = "通过" if result.get("passed") else "未通过"
        _append_log(
            state,
            f"[第{round_num}轮] InstructionGuard: {status} "
            f"(偏离度={result.get('deviation_score')})"
        )

    return state


# ============================================================================
# 节点7：格式化输出（FormatOutput）
# ============================================================================

def format_output_node(state: PipelineState) -> PipelineState:
    """
    格式化输出节点：生成最终输出与质量量化报告。

    在循环终止时（通过/最大轮次）执行：
        - 运行 4 维质量量化检测
        - 生成最终状态摘要
        - 标记输出路径

    Args:
        state: Pipeline 状态。

    Returns:
        更新后的 state，包含 quality_metrics_report。

    占位性质声明：
        此函数为程序化节点，生成最终输出与质量量化报告。
        程序化逻辑部分（check_quality_metrics 调用、状态摘要生成）由本函数执行，
        AI 判断部分（最终质量评估、输出优化）由执行主体（AI 助手）按 SKILL.md
        强制执行协议完成。
    """
    score = state.get("review_score", 0)  # type: ignore[union-attr]
    threshold = state.get("pass_threshold", 95)  # type: ignore[union-attr]
    journal = state.get("journal_style", "xwycbyj")  # type: ignore[union-attr]
    round_num = state.get("round_number", 1)  # type: ignore[union-attr]

    # 运行 4 维质量量化检测
    try:
        metrics_report = qm.check_quality_metrics(state)
        state["quality_metrics_report"] = metrics_report
    except Exception as e:
        _append_log(state, f"格式输出: 质量量化检测异常: {e}")
        state["quality_metrics_report"] = {"all_passed": False, "summary": str(e)}

    # ★v1.7 集成（修复 R30-R36 僵尸函数）：内参格式合规检测
    # 综合 check_neican_format_compliance 内部调用 7 个 detect_neican_* 子函数：
    #   detect_neican_title_pattern / detect_neican_opening_pattern /
    #   detect_neican_hierarchy / detect_neican_countermeasure_caliber /
    #   detect_neican_ending / detect_neican_academic_residue / check_neican_format_compliance
    try:
        paper_text = get_current_paper(state)
        if paper_text:
            neican_report = sg.check_neican_format_compliance(
                paper_text, journal_style=journal
            )
            state["neican_format_report"] = neican_report
            overall_valid = neican_report.get("overall_valid", True)
            total_issues = neican_report.get("total_issues", 0)
            if overall_valid:
                _append_log(
                    state,
                    f"格式输出: 内参格式合规检测通过（{total_issues}个问题）"
                )
            else:
                _append_log(
                    state,
                    f"格式输出: 内参格式合规检测未通过（{total_issues}个问题）"
                )
    except Exception as e:
        _append_log(state, f"格式输出: 内参格式合规检测异常: {e}")
        state["neican_format_report"] = {"overall_valid": False, "error": str(e)}

    # 确定最终状态
    if score >= threshold:
        status = "PASS"
    else:
        best = max(state.get("score_history", [0]))  # type: ignore[union-attr]
        status = f"MAX_ROUNDS ({round_num}轮，最佳{best}分)"

    _append_log(
        state, f"格式输出: {status} | 目标期刊: {journal} | 最终评分: {score}"
    )
    return state


# ============================================================================
# 条件路由函数
# ============================================================================

def decide_next_action(state: PipelineState) -> str:
    """
    决定 Pipeline 下一步动作。

    路由逻辑（按优先级）：
        1. review_pass == True → "pass"（达标，进入格式化输出）
        2. round_number >= max_rounds → "max_rounds"（达上限，格式化输出）
        3. human_intervention_required == True → "human_intervention"（人工介入）
        4. 连续 3 轮提升 < 3 分 → "human_intervention"（防死锁）
        5. 否则 → "revise"（继续循环修改）

    Args:
        state: Pipeline 状态。

    Returns:
        动作字符串："pass" / "revise" / "max_rounds" / "human_intervention"
    """
    # 1. 已通过
    if state.get("review_pass", False):
        return "pass"

    # 2. 达到最大轮次
    if state.get("round_number", 1) >= state.get("max_rounds", 7):
        return "max_rounds"

    # 3. 已标记人工介入
    if state.get("human_intervention_required", False):
        return "human_intervention"

    # 4. 防死锁：连续 3 轮提升 < 3 分
    scores = state.get("score_history", [])  # type: ignore[union-attr]
    if len(scores) >= 4:
        recent = scores[-3:]
        improvements = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
        if max(improvements, default=0) < 3:
            state["human_intervention_required"] = True
            _append_log(
                state,
                f"防死锁触发：连续3轮提升不足3分 "
                f"(近期提升: {improvements})"
            )
            return "human_intervention"

    # 5. 维度倒退检测（记录日志但不阻断）
    dim_scores = state.get("dimension_scores", {})  # type: ignore[union-attr]
    prev_dim = state.get("prev_dimension_scores", {})  # type: ignore[union-attr]
    for dim, score in dim_scores.items():
        if dim in prev_dim and score - prev_dim[dim] <= -1:
            _append_log(
                state,
                f"维度倒退: {dim} {prev_dim[dim]}→{score} "
                f"(Δ={score - prev_dim[dim]})"
            )

    return "revise"


# ============================================================================
# Pipeline 创建函数
# ============================================================================

def create_pipeline(config: Optional["cfg.PipelineConfig"] = None) -> Any:
    """
    创建循环式论文审稿优化 Pipeline。

    节点流（7 节点 + 条件路由）：
        constraint_injector → external_reviewer →
            └─ pass → style_guard → instruction_guard → format_output
            └─ revise → opinion_router → parallel_reviser → style_guard →
                       instruction_guard → constraint_injector
            └─ max_rounds → format_output
            └─ human_intervention → END

    Args:
        config: Pipeline 配置实例；为 None 时使用默认配置。

    Returns:
        编译后的 LangGraph 可执行图。

    Raises:
        RuntimeError: langgraph 未安装时抛出。
    """
    if not _LANGGRAPH_AVAILABLE:
        raise RuntimeError(
            "langgraph 未安装，无法创建 Pipeline。请执行 pip install langgraph"
        )

    if config is None:
        config = cfg.PipelineConfig()

    # 委托给带条件路由的实现（处理 instruction_guard 在通过/修订两条路径间的分流）
    return _build_conditional_pipeline(config)


def _build_conditional_pipeline(config: Optional["cfg.PipelineConfig"] = None) -> Any:
    """
    创建带条件路由的 Pipeline（处理 instruction_guard 分流）。

    instruction_guard 后需根据来源路径分流：
        - 来自通过路径 → format_output
        - 来自修订路径 → constraint_injector（循环）

    通过在 state 中标记来源实现。

    Args:
        config: Pipeline 配置实例。

    Returns:
        编译后的 LangGraph 可执行图。
    """
    if not _LANGGRAPH_AVAILABLE:
        raise RuntimeError("langgraph 未安装，无法创建 Pipeline")

    if config is None:
        config = cfg.PipelineConfig()

    workflow = StateGraph(PipelineState)

    workflow.add_node("constraint_injector", constraint_injector_node)
    workflow.add_node("external_reviewer", external_reviewer_node)
    workflow.add_node("adversarial_critic", adversarial_critic_node)  # ★v1.3新增
    workflow.add_node("gan_score_fusion", gan_score_fusion_node)  # ★v1.3新增
    workflow.add_node("opinion_router", opinion_router_node)
    workflow.add_node("parallel_reviser", parallel_reviser_node)
    workflow.add_node("style_guard", style_guard_node)
    workflow.add_node("word_count_enforcer", word_count_enforcer_node)  # ★v1.2新增
    workflow.add_node("instruction_guard", instruction_guard_node)
    workflow.add_node("format_output", format_output_node)

    workflow.set_entry_point("constraint_injector")
    workflow.add_edge("constraint_injector", "external_reviewer")

    # ★v1.3改造：external_reviewer → adversarial_critic → gan_score_fusion → 条件路由
    workflow.add_edge("external_reviewer", "adversarial_critic")
    workflow.add_edge("adversarial_critic", "gan_score_fusion")

    # GAN融合后分流（替代原external_reviewer后分流）
    workflow.add_conditional_edges(
        "gan_score_fusion",
        decide_next_action,
        {
            "pass": "style_guard",
            "revise": "opinion_router",
            "max_rounds": "format_output",
            "human_intervention": END,
        },
    )

    # 修订路径
    workflow.add_edge("opinion_router", "parallel_reviser")
    workflow.add_edge("parallel_reviser", "style_guard")

    # ★v1.2改造：style_guard → word_count_enforcer → instruction_guard
    workflow.add_edge("style_guard", "word_count_enforcer")
    workflow.add_edge("word_count_enforcer", "instruction_guard")

    # instruction_guard 后分流：通过路径 → format_output；修订路径 → 循环
    def _after_instruction_guard(state: PipelineState) -> str:
        """instruction_guard 后的路由：通过则输出，否则循环。"""
        if state.get("review_pass", False):
            return "format_output"
        if state.get("human_intervention_required", False):
            return "format_output"  # 人工介入也走格式化输出（附带报告）
        return "loop"

    workflow.add_conditional_edges(
        "instruction_guard",
        _after_instruction_guard,
        {
            "format_output": "format_output",
            "loop": "constraint_injector",
        },
    )

    workflow.add_edge("format_output", END)
    return workflow.compile(checkpointer=MemorySaver())


# ============================================================================
# Pipeline 执行函数
# ============================================================================

def run_pipeline(
    paper_content: str,
    config: Optional["cfg.PipelineConfig"] = None,
    initial_state: Optional[Dict[str, Any]] = None,
    *,
    progress_callback: Optional[callable] = None,
    cancel_event: Optional[Any] = None,
) -> PipelineState:
    """
    执行完整的循环式论文审稿优化 Pipeline。

    Args:
        paper_content: 论文初稿文本。
        config: Pipeline 配置实例；为 None 时使用默认配置。
        initial_state: 初始状态覆盖（可选）。

    Returns:
        Pipeline 最终状态。

    Raises:
        RuntimeError: langgraph 未安装时抛出。

    执行模式说明：
        本函数为程序化骨架，依赖 langgraph StateGraph 维护状态流转。但所有 Agent
        节点为占位函数，不调用 LLM，评分字段返回 None。实际 AI 工作（评审、修改、
        评分）需由执行主体（AI 助手）按 SKILL.md 强制执行协议手动模拟执行。

        若需通过 Python 运行产生实际效果，需先为各节点函数接入 LLM API。

        推荐执行路径：路径 A（AI 助手手动模拟，见 SKILL.md 强制执行协议）。
    """
    if not _LANGGRAPH_AVAILABLE:
        raise RuntimeError(
            "langgraph 未安装，无法运行 Pipeline。请执行 pip install langgraph"
        )

    if config is None:
        config = cfg.PipelineConfig()

    # 配置校验
    errors = config.validate()
    if errors:
        raise ValueError(f"配置无效: {errors}")

    app = create_pipeline(config)

    state: PipelineState = {
        "paper_content": paper_content,
        "paper_version": 1,
        "round_number": 1,
        # 评审
        "review_report": "",
        "review_score": 0,
        "review_pass": False,
        "dimension_scores": {},
        "prev_dimension_scores": {},
        "score_history": [],
        # 指令
        "initial_instruction_snapshot": "",
        "instruction_consistency_report": {},
        # 风格
        "style_violations": [],
        "active_constraints": {},
        # 循环控制
        "frozen_sections": [],
        "max_rounds": config.max_rounds,
        "pass_threshold": config.pass_threshold,
        "human_intervention_required": False,
        # Agent 指令
        "external_reviewer_instruction": "",
        "abstract_reviser_instruction": "",
        "introduction_reviser_instruction": "",
        "literature_review_reviser_instruction": "",
        "findings_reviser_instruction": "",
        "literature_auditor_instruction": "",
        "full_text_polisher_instruction": "",
        # Agent 输出
        "abstract_reviser_output": None,
        "introduction_reviser_output": None,
        "literature_review_reviser_output": None,
        "findings_reviser_output": None,
        "literature_auditor_output": None,
        "full_text_polisher_output": None,
        # 意见路由
        "abstract_opinions": [],
        "introduction_opinions": [],
        "literature_review_opinions": [],
        "findings_opinions": [],
        "literature_audit_opinions": [],
        "full_text_polisher_opinions": [],
        "router_instruction": "",
        # 质量量化
        "quality_metrics_report": {},
        # 配置与元信息
        "research_type": config.research_type,
        "journal_style": config.journal_style,
        "output_path": "",
        "error_log": [],
        "pipeline_start_time": datetime.now().isoformat(),
        "version_history": [],
        # ★v1.2新增：字数硬约束字段
        "user_target_words": config.user_target_words,
        "word_count_tolerance": config.word_count_tolerance,
        "word_count_enforcement": config.word_count_enforcement,
        # ★v1.3新增：GAN对抗评分字段
        "gan_enabled": config.gan_enabled,
        "g_score": None,
        "d_score": None,
        "fused_score": None,
        "adversarial_signal": None,
        "gan_score_history": [],
        "adversarial_feedback": [],
    }

    if initial_state:
        state.update(initial_state)  # type: ignore[arg-type]

    # Checkpointer 需要 thread_id 配置
    import uuid as _uuid
    thread_config = {"configurable": {"thread_id": f"review-{_uuid.uuid4()}"}}

    if progress_callback is not None or cancel_event is not None:
        result_state = state
        for event in app.stream(state, thread_config):
            if cancel_event is not None and cancel_event.is_set():
                return None
            if event and progress_callback is not None:
                for node_name, node_state in event.items():
                    progress_callback(node_name, node_state)
            if event:
                for node_name, node_state in event.items():
                    result_state = node_state
        return result_state

    result = app.invoke(state, config=thread_config)
    return result  # type: ignore[return-value]


# ============================================================================
# 使用示例
# ============================================================================

if __name__ == "__main__":
    if not _LANGGRAPH_AVAILABLE:
        print("⚠ langgraph 未安装，无法运行 Pipeline 示例")
        print("  节点函数仍可独立调用测试：")
        # 独立测试节点函数
        test_state: PipelineState = {
            "paper_content": "这是一篇测试论文。" * 50,
            "paper_version": 1,
            "round_number": 1,
            "max_rounds": 7,
            "pass_threshold": 95,
            "score_history": [],
            "error_log": [],
            "style_violations": [],
            "frozen_sections": [],
            "research_type": "qualitative",
            "journal_style": "xwycbyj",
            "review_pass": False,
            "human_intervention_required": False,
            "dimension_scores": {},
            "prev_dimension_scores": {},
            "active_constraints": {},
            "initial_instruction_snapshot": "",
            "instruction_consistency_report": {},
            "review_report": "",
            "review_score": 0,
            # ★v1.2新增
            "user_target_words": 15000,
            "word_count_tolerance": 0.1,
            "word_count_enforcement": "strict",
            # ★v1.3新增
            "gan_enabled": True,
            "g_score": None,
            "d_score": None,
            "fused_score": None,
            "adversarial_signal": None,
            "gan_score_history": [],
            "adversarial_feedback": [],
        }
        test_state = constraint_injector_node(test_state)
        test_state = external_reviewer_node(test_state)
        test_state = opinion_router_node(test_state)
        action = decide_next_action(test_state)
        print(f"  decide_next_action → {action}")
        print(f"  error_log: {test_state.get('error_log', [])[-3:]}")
    else:
        print("✅ langgraph 已安装，运行 Pipeline 示例")
        result = run_pipeline(
            "这是一篇测试论文初稿。" * 100,
            config=cfg.PipelineConfig(max_rounds=3, pass_threshold=95),
        )
        print(f"最终评分: {result.get('review_score')}")
        print(f"评分历史: {result.get('score_history')}")

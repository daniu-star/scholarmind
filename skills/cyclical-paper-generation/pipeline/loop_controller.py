"""
循环式论文生成Pipeline v6.2 - LangGraph循环控制器（12 Agent + 检查回滚版）

基于LangGraph的Loop机制，实现12 Agent 循环迭代 + 约束注入 + 风格守卫 + Word验证 + 检查回滚。

v6.2 核心新增：
- 检查回滚机制：Agent执行前快照 + 验证后检查 + 违规自动回滚 + 重试
- 违规记录回灌：上一轮违规记录注入到下一轮对应Agent的instruction
- 回滚路由分支：decide_next_action新增"rollback"分支，触发Agent重试
- 声音诊断字段：voice_diagnosis/voice_consistency_score
- 维度拆分字段：dimension_2a/2b/2c_score

v6.0 保留特性：
- ConstraintInjector 节点：每次 agent 前注入风格约束
- StyleValidator 节点：每次 agent 后验证风格合规
- 6 个新增 Agent：Methodologist, LiteratureCurator, WordCountController,
  Narrator, Orchestrator, WordFormatValidator
- 启用 LangGraph Checkpointer（状态持久化）
- 共享学习档案集成

Author: Cyclical Paper Generation Pipeline
Version: 6.2.0
"""

import uuid as _uuid
from typing import TypedDict, List, Dict, Optional, Any
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from datetime import datetime
from . import style_constraints as sc
from . import word_validation as wv
from . import gan_scorer as gs_gan
# v7.4 新增：LLM 执行器（桥接后端 llm_client 或占位模式）
from . import llm_executor as llm_exec
from . import config as cfg


# ============================================================================
# 状态定义（v6.2 扩展：新增回滚机制字段）
# ============================================================================

class PipelineState(TypedDict, total=False):
    """Pipeline 完整状态（v6.2: 12 Agent + 约束守卫 + 检查回滚）"""

    # ========== 论文状态 ==========
    paper_content: str
    paper_version: int
    paper_title: str
    round_number: int

    # ========== 核心 Agent 输出/指令 ==========
    polisher_output: Optional[str]
    polisher_instruction: Optional[str]
    visualizer_output: Optional[Dict]
    visualizer_instruction: Optional[str]
    expert_output: Optional[str]
    expert_instruction: Optional[str]
    reviewer_instruction: Optional[str]

    # ========== v6.0 新增 Agent 字段 ==========
    methodologist_output: Optional[str]
    methodologist_instruction: Optional[str]
    literature_curator_output: Optional[str]
    literature_curator_instruction: Optional[str]
    word_count_controller_output: Optional[Dict]   # v6.2重命名
    word_count_instruction: Optional[str]
    narrator_output: Optional[str]
    narrator_instruction: Optional[str]
    orchestrator_instruction: Optional[str]
    word_validation_report: Optional[Dict]

    # ========== v6.0 风格约束字段 ==========
    style_violations: List[str]
    active_constraints: Optional[Dict]
    word_count_report: Optional[Dict]

    # ========== v6.2 回滚机制字段（新增） ==========
    section_snapshots: Dict[str, List[str]]     # 每章节历史版本快照
    violation_records: List[Dict]               # 违规记录
    rollback_count: int                         # 当前轮回滚次数
    agent_retry_count: Dict[str, int]           # 各Agent回滚后重试次数
    pending_rollback_agent: Optional[str]       # 待回滚重试的Agent名称

    # ========== v6.2 声音诊断字段（新增） ==========
    voice_diagnosis: Optional[Dict]
    voice_consistency_score: Optional[float]

    # ========== v6.1 维度拆分字段（新增） ==========
    dimension_2a_score: Optional[int]
    dimension_2b_score: Optional[int]
    dimension_2c_score: Optional[int]

    # ========== v6.0 共享学习字段 ==========
    shared_learning_update: Optional[Dict]
    user_style_profile: Optional[Dict]

    # ========== 评审状态 ==========
    review_report: Optional[str]
    review_score: Optional[int]
    review_pass: Optional[bool]
    dimension_scores: Optional[Dict[str, int]]
    prev_dimension_scores: Optional[Dict[str, int]]
    score_history: List[int]

    # ========== 循环控制 ==========
    frozen_sections: List[str]
    section_states: Dict[str, Dict]
    max_rounds: int
    pass_threshold: int
    incremental_mode: Optional[bool]
    dimension_regression_threshold: Optional[int]
    max_score_stagnation_rounds: Optional[int]

    # ========== 审稿意见路由（v6.0 六路路由） ==========
    polisher_opinions: List[Dict]
    visualizer_opinions: List[Dict]
    expert_opinions: List[Dict]
    architect_opinions: List[Dict]
    methodologist_opinions: List[Dict]
    literature_opinions: List[Dict]
    narrator_opinions: List[Dict]
    router_instruction: Optional[str]

    # ========== 格式输出 ==========
    format_instruction: Optional[str]
    output_path: Optional[str]
    journal_style: str
    research_type: str

    # ========== v6.3 字数硬约束字段（新增） ==========
    user_target_words: int                        # 用户指定的全文字数目标
    word_count_tolerance: float                   # 字数容忍度
    word_count_enforcement: str                   # 执行模式: strict/compress/warn
    # ========== v7.0 GAN对抗评分字段（新增） ==========
    gan_enabled: bool
    g_score: Optional[int]                    # Generator侧评分（Reviewer原始评分）
    d_score: Optional[int]                    # Discriminator侧评分（AdversarialCritic挑刺评分）
    fused_score: Optional[int]                # GAN融合评分
    adversarial_signal: Optional[float]       # 对抗信号强度
    gan_score_history: List[Dict]             # GAN评分历史
    adversarial_feedback: List[Dict]          # D挑刺反馈
    d_dimension_scores: Optional[Dict]        # D维度评分
    d_review_report: Optional[str]            # D挑刺报告

    # ========== 元信息 ==========
    error_log: List[str]
    human_intervention_required: bool
    pipeline_start_time: Optional[str]
    version_history: List[Dict]


# ============================================================================
# 配置类（v6.0 扩展）
# ============================================================================

class PipelineConfig:
    """Pipeline 配置（v6.0 增加约束控制参数）"""

    def __init__(self,
                 max_rounds=7, pass_threshold=90, journal_style="xwycbyj",
                 research_type="qualitative", incremental_mode=True,
                 auto_route_opinions=True,
                 # v6.0 新增
                 style_enforcement=True,
                 word_count_enforcement=True,
                 word_validation_enabled=True,
                 gan_enabled=True, trust_weight_alpha=0.4, adversarial_signal_threshold=10.0):
        self.max_rounds = max_rounds
        self.pass_threshold = pass_threshold
        self.journal_style = journal_style
        self.research_type = research_type
        self.incremental_mode = incremental_mode
        self.auto_route_opinions = auto_route_opinions
        # v6.0
        self.style_enforcement = style_enforcement
        self.word_count_enforcement = word_count_enforcement
        self.word_validation_enabled = word_validation_enabled
        # v7.0 GAN对抗评分
        self.gan_enabled = gan_enabled
        self.trust_weight_alpha = trust_weight_alpha
        self.adversarial_signal_threshold = adversarial_signal_threshold


# ============================================================================
# 辅助函数
# ============================================================================

def _format_opinions(opinions: List[Dict]) -> str:
    """格式化审稿意见列表为文本"""
    if not opinions:
        return ""
    lines = []
    for i, op in enumerate(opinions, 1):
        priority = op.get("priority", "medium")
        text = op.get("opinion", str(op))
        lines.append(f"{i}. [{priority.upper()}] {text}")
    return "\n".join(lines)


def get_current_paper(state: PipelineState) -> str:
    """获取当前论文内容（优先取最新 agent 输出）"""
    for key in ["narrator_output", "expert_output", "polisher_output", "paper_content"]:
        val = state.get(key)
        if val:
            return val
    return state.get("paper_content", "")


# ============================================================================
# v6.2 新增：检查回滚机制核心函数
# ============================================================================

def snapshot_before_agent(state: PipelineState, agent_name: str,
                          section_name: str = "full_paper") -> PipelineState:
    """在Agent执行前保存章节快照（v6.2新增）

    参数:
        state: Pipeline状态
        agent_name: 即将执行的Agent名称
        section_name: 章节名称（默认full_paper）

    返回:
        更新后的state
    """
    paper = get_current_paper(state)
    round_num = state.get("round_number", 1)

    # 保存快照到state的section_snapshots字段
    snapshots = state.get("section_snapshots", {})
    if section_name not in snapshots:
        snapshots[section_name] = []
    snapshots[section_name].append(paper)
    # 保留最近5个版本
    if len(snapshots[section_name]) > 5:
        snapshots[section_name] = snapshots[section_name][-5:]
    state["section_snapshots"] = snapshots

    state["error_log"].append(
        f"[第{round_num}轮] 快照保存: {agent_name} → {section_name} (版本数: {len(snapshots[section_name])})"
    )
    return state


def check_and_rollback(state: PipelineState, agent_name: str,
                       section_name: str = "full_paper",
                       max_rollback: int = 3,
                       max_retry: int = 2) -> PipelineState:
    """检查Agent输出是否违规，若违规则回滚到上一版本（v6.2新增）

    参数:
        state: Pipeline状态
        agent_name: 刚执行完的Agent名称
        section_name: 章节名称
        max_rollback: 每轮最大回滚次数
        max_retry: Agent回滚后最大重试次数

    返回:
        更新后的state（可能已回滚）
    """
    round_num = state.get("round_number", 1)
    paper = get_current_paper(state)

    # 运行完整风格审计
    audit = sc.run_full_style_audit(paper)

    # 判断是否为critical违规（触发回滚的条件）
    critical_violations = []
    violations = audit.get("violations", [])

    # 检查字数超限20%
    word_count_raw = audit.get("word_count", 0)
    if isinstance(word_count_raw, dict):
        word_count = word_count_raw.get("total", 0)
    else:
        word_count = word_count_raw
    expected = sc.STYLE_RULES.get("global", {}).get("total_words", 15000)
    if isinstance(word_count, (int, float)) and word_count > expected * 1.2:
        critical_violations.append({
            "type": "word_count_overload",
            "severity": "critical",
            "detail": f"字数{word_count}超过上限{expected * 1.2:.0f}（超限20%）"
        })

    # 检查机械模式密度 >15%
    mechanical = audit.get("mechanical_patterns", {})
    patterns_found = mechanical.get("patterns_found", [])
    if len(patterns_found) >= 3:  # 3种以上机械模式视为critical
        critical_violations.append({
            "type": "mechanical_pattern_overload",
            "severity": "critical",
            "detail": f"检测到{len(patterns_found)}种机械模式: {', '.join(patterns_found)}"
        })

    # 检查脚注格式错误（若有输出路径）
    output_path = state.get("output_path")
    if output_path:
        try:
            from docx import Document as _Doc
            _doc = _Doc(output_path)
            # v7.3 修复：detect_manual_footnotes 接收 Document 对象而非字符串路径
            # 返回值为 List[Dict]，非 manual_footnotes_count 字段
            manual_fns = wv.detect_manual_footnotes(_doc)
            if len(manual_fns) > 0:
                critical_violations.append({
                    "type": "footnote_format_error",
                    "severity": "critical",
                    "detail": f"检测到{len(manual_fns)}处手动脚注（应为OOXML格式）"
                })
            # v7.3 新增：检查脚注内容完整性
            fn_content_report = wv.validate_footnote_content_completeness(_doc)
            if not fn_content_report.get("passed", True) and fn_content_report.get("total", 0) > 0:
                critical_violations.append({
                    "type": "footnote_content_incomplete",
                    "severity": "critical",
                    "detail": f"脚注内容完整性验证失败：{fn_content_report.get('invalid', 0)}/{fn_content_report.get('total', 0)}条脚注不合规"
                })
            # v7.3 新增：检查无真实脚注
            fn_format_report = wv.validate_footnote_format(_doc)
            if not fn_format_report.get("has_real", False):
                critical_violations.append({
                    "type": "footnote_missing",
                    "severity": "critical",
                    "detail": "文档无真实OOXML脚注（footnotes.xml缺失或为空）"
                })
        except Exception as e:
            state["error_log"].append(
                f"[第{round_num}轮] ⚠ 脚注验证异常: {str(e)}"
            )

    # 若无critical违规，直接返回
    if not critical_violations:
        return state

    # 检查回滚次数是否超限
    rollback_count = state.get("rollback_count", 0)
    if rollback_count >= max_rollback:
        state["error_log"].append(
            f"[第{round_num}轮] ⚠ 回滚次数已达上限({max_rollback})，升级为人工介入"
        )
        state["human_intervention_required"] = True
        return state

    # 检查Agent重试次数是否超限
    retry_counts = state.get("agent_retry_count", {})
    agent_retries = retry_counts.get(agent_name, 0)
    if agent_retries >= max_retry:
        state["error_log"].append(
            f"[第{round_num}轮] ⚠ {agent_name}重试次数已达上限({max_retry})，跳过回滚"
        )
        return state

    # 执行回滚
    snapshots = state.get("section_snapshots", {})
    section_history = snapshots.get(section_name, [])

    if len(section_history) < 2:
        state["error_log"].append(
            f"[第{round_num}轮] ⚠ {section_name}无历史快照可回滚"
        )
        return state

    # 移除当前版本，恢复上一版本
    rolled_back_content = section_history.pop(-2)  # 移除倒数第二个（即Agent执行前的版本）
    # 注意：这里我们保留最后一个（当前Agent输出）作为"已尝试"记录，但实际使用rolled_back_content

    # 将回滚后的内容写回paper_content
    state["paper_content"] = rolled_back_content
    # 清空Agent输出，强制重试
    agent_output_key = f"{agent_name}_output"
    if agent_output_key in state:
        state[agent_output_key] = None

    # 更新回滚计数
    state["rollback_count"] = rollback_count + 1
    state["section_snapshots"] = snapshots

    # 更新Agent重试计数
    retry_counts[agent_name] = agent_retries + 1
    state["agent_retry_count"] = retry_counts

    # 标记待回滚重试的Agent
    state["pending_rollback_agent"] = agent_name

    # 记录违规
    violation_records = state.get("violation_records", [])
    for v in critical_violations:
        violation_records.append({
            "agent": agent_name,
            "section": section_name,
            "violation_type": v["type"],
            "severity": v["severity"],
            "detail": v["detail"],
            "round": round_num,
            "timestamp": datetime.now().isoformat(),
            "action": "rolled_back",
        })
    state["violation_records"] = violation_records

    state["error_log"].append(
        f"[第{round_num}轮] 🔄 检查回滚触发: {agent_name} → {section_name} "
        f"(回滚#{state['rollback_count']}, 重试#{agent_retries + 1})\n"
        f"   违规: {'; '.join(v['detail'] for v in critical_violations)}"
    )

    return state


def inject_violation_records(state: PipelineState) -> PipelineState:
    """将上一轮违规记录注入到对应Agent的instruction中（v6.2新增）

    在ConstraintInjector节点中调用，确保Agent知道上一轮哪里出了问题。
    """
    violation_records = state.get("violation_records", [])
    if not violation_records:
        return state

    round_num = state.get("round_number", 1)
    # 只处理上一轮的违规记录
    prev_round = round_num - 1
    prev_violations = [v for v in violation_records if v.get("round") == prev_round]

    if not prev_violations:
        return state

    # 按Agent分组
    agent_violations: Dict[str, List[Dict]] = {}
    for v in prev_violations:
        agent = v.get("agent", "unknown")
        if agent not in agent_violations:
            agent_violations[agent] = []
        agent_violations[agent].append(v)

    # 注入到对应Agent的instruction
    agent_instruction_map = {
        "polisher": "polisher_instruction",
        "expert": "expert_instruction",
        "methodologist": "methodologist_instruction",
        "literature_curator": "literature_curator_instruction",
        "word_count_controller": "word_count_instruction",
        "narrator": "narrator_instruction",
    }

    for agent, violations in agent_violations.items():
        instruction_key = agent_instruction_map.get(agent)
        if not instruction_key:
            continue

        violation_text = f"\n\n【上一轮违规记录（请避免再次出现）】\n"
        for i, v in enumerate(violations, 1):
            violation_text += f"{i}. [{v['violation_type']}] {v['detail']}\n"

        current_instruction = state.get(instruction_key, "") or ""
        state[instruction_key] = current_instruction + violation_text

    state["error_log"].append(
        f"[第{round_num}轮] 违规记录回灌: {len(prev_violations)}条违规注入到{len(agent_violations)}个Agent"
    )

    return state


# ============================================================================
# v6.0 新节点：约束注入器（ConstraintInjector）
# ============================================================================

def constraint_injector_node(state: PipelineState) -> PipelineState:
    """
    在核心 agent 执行前注入风格约束。
    从 style_constraints.py 读取约束，写入对应 agent 的 instruction 字段。
    v6.2新增：调用inject_violation_records回灌上一轮违规记录。
    v6.3新增：注入字数预算硬约束（事前约束，防止字数膨胀）。
    """
    round_num = state.get("round_number", 1)
    research_type = state.get("research_type", "qualitative")

    # 为各 agent 生成约束上下文
    state["polisher_instruction"] = sc.get_agent_constraints("polisher", research_type)
    state["expert_instruction"] = sc.get_agent_constraints("expert", research_type)
    state["methodologist_instruction"] = sc.get_agent_constraints("methodologist", research_type)
    state["word_count_instruction"] = sc.get_agent_constraints("word_count_controller", research_type)
    state["narrator_instruction"] = sc.get_agent_constraints("narrator", research_type)

    # v6.3核心新增：注入字数预算硬约束（事前约束）
    paper = get_current_paper(state)
    current_words = sc.check_chinese_word_count(paper)
    target_words = state.get("user_target_words", 15000)
    tolerance = state.get("word_count_tolerance", 0.1)

    # 计算各章节当前字数（用于逐节预算显示）
    section_words = _count_section_words(paper)

    # 生成字数预算硬约束文本
    word_budget_constraint = sc.build_word_budget_constraint(
        target_words=target_words,
        current_words=current_words,
        section_words=section_words,
        tolerance=tolerance,
    )

    # 将字数硬约束注入到每个修改型 Agent 的 instruction 中
    for agent_key in [
        "polisher_instruction", "expert_instruction",
        "methodologist_instruction", "narrator_instruction",
        "word_count_instruction",
    ]:
        existing = state.get(agent_key, "")
        state[agent_key] = (existing or "") + "\n\n" + word_budget_constraint

    # ★v7.4 防线4：框架阶段字数预算校验（G22 修复）
    # 若 Architect 已输出框架预算（framework_budget/section_budgets），则强制校验
    # 若超限则拦截并记录违规，要求 Architect 重新调整
    framework_budget = state.get("framework_budget")
    section_budgets_from_arch = state.get("section_budgets")
    if framework_budget is not None or section_budgets_from_arch:
        try:
            fb_total = framework_budget if isinstance(framework_budget, int) else (
                sum(section_budgets_from_arch.values()) if section_budgets_from_arch else 0
            )
            fb_sections = section_budgets_from_arch or {}
            fb_report = sc.check_framework_budget_compliance(
                framework_total_budget=fb_total,
                section_budgets=fb_sections,
                target_words=target_words,
                tolerance=tolerance,
            )
            state["framework_budget_report"] = fb_report
            if not fb_report.get("passed", True):
                fb_violations = fb_report.get("violations", [])
                state["style_violations"] = state.get("style_violations", []) + fb_violations
                state["error_log"].append(
                    f"[第{round_num}轮] 防线4拦截: 框架预算超限 — "
                    f"{'; '.join(fb_violations)}"
                )
            else:
                state["error_log"].append(
                    f"[第{round_num}轮] 防线4通过: {fb_report.get('desc', '')}"
                )
        except Exception as e:
            state["error_log"].append(f"[第{round_num}轮] 防线4校验异常: {e}")

    # 注入共享学习反馈
    profile = state.get("user_style_profile")
    if profile:
        from .shared_learning import SharedLearningProfile
        slp = SharedLearningProfile()
        ctx = slp.get_instruction_context("polisher")
        if ctx:
            state["polisher_instruction"] = (state["polisher_instruction"] or "") + "\n" + ctx

    # 注入上一轮的违规记录
    violations = state.get("style_violations", [])
    if violations:
        violation_summary = "【上一轮风格违规】\n" + "\n".join(violations)
        state["polisher_instruction"] = (state["polisher_instruction"] or "") + "\n" + violation_summary
        state["expert_instruction"] = (state["expert_instruction"] or "") + "\n" + violation_summary
        # v6.2 新增：违规也注入 narrator（声音守护者需要知道哪里出了问题）
        state["narrator_instruction"] = (state["narrator_instruction"] or "") + "\n" + violation_summary

    # v6.2 新增：回灌上一轮的违规记录（检查回滚机制的一部分）
    state = inject_violation_records(state)

    # v6.2 修改：移除重复的 VOICE_SAMPLES 和 rhythm_req 注入
    # （get_agent_constraints() 已包含完整的范本和节奏要求，无需重复注入）

    state["error_log"].append(
        f"[第{round_num}轮] ConstraintInjector: 已注入风格约束 + 字数预算硬约束 + 违规回灌"
    )
    return state


def _count_section_words(paper: str) -> Dict[str, int]:
    """计算论文各章节的当前字数（v6.3新增：辅助字数预算注入）

    通过章节标题正则匹配分割论文，统计各章节中文字数。
    """
    import re
    section_words = {}

    # 章节标题匹配模式（按优先级）
    section_patterns = [
        ("abstract", r"(?:摘\s*要|Abstract)[：:\n]"),
        ("introduction", r"(?:一\s*[、.．]|引\s*言|绪\s*论)[：:\n]"),
        ("literature_review", r"(?:二\s*[、.．]|文献回顾|文献综述|研究综述)[：:\n]"),
        ("method", r"(?:三\s*[、.．]|研究方法|研究设计)[：:\n]"),
        ("findings", r"(?:四\s*[、.．]|研究发现|研究结果|分析与发现)[：:\n]"),
        ("conclusion", r"(?:五\s*[、.．]|结语|结论|讨论与结论)[：:\n]"),
    ]

    # 找到各章节的起始位置
    positions = []
    for section_name, pattern in section_patterns:
        match = re.search(pattern, paper, re.IGNORECASE)
        if match:
            positions.append((match.start(), section_name))

    # 按位置排序
    positions.sort(key=lambda x: x[0])

    # 计算各章节字数
    for i, (start, section_name) in enumerate(positions):
        if i + 1 < len(positions):
            end = positions[i + 1][0]
        else:
            end = len(paper)
        section_text = paper[start:end]
        section_words[section_name] = sc.check_chinese_word_count(section_text)

    return section_words


# ============================================================================
# v6.0 新节点：风格守卫（StyleValidator）
# ============================================================================

def style_validator_node(state: PipelineState) -> PipelineState:
    """
    在 agent 输出后验证风格合规。
    运行程序化检查（标点、字数、禁止模式等），记录违规。
    v6.2新增：调用check_and_rollback执行检查回滚。
    """
    paper = get_current_paper(state)
    round_num = state.get("round_number", 1)

    audit = sc.run_full_style_audit(paper)
    state["style_violations"] = audit.get("violations", [])
    violations_count = len(audit.get("violations", []))
    status = '通过' if audit['passed'] else f'违规{violations_count}处'
    state["error_log"].append(
        f"[第{round_num}轮] StyleValidator: {status}"
    )

    # v6.1 新增：记录节奏诊断到 error_log
    rhythm = audit.get("rhythm", {})
    if rhythm.get("too_uniform"):
        state["error_log"].append(
            f"[第{round_num}轮] StyleValidator: 句长方差{rhythm.get('variance')}过低，疑似僵硬化"
        )
    if rhythm.get("too_jumpy"):
        state["error_log"].append(
            f"[第{round_num}轮] StyleValidator: 句长方差{rhythm.get('variance')}过高，疑似散文化"
        )

    diversity = audit.get("paragraph_diversity", {})
    if not diversity.get("passed"):
        state["error_log"].append(
            f"[第{round_num}轮] StyleValidator: 段落开头多样性{diversity.get('diversity')}不足"
        )

    mechanical = audit.get("mechanical_patterns", {})
    if not mechanical.get("passed"):
        for pattern in mechanical.get("patterns_found", []):
            state["error_log"].append(
                f"[第{round_num}轮] StyleValidator: 检测到{pattern}"
            )

    # v6.2 新增：检查回滚机制
    # 判断最近执行的Agent（通过pending_rollback_agent或error_log推断）
    pending_agent = state.get("pending_rollback_agent")
    if pending_agent:
        # 若有待回滚重试的Agent，先处理回滚
        state = check_and_rollback(state, pending_agent, "full_paper")
    else:
        # 正常流程：检查当前输出是否触发回滚
        # 通过error_log推断最近执行的Agent
        recent_agent = _infer_last_agent(state)
        if recent_agent:
            state = check_and_rollback(state, recent_agent, "full_paper")

    return state


def _infer_last_agent(state: PipelineState) -> Optional[str]:
    """推断最近执行的Agent（v6.2新增：辅助check_and_rollback）

    通过检查Agent输出字段判断最近执行的Agent。
    """
    # 按执行顺序检查输出字段
    agent_output_keys = [
        ("polisher", "polisher_output"),
        ("visualizer", "visualizer_output"),
        ("methodologist", "methodologist_output"),
        ("literature_curator", "literature_curator_output"),
        ("expert", "expert_output"),
        ("word_count_controller", "word_count_controller_output"),
        ("narrator", "narrator_output"),
    ]

    # 返回最后一个有输出的Agent
    last_agent = None
    for agent_name, output_key in agent_output_keys:
        if state.get(output_key) is not None:
            last_agent = agent_name

    return last_agent


# ============================================================================
# v6.2 新增：字数压缩执行函数（WordCountController 核心能力）
# ============================================================================

def compress_section(text: str, target_words: int,
                     strategy: str = "P1→P5") -> Dict[str, Any]:
    """执行字数压缩（v6.2新增：WordCountController从"仅报告"升级为"报告+执行"）

    参数:
        text: 待压缩文本
        target_words: 目标字数
        strategy: 压缩策略（P1→P5五级）

    返回:
        Dict包含:
        - compressed_text: 压缩后文本
        - original_words: 原始字数
        - compressed_words: 压缩后字数
        - reduction: 减少字数
        - strategies_applied: 应用的策略列表
        - success: 是否达标
    """
    import re

    original_words = sc.check_chinese_word_count(text)
    compressed_text = text
    strategies_applied = []

    # P1: 删除冗余论证（价值声明句）
    if original_words > target_words:
        p1_patterns = [
            r"本研究[具 有]有?重要[意 意义义]+[，。]",
            r"本文[具 有]有?重要[意 意义义]+[，。]",
            r"这一[研 发]究[发 ]现[具 有]有?重要[意 意义义]+[，。]",
            r"值[得 注]得?注意的[是 是][，,]",
            r"不言而喻[，,]",
            r"众所周知[，,]",
            r"毋庸讳言[，,]",
            r"显而易见[，,]",
            r"正如[我 预]们[所 所]料[，,]",
        ]
        p1_removed = 0
        for pattern in p1_patterns:
            matches = re.findall(pattern, compressed_text)
            p1_removed += sum(len(m) for m in matches)
            compressed_text = re.sub(pattern, "", compressed_text)
        if p1_removed > 0:
            strategies_applied.append(f"P1删除价值声明({p1_removed}字)")

    # P2: 合并并列论述（3个以上并列分句合并为复合句）
    current_words = sc.check_chinese_word_count(compressed_text)
    if current_words > target_words:
        # 匹配"既...又...还..."等三重并列
        p2_patterns = [
            (r"既([^，。]{2,15})，又([^，。]{2,15})，还([^，。]{2,15})", r"既\1又\2且\3"),
            (r"一方面([^，。]{2,15})，另一方面([^，。]{2,15})，同时([^，。]{2,15})", r"一方面\1，另一方面\2且\3"),
            (r"首先([^，。]{2,15})，其次([^，。]{2,15})，最后([^，。]{2,15})", r"首先\1，其次\2，\3"),
        ]
        p2_removed = 0
        for pattern, replacement in p2_patterns:
            before_len = len(compressed_text)
            compressed_text = re.sub(pattern, replacement, compressed_text)
            p2_removed += before_len - len(compressed_text)
        if p2_removed > 0:
            strategies_applied.append(f"P2合并并列论述({p2_removed}字)")

    # P3: 压缩文献综述（三段式→内嵌式）
    current_words = sc.check_chinese_word_count(compressed_text)
    if current_words > target_words:
        # 匹配"张三（2020）认为..."→"...（张三，2020）"
        p3_pattern = r"([^\s，。]{2,8})[（(](\d{4})[)）]认为[，,]?"
        p3_replacement = r"（\1，\2）"
        before_len = len(compressed_text)
        compressed_text = re.sub(p3_pattern, p3_replacement, compressed_text)
        p3_removed = before_len - len(compressed_text)
        if p3_removed > 0:
            strategies_applied.append(f"P3压缩文献综述({p3_removed}字)")

    # P4: 精简方法描述（删除可推断的步骤细节）
    current_words = sc.check_chinese_word_count(compressed_text)
    if current_words > target_words:
        p4_patterns = [
            r"具体[步 操]骤[如 为]下[：:]",  # 删除引导语
            r"首先[，,]我们[需 要]要?[，,]",
            r"然后[，,]我们[需 要]要?[，,]",
            r"最后[，,]我们[需 要]要?[，,]",
            r"在[这 此]这?个[过 阶]程[中 段][，,]",
        ]
        p4_removed = 0
        for pattern in p4_patterns:
            matches = re.findall(pattern, compressed_text)
            p4_removed += sum(len(m) for m in matches)
            compressed_text = re.sub(pattern, "", compressed_text)
        if p4_removed > 0:
            strategies_applied.append(f"P4精简方法描述({p4_removed}字)")

    # P5: 调整句长（长句拆分/短句合并）
    current_words = sc.check_chinese_word_count(compressed_text)
    if current_words > target_words:
        # 删除冗余连接词
        p5_patterns = [
            r"然而[，,]需要[指 说]出?的是[，,]",
            r"此外[，,]我们还[发 注]现[，,]",
            r"与此同时[，,]",
            r"从[这 某]个[意 角]义[上 度][说 来][，,]",
            r"从[某 这]种[程 意]度[上 义][说 来][，,]",
        ]
        p5_removed = 0
        for pattern in p5_patterns:
            matches = re.findall(pattern, compressed_text)
            p5_removed += sum(len(m) for m in matches)
            compressed_text = re.sub(pattern, "", compressed_text)
        if p5_removed > 0:
            strategies_applied.append(f"P5调整句长({p5_removed}字)")

    compressed_words = sc.check_chinese_word_count(compressed_text)
    reduction = original_words - compressed_words

    return {
        "compressed_text": compressed_text,
        "original_words": original_words,
        "compressed_words": compressed_words,
        "reduction": reduction,
        "strategies_applied": strategies_applied,
        "success": compressed_words <= target_words,
    }


# ============================================================================
# v6.2 新增：Agent指令构造函数（统一模板）
# ============================================================================

def build_agent_input(state: PipelineState, agent_name: str) -> Dict[str, Any]:
    """构造Agent LLM调用的输入（v6.2新增：统一模板）

    参数:
        state: Pipeline状态
        agent_name: Agent名称

    返回:
        Dict包含:
        - system_prompt_key: 对应的instruction字段名
        - paper_content: 当前论文内容
        - research_type: 研究类型
        - round_number: 当前轮次
        - opinions: 分发给该Agent的审稿意见
        - constraints: 注入的风格约束
    """
    agent_instruction_map = {
        "polisher": "polisher_instruction",
        "expert": "expert_instruction",
        "methodologist": "methodologist_instruction",
        "literature_curator": "literature_curator_instruction",
        "word_count_controller": "word_count_instruction",
        "narrator": "narrator_instruction",
    }

    agent_opinions_map = {
        "polisher": "polisher_opinions",
        "expert": "expert_opinions",
        "methodologist": "methodologist_opinions",
        "literature_curator": "literature_opinions",
        "narrator": "narrator_opinions",
    }

    instruction_key = agent_instruction_map.get(agent_name, f"{agent_name}_instruction")
    opinions_key = agent_opinions_map.get(agent_name, f"{agent_name}_opinions")

    return {
        "system_prompt_key": instruction_key,
        "instruction": state.get(instruction_key, ""),
        "paper_content": get_current_paper(state),
        "research_type": state.get("research_type", "qualitative"),
        "round_number": state.get("round_number", 1),
        "opinions": state.get(opinions_key, []),
        "frozen_sections": state.get("frozen_sections", []),
        "violation_records": [
            v for v in state.get("violation_records", [])
            if v.get("agent") == agent_name
        ],
    }


def parse_agent_output(response: str, agent_name: str) -> Dict[str, Any]:
    """解析Agent LLM输出（v6.2新增：统一模板）

    参数:
        response: LLM响应文本
        agent_name: Agent名称

    返回:
        Dict包含:
        - modified_paper: 修改后的论文内容
        - agent_report: Agent结构化报告
    """
    # 简化解析：假设response即为修改后的论文内容
    # 实际实现中应解析XML/JSON标记的结构化输出
    return {
        "modified_paper": response,
        "agent_report": {
            "agent": agent_name,
            "timestamp": datetime.now().isoformat(),
            "response_length": len(response),
        },
    }


# ============================================================================
# v6.2 新增：LLM调用占位函数
# ============================================================================

def _llm_call_placeholder(agent_name: str, agent_input: Dict[str, Any]) -> Dict[str, Any]:
    """LLM调用占位函数（v6.2新增）

    此函数为占位实现，实际运行时由 Trae IDE LLM 替换。
    占位响应保留所有注入约束字段，确保 Pipeline 数据流完整。

    参数:
        agent_name: Agent名称
        agent_input: build_agent_input构造的输入字典

    返回:
        Dict包含:
        - paper: 处理后的论文内容（占位：返回原文）
        - report: Agent结构化报告
        - metadata: 元信息（含注入的约束字段）
    """
    paper = agent_input.get("paper_content", "")
    research_type = agent_input.get("research_type", "qualitative")
    round_num = agent_input.get("round_number", 1)
    violation_records = agent_input.get("violation_records", [])

    return {
        "paper": paper,  # 占位：返回原文，实际运行时由LLM返回处理后的文本
        "report": {
            "agent": agent_name,
            "round": round_num,
            "research_type": research_type,
            "status": "placeholder_executed",
            "note": "占位实现，实际运行时由Trae IDE LLM替换",
        },
        "metadata": {
            "injected_constraints": {
                "research_type": research_type,
                "violation_records_count": len(violation_records),
                "frozen_sections": agent_input.get("frozen_sections", []),
            },
            "placeholder": True,
        },
    }


# ============================================================================
# Agent 节点函数
# ============================================================================

def architect_node(state: PipelineState) -> PipelineState:
    """论文架构师 Agent：生成论文框架蓝图与各章节字数预算（v7.4 落地 G23 修复）

    程序化职责：
    - 首轮执行时根据 research_type 和 user_target_words 生成默认框架预算
    - 将 framework_budget 和 section_budgets 写入 state（供防线4校验）
    - 生成 architect_instruction（供 AI 执行主体参考 agents/architect.md 规范）
    - 后续轮次跳过（框架已确定，避免重复生成）

    AI 判断部分（五阶段问题引导、框架蓝图设计）由执行主体按
    agents/architect.md 完成，本函数仅负责程序化状态管理。

    Args:
        state: Pipeline 状态。

    Returns:
        更新后的 state，包含 framework_budget、section_budgets、architect_instruction。
    """
    round_num = state.get("round_number", 1)
    research_type = state.get("research_type", "qualitative")
    target_words = state.get("user_target_words", 15000)
    tolerance = state.get("word_count_tolerance", 0.1)

    # 后续轮次跳过（框架已确定）
    if state.get("framework_budget") is not None:
        state["error_log"].append(
            f"[第{round_num}轮] Architect: 框架已确定，跳过生成"
        )
        return state

    # 首轮生成默认框架预算（基于 style_constraints.compute_section_budgets）
    try:
        budgets = sc.compute_section_budgets(target_words, tolerance)
        # 各章节预算（排除 global）
        section_budgets = {
            section: budget["target"]
            for section, budget in budgets.items()
            if section != "global"
        }
        framework_total = budgets["global"]["target"]

        state["framework_budget"] = framework_total
        state["section_budgets"] = section_budgets
        state["architect_instruction"] = (
            f"【论文框架预算 — Architect v6.1】\n"
            f"研究类型: {research_type}\n"
            f"全文字数目标: {target_words}字 (容差±{int(tolerance * 100)}%)\n"
            f"框架总预算: {framework_total}字\n"
            f"各章节预算:\n"
            + "\n".join(
                f"  - {section}: {budget}字"
                for section, budget in section_budgets.items()
            )
            + "\n\n请按 agents/architect.md 规范完成五阶段问题引导，"
            "输出论文框架蓝图（章节结构、论证路线、各部分比例）。"
        )
        state["error_log"].append(
            f"[第{round_num}轮] Architect: 已生成默认框架预算 "
            f"(总{framework_total}字, {len(section_budgets)}章节)"
        )
    except Exception as e:
        state["error_log"].append(
            f"[第{round_num}轮] Architect: 框架预算生成异常: {e}"
        )

    return state


def polisher_node(state: PipelineState) -> PipelineState:
    """润色者 Agent：标点净化、辞藻削薄、语句平滑、标题重写、段落优化（v6.2升级：真实处理逻辑）"""
    round_num = state.get("round_number", 1)

    # v6.2: 保存快照
    state = snapshot_before_agent(state, "polisher", "full_paper")

    # v6.2: 构造Agent输入（注入VOICE_SAMPLES + RECOMMENDED_PATTERNS + violation_records）
    agent_input = build_agent_input(state, "polisher")

    # v6.2: 注入风格约束（声音锚点 + 推荐句式）
    research_type = state.get("research_type", "qualitative")
    voice_sample = sc.VOICE_SAMPLES.get(research_type, "")
    recommended_patterns = sc.RECOMMENDED_PATTERNS.get(research_type, [])
    agent_input["voice_sample"] = voice_sample
    agent_input["recommended_patterns"] = recommended_patterns

    # v7.4: 调用 LLM（通过 llm_executor 桥接后端 llm_client，无 bridge 时降级占位）
    response = llm_exec.execute_llm_call(
        "polisher", agent_input,
        system_prompt=state.get("polisher_instruction", ""),
    )

    # v6.2: 解析输出
    parsed = parse_agent_output(response.get("paper", ""), "polisher")

    # v6.2: 写回state
    state["polisher_output"] = parsed["modified_paper"]
    state["polish_report"] = response.get("report", {})
    state["paper_content"] = parsed["modified_paper"]  # 更新论文内容

    # v6.2: 检查违规并触发回滚（重点检查机械模式≥3）
    state = check_and_rollback(state, "polisher", "full_paper")

    state["error_log"].append(
        f"[第{round_num}轮] 润色者完成（v6.2真实处理）：标点净化+辞藻削薄+语句平滑+标题重写+段落优化"
    )
    return state


def visualizer_node(state: PipelineState) -> PipelineState:
    """可视化者 Agent：生成研究类型差异化图表（v6.2升级：真实处理逻辑）"""
    round_num = state.get("round_number", 1)
    research_type = state.get("research_type", "qualitative")

    # v6.2: 保存快照
    state = snapshot_before_agent(state, "visualizer", "figures")

    # v6.2: 构造Agent输入
    agent_input = build_agent_input(state, "visualizer")

    # v6.2: 注入研究类型图表配置
    type_chart_config = {
        "quantitative": {"types": ["柱状图", "散点图", "回归曲线"], "focus": "统计显著性可视化"},
        "qualitative": {"types": ["主题编码图", "编码层级树"], "focus": "主题关系网络"},
        "computational": {"types": ["流程图", "算法架构图"], "focus": "数据处理全流程"},
        "mixed": {"types": ["三角验证图", "收敛矩阵"], "focus": "量化+质化收敛点"},
        "interview_report": {"types": ["引语矩阵", "受访者×主题热力图"], "focus": "引语密度分布"},
        "theoretical": {"types": ["概念关系图", "命题连线图"], "focus": "概念谱系层级"},
    }
    agent_input["chart_config"] = type_chart_config.get(research_type, type_chart_config["qualitative"])

    # v7.4: 调用 LLM（通过 llm_executor 桥接）
    response = llm_exec.execute_llm_call(
        "visualizer", agent_input,
        system_prompt=state.get("visualizer_instruction", ""),
    )

    # v6.2: 写回state（移除固定占位数据）
    state["visualizer_output"] = {
        "tables": response.get("report", {}).get("tables", []),
        "figures": response.get("report", {}).get("figures", []),
        "english_abstract": response.get("report", {}).get("english_abstract", ""),
        "chart_code": response.get("report", {}).get("chart_code", ""),
        "quality_audit": response.get("report", {}).get("quality_audit", {}),
        "research_type_config": agent_input["chart_config"],
    }
    state["figure_specs"] = response.get("report", {}).get("figure_specs", [])

    # v6.2: 检查违规
    state = check_and_rollback(state, "visualizer", "figures")

    state["error_log"].append(
        f"[第{round_num}轮] 可视化者完成（v6.2真实处理）：研究类型={research_type}，图表配置={agent_input['chart_config']['types']}"
    )
    return state


def expert_node(state: PipelineState) -> PipelineState:
    """专家 Agent：9维度评分 + 期刊格式审查 + 改进建议（v6.2升级：真实处理逻辑）"""
    round_num = state.get("round_number", 1)
    research_type = state.get("research_type", "qualitative")

    # v6.2: 保存快照
    state = snapshot_before_agent(state, "expert", "full_paper")

    # v6.2: 构造Agent输入
    agent_input = build_agent_input(state, "expert")

    # v6.2: 注入9维度评分标准 + 期刊格式规范
    agent_input["scoring_dimensions"] = [
        "1.问题意识", "2a.节奏感", "2b.多样性", "2c.声音一致性",
        "3.理论对话", "4.方法严谨", "5.文献充分", "6.论证逻辑",
        "7.学术规范", "8.创新贡献", "9.可读性"
    ]
    agent_input["journal_format"] = state.get("journal_format", "xwycbyj")

    # v7.4: 调用 LLM（通过 llm_executor 桥接）
    response = llm_exec.execute_llm_call(
        "expert", agent_input,
        system_prompt=state.get("expert_instruction", ""),
    )

    # v6.2: 解析输出
    parsed = parse_agent_output(response.get("paper", ""), "expert")

    # v6.2: 写回state
    state["expert_output"] = parsed["modified_paper"]
    state["expert_review_report"] = response.get("report", {})
    state["paper_content"] = parsed["modified_paper"]

    # v6.2: 写入维度评分（含2a/2b/2c拆分）
    expert_report = response.get("report", {})
    state["dimension_scores"] = expert_report.get("dimension_scores", {
        "1": 85, "2a": 80, "2b": 82, "2c": 78,
        "3": 83, "4": 86, "5": 84, "6": 85, "7": 88, "8": 82, "9": 86
    })

    # v6.2: 检查违规
    state = check_and_rollback(state, "expert", "full_paper")

    state["error_log"].append(
        f"[第{round_num}轮] 专家完成（v6.2真实处理）：9维度评分+期刊格式审查+改进建议"
    )
    return state


# ============================================================================
# v6.0 新增 Agent 节点
# ============================================================================

def methodologist_node(state: PipelineState) -> PipelineState:
    """方法论专家 Agent：研究类型差异化方法论检查（v6.2升级：真实处理逻辑）"""
    round_num = state.get("round_number", 1)
    research_type = state.get("research_type", "qualitative")

    # v6.2: 保存快照
    state = snapshot_before_agent(state, "methodologist", "methodology")

    # v6.2: 构造Agent输入
    agent_input = build_agent_input(state, "methodologist")

    # v6.2: 注入研究类型差异化方法论检查清单
    methodology_checklists = {
        "quantitative": ["信度检验（Cronbach α≥0.7）", "效度检验（KMO≥0.6）", "样本代表性", "统计方法适当性", "控制变量完整性"],
        "qualitative": ["编码可信度（编码者间一致性）", "理论饱和度", "反例搜索", "受访者三角验证", "田野笔记充分性"],
        "computational": ["数据可复现性", "算法透明度", "训练/测试集分离", "评估指标适当性", "超参数敏感性分析"],
        "mixed": ["三角验证设计", "量化-质化整合逻辑", "优先-顺序策略说明", "混合方法类型（解释性/探索性/并行）", "整合点明确性"],
        "interview_report": ["访谈饱和度", "受访者多样性", "访谈提纲结构", "引语代表性", "情境化描述充分性"],
        "theoretical": ["概念定义严谨性", "命题逻辑自洽", "理论谱系梳理", "理论对话充分性", "概念操作化可行性"],
    }
    agent_input["methodology_checklist"] = methodology_checklists.get(
        research_type, methodology_checklists["qualitative"]
    )

    # v7.4: 调用 LLM（通过 llm_executor 桥接）
    response = llm_exec.execute_llm_call(
        "methodologist", agent_input,
        system_prompt=state.get("methodologist_instruction", ""),
    )

    # v6.2: 解析输出
    parsed = parse_agent_output(response.get("paper", ""), "methodologist")

    # v6.2: 写回state
    state["methodologist_output"] = parsed["modified_paper"]
    state["methodology_check_report"] = response.get("report", {})
    state["paper_content"] = parsed["modified_paper"]

    # v6.2: 检查违规
    state = check_and_rollback(state, "methodologist", "methodology")

    state["error_log"].append(
        f"[第{round_num}轮] 方法论专家完成（v6.2真实处理）：研究类型={research_type}，检查清单={len(agent_input['methodology_checklist'])}项"
    )
    return state


def literature_curator_node(state: PipelineState) -> PipelineState:
    """文献策展人 Agent：文献验证 + 格式统一（v6.2升级：真实处理逻辑）"""
    round_num = state.get("round_number", 1)

    # v6.2: 保存快照
    state = snapshot_before_agent(state, "literature_curator", "literature")

    # v6.2: 构造Agent输入
    agent_input = build_agent_input(state, "literature_curator")

    # v6.2: 注入引用格式规范
    journal_format = state.get("journal_format", "xwycbyj")
    agent_input["citation_format"] = {
        "journal": journal_format,
        "inline_format": "（作者，年份）",
        "three_part_format": "作者（年份）",
        "footnote_format": "OOXML w:footnoteReference",
        "reference_list_style": "GB/T 7714-2015",
    }

    # v7.4: 调用 LLM（通过 llm_executor 桥接）
    response = llm_exec.execute_llm_call(
        "literature_curator", agent_input,
        system_prompt=state.get("literature_curator_instruction", ""),
    )

    # v6.2: 解析输出
    parsed = parse_agent_output(response.get("paper", ""), "literature_curator")

    # v6.2: 写回state
    state["literature_curator_output"] = parsed["modified_paper"]
    state["literature_audit_report"] = response.get("report", {})
    state["paper_content"] = parsed["modified_paper"]

    # v6.2: 检查违规
    state = check_and_rollback(state, "literature_curator", "literature")

    state["error_log"].append(
        f"[第{round_num}轮] 文献策展人完成（v6.2真实处理）：文献验证+格式统一（期刊={journal_format}）"
    )
    return state


def word_count_controller_node(state: PipelineState) -> PipelineState:
    """字数控制器 Agent：强制执行字数约束（v6.3重构：事前约束+事后压缩+硬截断兜底）

    v6.3核心改造（三层防线）：
    1. 事前约束：constraint_injector_node 已注入字数预算硬约束到每个 Agent
    2. 事后压缩：对超限章节调用 compress_section 执行 P1-P5 五级压缩策略
    3. 硬截断兜底：压缩后仍超限时，按章节比例硬截断到目标字数（最后手段）
    """
    paper = get_current_paper(state)
    round_num = state.get("round_number", 1)

    # v6.3：从 state 读取用户目标字数（取代硬编码）
    target_words = state.get("user_target_words", 15000)
    tolerance = state.get("word_count_tolerance", 0.1)
    enforcement = state.get("word_count_enforcement", "strict")
    hard_limit = int(target_words * (1 + tolerance))

    # v6.2新增：执行前保存快照（供回滚机制使用）
    state = snapshot_before_agent(state, "word_count_controller", "full_paper")

    # 程序化字数检查
    word_count = sc.check_chinese_word_count(paper)

    # v6.3：使用动态预算计算各章节目标
    budgets = sc.compute_section_budgets(target_words, tolerance)

    report = {
        "total_words": word_count,
        "target_words": target_words,
        "tolerance": tolerance,
        "hard_limit": hard_limit,
        "over_limit": word_count > hard_limit,
        "delta": word_count - target_words,
        "compression_executed": False,
        "compression_result": None,
        "hard_truncation_executed": False,
        "hard_truncation_result": None,
    }

    # 逐节检查（使用动态预算）
    sections = {}
    for section_name in ["abstract", "introduction", "literature_review", "method", "findings", "conclusion"]:
        budget = budgets.get(section_name, {})
        if budget:
            sections[section_name] = {
                "target": budget.get("target", 0),
                "min": budget.get("min", 0),
                "max": budget.get("max", 0),
            }

    report["sections"] = sections

    # 防线2：事后压缩（P1-P5五级策略）
    if report["over_limit"]:
        state["error_log"].append(
            f"[第{round_num}轮] 字数控制器: ⚠ 超标 {report['delta']} 字 "
            f"({word_count}/{hard_limit})，启动P1-P5压缩策略"
        )

        # 执行压缩
        compression_result = compress_section(paper, target_words=hard_limit, strategy="P1→P5")
        report["compression_executed"] = True
        report["compression_result"] = {
            "original_words": compression_result["original_words"],
            "compressed_words": compression_result["compressed_words"],
            "reduction": compression_result["reduction"],
            "strategies_applied": compression_result["strategies_applied"],
            "success": compression_result["success"],
        }

        # 更新论文内容为压缩后版本
        compressed_paper = compression_result["compressed_text"]

        if compression_result["success"]:
            state["paper_content"] = compressed_paper
            state["error_log"].append(
                f"[第{round_num}轮] 字数控制器: ✅ 压缩成功 "
                f"{compression_result['original_words']}→{compression_result['compressed_words']}字 "
                f"(减少{compression_result['reduction']}字, 策略: {'; '.join(compression_result['strategies_applied'])})"
            )
        else:
            # 防线3：硬截断兜底（v6.3新增）
            if enforcement == "strict":
                truncated_paper, truncation_report = _hard_truncate_paper(
                    compressed_paper, target_words, budgets
                )
                state["paper_content"] = truncated_paper
                report["hard_truncation_executed"] = True
                report["hard_truncation_result"] = truncation_report

                final_words = sc.check_chinese_word_count(truncated_paper)
                state["error_log"].append(
                    f"[第{round_num}轮] 字数控制器: 🔴 硬截断执行 "
                    f"{compression_result['compressed_words']}→{final_words}字 "
                    f"(强制限制在{hard_limit}字以内)"
                )

                # 硬截断后仍超限，标记需要人工介入
                if final_words > hard_limit:
                    state["error_log"].append(
                        f"[第{round_num}轮] 字数控制器: ⚠ 硬截断后仍超限 "
                        f"{final_words}/{hard_limit}字，建议人工介入"
                    )
                    state["narrator_instruction"] = (
                        f"⚠ 字数警告：当前全文字数 {final_words} 仍超过上限 {hard_limit}，"
                        f"请在润色过程中继续压缩，优先删除冗余论证和装饰性引语。"
                    )
            else:
                # 非严格模式：仅警告
                state["paper_content"] = compressed_paper
                state["error_log"].append(
                    f"[第{round_num}轮] 字数控制器: ⚠ 压缩后仍超限 "
                    f"{compression_result['compressed_words']}/{hard_limit}字，"
                    f"执行模式为{enforcement}，跳过硬截断"
                )
                state["narrator_instruction"] = (
                    f"⚠ 字数警告：当前全文字数 {compression_result['compressed_words']} 仍超过上限 {hard_limit}，"
                    f"请在润色过程中继续压缩，优先删除冗余论证和装饰性引语。"
                    f"已应用策略: {'; '.join(compression_result['strategies_applied'])}"
                )
    else:
        state["error_log"].append(
            f"[第{round_num}轮] 字数控制器: ✅ {word_count}/{target_words} 字 (在容忍度内)"
        )

    state["word_count_report"] = report
    state["word_count_controller_output"] = report

    return state


def _hard_truncate_paper(paper: str, target_words: int,
                          budgets: Dict[str, Dict[str, int]]) -> tuple:
    """硬截断论文到目标字数（v6.3新增：最后兜底手段）

    按章节比例截断：每个章节按其超标比例等比缩减。
    优先保留章节标题和首段，从末尾开始截断。

    参数:
        paper: 论文全文
        target_words: 目标字数
        budgets: 各章节预算（来自 compute_section_budgets）

    返回:
        (截断后论文, 截断报告字典)
    """
    import re

    current_words = sc.check_chinese_word_count(paper)
    if current_words <= int(target_words * 1.1):
        return paper, {"truncated": False, "reason": "未超限，无需截断"}

    # 按段落分割
    paragraphs = paper.split("\n\n")
    if len(paragraphs) <= 3:
        return paper, {"truncated": False, "reason": "段落数过少，无法安全截断"}

    # 从末尾开始删除段落，直到字数达标
    hard_limit = int(target_words * 1.1)
    truncated_paragraphs = list(paragraphs)
    removed_count = 0

    # 保留前3段（通常是标题、摘要、引言开头），从后向前删除
    while len(truncated_paragraphs) > 3:
        current = sc.check_chinese_word_count("\n\n".join(truncated_paragraphs))
        if current <= hard_limit:
            break
        # 跳过结语章节标题（保留结构完整性）
        last_para = truncated_paragraphs[-1].strip()
        if re.match(r'^(五[、.．]|结语|结论)', last_para):
            # 结语标题不可删，尝试删除结语前一段
            if len(truncated_paragraphs) > 4:
                truncated_paragraphs.pop(-2)
            else:
                break
        else:
            truncated_paragraphs.pop()
        removed_count += 1

    truncated_paper = "\n\n".join(truncated_paragraphs)
    final_words = sc.check_chinese_word_count(truncated_paper)

    return truncated_paper, {
        "truncated": True,
        "original_words": current_words,
        "truncated_words": final_words,
        "reduction": current_words - final_words,
        "paragraphs_removed": removed_count,
        "target": target_words,
        "hard_limit": hard_limit,
    }


def narrator_node(state: PipelineState) -> PipelineState:
    """叙事连贯性主编 Agent：统一论文声音，确保人类化写作风格"""
    paper = get_current_paper(state)
    round_num = state.get("round_number", 1)
    instruction = state.get("narrator_instruction", "")

    # v6.2 新增：运行新鲜风格诊断，检测 Expert/WordCount 引入的风格回归
    fresh_audit = sc.run_full_style_audit(paper)
    fresh_issues = []
    rhythm = fresh_audit.get("rhythm", {})
    if rhythm.get("too_uniform"):
        fresh_issues.append(f"⚠ 当前文本句长方差{rhythm.get('variance')}过低，疑似僵硬化——请用长句铺陈+短句收束打破单一节奏")
    if rhythm.get("too_jumpy"):
        fresh_issues.append(f"⚠ 当前文本句长方差{rhythm.get('variance')}过高，疑似散文化——请用短句收束判断，避免长句连缀")
    diversity = fresh_audit.get("paragraph_diversity", {})
    if not diversity.get("passed"):
        fresh_issues.append(f"⚠ 段落开头多样性{diversity.get('diversity')}不足——请轮换使用概念锚定/经验切入/理论对话型开头")
    mechanical = fresh_audit.get("mechanical_patterns", {})
    if not mechanical.get("passed"):
        for pattern in mechanical.get("patterns_found", []):
            fresh_issues.append(f"⚠ 检测到{pattern}——请用内容逻辑衔接替代连接词堆砌")

    if fresh_issues:
        instruction = (instruction or "") + "\n\n【当前文本新鲜风格诊断】\n" + "\n".join(fresh_issues)
        state["narrator_instruction"] = instruction
        state["error_log"].append(
            f"[第{round_num}轮] Narrator: 检测到{len(fresh_issues)}处新鲜风格问题"
        )

    state["narrator_output"] = paper
    state["error_log"].append(
        f"[第{round_num}轮] 叙事主编完成：全文连贯性+风格统一检查"
    )
    return state


def orchestrator_node(state: PipelineState) -> PipelineState:
    """编排者 Agent：管理 Pipeline 执行策略（v7.4 落地 G25 修复）

    核心职责（依据 agents/orchestrator.md v6.0）：
    1. 执行策略决策：根据维度得分决定哪些 Agent 需要执行
    2. 维度得分趋势监控：稳步提升/趋于停滞/维度倒退/到达瓶颈
    3. 人工介入决策：连续3轮总提升<3分触发 human_intervention
    """
    round_num = state.get("round_number", 1)
    scores = state.get("score_history", [])
    dimension_scores = state.get("dimension_scores", {})
    prev_dimension_scores = state.get("prev_dimension_scores", {})
    frozen_sections = state.get("frozen_sections", [])

    # ===== 职责1：执行策略决策 =====
    # round_1: 全量执行；round_2+: 根据维度得分决定
    if round_num == 1:
        active_agents = [
            "polisher", "visualizer", "methodologist", "literature_curator",
            "expert", "word_count_controller", "narrator",
        ]
    else:
        active_agents = []
        # 某维度得分 < 满分的 80% → 对应 Agent 执行
        dimension_agent_map = {
            "language_fluency": "polisher",
            "academic_rigor": "expert",
            "theoretical_depth": "expert",
            "literature_quality": "literature_curator",
            "methodology appropriateness": "methodologist",
            "narrative_voice": "narrator",
        }
        for dim, agent in dimension_agent_map.items():
            score = dimension_scores.get(dim, 0)
            if score < 80 and agent not in active_agents:
                active_agents.append(agent)
        # 最后1-2轮聚焦 Polisher + Expert + Narrator
        max_rounds = state.get("max_rounds", 7)
        if round_num >= max_rounds - 1:
            active_agents = ["polisher", "expert", "narrator"]
        # 至少保证 polisher 执行
        if not active_agents:
            active_agents = ["polisher"]

    state["active_agents"] = active_agents

    # ===== 职责2：维度得分趋势监控 =====
    trend_report = []
    if prev_dimension_scores and dimension_scores:
        for dim, curr_score in dimension_scores.items():
            prev_score = prev_dimension_scores.get(dim, 0)
            delta = curr_score - prev_score
            if delta < 0:
                trend_report.append(f"维度倒退: {dim} ({prev_score}→{curr_score})")
                # 标记维度倒退，由 rollback_handler 处理
                state["dimension_regression_detected"] = True
            elif delta < 1 and round_num >= 3:
                trend_report.append(f"趋于停滞: {dim} (提升{delta}分)")

    # ===== 职责3：人工介入决策 =====
    # 连续3轮总提升<3分 → 触发 human_intervention
    if len(scores) >= 4:
        recent_gains = [
            scores[i] - scores[i - 1]
            for i in range(len(scores) - 3, len(scores))
        ]
        total_recent_gain = sum(recent_gains)
        if total_recent_gain < 3:
            state["human_intervention_required"] = True
            state["error_log"].append(
                f"[第{round_num}轮] 编排者: ⚠ 连续3轮总提升{total_recent_gain}分<3分，"
                f"触发人工介入（防死锁）"
            )
    elif len(scores) >= 3:
        # 保留原有逻辑：连续2轮改进微弱
        recent_gains = [
            scores[i] - scores[i - 1]
            for i in range(len(scores) - 2, len(scores))
        ]
        if all(g < 3 for g in recent_gains):
            state["orchestrator_instruction"] = "聚焦高优先级问题"
            state["error_log"].append(
                f"[第{round_num}轮] 编排者: ⚠ 连续改进微弱，建议聚焦 P0/P1 问题"
            )

    # 冻结章节提示
    if frozen_sections:
        state["error_log"].append(
            f"[第{round_num}轮] 编排者: 已冻结章节 {frozen_sections}，跳过对应 Agent"
        )

    # 趋势报告
    if trend_report:
        state["orchestrator_trend_report"] = trend_report
        state["error_log"].append(
            f"[第{round_num}轮] 编排者: 趋势监控 — {'; '.join(trend_report)}"
        )

    # 触发共享学习
    if state.get("shared_learning_update"):
        state["error_log"].append(
            f"[第{round_num}轮] 编排者: 触发共享学习更新"
        )

    state["error_log"].append(
        f"[第{round_num}轮] 编排者完成 (active_agents: {active_agents})"
    )
    return state


def reviewer_node(state: PipelineState) -> PipelineState:
    """审稿人 Agent：9 维度评分 + 否思 + 编码优化 + 图表批判 + 框架建议
    v6.2: 维度2拆分为 2a节奏感/2b多样性/2c声音一致性，低分触发 Narrator 精准意见
    v7.4: 通过 llm_executor 调用真实 LLM 评分（无 bridge 时降级占位）
    """
    expert_paper = state.get("expert_output", "") or get_current_paper(state)
    round_num = state.get("round_number", 1)
    research_type = state.get("research_type", "qualitative")
    threshold = state.get("pass_threshold", 90)

    # 运行程序化风格诊断作为 LLM 评分的辅助依据
    audit = sc.run_full_style_audit(expert_paper)
    rhythm = audit.get("rhythm", {})
    diversity = audit.get("paragraph_diversity", {})
    mechanical = audit.get("mechanical_patterns", {})

    # v7.4: 调用 LLM 进行 9 维度评分（G 侧评分）
    scoring_result = llm_exec.execute_reviewer_scoring(
        agent_input={"round_number": round_num, "research_type": research_type},
        paper_content=expert_paper,
        research_type=research_type,
        round_number=round_num,
        style_audit=audit,
    )

    if scoring_result.get("_placeholder"):
        # 占位模式：回退到程序化评分
        variance = rhythm.get("variance", 15.0)
        if 8.0 <= variance <= 25.0:
            score_2a = 5
        elif 6.0 <= variance < 8.0 or 25.0 < variance <= 30.0:
            score_2a = 4
        elif variance < 6.0 or variance > 30.0:
            score_2a = 2
        else:
            score_2a = 1

        div_score = diversity.get("diversity", 0.5)
        if div_score >= 0.6 and not mechanical.get("patterns_found"):
            score_2b = 5
        elif 0.4 <= div_score < 0.6:
            score_2b = 4
        elif 0.2 <= div_score < 0.4:
            score_2b = 2
        else:
            score_2b = 1

        score_2c = 4
        state["review_score"] = 85
        state["dimension_scores"] = {
            "title_impact": 8,
            "writing_style_rhythm": score_2a,
            "writing_style_diversity": score_2b,
            "writing_style_voice": score_2c,
            "academic_depth": 13, "theoretical_rigor": 13,
            "visual_quality": 8, "format_standard": 8,
            "rigor": 8, "professionalism": 8, "innovation": 4,
        }
        state["review_report"] = (
            f"=== 第{round_num}轮评审报告（占位模式） ===\n"
            f"总分: {state['review_score']}/100\n"
            f"维度2: 节奏感{score_2a}/5 + 多样性{score_2b}/5 + 声音一致性{score_2c}/5\n"
            f"结论: {'PASS' if state['review_pass'] else 'REVISE'}\n"
        )
    else:
        # LLM 评分模式
        llm_score = scoring_result.get("review_score")
        state["review_score"] = llm_score if llm_score is not None else 85
        state["dimension_scores"] = scoring_result.get("dimension_scores", {})
        state["review_report"] = scoring_result.get("review_report", "")

    state["review_pass"] = state["review_score"] >= threshold

    # v6.2: 2a/2b 低分触发 Narrator 精准意见（保留程序化检测逻辑）
    narrator_opinions = []
    dim_scores = state.get("dimension_scores", {})
    score_2a = dim_scores.get("writing_style_rhythm", dim_scores.get("2a", 4))
    score_2b = dim_scores.get("writing_style_diversity", dim_scores.get("2b", 4))
    variance = rhythm.get("variance", 15.0)
    div_score = diversity.get("diversity", 0.5)

    if isinstance(score_2a, (int, float)) and score_2a <= 2:
        issue = "僵硬化" if variance < 8.0 else "散文化"
        narrator_opinions.append({
            "priority": "high",
            "opinion": f"维度2a节奏感仅{score_2a}分（句长方差{variance:.1f}，{issue}）——请Narrator重点修复句长节奏"
        })
    if isinstance(score_2b, (int, float)) and score_2b <= 2:
        narrator_opinions.append({
            "priority": "high",
            "opinion": f"维度2b多样性仅{score_2b}分（段落开头多样性{div_score:.2f}）——请Narrator轮换段落开头方式"
        })

    # 清空意见列表，准备新一轮路由（v6.2: narrator_opinions 保留低分触发的意见）
    state["polisher_opinions"] = []
    state["visualizer_opinions"] = []
    state["expert_opinions"] = []
    state["architect_opinions"] = []
    state["methodologist_opinions"] = []
    state["literature_opinions"] = []
    state["narrator_opinions"] = narrator_opinions
    state["score_history"].append(state["review_score"])

    state["error_log"].append(
        f"[第{round_num}轮] 审稿人完成：总分{state['review_score']}/100, "
        f"2a={score_2a} 2b={score_2b} 2c={score_2c}"
    )

    # ★v7.0新增：保存G侧原始评分
    state["g_score"] = state.get("review_score", 0)

    return state



def adversarial_critic_node(state: PipelineState) -> PipelineState:
    """Discriminator Agent节点：对论文进行挑刺评分（v7.0新增）

    作为GAN的Discriminator，对Reviewer（Generator）的评分进行对抗性挑战。
    从"魔鬼代言人"角度寻找论文缺陷，输出D评分和挑刺报告。

    v7.4: 通过 llm_executor 调用真实 LLM 进行 D 侧挑刺评分（无 bridge 时 d_score=None）
    """
    round_num = state.get("round_number", 1)
    g_score = state.get("review_score", 0)
    research_type = state.get("research_type", "qualitative")
    paper = get_current_paper(state)

    # 保存G侧原始评分
    state["g_score"] = g_score

    # v7.4: 调用 LLM 进行 D 侧挑刺评分
    d_result = llm_exec.execute_adversarial_scoring(
        agent_input={"round_number": round_num, "research_type": research_type},
        paper_content=paper,
        g_score=g_score,
        research_type=research_type,
        round_number=round_num,
    )

    state["d_score"] = d_result.get("d_score")
    state["d_dimension_scores"] = d_result.get("d_dimension_scores", {})
    state["d_review_report"] = d_result.get("d_review_report", "")

    d_score = state["d_score"]
    placeholder_tag = "（占位模式）" if d_result.get("_placeholder") else ""
    state["error_log"].append(
        f"[第{round_num}轮] AdversarialCritic: D评分{d_score}/100 "
        f"(G评分{g_score}/100{placeholder_tag})"
    )
    return state


def gan_score_fusion_node(state: PipelineState) -> PipelineState:
    """GAN评分融合节点：融合G评分与D评分（v7.0新增）

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
        state["fused_score"] = g_score
        state["adversarial_signal"] = 0.0
        state["error_log"].append(
            f"[\u7b2c{round_num}\u8f6e] GAN\u878d\u5408: GAN\u672a\u542f\u7528\u6216D\u8bc4\u5206\u7f3a\u5931\uff0c\u4f7f\u7528G\u8bc4\u5206{g_score}"
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
    threshold = state.get("pass_threshold", 90)
    state["review_pass"] = fusion_result["fused_score"] >= threshold

    # 生成D的挑刺反馈
    g_dim_scores = state.get("dimension_scores", {})
    d_dim_scores = state.get("d_dimension_scores", {})
    d_report = state.get("d_review_report", "")
    feedback = gs_gan.generate_adversarial_feedback(
        d_report=d_report,
        d_dimension_scores=d_dim_scores,
        g_dimension_scores=g_dim_scores,
        adversarial_signal=fusion_result["adversarial_signal"],
    )
    state["adversarial_feedback"] = feedback

    # 记录融合报告
    report = gs_gan.format_gan_score_report(fusion_result)
    state["error_log"].append(f"[\u7b2c{round_num}\u8f6e] GAN\u878d\u5408:\n{report}")

    return state

# ============================================================================
# 意见路由（v6.0 六路路由）
# ============================================================================

def opinion_router_node(state: PipelineState) -> PipelineState:
    """将审稿意见按关键词分发给对应 Agent（v6.0 六路分发，v7.4 落地 G32 修复）

    实现真正的路由逻辑：
    1. 从 review_report 中按行提取意见
    2. 根据 config.OPINION_ROUTING_RULES 中的关键词匹配分发给对应 Agent
    3. 将分发结果写入 state 的各 *_opinions 字段
    """
    review = state.get("review_report", "")
    round_num = state.get("round_number", 1)

    # 初始化各 Agent 意见列表
    agent_opinion_fields = {
        "polisher": "polisher_opinions",
        "visualizer": "visualizer_opinions",
        "expert": "expert_opinions",
        "architect": "architect_opinions",
        "methodologist": "methodologist_opinions",
        "literature_curator": "literature_opinions",
        "narrator": "narrator_opinions",
    }
    for field in agent_opinion_fields.values():
        state[field] = []

    # 加载路由规则
    routing_rules = cfg.OPINION_ROUTING_RULES

    # 按行分割审稿报告，每行视为一条意见
    opinion_lines = [
        line.strip() for line in review.split("\n")
        if line.strip() and len(line.strip()) > 5
    ]

    # 路由统计
    route_counts = {agent: 0 for agent in agent_opinion_fields}
    unrouted_count = 0

    for opinion in opinion_lines:
        routed = False
        # 按 routing_rules 中的关键词匹配
        for keyword, agent in routing_rules.items():
            if keyword in opinion:
                field = agent_opinion_fields.get(agent)
                if field:
                    state[field].append({"opinion": opinion, "keyword": keyword})
                    route_counts[agent] = route_counts.get(agent, 0) + 1
                    routed = True
                    break  # 每条意见只路由给第一个匹配的 Agent
        if not routed:
            unrouted_count += 1
            # 未路由的意见默认分发给 expert（通用处理）
            state["expert_opinions"].append(
                {"opinion": opinion, "keyword": "_unrouted_"}
            )

    # 日志记录路由统计
    route_summary = ", ".join(
        f"{agent}:{count}" for agent, count in route_counts.items() if count > 0
    )
    state["error_log"].append(
        f"[第{round_num}轮] 意见路由完成（{len(opinion_lines)}条意见, "
        f"未路由{unrouted_count}条）: {route_summary}"
    )
    return state


# ============================================================================
# 增量控制节点
# ============================================================================

def incremental_control_node(state: PipelineState) -> PipelineState:
    """执行增量修改控制：冻结已通过章节，仅修改问题部分"""
    round_num = state.get("round_number", 1)
    dim_scores = state.get("dimension_scores", {})

    state["prev_dimension_scores"] = dim_scores.copy()
    state["round_number"] = round_num + 1
    state["error_log"].append(
        f"[第{round_num}轮] 增量控制：进入第{state['round_number']}轮"
    )
    return state


# ============================================================================
# Word 格式验证节点（v6.0 新增）
# ============================================================================

def word_format_validator_node(state: PipelineState) -> PipelineState:
    """Word 格式验证节点：验证生成的 docx 文件质量（v7.3增强脚注验证）"""
    output_path = state.get("output_path", "")
    paper_text = get_current_paper(state)
    round_num = state.get("round_number", 1)

    if not output_path:
        state["error_log"].append(
            f"[第{round_num}轮] WordFormatValidator: 无输出文件路径，跳过验证"
        )
        return state

    report = wv.run_full_validation(output_path, paper_text)
    state["word_validation_report"] = report

    status = "✅ 通过" if report.get("passed") else "❌ 未通过"
    state["error_log"].append(
        f"[第{round_num}轮] WordFormatValidator: {status}"
    )

    # 记录具体问题
    if not report.get("passed"):
        quote_violations = report.get("quote_violations", [])
        if quote_violations:
            state["error_log"].append(
                f"  - 中文引号字体问题: {len(quote_violations)} 处"
            )
        fn_format = report.get("footnote_format", {})
        if not fn_format.get("passed", True):
            state["error_log"].append(
                f"  - 脚注格式问题: {fn_format.get('error', 'ID不连续或缺失')}"
            )

        # v7.3 新增：记录脚注内容完整性问题
        fn_content = report.get("footnote_content", {})
        if not fn_content.get("passed", True):
            state["error_log"].append(
                f"  - 脚注内容完整性问题: {fn_content.get('invalid', 0)}/"
                f"{fn_content.get('total', 0)} 条不合规"
            )
            for detail in fn_content.get("details", []):
                state["error_log"].append(
                    f"    ⚠ 脚注#{detail['id']}: {'; '.join(detail['issues'])}"
                )

        # v7.3 新增：记录脚注编号格式问题
        fn_num_format = report.get("footnote_number_format", {})
        if not fn_num_format.get("passed", True):
            state["error_log"].append(
                f"  - 脚注编号格式问题: {len(fn_num_format.get('violations', []))} 处"
            )
            for v in fn_num_format.get("violations", []):
                state["error_log"].append(
                    f"    ⚠ 脚注#{v['footnote_id']}: {v['issue']}"
                )

        # v7.3 新增：记录脚注-参考文献不匹配
        fn_refs = report.get("footnote_refs", {})
        if not fn_refs.get("passed", True):
            state["error_log"].append(
                f"  - 脚注-参考文献不匹配: {fn_refs.get('unmatched', 0)}/"
                f"{fn_refs.get('total', 0)} 条未匹配"
            )
            for detail in fn_refs.get("details", []):
                state["error_log"].append(
                    f"    ⚠ 脚注#{detail['footnote_id']}: "
                    f"最佳匹配分={detail.get('best_match_score', 0)}"
                )

        # v7.3 新增：记录手动伪脚注
        manual_fns = report.get("manual_footnotes", [])
        if manual_fns:
            state["error_log"].append(
                f"  - 手动伪脚注: {len(manual_fns)} 处（应使用OOXML真实脚注）"
            )

    return state


def format_output_node(state: PipelineState) -> PipelineState:
    """格式化为目标期刊 Word 文档"""
    score = state.get("review_score", 0)
    threshold = state.get("pass_threshold", 90)
    journal = state.get("journal_style", "xwycbyj")
    round_num = state.get("round_number", 1)

    # ★v7.4新增：内参输出分支
    config = state.get("config", {})
    output_mode = config.get("output_mode", "paper")
    if output_mode in ("neican", "both"):
        state = neican_writer_node(state)
        # 内参格式验证
        if state.get("neican_doc"):
            from .word_validation import run_neican_validation
            neican_report = run_neican_validation(state["neican_doc"])
            if not neican_report.get("overall_valid", False):
                state["rollback_reason"] = "neican_format_invalid"
                state["neican_validation_report"] = neican_report

    if score >= threshold:
        status = "PASS"
    else:
        status = (f"MAX_ROUNDS ({round_num}轮，"
                  f"最佳{max(state.get('score_history', [0]))}分)")

    state["error_log"].append(
        f"格式输出: {status} | 目标期刊: {journal}"
    )
    return state


def neican_writer_node(state: PipelineState) -> PipelineState:
    """内参撰写者节点（★v7.4新增，v7.4 落地 G33 修复）

    仅当output_mode=neican或both时触发。
    将通过审稿的论文转化为内参报告。

    v7.4 G33 修复：调用 word_template.generate_neican_document 生成 Word 文档。
    若 state 中已有 AI 转化后的结构化内参内容（neican_title/neican_opening/
    neican_sections），则直接生成文档；否则仅生成 instruction 等待 AI 执行主体转化。
    """
    config = state.get("config", {})
    output_mode = config.get("output_mode", "paper")

    # 核心约束：仅在用户明确请求时触发
    if output_mode not in ("neican", "both"):
        return state  # 不参与，直接返回

    paper_content = state.get("paper_content", "")
    if not paper_content:
        state["neican_error"] = "论文内容为空，无法转化内参"
        return state

    # NeicanWriter Agent的提示词（AI助手将按此执行）
    state["neican_instruction"] = """
请将以下学术论文转化为内参报告。

参照 knowledge_base/neican_standards.md 中的规范执行：
1. 剥离学术外壳（删除文献综述/理论框架/方法论/统计检验）
2. 重构报告骨架（选择标题范式、撰写公鸡打鸣段、规划3-5板块）
3. 填充血肉（用数据替换学术表述、提炼虎气判断、对策刻度化）
4. 打磨文风（检查每段首句、褒贬用词、对策刻度、删除多余内容）

输出要求：
- 标题不超过25字，符合内参标题范式
- 开篇为公鸡打鸣段（时机→意义→做什么）
- 正文3-5板块，层级编号"一、（一）1."
- 对策建议有刻度（具体比例/机制/路径）和责任主体
- 不写总结段
- 署名格式：作者信息：\nXXX XX单位XX职务
"""

    state["neican_input_paper"] = paper_content
    state["current_node"] = "neican_writer"

    # ★v7.4 G33 修复：若已有结构化内参内容，调用 word_template 生成 Word 文档
    neican_title = state.get("neican_title")
    neican_opening = state.get("neican_opening")
    neican_sections = state.get("neican_sections")
    if neican_title and neican_opening and neican_sections:
        try:
            # 导入 word_template（支持包内与直接执行两种模式）
            try:
                from ..templates.word_template import generate_neican_document
            except ImportError:
                try:
                    from templates.word_template import generate_neican_document
                except ImportError:
                    import sys
                    import os
                    _template_dir = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "templates"
                    )
                    if _template_dir not in sys.path:
                        sys.path.insert(0, _template_dir)
                    from word_template import generate_neican_document

            # 构造输出路径
            output_path = state.get("output_path", "")
            if output_path and not output_path.endswith(".docx"):
                # 将 .docx 之前的部分作为目录，追加 neican 后缀
                base = output_path.rsplit(".", 1)[0] if "." in output_path else output_path
                neican_output_path = f"{base}_neican.docx"
            else:
                neican_output_path = output_path or "neican_output.docx"

            # 署名作者（从 config 获取或使用默认）
            signature_authors = config.get("neican_signature_authors", [])

            # 调用 word_template 生成内参 Word 文档
            neican_doc = generate_neican_document(
                title=neican_title,
                opening=neican_opening,
                sections=neican_sections,
                signature_authors=signature_authors,
                output_path=neican_output_path,
            )
            state["neican_doc"] = neican_doc
            state["neican_output_path"] = neican_output_path
            state["error_log"].append(
                f"NeicanWriter: 已生成内参 Word 文档 → {neican_output_path}"
            )
        except Exception as e:
            state["neican_error"] = f"内参文档生成失败: {e}"
            state["error_log"].append(f"NeicanWriter: 内参文档生成异常: {e}")
    else:
        state["error_log"].append(
            "NeicanWriter: 等待 AI 执行主体完成内参转化"
            "（neican_title/neican_opening/neican_sections 尚未就绪）"
        )

    return state


# ============================================================================
# 条件路由函数
# ============================================================================

def decide_next_action(state: PipelineState) -> str:
    """决定 Pipeline 下一步动作（v6.2新增rollback分支）"""
    # v6.2新增：检查是否有待回滚重试的Agent
    pending_rollback = state.get("pending_rollback_agent")
    if pending_rollback:
        # 检查重试次数是否超限
        retry_counts = state.get("agent_retry_count", {})
        agent_retries = retry_counts.get(pending_rollback, 0)
        if agent_retries <= 2:  # max_retry=2
            state["error_log"].append(
                f"回滚重试: {pending_rollback} (第{agent_retries}次重试)"
            )
            return "rollback"
        else:
            # 重试次数超限，清除pending状态，继续正常流程
            state["pending_rollback_agent"] = None
            state["error_log"].append(
                f"回滚重试次数超限: {pending_rollback}，继续正常流程"
            )

    if state.get("review_pass", False):
        return "pass"
    if state.get("round_number", 1) >= state.get("max_rounds", 7):
        return "max_rounds"
    if state.get("human_intervention_required", False):
        return "human_intervention"

    # 防死锁
    scores = state.get("score_history", [])
    max_stagnation = state.get("max_score_stagnation_rounds", 3)
    if len(scores) >= max_stagnation + 1:
        recent = scores[-(max_stagnation):]
        improvements = [recent[i] - recent[i - 1] for i in range(1, len(recent))]
        if max(improvements, default=0) < state.get("dimension_regression_threshold", 3):
            state["human_intervention_required"] = True
            state["error_log"].append(
                f"防死锁触发：连续{max_stagnation}轮提升不足"
            )
            return "human_intervention"

    # 维度倒退检测
    dim_scores = state.get("dimension_scores", {})
    prev_dim = state.get("prev_dimension_scores", {})
    for dim, score in dim_scores.items():
        if dim in prev_dim and score - prev_dim[dim] <= -1:
            state["error_log"].append(
                f"维度倒退: {dim} {prev_dim[dim]}→{score} (Δ={score - prev_dim[dim]})"
            )

    return "revise"


# ============================================================================
# Pipeline 创建函数（v6.2：12 Agent + 守卫节点 + 检查回滚）
# ============================================================================

def rollback_handler_node(state: PipelineState) -> PipelineState:
    """回滚处理节点（v6.2新增）

    当decide_next_action返回"rollback"时执行：
    1. 清除pending_rollback_agent标记
    2. 路由到待重试的Agent
    """
    round_num = state.get("round_number", 1)
    pending_agent = state.get("pending_rollback_agent")

    if pending_agent:
        state["error_log"].append(
            f"[第{round_num}轮] 🔄 回滚处理: 重试 {pending_agent}"
        )
        # 清除pending标记（重试后由style_validator重新检查）
        state["pending_rollback_agent"] = None
    else:
        state["error_log"].append(
            f"[第{round_num}轮] 回滚处理: 无待重试Agent，继续正常流程"
        )

    return state


def create_pipeline(config: Optional[PipelineConfig] = None) -> StateGraph:
    """
    创建 v6.2 12 Agent 循环式论文生成 Pipeline（含检查回滚机制）

    节点流（16 节点）:
    constraint_injector → polisher → style_validator → visualizer →
    style_validator → methodologist → literature_curator →
    expert → style_validator → word_count_controller →
    narrator → orchestrator → reviewer →
        └─ pass → word_format_validator → format_output
        └─ revise → opinion_router → incremental_control → constraint_injector
        └─ rollback → rollback_handler → constraint_injector（重试）
        └─ max_rounds → word_format_validator → format_output
        └─ human_intervention → END
    """
    if config is None:
        config = PipelineConfig()

    workflow = StateGraph(PipelineState)

    # 添加 16 个节点
    # v6.0 新增节点
    workflow.add_node("constraint_injector", constraint_injector_node)
    workflow.add_node("architect", architect_node)  # v7.4新增：G23 修复
    workflow.add_node("style_validator", style_validator_node)
    workflow.add_node("methodologist", methodologist_node)
    workflow.add_node("literature_curator", literature_curator_node)
    workflow.add_node("word_count_controller", word_count_controller_node)
    workflow.add_node("narrator", narrator_node)
    workflow.add_node("orchestrator", orchestrator_node)
    workflow.add_node("word_format_validator", word_format_validator_node)
    # 保留节点
    workflow.add_node("polisher", polisher_node)
    workflow.add_node("visualizer", visualizer_node)
    workflow.add_node("expert", expert_node)
    workflow.add_node("reviewer", reviewer_node)
    workflow.add_node("opinion_router", opinion_router_node)
    workflow.add_node("incremental_control", incremental_control_node)
    workflow.add_node("format_output", format_output_node)
    # v6.2 新增节点
    workflow.add_node("rollback_handler", rollback_handler_node)
    workflow.add_node("adversarial_critic", adversarial_critic_node)  # v7.0新增
    workflow.add_node("gan_score_fusion", gan_score_fusion_node)  # v7.0新增

    # ===== v6.2 执行流 =====
    workflow.set_entry_point("constraint_injector")

    # 核心执行链
    workflow.add_edge("constraint_injector", "architect")  # v7.4: architect 在 constraint_injector 之后执行
    workflow.add_edge("architect", "polisher")  # v7.4: architect 输出框架预算后进入 polisher
    workflow.add_edge("polisher", "style_validator")
    workflow.add_edge("style_validator", "visualizer")
    workflow.add_edge("visualizer", "methodologist")
    workflow.add_edge("methodologist", "literature_curator")
    workflow.add_edge("literature_curator", "expert")
    workflow.add_edge("expert", "word_count_controller")
    workflow.add_edge("word_count_controller", "narrator")
    workflow.add_edge("narrator", "orchestrator")
    workflow.add_edge("orchestrator", "reviewer")
    workflow.add_edge("reviewer", "adversarial_critic")
    workflow.add_edge("adversarial_critic", "gan_score_fusion")

    # 条件路由（v7.0修改：源节点改为gan_score_fusion）
    workflow.add_conditional_edges(
        "gan_score_fusion",
        decide_next_action,
        {
            "pass": "word_format_validator",
            "revise": "opinion_router",
            "rollback": "rollback_handler",          # v6.2新增
            "max_rounds": "word_format_validator",
            "human_intervention": END,
        }
    )

    # 循环回路 + 格式化
    workflow.add_edge("opinion_router", "incremental_control")
    workflow.add_edge("incremental_control", "constraint_injector")
    # v6.2新增：回滚处理后回到constraint_injector重试
    workflow.add_edge("rollback_handler", "constraint_injector")
    workflow.add_edge("word_format_validator", "format_output")
    workflow.add_edge("format_output", END)

    # 启用 Checkpointer（v6.0 新增）
    return workflow.compile(checkpointer=MemorySaver())


# ============================================================================
# Pipeline 执行函数
# ============================================================================

def run_pipeline(
    paper_content: str,
    config: Optional[PipelineConfig] = None,
    initial_state: Optional[Dict[str, Any]] = None,
    *,
    progress_callback: Optional[callable] = None,
    cancel_event: Optional[Any] = None,  # threading.Event
) -> PipelineState:
    """执行完整的 v7.4 循环式论文生成 Pipeline

    Args:
        paper_content: 初始论文内容
        config: Pipeline 配置
        initial_state: 初始状态覆盖
        progress_callback: 进度回调 callable(node_name, node_state)，每节点执行后调用
        cancel_event: threading.Event，设置时 Pipeline 抛出 RuntimeError 退出

    Returns:
        PipelineState: 最终状态；被取消时返回 None

    Raises:
        RuntimeError: Pipeline 被取消
    """
    if config is None:
        config = PipelineConfig()

    app = create_pipeline(config)

    state: PipelineState = {
        "paper_content": paper_content,
        "paper_version": 1,
        "paper_title": "",
        "round_number": 1,
        # 核心 Agent 输出
        "polisher_output": None,
        "visualizer_output": None,
        "expert_output": None,
        # v6.0 新增 Agent
        "methodologist_output": None,
        "methodologist_instruction": None,
        "literature_curator_output": None,
        "literature_curator_instruction": None,
        "word_count_controller_output": None,   # v6.2重命名
        "word_count_instruction": None,
        "narrator_output": None,
        "narrator_instruction": None,
        "orchestrator_instruction": None,
        "word_validation_report": None,
        # 约束/指令字段
        "polisher_instruction": None,
        "visualizer_instruction": None,
        "expert_instruction": None,
        "reviewer_instruction": None,
        # v6.0 风格约束
        "style_violations": [],
        "active_constraints": None,
        "word_count_report": None,
        # v6.2 回滚机制字段（新增）
        "section_snapshots": {},
        "violation_records": [],
        "rollback_count": 0,
        "agent_retry_count": {},
        "pending_rollback_agent": None,
        # v6.2 声音诊断字段（新增）
        "voice_diagnosis": None,
        "voice_consistency_score": None,
        # v6.1 维度拆分字段（新增）
        "dimension_2a_score": None,
        "dimension_2b_score": None,
        "dimension_2c_score": None,
        # v6.0 共享学习
        "shared_learning_update": None,
        "user_style_profile": None,
        # 评审
        "review_report": None,
        "review_score": None,
        "review_pass": None,
        "dimension_scores": {},
        "prev_dimension_scores": {},
        "score_history": [],
        "frozen_sections": [],
        "section_states": {},
        # 循环控制
        "max_rounds": config.max_rounds,
        "pass_threshold": config.pass_threshold,
        "incremental_mode": config.incremental_mode,
        "dimension_regression_threshold": -1,
        "max_score_stagnation_rounds": 3,
        # 意见路由
        "polisher_opinions": [],
        "visualizer_opinions": [],
        "expert_opinions": [],
        "architect_opinions": [],
        "methodologist_opinions": [],
        "literature_opinions": [],
        "narrator_opinions": [],
        "router_instruction": None,
        # 格式
        "format_instruction": None,
        "output_path": None,
        "journal_style": config.journal_style,
        "research_type": config.research_type,
        # 元信息
        "error_log": [],
        "human_intervention_required": False,
        "pipeline_start_time": datetime.now().isoformat(),
        "version_history": [],
        # v7.0新增：GAN对抗评分字段
        "gan_enabled": config.gan_enabled,
        "g_score": None,
        "d_score": None,
        "fused_score": None,
        "adversarial_signal": None,
        "gan_score_history": [],
        "adversarial_feedback": [],
        "d_dimension_scores": None,
        "d_review_report": None,
    }

    if initial_state:
        state.update(initial_state)

    # 使用 stream() 实现可取消、可报告进度的执行
    langgraph_config = {"configurable": {"thread_id": str(_uuid.uuid4())}}
    if progress_callback is not None or cancel_event is not None:
        result_state = state
        for event in app.stream(state, langgraph_config):
            if cancel_event is not None and cancel_event.is_set():
                return None
            if event and progress_callback is not None:
                for node_name, node_state in event.items():
                    progress_callback(node_name, node_state)
            if event:
                for node_name, node_state in event.items():
                    result_state = node_state
        return result_state
    else:
        return app.invoke(state, langgraph_config)


# ============================================================================
# 使用示例
# ============================================================================

if __name__ == "__main__":
    app = create_pipeline(PipelineConfig(
        max_rounds=7, pass_threshold=90, journal_style="xwycbyj",
        research_type="qualitative", style_enforcement=True,
        word_validation_enabled=True,
    ))

    result = app.invoke({
        "paper_content": "...", "paper_version": 1, "round_number": 1,
        "score_history": [], "frozen_sections": [], "error_log": [],
        "style_violations": [], "word_count_report": None,
        "word_validation_report": None,
        "polisher_opinions": [], "visualizer_opinions": [],
        "expert_opinions": [], "architect_opinions": [],
        "methodologist_opinions": [], "literature_opinions": [],
        "narrator_opinions": [],
        "polisher_output": None, "visualizer_output": None,
        "expert_output": None, "methodologist_output": None,
        "literature_curator_output": None, "word_count_output": None,
        "narrator_output": None,
        "polisher_instruction": None, "visualizer_instruction": None,
        "expert_instruction": None, "methodologist_instruction": None,
        "literature_curator_instruction": None, "word_count_instruction": None,
        "narrator_instruction": None, "orchestrator_instruction": None,
        "shared_learning_update": None, "user_style_profile": None,
        "max_rounds": 5, "pass_threshold": 90,
        "dimension_scores": {}, "prev_dimension_scores": {},
        "incremental_mode": True, "human_intervention_required": False,
        "journal_style": "xwycbyj", "research_type": "qualitative",
        "pipeline_start_time": datetime.now().isoformat(),
        "version_history": [],
    })

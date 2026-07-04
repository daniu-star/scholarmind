"""
ScholarMind 枚举常量
Agent类型、图表类型、技能分类等枚举定义
"""
from __future__ import annotations

from enum import Enum


class AgentType(str, Enum):
    """Agent 类型"""
    RESEARCHER = "researcher"
    REVIEWER = "reviewer"
    ARCHITECT = "architect"
    SYNTHESIZER = "synthesizer"
    POLISHER = "polisher"
    CUSTOM = "custom"


class ChartType(str, Enum):
    """图表类型（12种 Origin 风格高级图表）"""
    RIBBON = "ribbon"
    VIOLIN = "violin"
    ALLUVIAL = "alluvial"
    BUBBLE_KDE = "bubble_kde"
    GRADIENT_AREA = "gradient_area"
    SURFACE3D = "surface3d"
    PARALLEL = "parallel"
    CONTOUR = "contour"
    SWARM = "swarm"
    SCATTER_DENSITY = "scatter_density"
    CHORD = "chord"
    HEATMAP_DENDRO = "heatmap_dendro"


class SkillCategory(str, Enum):
    """技能分类"""
    CORE = "core"           # 核心技能
    ADVANCED = "advanced"   # 高级技能
    UTILITY = "utility"     # 实用工具
    AUXILIARY = "auxiliary" # 辅助技能
    CUSTOM = "custom"       # 自定义技能


class MessageRole(str, Enum):
    """对话角色"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Discipline(str, Enum):
    """学科领域"""
    ENGINEERING = "engineering"
    SCIENCE = "science"
    HUMANITIES = "humanities"
    INTERDISCIPLINARY = "interdisciplinary"


class ResearchType(str, Enum):
    """研究类型（人文社科）"""
    SURVEY = "survey"               # 调查报告
    QUALITATIVE = "qualitative"     # 质化研究
    QUANTITATIVE = "quantitative"   # 量化研究
    MIXED = "mixed"                 # 混合研究
    LITERATURE = "literature"       # 文献综述
    CASE_STUDY = "case_study"       # 案例研究


class Readiness(str, Enum):
    """研究准备度"""
    NO_IDEA = "no_idea"               # 暂未有思路
    HAS_IDEA = "has_idea"             # 已有思路
    HAS_STRUCTURE = "has_structure"   # 已写好论文架构
"""
UI 规则检查器 — 自动化 UI 质量检查

职责:
  对每个 UI 变体的 HTML 代码进行静态规则检查,
  检测常见的 UI/UX 问题(对比度、可访问性、响应式等)。

不依赖 LLM,纯规则匹配,确保检查结果的确定性。
"""

from __future__ import annotations

import re
import structlog
from dataclasses import dataclass, field

logger = structlog.get_logger(__name__)


@dataclass
class RuleViolation:
    """规则违规"""
    rule_id: str           # 规则 ID
    rule_name: str         # 规则名称
    severity: str          # "error" | "warning" | "info"
    message: str           # 违规描述
    line_hint: str = ""    # 违规位置提示


@dataclass
class RuleCheckResult:
    """规则检查结果"""
    variant_id: str
    total_count: int = 0
    passed_count: int = 0
    violations: list[RuleViolation] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.violations) == 0

    def to_dict(self) -> dict:
        return {
            "variant_id": self.variant_id,
            "total_count": self.total_count,
            "passed_count": self.passed_count,
            "passed": self.passed,
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "rule_name": v.rule_name,
                    "severity": v.severity,
                    "message": v.message,
                }
                for v in self.violations
            ],
        }


# ── 规则定义 ──
def _check_color_contrast(html: str) -> list[RuleViolation]:
    """检查颜色对比度(简化版:检测低对比度颜色组合)"""
    violations = []

    # 检测 #333 on #fff 或类似低对比度组合
    low_contrast_patterns = [
        (r"color:\s*#?([0-9a-fA-F]{6}).*?background[^;]*#?([0-9a-fA-F]{6})", "低对比度颜色组合"),
    ]

    # 检测过浅的文字颜色
    light_colors = ["#999", "#aaa", "#bbb", "#ccc", "#ddd", "#eee", "#f0f0f0"]
    for color in light_colors:
        if f"color: {color}" in html or f"color:#{color[1:]}" in html:
            violations.append(RuleViolation(
                rule_id="CONTRAST-001",
                rule_name="颜色对比度",
                severity="warning",
                message=f"检测到浅色文字 {color},可能对比度不足(WCAG AA要求4.5:1)",
            ))
            break

    return violations


def _check_button_size(html: str) -> list[RuleViolation]:
    """检查按钮尺寸(最小44px触控目标)"""
    violations = []

    # 查找所有按钮样式
    button_patterns = re.findall(
        r'(?:button|btn|chat-option-btn|sidebar-btn)[^{]*\{[^}]*?(?:height|padding)[^}]*?\}',
        html,
        re.IGNORECASE,
    )

    for match in button_patterns:
        # 提取 height 值
        height_match = re.search(r'(?:min-)?height:\s*(\d+)px', match)
        if height_match:
            height = int(height_match.group(1))
            if height < 44:
                violations.append(RuleViolation(
                    rule_id="TOUCH-001",
                    rule_name="触控目标尺寸",
                    severity="warning",
                    message=f"按钮高度 {height}px 低于最小触控目标 44px",
                ))

    return violations


def _check_aria_labels(html: str) -> list[RuleViolation]:
    """检查 ARIA 标签(可访问性)"""
    violations = []

    # 查找没有 aria-label 的图标按钮
    icon_buttons = re.findall(
        r'<button[^>]*(?:svg|✎|✓)[^>]*>(?:[^<]*<(?:svg|span)[^>]*>)?',
        html,
        re.IGNORECASE,
    )

    for match in icon_buttons:
        if "aria-label" not in match and "title=" not in match:
            violations.append(RuleViolation(
                rule_id="A11Y-001",
                rule_name="ARIA 标签",
                severity="info",
                message="图标按钮缺少 aria-label 或 title 属性",
            ))

    return violations[:5]  # 最多报告5个


def _check_responsive_meta(html: str) -> list[RuleViolation]:
    """检查响应式 meta 标签"""
    violations = []

    if "viewport-fit=cover" not in html:
        violations.append(RuleViolation(
            rule_id="RESPONSIVE-001",
            rule_name="响应式视口",
            severity="info",
            message="viewport meta 标签缺少 viewport-fit=cover(影响刘海屏安全区)",
        ))

    if "@media" not in html:
        violations.append(RuleViolation(
            rule_id="RESPONSIVE-002",
            rule_name="响应式断点",
            severity="warning",
            message="未检测到 @media 媒体查询,可能不支持响应式布局",
        ))

    return violations


def _check_font_usage(html: str) -> list[RuleViolation]:
    """检查字体使用"""
    violations = []

    # 检查是否使用了衬线字体(学术风格)
    if "serif" not in html.lower():
        violations.append(RuleViolation(
            rule_id="FONT-001",
            rule_name="字体选择",
            severity="info",
            message="未检测到衬线字体,学术产品建议使用 Source Serif / Noto Serif",
        ))

    return violations


def _check_emoji_usage(html: str) -> list[RuleViolation]:
    """检查 emoji 使用(学术产品应避免 emoji)"""
    violations = []

    # 匹配常见 emoji 范围
    emoji_pattern = re.compile(
        "[\U0001F300-\U0001FAFF]"
        "|[\U0001F600-\U0001F64F]"
        "|[\U0001F680-\U0001F6FF]"
        "|[\u2600-\u27BF]",
        flags=re.UNICODE,
    )

    matches = emoji_pattern.findall(html)
    # 排除标准 Unicode 符号(✓ ✎ ⚠)
    real_emojis = [m for m in matches if m not in ("✓", "✎", "⚠", "✕", "ℹ", "→", "◀", "▶", "▾")]

    if real_emojis:
        violations.append(RuleViolation(
            rule_id="EMOJI-001",
            rule_name="Emoji 使用",
            severity="warning",
            message=f"检测到 {len(real_emojis)} 个 emoji,学术产品建议使用 SVG 图标替代",
        ))

    return violations


def _check_safe_area(html: str) -> list[RuleViolation]:
    """检查安全区支持"""
    violations = []

    if "safe-area-inset" not in html:
        violations.append(RuleViolation(
            rule_id="SAFE-AREA-001",
            rule_name="安全区适配",
            severity="info",
            message="未检测到 env(safe-area-inset-*) 支持,影响刘海屏设备",
        ))

    return violations


def _check_skeleton_loading(html: str) -> list[RuleViolation]:
    """检查骨架屏支持"""
    violations = []

    if "skeleton" not in html.lower():
        violations.append(RuleViolation(
            rule_id="LOADING-001",
            rule_name="加载状态",
            severity="info",
            message="未检测到骨架屏(skeleton)加载状态",
        ))

    return violations


# ── 所有规则 ──
ALL_RULES = [
    ("CONTRAST", _check_color_contrast),
    ("TOUCH_TARGET", _check_button_size),
    ("ARIA", _check_aria_labels),
    ("RESPONSIVE", _check_responsive_meta),
    ("FONT", _check_font_usage),
    ("EMOJI", _check_emoji_usage),
    ("SAFE_AREA", _check_safe_area),
    ("SKELETON", _check_skeleton_loading),
]


def check_variant(variant_id: str, html: str) -> RuleCheckResult:
    """
    对单个变体执行所有规则检查

    Args:
        variant_id: 变体 ID
        html: 变体的 HTML 代码

    Returns:
        RuleCheckResult
    """
    result = RuleCheckResult(variant_id=variant_id)
    result.total_count = len(ALL_RULES)

    for rule_name, check_fn in ALL_RULES:
        try:
            violations = check_fn(html)
            if not violations:
                result.passed_count += 1
            else:
                result.violations.extend(violations)
        except Exception as e:
            logger.error("Rule check %s failed: %s", rule_name, e)
            result.violations.append(RuleViolation(
                rule_id=f"{rule_name}-ERR",
                rule_name=rule_name,
                severity="error",
                message=f"规则检查执行异常: {e}",
            ))

    logger.info("Rule check for variant %s: %d/%d passed, %d violations",
                variant_id, result.passed_count, result.total_count, len(result.violations))
    return result


def check_all_variants(variants: list) -> dict[str, dict]:
    """
    对所有变体执行规则检查

    Args:
        variants: UIVariant 列表

    Returns:
        {"A": {...}, "B": {...}}  (每个变体的检查结果字典)
    """
    results: dict[str, dict] = {}
    all_violations: dict[str, list] = {}

    for variant in variants:
        if hasattr(variant, "__dict__"):
            vid = variant.variant_id
            html = variant.html_snippet
        elif isinstance(variant, dict):
            vid = variant.get("variant_id", "?")
            html = variant.get("html_snippet", "")
        else:
            continue

        check_result = check_variant(vid, html)
        results[vid] = check_result.to_dict()
        all_violations[vid] = [v.to_dict() if hasattr(v, "to_dict") else v
                                for v in check_result.violations]

    return {"results": results, "violations": all_violations}

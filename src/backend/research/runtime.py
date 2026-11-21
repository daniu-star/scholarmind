"""研究模型运行时的实例化绑定（FR-10、T04、AT-021）。

设计要点：
- **实例化、非全局**：``ModelSnapshot`` 在任务开始时捕获一次（provider/model/mode/
  captured_at），随后整条流水线复用同一快照；不读全局 bridge、不在中途换模型。
- **可替换**：``get_client`` 返回注入式 ``ModelClient``；测试直接构造
  ``FakeClient`` 传给流水线即可，不需要本模块。
- **无凭证即不可用**：缺少 API Key 或 provider 未知时返回 ``UnavailableClient``，
  由执行器落 ``recoverable``/``failed``，绝不伪造“已分析”。
- 导入本模块不产生 I/O：``settings`` 与底层 ``llm_client`` 都在函数内延迟导入。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

import structlog

from .contracts import utcnow
from .errors import ResearchAPIError, unavailable
from .pipelines.base import (
    PIPELINE_VERSION,
    REVIEW_PROMPT_VERSION,
    ModelClient,
    ModelOutputError,
)

#: 支持的提供方（新增提供方需同时实现适配器与策略，不做字符串猜测）。
SUPPORTED_PROVIDERS = frozenset({"deepseek"})

logger = structlog.get_logger(__name__)

#: 合法模式：``None``（套餐默认）/``flash``/``pro``。
SUPPORTED_MODES = ("flash", "pro")

_MODEL_UNAVAILABLE_CODE = "MODEL_UNAVAILABLE"


@dataclass(frozen=True)
class ModelSnapshot:
    """一次任务内固定不变的模型绑定快照。

    ``mode`` 记录解析后的模式（未指定时为 ``"default"``），
    ``captured_at`` 为捕获时刻（UTC naive），用于审计与重放。
    """

    provider: str
    model: str
    mode: str
    captured_at: datetime

    def __post_init__(self) -> None:
        for name in ("provider", "model", "mode"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"ModelSnapshot.{name} 必须是非空字符串")
        if not isinstance(self.captured_at, datetime):
            raise ValueError("ModelSnapshot.captured_at 必须是 datetime")

    # ── 序列化（进 snapshot_summary / 事件载荷）────────────

    def to_dict(self) -> Dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "mode": self.mode,
            "captured_at": self.captured_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelSnapshot":
        """从持久化快照还原；字段缺失或非法时抛 ``ValueError``。"""
        if not isinstance(data, dict):
            raise ValueError("模型快照必须是对象")
        provider = str(data.get("provider") or "").strip()
        model = str(data.get("model") or "").strip()
        mode = str(data.get("mode") or "default").strip()
        raw_at = data.get("captured_at")
        if isinstance(raw_at, datetime):
            captured_at = raw_at
        elif isinstance(raw_at, str) and raw_at.strip():
            try:
                captured_at = datetime.fromisoformat(raw_at.strip())
            except ValueError as exc:  # pragma: no cover - 脏数据兜底
                raise ValueError(f"captured_at 不是合法时间：{raw_at!r}") from exc
        else:
            raise ValueError("captured_at 缺失")
        return cls(
            provider=provider, model=model, mode=mode, captured_at=captured_at
        )


def _settings():
    """延迟导入全局配置（导入期不读配置、不做 I/O）。"""
    from ..config import settings  # 局部导入：避免 import 期副作用

    return settings


def _base_max_tokens() -> int:
    """单次模型调用的输出上限（关闭思维链后正文可用的预算）。"""
    return max(2048, int(getattr(_settings(), "RESEARCH_MODEL_MAX_OUTPUT_TOKENS", 8192)))


def _resolve_model(mode: Optional[str], plan: Optional[str]) -> str:
    settings = _settings()
    if mode == "flash":
        return str(getattr(settings, "DEEPSEEK_MODEL_FLASH", "") or "")
    if mode == "pro":
        return str(getattr(settings, "DEEPSEEK_MODEL_PRO", "") or "")
    # 未指定模式：pro/enterprise 套餐走 pro 模型，其余走 flash。
    plan_name = (plan or "").strip().lower()
    if plan_name in ("pro", "enterprise"):
        return str(
            getattr(settings, "DEEPSEEK_MODEL_PRO", "")
            or getattr(settings, "DEEPSEEK_MODEL", "")
        )
    return str(
        getattr(settings, "DEEPSEEK_MODEL_FLASH", "")
        or getattr(settings, "DEEPSEEK_MODEL", "")
    )


def capture_snapshot(
    *,
    mode: Optional[str],
    plan: Optional[str] = None,
    resolved_model: Optional[str] = None,
) -> ModelSnapshot:
    """捕获一次模型快照；任务全生命周期复用，不中途换模型。

    ``resolved_model`` 允许调用方（已按套餐策略解析过）直接指定模型；
    ``plan`` 仅用于“未指定模式”时的默认选择。非法 ``mode`` 抛 ``ValueError``。
    """
    if mode is not None and mode not in SUPPORTED_MODES:
        raise ValueError(f"不支持的模型模式：{mode!r}")
    model = (resolved_model or "").strip() or _resolve_model(mode, plan)
    if not model:
        # 配置缺失时不猜模型名，交由 UnavailableClient 落 recoverable。
        model = "unconfigured"
    return ModelSnapshot(
        provider="deepseek",
        model=model,
        mode=mode or "default",
        captured_at=utcnow(),
    )


def snapshot_from_dict(data: Dict[str, Any]) -> ModelSnapshot:
    """从 ``snapshot_summary["model_snapshot"]`` 还原快照。"""
    return ModelSnapshot.from_dict(data)


def snapshot_to_dict(snapshot: ModelSnapshot) -> Dict[str, str]:
    return snapshot.to_dict()


def capture_runtime_info(snapshot: ModelSnapshot) -> Dict[str, Any]:
    """审计用的运行时绑定信息（进入 snapshot_summary / 事件载荷）。"""
    return {
        "model_snapshot": snapshot.to_dict(),
        "provider": snapshot.provider,
        "actual_model": snapshot.model,
        "mode": snapshot.mode,
        "pipeline_version": PIPELINE_VERSION,
        "prompt_version": REVIEW_PROMPT_VERSION,
    }


class UnavailableClient:
    """无凭证/provider 不可用时的占位客户端：调用即抛 503 ``unavailable``。

    绝不允许吞掉失败返回空结果——那会把“没分析”伪装成“没问题”。
    """

    def __init__(self, reason: str = "") -> None:
        self.reason = reason or "模型服务不可用"

    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> str:
        raise unavailable(
            _MODEL_UNAVAILABLE_CODE,
            f"模型不可用：{self.reason}",
            {"reason": self.reason},
        )

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"UnavailableClient(reason={self.reason!r})"


class LlmClientAdapter:
    """把现有 ``utils.llm_client`` 适配成流水线的 ``ModelClient``。

    每个实例绑定一个 ``ModelSnapshot``：模型名来自快照，不读全局默认，
    因此两条流水线并行持有不同快照时不会串用模型（AT-021）。
    """

    def __init__(
        self,
        snapshot: ModelSnapshot,
        llm: Any = None,
        *,
        session_key: Optional[str] = None,
    ) -> None:
        self._snapshot = snapshot
        self._llm = llm  # 允许注入替身，便于测试
        # 压缩代理的会话键：同一任务的所有窗口共享，代理才能把已分析窗口
        # 的历史折叠掉。任务之间必须不同，避免跨任务串上下文。
        self._session_key = session_key

    @property
    def snapshot(self) -> ModelSnapshot:
        return self._snapshot

    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> str:
        client = self._llm
        if client is None:
            from ..utils.llm_client import llm_client as client  # 延迟导入单例
        settings = _settings()
        # 推理模型的思维链与正文输出共享 max_tokens：审稿/改写这类结构化
        # 任务的推理可能吃光 2048 预算，表现为 finish_reason=length 且
        # content 为空（2026-11-20 实测 deepseek-v4-flash）。默认关闭思维链，
        # 并在空内容时按 finish_reason 诊断/补偿一次。
        disable_thinking = bool(
            getattr(settings, "RESEARCH_DISABLE_MODEL_THINKING", True)
        )
        text, finish_reason, raw = await self._chat(
            client,
            system,
            user,
            json_schema=json_schema,
            disable_thinking=disable_thinking,
        )
        if finish_reason == "length":
            # 输出被截断：首次多半是推理吃光预算，也可能是诊断条目过多。
            # 统一关闭思维链并放大输出上限重试（最多两次），仍截断则交给
            # 流水线按“输出不可解析”诚实降级，绝不假装分析过。
            for attempt in range(1, 3):
                logger.warning(
                    "research.model_output_length_retry",
                    model=self._snapshot.model,
                    provider=self._snapshot.provider,
                    attempt=attempt,
                )
                text, finish_reason, raw = await self._chat(
                    client,
                    system,
                    user,
                    json_schema=json_schema,
                    disable_thinking=True,
                    max_tokens_override=min(
                        16384,
                        _base_max_tokens() * (2 ** attempt),
                    ),
                )
                if finish_reason != "length":
                    break
        if not text:
            # 空输出不是“无问题”，交给流水线按契约失败处理；附上可诊断信息。
            raise ModelOutputError(
                "模型返回空内容"
                + (f"（finish_reason={finish_reason}）" if finish_reason else "")
            )
        return text

    async def _chat(
        self,
        client: Any,
        system: str,
        user: str,
        *,
        json_schema: Optional[Dict[str, Any]],
        disable_thinking: bool,
        max_tokens_override: Optional[int] = None,
    ) -> tuple[str, Optional[str], Any]:
        """调用一次模型；返回 ``(text, finish_reason, raw)``，异常统一收敛为可重试不可用。"""
        kwargs: Dict[str, Any] = {
            "model": self._snapshot.model,
            "temperature": 0.2,
            "max_tokens": max_tokens_override or _base_max_tokens(),
        }
        if json_schema is not None:
            kwargs["response_format"] = {"type": "json_object"}
        if disable_thinking:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        session_key = self._session_key
        if session_key:
            kwargs["session_key"] = session_key
        try:
            response = await client.chat(system, user, **kwargs)
        except TypeError as exc:
            # 注入的测试替身可能不接受 extra_body / session_key：逐项去掉后
            # 重试一次，避免因适配层参数差异把真实调用判成“模型不可用”。
            message = str(exc)
            dropped = False
            if "session_key" in message:
                kwargs.pop("session_key", None)
                dropped = True
            if "extra_body" in message:
                kwargs.pop("extra_body", None)
                dropped = True
            if dropped:
                response = await client.chat(system, user, **kwargs)
            else:
                raise unavailable(
                    _MODEL_UNAVAILABLE_CODE,
                    f"模型调用失败：{type(exc).__name__}: {exc}",
                    {
                        "provider": self._snapshot.provider,
                        "model": self._snapshot.model,
                        "exception": type(exc).__name__,
                    },
                ) from exc
        except ResearchAPIError:
            raise
        except Exception as exc:  # 鉴权/限流/超时/断流统一收敛为可重试不可用
            raise unavailable(
                _MODEL_UNAVAILABLE_CODE,
                f"模型调用失败：{type(exc).__name__}: {exc}",
                {
                    "provider": self._snapshot.provider,
                    "model": self._snapshot.model,
                    "exception": type(exc).__name__,
                },
            ) from exc
        content = getattr(response, "content", None)
        if content is None and isinstance(response, str):
            content = response
        text = (content or "").strip() if isinstance(content, str) else ""
        raw = getattr(response, "raw", None)
        finish_reason: Optional[str] = None
        try:
            finish_reason = str(raw.choices[0].finish_reason or "") or None
        except Exception:  # 替身/异常结构：不做额外假设
            finish_reason = None
        return text, finish_reason, raw


def get_client(
    snapshot: ModelSnapshot,
    *,
    session_key: Optional[str] = None,
) -> ModelClient:
    """按快照构造模型客户端；无凭证或未知 provider 返回 ``UnavailableClient``。

    ``session_key`` 传给上下文压缩代理（未启用代理时被忽略），让同一任务
    的所有窗口共享压缩状态。
    """
    if not isinstance(snapshot, ModelSnapshot):
        raise TypeError("get_client 需要 ModelSnapshot 实例")
    if snapshot.provider not in SUPPORTED_PROVIDERS:
        return UnavailableClient(f"不支持的模型提供方：{snapshot.provider}")
    settings = _settings()
    # R2/E2E：替身模型只在非生产环境生效，且不得被当作真实模型质量证据。
    if bool(getattr(settings, "RESEARCH_MODEL_STUB", False)):
        if str(getattr(settings, "ENVIRONMENT", "development")) == "production":
            logger.warning(
                "research.model_stub_ignored_in_production",
                reason="生产环境禁止启用替身模型，忽略 RESEARCH_MODEL_STUB",
            )
        else:
            from .stub_model import StubModelClient

            return StubModelClient(snapshot)
    api_key = str(getattr(settings, "DEEPSEEK_API_KEY", "") or "").strip()
    if not api_key:
        return UnavailableClient("未配置 DEEPSEEK_API_KEY")
    if snapshot.model in ("", "unconfigured"):
        return UnavailableClient("模型名称未配置")
    return LlmClientAdapter(snapshot, session_key=session_key)


__all__ = [
    "LlmClientAdapter",
    "ModelSnapshot",
    "SUPPORTED_MODES",
    "SUPPORTED_PROVIDERS",
    "UnavailableClient",
    "capture_runtime_info",
    "capture_snapshot",
    "get_client",
    "snapshot_from_dict",
    "snapshot_to_dict",
]

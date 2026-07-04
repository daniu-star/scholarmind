"""
Pipeline LLM Bridge — 将后端 LLM 客户端桥接到 cyclical-paper-generation /
cyclical-paper-review 两个技能的 Pipeline 节点

设计模式：桥接模式（Bridge Pattern）
- 技能的 pipeline/llm_executor.py 定义了 Bridge 接口（chat_sync/async_chat 等）
- 后端通过本模块将 llm_client（DeepSeek AsyncOpenAI 封装）适配为 Bridge
- 在应用启动时调用 install_bridge_to_skills() 注入到两个技能

接口映射：
    Bridge.async_chat(system, user, *, temperature, max_tokens) -> str
        ↓ 调用
    llm_client.chat(system, user, *, temperature, max_tokens) -> LLMResponse.content

    Bridge.async_chat_json(system, user, *, temperature, max_tokens) -> dict
        ↓ 调用
    llm_client.chat_json(system, user, *, temperature, max_tokens) -> dict

执行环境：
    Pipeline 在后端 loop.run_in_executor() 的线程中运行，节点为同步函数。
    llm_executor 内部通过 asyncio.run() 调用本 Bridge 的 async 方法。

Author: ScholarMind Backend
Version: 1.0.0
"""
from __future__ import annotations

import structlog
import os
import sys
from pathlib import Path
from typing import Any, Optional

from .llm_client import llm_client

logger = structlog.get_logger(__name__)


class BackendLLMBridge:
    """后端 LLM 桥接实现

    将后端的 llm_client（异步）适配为技能 llm_executor 期望的 Bridge 接口。
    仅实现 async 接口，由 llm_executor 内部的 _run_async() 桥接到同步调用。
    """

    def __init__(self, client=llm_client):
        """初始化 Bridge

        Args:
            client: 后端 LLMClient 实例（默认使用全局单例 llm_client）
        """
        self._client = client

    # ── 同步接口（供 llm_executor 在线程池中直接调用）──────

    def chat_sync(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.5,
        max_tokens: int = 4096,
    ) -> str:
        """同步对话接口 — 高效路径，避免每次创建/销毁事件循环

        Pipeline 在 run_in_executor 的线程中执行，无事件循环。
        使用 threading 将 async_chat 适配为同步调用，复用底层连接池。
        """
        return asyncio.run(self.async_chat(
            system, user, temperature=temperature, max_tokens=max_tokens,
        ))

    def chat_json_sync(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """同步 JSON 对话接口"""
        return asyncio.run(self.async_chat_json(
            system, user, temperature=temperature, max_tokens=max_tokens,
        ))

    # ── 异步接口（由 llm_executor._run_async 桥接为同步调用）──

    async def async_chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.5,
        max_tokens: int = 4096,
    ) -> str:
        """异步对话接口，返回 LLM 响应文本"""
        response = await self._client.chat(
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.content

    async def async_chat_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """异步 JSON 对话接口，返回解析后的 dict"""
        return await self._client.chat_json(
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
        )


# ============================================================================
# Bridge 安装（应用启动时调用）
# ============================================================================

_bridge_installed: bool = False
_installed_bridge: Optional[BackendLLMBridge] = None


def install_bridge_to_skills() -> bool:
    """将后端 LLM Bridge 注入到两个技能的 Pipeline

    在应用 startup 事件中调用（core/events.py），将 BackendLLMBridge
    注入到 cyclical-paper-generation 和 cyclical-paper-review 两个技能的
    pipeline/llm_executor.py 模块。

    Returns:
        bool: 是否至少成功注入一个技能
    """
    global _bridge_installed, _installed_bridge

    if _bridge_installed:
        logger.debug("pipeline_llm_bridge_already_installed")
        return True

    bridge = BackendLLMBridge()
    success_count = 0

    # ★ 修复：先将两个技能目录加入 sys.path，确保 import pipeline.llm_executor 可以找到
    _SKILLS_BASE = os.environ.get(
        'SKILLS_DIR',
        str(Path.home() / ".trae-cn" / "skills")
    )
    for _skill_name in ["cyclical-paper-generation", "cyclical-paper-review"]:
        _skill_path = str(Path(_SKILLS_BASE) / _skill_name)
        if _skill_path not in sys.path:
            sys.path.insert(0, _skill_path)

    # ── 注入到 cyclical-paper-generation ──
    try:
        from pipeline.llm_executor import set_llm_bridge as gen_set_bridge
        gen_set_bridge(bridge)
        success_count += 1
        logger.info("bridge_installed_to_generation_pipeline")
    except ImportError as e:
        logger.warning(f"bridge_install_generation_failed reason=import_error error={e}")
    except Exception as e:
        logger.warning(f"bridge_install_generation_failed reason=unexpected error={e}")

    # ── 注入到 cyclical-paper-review ──
    try:
        # 注意：两个技能的 llm_executor 是独立模块，需要分别导入。
        # 不能从 sys.modules 取 "pipeline.llm_executor"，因为该键已被 generation 占用
        # （generation 注入时建立），错误命中会把 generation 模块当成 review 模块，
        # 导致 review 永远拿不到独立 bridge。直接走 importlib fallback 从 review
        # 技能目录加载独立模块（唯一模块名 cyclical_paper_review_llm_executor）。
        # Task 23.3: 删除原冗余赋值 + 永真 if 分支，直接进入加载流程。
        import importlib.util
        # P4-T7：从环境变量读取技能根目录，避免硬编码
        _SKILLS_BASE = os.environ.get('SKILLS_DIR', str(Path.home() / ".trae-cn" / "skills"))
        review_skill_dir = Path(_SKILLS_BASE) / "cyclical-paper-review"
        executor_path = review_skill_dir / "pipeline" / "llm_executor.py"

        loaded_mod = None  # 临时变量，加载失败保持为 None
        if executor_path.exists():
            spec = importlib.util.spec_from_file_location(
                "cyclical_paper_review_llm_executor", str(executor_path)
            )
            if spec and spec.loader:
                loaded_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(loaded_mod)

        if loaded_mod and hasattr(loaded_mod, "set_llm_bridge"):
            loaded_mod.set_llm_bridge(bridge)
            success_count += 1
            logger.info("bridge_installed_to_review_pipeline")
        else:
            logger.warning("bridge_install_review_failed reason=module_not_found")
    except Exception as e:
        logger.warning(f"bridge_install_review_failed reason=unexpected error={e}")

    _bridge_installed = success_count > 0
    _installed_bridge = bridge if _bridge_installed else None

    if success_count == 0:
        logger.warning(
            "pipeline_llm_bridge_install_failed hint=确保技能目录存在且 pipeline/llm_executor.py 可导入"
        )
    elif success_count == 1:
        logger.info(f"pipeline_llm_bridge_partial_install success_count={success_count}")
    else:
        logger.info(f"pipeline_llm_bridge_installed success_count={success_count}")

    return _bridge_installed


def uninstall_bridge_from_skills() -> None:
    """从两个技能中移除 Bridge（应用关闭时调用）"""
    global _bridge_installed, _installed_bridge

    try:
        from pipeline.llm_executor import clear_llm_bridge as gen_clear
        gen_clear()
    except Exception as e:
        # P1 Task 8.2：不再静默吞异常，记录便于排查卸载失败
        logger.warning(f"uninstall bridge failed module=pipeline.llm_executor exc={e}")

    try:
        import sys
        mod_name = "unknown"
        for mod_name in ["cyclical_paper_review.pipeline.llm_executor",
                         "cyclical_paper_review_llm_executor"]:
            if mod_name in sys.modules:
                sys.modules[mod_name].clear_llm_bridge()
                break
    except Exception as e:
        # P1 Task 8.2：记录卸载失败与出错的模块名
        logger.warning(f"uninstall bridge failed module={mod_name} exc={e}")

    _bridge_installed = False
    _installed_bridge = None
    logger.info("pipeline_llm_bridge_uninstalled")


def get_installed_bridge() -> Optional[BackendLLMBridge]:
    """获取已安装的 Bridge 实例（用于测试）"""
    return _installed_bridge

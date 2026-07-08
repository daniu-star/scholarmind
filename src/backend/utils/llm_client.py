"""
统一 LLM 客户端

封装 AsyncOpenAI，提供：
- 超时配置（默认 60s，避免 OpenAI 默认 600s 阻塞）
- tenacity 重试（对 429/连接错误/超时指数退避）
- 复用 deepseek_circuit_breaker 熔断器
- 统一 chat / stream_chat / chat_json 接口

解决历史问题：
- H1：LLM 调用无重试，单次失败即触发熔断
- H2：LLM 调用无超时（默认 600s）
- H8：_execute_chart_skill / _execute_cnki_skill 绕过熔断器
"""
from __future__ import annotations

import base64
import json
import logging  # for logging.WARNING constant used by tenacity.before_sleep_log
from typing import AsyncIterator, Optional

import httpx
import structlog
from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.backend.config import settings
from src.backend.core.exceptions import LLMTruncatedError
from src.backend.utils.circuit_breaker import CircuitBreakerOpenError, deepseek_circuit_breaker

logger = structlog.get_logger(__name__)


# 可重试的异常类型
_RETRYABLE_EXCEPTIONS = (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    httpx.TimeoutException,
    httpx.NetworkError,
)


class LLMResponse:
    """LLM 响应包装"""

    def __init__(self, content: str, *, raw=None, thought: Optional[str] = None):
        self.content = content
        self.raw = raw
        self.thought = thought  # CoT 思考过程（如有）

    def __str__(self) -> str:
        return self.content


class LLMClient:
    """统一 LLM 客户端单例

    用法：
        from src.backend.utils.llm_client import llm_client
        resp = await llm_client.chat(system="...", user="...")
        print(resp.content)

        # JSON 模式
        data = await llm_client.chat_json(system="...", user="...")

        # 流式
        async for chunk in llm_client.stream_chat(system="...", user="..."):
            print(chunk, end="")
    """

    _instance: Optional["LLMClient"] = None

    def __init__(self):
        self._client: Optional[AsyncOpenAI] = None
        self._model = settings.DEEPSEEK_MODEL
        self._timeout = settings.LLM_TIMEOUT
        self._max_retries = settings.LLM_MAX_RETRIES

    @classmethod
    def get_instance(cls) -> "LLMClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_client(self) -> AsyncOpenAI:
        """懒加载 AsyncOpenAI 客户端"""
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=settings.DEEPSEEK_API_KEY or "dummy-key",
                base_url=settings.DEEPSEEK_BASE_URL,
                timeout=httpx.Timeout(self._timeout, connect=10.0),
                max_retries=0,  # 由 tenacity 接管重试
            )
        return self._client

    def _build_retry_decorator(self):
        """构建 tenacity 重试装饰器"""
        return retry(
            stop=stop_after_attempt(self._max_retries + 1),
            wait=wait_exponential(
                multiplier=settings.LLM_RETRY_INITIAL_DELAY,
                min=settings.LLM_RETRY_INITIAL_DELAY,
                max=30.0,
            ),
            retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )

    async def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        response_format: Optional[dict] = None,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """同步对话（非流式）

        自动应用：超时、重试、熔断器
        """
        if not settings.DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置，无法调用 LLM")

        # 熔断器检查
        if not deepseek_circuit_breaker.allow_request():
            raise CircuitBreakerOpenError("deepseek")

        retry_decorator = self._build_retry_decorator()

        @retry_decorator
        async def _call():
            client = self._get_client()
            kwargs = {
                "model": model or self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if response_format is not None:
                kwargs["response_format"] = response_format
            return await client.chat.completions.create(**kwargs)

        try:
            completion = await _call()
            deepseek_circuit_breaker.record_success()
            content = completion.choices[0].message.content or ""
            return LLMResponse(content=content, raw=completion)
        except _RETRYABLE_EXCEPTIONS as e:
            deepseek_circuit_breaker.record_failure()
            logger.error(f"llm_call_failed error={e} error_type={type(e).__name__}")
            raise
        except Exception as e:
            # 非可重试异常（如 AuthenticationError）不计入熔断
            logger.error(f"llm_call_error error={e} error_type={type(e).__name__}")
            raise

    async def stream_chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """流式对话，逐 chunk 产出文本

        注意：流式不应用 tenacity 重试（流一旦开始无法回放），
        但仍受熔断器保护。流式中断由调用方处理（如 AgentService.stream_chat）
        """
        if not settings.DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置，无法调用 LLM")

        if not deepseek_circuit_breaker.allow_request():
            raise CircuitBreakerOpenError("deepseek")

        client = self._get_client()
        try:
            stream = await client.chat.completions.create(
                model=model or self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            finish_reason = None
            async for chunk in stream:
                if chunk.choices:
                    if chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                    if chunk.choices[0].finish_reason:
                        finish_reason = chunk.choices[0].finish_reason
            deepseek_circuit_breaker.record_success()
            # 流结束后，若因 max_tokens 截断（finish_reason=="length"），
            # 抛 LLMTruncatedError 让上层优雅处理（已 record_success 不计熔断失败）
            if finish_reason == "length":
                raise LLMTruncatedError("LLM output truncated due to max_tokens")
        except _RETRYABLE_EXCEPTIONS as e:
            deepseek_circuit_breaker.record_failure()
            logger.error(f"llm_stream_failed error={e} error_type={type(e).__name__}")
            raise
        except Exception as e:
            logger.error(f"llm_stream_error error={e} error_type={type(e).__name__}")
            raise

    def chat_messages(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        response_format: Optional[dict] = None,
        model: Optional[str] = None,
        stream: bool = False,
    ):
        """多轮对话（支持完整消息列表）

        当 stream=True 时返回异步生成器（async for 直接迭代）；
        当 stream=False 时返回 coroutine（需 await 获取 LLMResponse）。
        """
        if not settings.DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置")
        if not deepseek_circuit_breaker.allow_request():
            raise CircuitBreakerOpenError("deepseek")

        client = self._get_client()
        kwargs = {
            "model": model or self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format

        if stream:
            return self._chat_messages_stream(client, **kwargs)
        return self._chat_messages_sync(client, **kwargs)

    async def _chat_messages_stream(self, client, **kwargs):
        """流式对话（异步生成器）"""
        kwargs["stream"] = True
        try:
            stream_resp = await client.chat.completions.create(**kwargs)
            async for chunk in stream_resp:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
            deepseek_circuit_breaker.record_success()
        except _RETRYABLE_EXCEPTIONS:
            deepseek_circuit_breaker.record_failure()
            raise

    async def _chat_messages_sync(self, client, **kwargs):
        """非流式对话"""
        retry_decorator = self._build_retry_decorator()

        @retry_decorator
        async def _call():
            return await client.chat.completions.create(**kwargs)

        try:
            completion = await _call()
            deepseek_circuit_breaker.record_success()
            content = completion.choices[0].message.content or ""
            return LLMResponse(content=content, raw=completion)
        except _RETRYABLE_EXCEPTIONS as e:
            deepseek_circuit_breaker.record_failure()
            logger.error(f"llm_chat_messages_failed error={e} error_type={type(e).__name__}")
            raise
        except Exception as e:
            logger.error(f"llm_chat_messages_error error={e} error_type={type(e).__name__}")
            raise

    async def chat_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        model: Optional[str] = None,
    ) -> dict:
        """JSON 模式对话，强制返回 dict

        使用 response_format={"type": "json_object"}，并解析 JSON。
        解析失败时抛出 ValueError。
        """
        resp = await self.chat(
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            model=model,
        )
        try:
            return json.loads(resp.content)
        except json.JSONDecodeError as e:
            logger.error(
                "llm_json_parse_failed",
                error=str(e),
                content_preview=resp.content[:500],
            )
            # 尝试从 markdown 代码块中提取
            import re
            match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", resp.content)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass
            raise ValueError(f"LLM 返回非合法 JSON: {e}") from e


    async def chat_vision(
        self,
        system: str,
        user_text: str,
        image_path: str | None = None,
        image_base64: str | None = None,
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        model: str | None = None,
    ) -> LLMResponse:
        """视觉对话：发送图片 + 文本给 LLM 分析。

        支持两种传图方式：
        - image_path: 本地文件路径（自动读取并 base64 编码）
        - image_base64: 已有的 base64 字符串（不含 data URI 前缀）
        """
        if not settings.DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置")

        if not deepseek_circuit_breaker.allow_request():
            raise CircuitBreakerOpenError("deepseek")

        # 构建用户消息（多模态 content 数组）
        user_content = [{"type": "text", "text": user_text}]

        image_data = None
        if image_path:
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode()
        elif image_base64:
            image_data = image_base64

        if image_data:
            # 自动检测图片格式
            mime = "image/jpeg"
            if image_path and image_path.lower().endswith(".png"):
                mime = "image/png"
            elif image_path and image_path.lower().endswith(".gif"):
                mime = "image/gif"
            elif image_path and image_path.lower().endswith(".webp"):
                mime = "image/webp"
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{image_data}"},
            })

        retry_decorator = self._build_retry_decorator()

        @retry_decorator
        async def _call():
            client = self._get_client()
            return await client.chat.completions.create(
                model=model or self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )

        try:
            completion = await _call()
            deepseek_circuit_breaker.record_success()
            content = completion.choices[0].message.content or ""
            return LLMResponse(content=content, raw=completion)
        except _RETRYABLE_EXCEPTIONS as e:
            deepseek_circuit_breaker.record_failure()
            logger.error(f"llm_vision_failed error={e}")
            raise
        except Exception as e:
            logger.error(f"llm_vision_error error={e}")
            raise


# 全局单例
llm_client = LLMClient.get_instance()

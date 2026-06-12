"""
ScholarMind WebSocket 流式对话服务
管理 WebSocket 连接生命周期、心跳检测、流式token分发
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from .agent_service import AgentService

logger = logging.getLogger(__name__)


class StreamService:
    """WebSocket 流式对话管理服务"""

    # 心跳间隔（秒）
    PING_INTERVAL = 30
    # 心跳超时（秒）
    PING_TIMEOUT = 10
    # 最大消息大小（字节）
    MAX_MESSAGE_SIZE = 64 * 1024  # 64KB

    def __init__(self, websocket: WebSocket, agent_service: AgentService):
        self.ws = websocket
        self.agent_service = agent_service
        self._ping_task: Optional[asyncio.Task] = None
        self._stream_task: Optional[asyncio.Task] = None
        self._cancelled = False

    async def handle(self, agent_id: str, session_id: str) -> None:
        """主处理循环：接受连接、处理消息、管理心跳"""
        await self.ws.accept()
        logger.info("WebSocket connected", agent_id=agent_id, session_id=session_id)

        # 启动心跳
        self._ping_task = asyncio.create_task(self._ping_loop())

        try:
            while not self._cancelled:
                # 接收消息（带大小限制）
                try:
                    raw = await asyncio.wait_for(
                        self.ws.receive_text(),
                        timeout=self.PING_INTERVAL + self.PING_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.debug("WebSocket receive timeout, sending ping")
                    await self._send_json({"type": "ping"})
                    continue

                # 检查消息大小
                if len(raw) > self.MAX_MESSAGE_SIZE:
                    await self._send_error("消息过大，请缩短输入")
                    continue

                # 解析消息
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    await self._send_error("无效的JSON消息格式")
                    continue

                msg_type = data.get("type", "")

                if msg_type == "chat":
                    await self._handle_chat(data, agent_id, session_id)
                elif msg_type == "cancel":
                    self._cancelled = True
                    await self._send_json({"type": "cancelled"})
                    break
                elif msg_type == "pong":
                    continue  # 心跳响应，无需处理
                else:
                    await self._send_error(f"未知消息类型: {msg_type}")

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected", agent_id=agent_id)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            await self._send_error(f"服务异常: {str(e)}")
        finally:
            await self._cleanup()

    async def _handle_chat(
        self, data: dict, agent_id: str, session_id: str
    ) -> None:
        """处理聊天消息：调用 AgentService 流式接口并逐token发送"""
        message = data.get("message", "").strip()
        if not message:
            await self._send_error("消息不能为空")
            return

        context = data.get("context")
        logger.info("WebSocket chat", agent_id=agent_id, session_id=session_id)

        try:
            # 调用流式接口
            token_index = 0
            async for token in self.agent_service.stream_chat(
                message=message,
                agent_id=agent_id,
                session_id=session_id,
                context=context,
            ):
                if self._cancelled:
                    break

                if token.get("type") == "token":
                    await self._send_json({
                        "type": "token",
                        "content": token["content"],
                        "index": token_index,
                    })
                    token_index += 1
                elif token.get("type") == "done":
                    await self._send_json({
                        "type": "done",
                        "skills_used": token.get("skills_used", []),
                        "options": token.get("options", []),
                        "chart_info": token.get("chart_info"),
                        "cnki_results": token.get("cnki_results"),
                    })
                    break
                elif token.get("type") == "error":
                    await self._send_error(token.get("message", "对话失败"))
                    break

        except Exception as e:
            logger.error(f"Stream chat error: {e}")
            await self._send_error(f"流式对话失败: {str(e)}")

    async def _ping_loop(self) -> None:
        """心跳循环：定期发送 ping"""
        try:
            while not self._cancelled:
                await asyncio.sleep(self.PING_INTERVAL)
                if not self._cancelled:
                    try:
                        await self._send_json({"type": "ping"})
                    except Exception:
                        break
        except asyncio.CancelledError:
            pass

    async def _send_json(self, data: dict) -> None:
        """发送JSON消息"""
        try:
            await self.ws.send_text(json.dumps(data, ensure_ascii=False))
        except Exception:
            self._cancelled = True

    async def _send_error(self, message: str) -> None:
        """发送错误消息"""
        await self._send_json({"type": "error", "message": message})

    async def _cleanup(self) -> None:
        """清理资源"""
        self._cancelled = True
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
        try:
            await self.ws.close()
        except Exception:
            pass
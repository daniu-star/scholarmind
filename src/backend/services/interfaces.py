"""
ScholarMind 服务层接口抽象（ABC协议）
为关键Service定义抽象基类，支持多实现替换（Mock测试、不同LLM提供商等）。

遵循依赖倒置原则（DIP）：高层模块（routers）依赖接口，而非具体实现。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Optional


class IAgentService(ABC):
    """Agent对话服务接口

    实现类：services.agent_service.AgentService
    """

    @abstractmethod
    async def chat(
        self,
        message: str,
        agent_id: str,
        session_id: str,
        context: Optional[dict] = None,
        user_id: int = 0,
        model: Optional[str] = None,
    ) -> dict:
        """同步对话：发送消息并获取完整回复

        P0 Task 4.4：model 由 Router 通过 model_policy.resolve_model() 解析后传入。
        """
        ...

    @abstractmethod
    async def stream_chat(
        self,
        message: str,
        agent_id: str,
        session_id: str,
        context: Optional[dict] = None,
        user_id: int = 0,
        model: Optional[str] = None,
    ) -> AsyncGenerator[dict, None]:
        """流式对话：逐token生成回复

        P0 Task 4.4：model 由 Router 通过 model_policy.resolve_model() 解析后传入。
        """
        ...

    @abstractmethod
    async def clear_conversation(self, session_id: str, user_id: int = 0) -> bool:
        """清空会话历史"""
        ...

    @abstractmethod
    async def get_conversation_history(
        self, session_id: str, user_id: int = 0
    ) -> list[dict]:
        """获取会话历史"""
        ...

    @abstractmethod
    def list_agents(self) -> list[dict]:
        """列出所有可用Agent"""
        ...


class ICNKIService(ABC):
    """CNKI学术检索服务接口

    实现类：services.cnki_service.CNKIService
    """

    @abstractmethod
    async def search(
        self, query: str, year_filter: str = "", count: int = 20
    ) -> list:
        """检索学术文献"""
        ...

    @abstractmethod
    async def check_connection(self) -> dict:
        """检查各数据源连接状态"""
        ...

    @abstractmethod
    async def close(self) -> None:
        """关闭连接和资源"""
        ...


class IChartService(ABC):
    """图表生成服务接口

    实现模块：services.chart_service
    """

    @abstractmethod
    def generate_chart(
        self,
        chart_type: str,
        data: Any,
        title: str = "学术研究图表",
        x_label: str = "",
        y_label: str = "",
        width: int = 1200,
        height: int = 800,
        dpi: int = 300,
        **kwargs,
    ) -> bytes:
        """生成学术图表，返回PNG字节数据"""
        ...


class ISkillsService(ABC):
    """技能管理服务接口

    实现类：services.skills_service.SkillsService
    """

    @abstractmethod
    def list_all(self) -> list:
        """列出所有技能（预设 + 自定义）"""
        ...

    @abstractmethod
    def get_skill(self, skill_id: str) -> dict | None:
        """获取单个技能"""
        ...

    @abstractmethod
    def create_skill(self, skill_data: dict) -> dict:
        """创建自定义技能"""
        ...

    @abstractmethod
    def update_skill(self, skill_id: str, skill_data: dict) -> dict:
        """更新技能"""
        ...

    @abstractmethod
    def delete_skill(self, skill_id: str) -> bool:
        """删除技能"""
        ...

    @abstractmethod
    def toggle_skill(self, skill_id: str, enabled: bool) -> dict:
        """切换技能启用状态"""
        ...
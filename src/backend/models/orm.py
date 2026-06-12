"""
ScholarMind ORM 数据模型
SQLAlchemy 异步 ORM 模型定义
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    JSON,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..db.session import Base


class Conversation(Base):
    """对话消息模型 —— 替代 JSON 文件存储"""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="会话唯一标识"
    )
    agent_id: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="Agent 类型"
    )
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="user / assistant"
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False, comment="消息内容"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, comment="创建时间"
    )

    __table_args__ = (
        Index("idx_conversations_session_time", "session_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Conversation(id={self.id}, session={self.session_id}, "
            f"role={self.role}, created_at={self.created_at})>"
        )


class Skill(Base):
    """技能配置模型 —— 替代 YAML 文件存储"""

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    skill_id: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True, comment="技能唯一标识"
    )
    display_name: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="展示名称"
    )
    description: Mapped[str] = mapped_column(
        Text, default="", comment="技能描述"
    )
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="custom", comment="技能分类"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="是否启用"
    )
    agents: Mapped[list] = mapped_column(
        JSON, default=list, comment="关联的 Agent 列表"
    )
    triggers: Mapped[list] = mapped_column(
        JSON, default=list, comment="触发关键词列表"
    )
    rules: Mapped[str] = mapped_column(
        Text, default="", comment="技能规则（Markdown）"
    )
    is_preset: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否预设技能"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, comment="更新时间"
    )

    __table_args__ = (
        Index("idx_skills_enabled", "enabled"),
        Index("idx_skills_category", "category"),
    )

    def __repr__(self) -> str:
        return (
            f"<Skill(id={self.id}, skill_id={self.skill_id}, "
            f"name={self.display_name}, enabled={self.enabled})>"
        )


class ChartRecord(Base):
    """图表生成记录模型"""

    __tablename__ = "chart_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chart_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True, comment="图表 UUID"
    )
    chart_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="图表类型"
    )
    title: Mapped[str] = mapped_column(
        String(256), default="", comment="图表标题"
    )
    filepath: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="文件路径"
    )
    session_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="会话标识"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, comment="创建时间"
    )

    __table_args__ = (
        Index("idx_chart_records_session", "session_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ChartRecord(id={self.id}, chart_id={self.chart_id}, "
            f"type={self.chart_type}, session={self.session_id})>"
        )
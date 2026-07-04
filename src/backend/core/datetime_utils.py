"""日期时间工具函数。"""
from __future__ import annotations

from datetime import datetime, timezone


def as_utc(value: datetime | None) -> datetime | None:
    """将 naive datetime 转为 UTC-aware；已带时区的转为 UTC。

    用于支付回调、权益过期等场景的统一时区处理。
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

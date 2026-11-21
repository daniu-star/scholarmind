"""确定性替身模型（仅用于本地联调、浏览器 E2E 与预算测量）。

设计约束（R2 / T21）：

- **不是质量证据**：替身模型返回固定结构，不读语义、不产生真实诊断结论。
  任何用它跑出的"缺陷识别率/误报率"都不成立；质量验收必须走真人盲评。
- **默认关闭**：只有 ``RESEARCH_MODEL_STUB=true`` 且 ``ENVIRONMENT != production``
  才会被 ``runtime.get_client`` 选中；生产环境无条件忽略该开关。
- **确定性**：同样输入永远得到同样输出，便于 E2E 断言与预算基线比较。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

STUB_ARTIFACT_NOTE = "[stub] 替身模型：未进行真实语义诊断，仅用于流程联调"

_ORIGINAL_RE = re.compile(r"<<<\n(?P<body>.*?)\n>>>", re.DOTALL)

_REVIEW_JSON: Dict[str, Any] = {
    "findings": [],
    "notes": [STUB_ARTIFACT_NOTE],
    "unresolved": [],
}


def _revision_reply(prompt: str) -> Dict[str, Any]:
    """在原文片段末尾追加可识别的示例改写，保留全部原文以备校验通过。"""
    match = _ORIGINAL_RE.search(prompt)
    original = match.group("body") if match else ""
    return {
        "replacement": original + "（示例改写）",
        "reason": STUB_ARTIFACT_NOTE,
    }


class StubModelClient:
    """满足 ``ModelClient`` 协议的最小确定性实现。"""

    def __init__(self, snapshot: Any) -> None:
        self._snapshot = snapshot
        self.calls = 0

    @property
    def snapshot(self) -> Any:
        return self._snapshot

    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> str:
        self.calls += 1
        if "【原文片段】" in user or "replacement" in user:
            payload = _revision_reply(user)
        elif "outline" in user.lower() or "大纲" in user:
            payload = {"outline": [], "notes": [STUB_ARTIFACT_NOTE]}
        else:
            payload = dict(_REVIEW_JSON)
        return json.dumps(payload, ensure_ascii=False)


__all__ = ["StubModelClient", "STUB_ARTIFACT_NOTE"]

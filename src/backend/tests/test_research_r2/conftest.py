"""R2 验证夹具：复用 R0/R1 的临时 SQLite / 双用户 / 真 app 夹具。

并解决一个真实工程事实：仓库里同时存在 ``backend.*`` 与 ``src.backend.*``
两套模块实例（``app.py`` 把项目根塞进 ``sys.path``，测试/应用各自按不同
包名导入），因此 ``settings`` 也有两份。改开关或打桩必须同时作用于两份，
否则会出现"测试里改成了 True、应用里还是 False"的假失败。
"""
from __future__ import annotations

import sys
from types import ModuleType

from ..test_research.conftest import *  # noqa: F403


def _settings_instances() -> list:
    """返回当前已加载的所有 settings 实例（``backend.config`` / ``src.backend.config``）。"""
    found = []
    for name in ("backend.config", "src.backend.config"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "settings"):
            found.append(module.settings)
    if not found:  # pragma: no cover - 正常测试会话里一定已加载
        from ...config import settings as fallback

        found.append(fallback)
    return found


def patch_switch(monkeypatch, name: str, value) -> None:
    """把配置开关写到每一份 settings 实例上。"""
    for settings in _settings_instances():
        monkeypatch.setattr(settings, name, value, raising=False)


def modules_named(suffix: str) -> list[ModuleType]:
    """按后缀取已加载模块（用于同时给两套实例打桩）。"""
    return [
        module
        for name, module in list(sys.modules.items())
        if name.endswith(suffix) and module is not None
    ]


def patch_in_modules(monkeypatch, suffix: str, attr: str, value) -> int:
    """把所有匹配后缀的模块里的 ``attr`` 替换成 ``value``，返回替换个数。"""
    count = 0
    for module in modules_named(suffix):
        if hasattr(module, attr):
            monkeypatch.setattr(module, attr, value)
            count += 1
    return count

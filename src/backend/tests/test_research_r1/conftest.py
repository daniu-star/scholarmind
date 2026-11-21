"""R1 验证夹具：复用 R0 的临时 SQLite / 双用户 / 真 app 夹具。

R1 只新增“验证”测试，不重复造环境：``research_store`` / ``research_env`` /
``client_a`` / ``db`` 等全部来自 ``tests/test_research/conftest.py``。conftest
星号导入会把 fixture 对象放进本模块命名空间，pytest 因而能在本目录发现它们。
"""
from __future__ import annotations

from ..test_research.conftest import *  # noqa: F403

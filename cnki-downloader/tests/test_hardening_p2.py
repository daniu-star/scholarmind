"""P2 架构强化修复的单元测试。

测试范围：
  1. warmup_session 循环条件修复（anti_anti_crawl/session_manager.py）
     验证循环条件不再恒为 False，能正常迭代 warmup_urls
  2. retry.py Any 导入（utils/retry.py）
     验证 Any 可被导入且在类型注解中使用
  3. progress.json 文件锁（crawler/hybrid_scraper.py）
     验证 _file_lock 上下文管理器存在且可调用
  4. stealth 脚本动态生成（anti_anti_crawl/browser_manager.py）
     验证 _stealth_hardware_script() 每次返回不同的随机值
  5. LOG_FILE 启用（utils/logging_config.py）
     验证 LOG_FILE 配置存在且非空
  6. TLS 指纹配置统一（config/settings.py + crawler/hybrid_scraper.py + anti_anti_crawl/tls_client.py）
     验证 settings.TLS_FINGERPRINT_POOL 存在且被两个模块引用

运行方式：
    cd c:\\Users\\13067\\Desktop\\AI产品\\cnki-downloader
    python -m pytest tests/test_hardening_p2.py -v
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 确保能导入项目模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ═══════════════════════════════════════════════════════════════
# SubTask 5.3.1: warmup_session 循环条件修复
# ═══════════════════════════════════════════════════════════════


def test_session_manager_warmup_session_loop_condition():
    """warmup_session 的循环条件应能正常迭代 warmup_urls。

    修复前：循环条件恒为 False（如 `while False:` 或 `if False:`），导致循环体不执行
    修复后：使用 `asyncio.get_event_loop().time() - start > duration` 作为退出条件
    """
    from anti_anti_crawl.session_manager import SessionManager

    source = inspect.getsource(SessionManager.warmup_session)

    # 验证循环使用 start 时间戳作为退出条件（而非恒为 False）
    assert "start" in source, \
        "warmup_session 应使用 start 变量记录开始时间"
    assert "asyncio.get_event_loop().time()" in source or "loop.time()" in source, \
        "warmup_session 应使用 asyncio.get_event_loop().time() 获取当前时间"
    # 验证循环条件检查 duration
    assert "duration" in source, \
        "warmup_session 循环条件应检查 duration 参数"


def test_session_manager_warmup_session_iterates_urls():
    """warmup_session 应迭代 warmup_urls 列表（而非跳过循环体）。"""
    from anti_anti_crawl.session_manager import SessionManager

    source = inspect.getsource(SessionManager.warmup_session)

    # 验证有 warmup_urls 列表
    assert "warmup_urls" in source
    # 验证使用 for 循环迭代
    assert "for url in warmup_urls" in source
    # 验证循环体内调用 page.goto
    assert "page.goto" in source


def test_session_manager_warmup_session_loop_not_constant_false():
    """warmup_session 的循环条件不应是常量 False。"""
    from anti_anti_crawl.session_manager import SessionManager

    source = inspect.getsource(SessionManager.warmup_session)

    # 检查是否存在 `while False:` 或 `if False:` 这样的死代码
    # 修复后的代码应使用动态条件
    assert "while False" not in source, \
        "warmup_session 不应包含 'while False' 死循环"
    assert "if False" not in source, \
        "warmup_session 不应包含 'if False' 死分支"


def test_session_manager_warmup_session_uses_behavior_simulator():
    """warmup_session 应调用 behavior_simulator 模拟人类浏览。"""
    from anti_anti_crawl.session_manager import SessionManager

    source = inspect.getsource(SessionManager.warmup_session)

    # 验证调用了 behavior_simulator
    assert "behavior_simulator" in source
    # 验证调用了 slow_scroll_through 或 human_scroll 或 random_browsing
    assert any(
        method in source
        for method in ["slow_scroll_through", "human_scroll", "random_browsing"]
    ), "warmup_session 应调用 behavior_simulator 的某个方法"


def test_session_manager_imports_settings():
    """session_manager.py 应导入 settings（P1 修复项，验证不回归）。"""
    import anti_anti_crawl.session_manager as sm_mod

    source = inspect.getsource(sm_mod)
    assert "from config.settings import settings" in source, \
        "session_manager.py 应导入 settings"


def test_session_manager_uses_settings_proxy_url():
    """warmup_session_via_tls 应使用 settings.PROXY_URL。"""
    from anti_anti_crawl.session_manager import SessionManager

    source = inspect.getsource(SessionManager.warmup_session_via_tls)

    # 验证使用 settings.PROXY_URL 和 settings.PROXY_ENABLED
    assert "settings.PROXY_URL" in source or "settings.PROXY_ENABLED" in source, \
        "warmup_session_via_tls 应使用 settings.PROXY_URL/PROXY_ENABLED"


# ═══════════════════════════════════════════════════════════════
# SubTask 5.3.2: retry.py Any 导入
# ═══════════════════════════════════════════════════════════════


def test_retry_module_imports_any():
    """utils/retry.py 应从 typing 导入 Any。"""
    import utils.retry as retry_mod

    source = inspect.getsource(retry_mod)
    # 验证从 typing 导入 Any
    assert "from typing import" in source
    assert "Any" in source, \
        "retry.py 应从 typing 导入 Any（用于 RetryManager.execute 的返回类型）"


def test_retry_any_is_actual_typing_any():
    """retry.py 中导入的 Any 应是 typing.Any。"""
    from utils.retry import Any as retry_any
    from typing import Any as typing_any

    # 验证导入的 Any 与 typing.Any 是同一对象
    assert retry_any is typing_any


def test_retry_manager_execute_returns_any():
    """RetryManager.execute 的返回类型注解应为 Any。

    注意：retry.py 使用 `from __future__ import annotations`（PEP 563），
    因此 inspect.signature 返回的注解是字符串 'Any' 而非 typing.Any 对象。
    """
    from utils.retry import RetryManager

    sig = inspect.signature(RetryManager.execute)
    return_annotation = sig.return_annotation

    # 由于 PEP 563，注解可能是字符串 'Any' 或 typing.Any 对象
    if isinstance(return_annotation, str):
        # 字符串形式：应为 'Any'
        assert return_annotation == "Any", \
            f"RetryManager.execute 返回类型应为 'Any'，实际为 {return_annotation!r}"
    else:
        # 对象形式：应为 typing.Any
        from typing import Any
        assert return_annotation is Any, \
            f"RetryManager.execute 返回类型应为 Any，实际为 {return_annotation}"


def test_retry_module_any_usable_in_code():
    """Any 应可在代码中作为类型注解使用（不抛异常）。"""
    from utils.retry import Any

    # 用 Any 作为类型注解（仅类型检查，运行时不影响）
    def example(x: Any) -> Any:
        return x

    assert example(42) == 42
    assert example("hello") == "hello"


# ═══════════════════════════════════════════════════════════════
# SubTask 5.3.3: progress.json 文件锁
# ═══════════════════════════════════════════════════════════════


def test_hybrid_scraper_has_file_lock():
    """hybrid_scraper.py 应定义 _file_lock 上下文管理器。"""
    import crawler.hybrid_scraper as hs_mod

    assert hasattr(hs_mod, "_file_lock")
    assert callable(hs_mod._file_lock)


def test_hybrid_scraper_file_lock_is_context_manager():
    """_file_lock 应是上下文管理器（可被 with 语句使用）。"""
    from crawler.hybrid_scraper import _file_lock
    import contextlib

    # 验证 _file_lock 是 contextmanager 装饰的函数
    # 调用后返回的对象应有 __enter__ 和 __exit__
    with tempfile.TemporaryDirectory() as tmp_dir:
        lock_path = Path(tmp_dir) / "test.lock"
        ctx = _file_lock(lock_path)
        # 验证是 context manager
        assert hasattr(ctx, "__enter__")
        assert hasattr(ctx, "__exit__")


def test_hybrid_scraper_file_lock_creates_parent_dir(tmp_path):
    """_file_lock 应自动创建父目录。"""
    from crawler.hybrid_scraper import _file_lock

    # 父目录不存在
    lock_path = tmp_path / "subdir" / "nested" / "test.lock"
    assert not lock_path.parent.exists()

    # 使用 _file_lock 应自动创建父目录
    with _file_lock(lock_path):
        assert lock_path.parent.exists()


def test_hybrid_scraper_file_lock_acquires_and_releases(tmp_path):
    """_file_lock 应能正常获取和释放锁。"""
    from crawler.hybrid_scraper import _file_lock

    lock_path = tmp_path / "test.lock"

    # 进入上下文应能正常执行
    with _file_lock(lock_path):
        # 锁文件应被创建
        assert lock_path.exists()

    # 退出上下文后锁应被释放（文件可能仍存在，但锁应解除）
    # 在 Windows 上，文件锁释放后可再次获取
    with _file_lock(lock_path):
        pass  # 再次获取应成功


def test_hybrid_scraper_load_progress_uses_file_lock():
    """_load_progress 应使用 _file_lock 保护文件读取。"""
    from crawler.hybrid_scraper import CNKIHybridScraper

    source = inspect.getsource(CNKIHybridScraper._load_progress)
    assert "_file_lock" in source, \
        "_load_progress 应使用 _file_lock 保护文件读取"


def test_hybrid_scraper_save_progress_uses_file_lock():
    """_save_progress 应使用 _file_lock 保护文件写入。"""
    from crawler.hybrid_scraper import CNKIHybridScraper

    source = inspect.getsource(CNKIHybridScraper._save_progress)
    assert "_file_lock" in source, \
        "_save_progress 应使用 _file_lock 保护文件写入"


def test_hybrid_scraper_load_progress_unlocked_exists():
    """_load_progress_unlocked 应存在（供持锁调用方使用，避免重入死锁）。"""
    from crawler.hybrid_scraper import CNKIHybridScraper

    assert hasattr(CNKIHybridScraper, "_load_progress_unlocked")
    assert callable(CNKIHybridScraper._load_progress_unlocked)


def test_hybrid_scraper_progress_lock_round_trip(tmp_path):
    """集成测试：通过 _file_lock 保护 progress.json 的读写。"""
    from crawler.hybrid_scraper import CNKIHybridScraper, FullPaperData

    scraper = CNKIHybridScraper(
        cookies={"_test": "1"},
        output_dir=str(tmp_path / "output"),
    )

    # 初始状态：progress.json 不存在，应返回空结构
    data = scraper._load_progress()
    assert data == {"downloaded": []}

    # 模拟下载一篇论文后保存进度
    paper = FullPaperData(
        title="测试论文",
        doi="10.1234/test.001",
        cnki_url="https://kns.cnki.net/test",
        filename="test_file",
        file_path="/tmp/test.pdf",
    )
    scraper._save_progress(paper)

    # 重新加载应能看到保存的记录
    data = scraper._load_progress()
    assert len(data["downloaded"]) == 1
    assert data["downloaded"][0]["doi"] == "10.1234/test.001"
    assert data["downloaded"][0]["url"] == "https://kns.cnki.net/test"


# ═══════════════════════════════════════════════════════════════
# SubTask 5.3.4: stealth 脚本动态生成
# ═══════════════════════════════════════════════════════════════


def test_browser_manager_has_stealth_hardware_script():
    """browser_manager.py 应有 _stealth_hardware_script 函数。"""
    import anti_anti_crawl.browser_manager as bm_mod

    assert hasattr(bm_mod, "_stealth_hardware_script")
    assert callable(bm_mod._stealth_hardware_script)


def test_stealth_hardware_script_returns_string():
    """_stealth_hardware_script 应返回字符串。"""
    from anti_anti_crawl.browser_manager import _stealth_hardware_script

    script = _stealth_hardware_script()
    assert isinstance(script, str)
    assert len(script) > 0


def test_stealth_hardware_script_contains_hardware_concurrency():
    """_stealth_hardware_script 应包含 hardwareConcurrency 注入。"""
    from anti_anti_crawl.browser_manager import _stealth_hardware_script

    script = _stealth_hardware_script()
    assert "hardwareConcurrency" in script
    assert "deviceMemory" in script


def test_stealth_hardware_script_generates_different_values():
    """_stealth_hardware_script 每次调用应生成不同的随机值。

    修复前：f-string 在模块导入时固化，每次调用返回相同值
    修复后：使用 random.randint 在函数内部生成，每次调用不同
    """
    from anti_anti_crawl.browser_manager import _stealth_hardware_script

    # 生成多个脚本，验证至少有两个不同
    scripts = [_stealth_hardware_script() for _ in range(20)]

    # 验证存在不同的脚本（随机性使然，20 次应有差异）
    unique_scripts = set(scripts)
    assert len(unique_scripts) > 1, \
        "20 次调用应生成至少 2 个不同的脚本（验证动态生成）"


def test_stealth_hardware_script_uses_random_module():
    """_stealth_hardware_script 应使用 random 模块生成随机值。"""
    import anti_anti_crawl.browser_manager as bm_mod

    source = inspect.getsource(bm_mod._stealth_hardware_script)
    # 验证使用 random.randint
    assert "random.randint" in source, \
        "_stealth_hardware_script 应使用 random.randint 生成随机值"


def test_browser_manager_stealth_scripts_list_exists():
    """STEALTH_SCRIPTS 列表应存在且非空。"""
    from anti_anti_crawl.browser_manager import STEALTH_SCRIPTS

    assert isinstance(STEALTH_SCRIPTS, list)
    assert len(STEALTH_SCRIPTS) > 0


# ═══════════════════════════════════════════════════════════════
# SubTask 5.3.5: LOG_FILE 启用
# ═══════════════════════════════════════════════════════════════


def test_settings_has_log_file():
    """settings 应有 LOG_FILE 配置。"""
    from config.settings import settings

    assert hasattr(settings, "LOG_FILE")
    assert isinstance(settings.LOG_FILE, str)


def test_settings_log_file_non_empty():
    """LOG_FILE 不应为空字符串。"""
    from config.settings import settings

    assert settings.LOG_FILE, "LOG_FILE 不应为空"
    assert len(settings.LOG_FILE) > 0


def test_settings_log_file_is_valid_path():
    """LOG_FILE 应是有效的文件路径。"""
    from config.settings import settings

    log_path = Path(settings.LOG_FILE)
    # 验证路径有父目录
    assert log_path.parent is not None
    # 验证有 .log 扩展名（约定）
    assert log_path.suffix == ".log"


def test_logging_config_uses_log_file():
    """setup_logging 应使用 settings.LOG_FILE 配置 FileHandler。"""
    from utils.logging_config import setup_logging
    import utils.logging_config as lc_mod

    source = inspect.getsource(lc_mod)
    # 验证使用 settings.LOG_FILE
    assert "settings.LOG_FILE" in source or "LOG_FILE" in source
    # 验证创建了 FileHandler
    assert "FileHandler" in source, \
        "setup_logging 应创建 FileHandler 输出到 LOG_FILE"


def test_logging_config_creates_log_directory():
    """setup_logging 应创建日志目录。"""
    from utils.logging_config import setup_logging

    source = inspect.getsource(setup_logging)
    # 验证有 mkdir 调用创建父目录
    assert "mkdir" in source or "makedirs" in source, \
        "setup_logging 应创建日志目录（log_file.parent.mkdir）"


# ═══════════════════════════════════════════════════════════════
# SubTask 5.3.6: TLS 指纹配置统一
# ═══════════════════════════════════════════════════════════════


def test_settings_has_tls_fingerprint_pool():
    """settings 应有 TLS_FINGERPRINT_POOL 配置。"""
    from config.settings import settings

    assert hasattr(settings, "TLS_FINGERPRINT_POOL")


def test_settings_tls_fingerprint_pool_is_list():
    """TLS_FINGERPRINT_POOL 应是列表。"""
    from config.settings import settings

    assert isinstance(settings.TLS_FINGERPRINT_POOL, list)


def test_settings_tls_fingerprint_pool_non_empty():
    """TLS_FINGERPRINT_POOL 不应为空。"""
    from config.settings import settings

    assert len(settings.TLS_FINGERPRINT_POOL) > 0, \
        "TLS_FINGERPRINT_POOL 应至少包含一个指纹"


def test_settings_tls_fingerprint_pool_contains_strings():
    """TLS_FINGERPRINT_POOL 中的元素应是字符串。"""
    from config.settings import settings

    for fp in settings.TLS_FINGERPRINT_POOL:
        assert isinstance(fp, str), f"指纹 {fp} 应为字符串"
        assert len(fp) > 0, "指纹不应为空字符串"


def test_settings_tls_fingerprint_pool_has_multiple_entries():
    """TLS_FINGERPRINT_POOL 应有多个指纹（用于轮换）。"""
    from config.settings import settings

    assert len(settings.TLS_FINGERPRINT_POOL) >= 3, \
        "TLS_FINGERPRINT_POOL 应至少有 3 个指纹用于轮换"


def test_hybrid_scraper_uses_settings_tls_fingerprint_pool():
    """hybrid_scraper 应引用 settings.TLS_FINGERPRINT_POOL。"""
    import crawler.hybrid_scraper as hs_mod

    source = inspect.getsource(hs_mod)
    # 验证引用了 settings.TLS_FINGERPRINT_POOL
    assert "settings.TLS_FINGERPRINT_POOL" in source, \
        "hybrid_scraper 应使用 settings.TLS_FINGERPRINT_POOL"


def test_hybrid_scraper_pick_fingerprint_uses_pool():
    """_pick_fingerprint 应从 settings.TLS_FINGERPRINT_POOL 选取指纹。"""
    from crawler.hybrid_scraper import CNKIHybridScraper

    source = inspect.getsource(CNKIHybridScraper._pick_fingerprint)
    assert "settings.TLS_FINGERPRINT_POOL" in source, \
        "_pick_fingerprint 应从 settings.TLS_FINGERPRINT_POOL 选取指纹"


def test_tls_client_uses_settings_tls_fingerprint_pool():
    """tls_client.py 应引用 settings.TLS_FINGERPRINT_POOL。"""
    import anti_anti_crawl.tls_client as tc_mod

    source = inspect.getsource(tc_mod)
    assert "settings.TLS_FINGERPRINT_POOL" in source, \
        "tls_client.py 应使用 settings.TLS_FINGERPRINT_POOL"


def test_tls_client_rotate_impersonate_uses_pool():
    """TLSClient.rotate_impersonate 应从 settings.TLS_FINGERPRINT_POOL 选取。"""
    from anti_anti_crawl.tls_client import TLSClient

    source = inspect.getsource(TLSClient.rotate_impersonate)
    assert "settings.TLS_FINGERPRINT_POOL" in source, \
        "rotate_impersonate 应从 settings.TLS_FINGERPRINT_POOL 选取新指纹"


def test_tls_fingerprint_pool_same_reference_in_both_modules():
    """hybrid_scraper 和 tls_client 应引用同一 settings.TLS_FINGERPRINT_POOL。"""
    from config.settings import settings
    from crawler.hybrid_scraper import CNKIHybridScraper
    from anti_anti_crawl.tls_client import TLSClient

    # 构造两个实例，验证它们都从同一个 settings 读取
    # 通过修改 settings.TLS_FINGERPRINT_POOL 验证引用关系
    original_pool = settings.TLS_FINGERPRINT_POOL
    try:
        # 添加一个标记指纹
        test_pool = list(original_pool) + ["test_fingerprint_marker"]
        settings.TLS_FINGERPRINT_POOL = test_pool

        # hybrid_scraper._pick_fingerprint 应能从修改后的池中选取
        scraper = CNKIHybridScraper(
            cookies={"_test": "1"},
            output_dir="./_test_output_tmp",
        )
        # 多次选取，应有机会选到标记指纹（或至少不抛异常）
        for _ in range(20):
            fp = scraper._pick_fingerprint()
            assert fp in test_pool, \
                f"_pick_fingerprint 应从 settings.TLS_FINGERPRINT_POOL 选取，实际: {fp}"

        # tls_client.rotate_impersonate 也应从修改后的池中选取
        tls = TLSClient(impersonate="chrome124")
        # 多次轮换
        for _ in range(20):
            new_fp = tls.rotate_impersonate()
            assert new_fp in test_pool, \
                f"rotate_impersonate 应从 settings.TLS_FINGERPRINT_POOL 选取，实际: {new_fp}"

    finally:
        # 恢复原始配置
        settings.TLS_FINGERPRINT_POOL = original_pool


def test_tls_fingerprint_pool_contains_chrome_variants():
    """TLS_FINGERPRINT_POOL 应包含 Chrome 指纹变体。"""
    from config.settings import settings

    chrome_fingerprints = [fp for fp in settings.TLS_FINGERPRINT_POOL if "chrome" in fp.lower()]
    assert len(chrome_fingerprints) > 0, \
        "TLS_FINGERPRINT_POOL 应至少包含一个 Chrome 指纹"


def test_hybrid_scraper_pick_fingerprint_avoids_recent():
    """_pick_fingerprint 应避免最近使用的指纹（历史窗口）。"""
    from crawler.hybrid_scraper import CNKIHybridScraper

    scraper = CNKIHybridScraper(
        cookies={"_test": "1"},
        output_dir="./_test_output_tmp",
    )

    # 模拟历史记录
    from config.settings import settings
    pool = settings.TLS_FINGERPRINT_POOL

    if len(pool) > 1:
        # 设置历史为第一个指纹
        scraper._fingerprint_history = [pool[0]]
        # 选取应避开 pool[0]（如果池中有足够多的指纹）
        chosen = scraper._pick_fingerprint()
        # 如果池大小 > 历史窗口（3），应避开最近的指纹
        if len(pool) > 3:
            assert chosen != pool[0], \
                "_pick_fingerprint 应避开最近使用的指纹"


# ═══════════════════════════════════════════════════════════════
# 测试运行入口
# ═══════════════════════════════════════════════════════════════


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

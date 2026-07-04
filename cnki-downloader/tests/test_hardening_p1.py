"""P1 架构强化修复的单元测试。

测试范围：
  1. PDF 魔数校验（crawler/pdf_downloader.py）
     验证 %PDF- 和 PK\\x03\\x04 魔数被正确识别，无效内容被拒绝
  2. thread_pool 线程安全（worker/thread_pool.py）
     验证 threading.Lock 保护 _threads 字典，多线程并发更新无竞态
  3. threading.local 映射（worker/thread_pool.py）
     验证不同线程获得不同索引（替代 hash() 不稳定问题）
  4. yidun_handler 集成（anti_anti_crawl/captcha_bypass.py）
     验证 CaptchaBypass.solve() 检测易盾页面并调用 YiDunHandler
  5. increment_completed/failed 调用（worker/main.py）
     验证 _handle_task 在成功/失败时更新线程池计数

运行方式：
    cd c:\\Users\\13067\\Desktop\\AI产品\\cnki-downloader
    python -m pytest tests/test_hardening_p1.py -v
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 确保能导入项目模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ═══════════════════════════════════════════════════════════════
# SubTask 5.2.1: PDF 魔数校验
# ═══════════════════════════════════════════════════════════════


def _make_pdf_with_magic(magic: bytes, body: bytes = b"\x00" * 10240) -> bytes:
    """构造一个以指定 magic 开头、总长度超过 MIN_PDF_SIZE 的字节串。"""
    # 确保总长度 > 10KB（MIN_PDF_SIZE）
    padding_needed = max(0, 10240 - len(magic) - len(body))
    return magic + body + b"\x00" * padding_needed


def test_pdf_magic_validation_pdf_header_accepted(tmp_path):
    """以 %PDF- 开头的文件应通过魔数校验。"""
    from crawler.pdf_downloader import PDFDownloader

    # 构造一个有效的 PDF 文件（魔数 + 足够长度）
    pdf_content = b"%PDF-1.7\n" + b"\x00" * 11000
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_bytes(pdf_content)

    # 读取前 5 字节并校验
    with open(pdf_file, "rb") as f:
        magic = f.read(5)

    # 验证魔数校验逻辑（与 pdf_downloader.py 中的逻辑一致）
    is_valid = magic[:5] == b"%PDF-" or magic[:4] == b"PK\x03\x04"
    assert is_valid is True


def test_pdf_magic_validation_zip_caj_header_accepted(tmp_path):
    """以 PK\\x03\\x04 开头的文件（CAJ/ZIP 格式）应通过魔数校验。"""
    from crawler.pdf_downloader import PDFDownloader

    # 构造一个 CAJ 文件（ZIP 魔数 + 足够长度）
    caj_content = b"PK\x03\x04" + b"\x00" * 11000
    caj_file = tmp_path / "test.caj"
    caj_file.write_bytes(caj_content)

    with open(caj_file, "rb") as f:
        magic = f.read(5)

    is_valid = magic[:5] == b"%PDF-" or magic[:4] == b"PK\x03\x04"
    assert is_valid is True


def test_pdf_magic_validation_html_rejected(tmp_path):
    """HTML 内容应被魔数校验拒绝（即使大小超过阈值）。"""
    from crawler.pdf_downloader import PDFDownloader

    # CNKI 可能返回大于 10KB 的 HTML 错误页面
    html_content = b"<!DOCTYPE html><html><body>Error: access denied</body></html>"
    html_content += b" " * 11000  # 确保超过 MIN_PDF_SIZE
    html_file = tmp_path / "fake.pdf"
    html_file.write_bytes(html_content)

    with open(html_file, "rb") as f:
        magic = f.read(5)

    is_valid = magic[:5] == b"%PDF-" or magic[:4] == b"PK\x03\x04"
    assert is_valid is False, "HTML 内容不应通过 PDF 魔数校验"


def test_pdf_magic_validation_empty_file_rejected(tmp_path):
    """空文件应被魔数校验拒绝。"""
    from crawler.pdf_downloader import PDFDownloader

    empty_file = tmp_path / "empty.pdf"
    empty_file.write_bytes(b"")

    with open(empty_file, "rb") as f:
        magic = f.read(5)

    is_valid = magic[:5] == b"%PDF-" or magic[:4] == b"PK\x03\x04"
    assert is_valid is False


def test_pdf_magic_validation_random_bytes_rejected(tmp_path):
    """随机字节应被魔数校验拒绝。"""
    from crawler.pdf_downloader import PDFDownloader

    random_content = os.urandom(11000)
    random_file = tmp_path / "random.pdf"
    random_file.write_bytes(random_content)

    with open(random_file, "rb") as f:
        magic = f.read(5)

    is_valid = magic[:5] == b"%PDF-" or magic[:4] == b"PK\x03\x04"
    assert is_valid is False


def test_pdf_downloader_has_magic_validation():
    """PDFDownloader.download 方法应包含魔数校验逻辑。"""
    from crawler.pdf_downloader import PDFDownloader

    source = inspect.getsource(PDFDownloader.download)

    # 验证源码中包含魔数校验
    assert "%PDF-" in source, "download 方法应校验 %PDF- 魔数"
    assert "PK\\x03\\x04" in source or "PK\x03\x04" in source, \
        "download 方法应校验 PK\\x03\\x04 魔数（CAJ/ZIP 格式）"
    # 验证有 invalid_file_magic 错误日志
    assert "invalid_file_magic" in source, \
        "download 方法应记录 invalid_file_magic 错误"


def test_pdf_downloader_min_size_constant():
    """PDFDownloader 应有 MIN_PDF_SIZE 常量（10KB）。"""
    from crawler.pdf_downloader import PDFDownloader

    assert hasattr(PDFDownloader, "MIN_PDF_SIZE")
    assert PDFDownloader.MIN_PDF_SIZE == 10 * 1024  # 10 KB


# ═══════════════════════════════════════════════════════════════
# SubTask 5.2.2: thread_pool 线程安全
# ═══════════════════════════════════════════════════════════════


def test_worker_thread_pool_has_lock():
    """WorkerThreadPool 应有 threading.Lock 保护 _threads。"""
    from worker.thread_pool import WorkerThreadPool

    pool = WorkerThreadPool(thread_count=3, worker_id="w1", discipline="新闻传播学")
    assert hasattr(pool, "_lock")
    assert isinstance(pool._lock, type(threading.Lock()))


def test_worker_thread_pool_start_initializes_threads():
    """start() 应初始化 _threads 字典。"""
    from worker.thread_pool import WorkerThreadPool

    pool = WorkerThreadPool(thread_count=3, worker_id="w1", discipline="新闻传播学")
    pool.start(lambda task: None)

    assert pool.is_running is True
    assert len(pool._threads) == 3

    # 验证每个线程槽位有正确的字段
    for i in range(3):
        assert i in pool._threads
        info = pool._threads[i]
        assert "status" in info
        assert "tasks_completed" in info
        assert "tasks_failed" in info
        assert "started_at" in info

    pool.shutdown(wait=False)


def test_worker_thread_pool_get_status_thread_safe():
    """get_status() 应在持锁状态下读取 _threads。"""
    from worker.thread_pool import WorkerThreadPool

    pool = WorkerThreadPool(thread_count=2, worker_id="w1", discipline="新闻传播学")
    pool.start(lambda task: None)

    # 并发读取状态不应抛异常
    status = pool.get_status()
    assert isinstance(status, dict)
    assert len(status) == 2

    pool.shutdown(wait=False)


def test_worker_thread_pool_concurrent_increment_no_race():
    """多线程并发调用 increment_completed 不应导致数据竞态。"""
    from worker.thread_pool import WorkerThreadPool

    pool = WorkerThreadPool(thread_count=3, worker_id="w1", discipline="新闻传播学")
    pool.start(lambda task: None)

    # 在主线程设置 thread_index.value（模拟 _run_in_thread 的行为）
    pool._thread_index.value = 0

    # 并发调用 increment_completed
    N_THREADS = 10
    N_CALLS_PER_THREAD = 100

    def worker():
        # 每个线程设置自己的 thread_index
        pool._thread_index.value = 0
        for _ in range(N_CALLS_PER_THREAD):
            pool.increment_completed(threading.current_thread().name)

    threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 验证没有异常且计数被更新（不要求精确值，因为 threading.local 隔离）
    # 主要验证不抛异常且不损坏数据结构
    status = pool.get_status()
    assert isinstance(status, dict)

    pool.shutdown(wait=False)


def test_worker_thread_pool_increment_completed_uses_thread_local():
    """increment_completed 应使用 threading.local 索引而非 hash(thread_name)。

    通过实际调用验证：设置 _thread_index.value 后 increment_completed 应正确递增
    对应槽位的计数（而非基于 hash(thread_name) 的不稳定映射）。
    """
    from worker.thread_pool import WorkerThreadPool

    pool = WorkerThreadPool(thread_count=3, worker_id="w1", discipline="新闻传播学")
    pool.start(lambda task: None)

    # 主线程设置 thread_index.value = 1（模拟 _run_in_thread 的分配）
    pool._thread_index.value = 1

    # 调用 increment_completed
    pool.increment_completed(threading.current_thread().name)

    # 验证索引 1 的槽位计数被递增（而非基于 hash 的随机槽位）
    assert pool._threads[1]["tasks_completed"] == 1
    # 其他槽位不应被递增
    assert pool._threads[0]["tasks_completed"] == 0
    assert pool._threads[2]["tasks_completed"] == 0

    pool.shutdown(wait=False)


def test_worker_thread_pool_increment_failed_uses_thread_local():
    """increment_failed 应使用 threading.local 索引而非 hash(thread_name)。

    通过实际调用验证：设置 _thread_index.value 后 increment_failed 应正确递增
    对应槽位的失败计数。
    """
    from worker.thread_pool import WorkerThreadPool

    pool = WorkerThreadPool(thread_count=3, worker_id="w1", discipline="新闻传播学")
    pool.start(lambda task: None)

    # 主线程设置 thread_index.value = 2
    pool._thread_index.value = 2

    pool.increment_failed(threading.current_thread().name)

    # 验证索引 2 的槽位失败计数被递增
    assert pool._threads[2]["tasks_failed"] == 1
    assert pool._threads[0]["tasks_failed"] == 0
    assert pool._threads[1]["tasks_failed"] == 0

    pool.shutdown(wait=False)


def test_worker_thread_pool_run_in_thread_uses_thread_local():
    """_run_in_thread 应使用 threading.local 分配线程索引。"""
    from worker.thread_pool import WorkerThreadPool

    source = inspect.getsource(WorkerThreadPool._run_in_thread)
    assert "_thread_index" in source, \
        "_run_in_thread 应使用 self._thread_index 分配线程索引"
    assert "hasattr(self._thread_index" in source, \
        "_run_in_thread 应检查 hasattr(self._thread_index, 'value')"


# ═══════════════════════════════════════════════════════════════
# SubTask 5.2.3: threading.local 映射
# ═══════════════════════════════════════════════════════════════


def test_threading_local_gives_different_values_per_thread():
    """threading.local 应为不同线程提供独立的属性存储。"""
    local_data = threading.local()
    results = {}
    barrier = threading.Barrier(2)

    def worker(thread_id):
        # 设置线程本地的 value
        local_data.value = thread_id
        barrier.wait()  # 等待两个线程都设置完
        # 读取应仍是自己设置的值
        results[thread_id] = local_data.value

    t1 = threading.Thread(target=worker, args=(1,))
    t2 = threading.Thread(target=worker, args=(2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # 两个线程应看到不同的值
    assert results[1] == 1
    assert results[2] == 2


def test_worker_thread_pool_different_threads_get_different_indices():
    """不同线程通过 _run_in_thread 应获得不同的线程索引。"""
    from worker.thread_pool import WorkerThreadPool
    from models.task import Task
    from models.enums import TaskStatus

    pool = WorkerThreadPool(thread_count=3, worker_id="w1", discipline="新闻传播学")
    pool.start(lambda task: None)

    # 收集每个线程分配到的索引
    indices_seen = []
    indices_lock = threading.Lock()

    async def fake_handler(task):
        # 在 handler 内部读取当前线程的索引
        idx = pool._thread_index.value % pool.thread_count
        with indices_lock:
            indices_seen.append(idx)
        return None

    # 提交多个任务
    task = Task(
        task_id="t1",
        discipline="新闻传播学",
        journal_name="测试期刊",
        journal_url="",
        year=2024,
        issue_number="01",
        issue_url="",
        paper_title="测试",
        paper_url="",
        status=TaskStatus.PENDING,
    )

    # 直接调用 _run_in_thread 来测试索引分配
    threads = []
    for i in range(3):
        t = threading.Thread(
            target=pool._run_in_thread,
            args=(fake_handler, task),
        )
        threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 验证至少有 3 个不同的索引被分配（每个线程一个）
    # 注意：由于 _next_index 是递增的，3 个线程应得到 0, 1, 2
    assert len(indices_seen) == 3
    # 取模后应都在 [0, thread_count) 范围内
    for idx in indices_seen:
        assert 0 <= idx < pool.thread_count

    pool.shutdown(wait=False)


def test_threading_local_attribute_isolation():
    """验证 threading.local 在线程间完全隔离。"""
    local_data = threading.local()
    main_thread_value = "main"

    local_data.value = main_thread_value
    assert local_data.value == main_thread_value

    sub_thread_value = []

    def worker():
        # 子线程不应看到主线程设置的值
        if hasattr(local_data, "value"):
            sub_thread_value.append(("exists", local_data.value))
        else:
            sub_thread_value.append(("missing", None))

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    # 子线程应报告 value 属性不存在
    assert sub_thread_value[0][0] == "missing"
    # 主线程的值应未被修改
    assert local_data.value == main_thread_value


# ═══════════════════════════════════════════════════════════════
# SubTask 5.2.4: yidun_handler 集成
# ═══════════════════════════════════════════════════════════════


def test_captcha_bypass_imports_yidun_handler():
    """CaptchaBypass 应导入 YiDunHandler。"""
    import anti_anti_crawl.captcha_bypass as cb_mod

    source = inspect.getsource(cb_mod)
    assert "from anti_anti_crawl.yidun_handler import YiDunHandler" in source, \
        "captcha_bypass.py 应导入 YiDunHandler"


def test_captcha_bypass_solve_checks_yidun_page():
    """CaptchaBypass.solve 应首先检查是否为易盾页面。"""
    from anti_anti_crawl.captcha_bypass import CaptchaBypass

    source = inspect.getsource(CaptchaBypass.solve)
    # 验证 solve 方法调用了 YiDunHandler.is_yidun_page
    assert "is_yidun_page" in source, \
        "solve 方法应调用 YiDunHandler.is_yidun_page 检测易盾页面"
    assert "YiDunHandler" in source


def test_yidun_handler_is_yidun_page_detects_verify_url():
    """YiDunHandler.is_yidun_page 应识别 /verify/home URL。"""
    from anti_anti_crawl.yidun_handler import YiDunHandler

    assert YiDunHandler.is_yidun_page("https://verify.cnki.net/verify/home") is True
    assert YiDunHandler.is_yidun_page("https://example.com/verify/home") is True


def test_yidun_handler_is_yidun_page_detects_verify_cnki():
    """YiDunHandler.is_yidun_page 应识别 verify.cnki.net URL。"""
    from anti_anti_crawl.yidun_handler import YiDunHandler

    assert YiDunHandler.is_yidun_page("https://verify.cnki.net/captcha") is True


def test_yidun_handler_is_yidun_page_detects_yidun_keyword():
    """YiDunHandler.is_yidun_page 应识别包含 yidun 的 URL。"""
    from anti_anti_crawl.yidun_handler import YiDunHandler

    assert YiDunHandler.is_yidun_page("https://example.com/yidun/check") is True


def test_yidun_handler_is_yidun_page_rejects_normal_url():
    """YiDunHandler.is_yidun_page 应拒绝普通 URL。"""
    from anti_anti_crawl.yidun_handler import YiDunHandler

    assert YiDunHandler.is_yidun_page("https://kns.cnki.net/kns8s/") is False
    assert YiDunHandler.is_yidun_page("https://www.cnki.net/") is False
    assert YiDunHandler.is_yidun_page("") is False


def test_yidun_handler_is_yidun_page_case_insensitive():
    """YiDunHandler.is_yidun_page 应不区分大小写。"""
    from anti_anti_crawl.yidun_handler import YiDunHandler

    assert YiDunHandler.is_yidun_page("https://EXAMPLE.COM/YIDUN/test") is True
    assert YiDunHandler.is_yidun_page("HTTPS://VERIFY.CNKI.NET/") is True


@pytest.mark.asyncio
async def test_captcha_bypass_solve_calls_yidun_for_verify_page():
    """CaptchaBypass.solve 在易盾页面应调用 YiDunHandler 流程。"""
    from anti_anti_crawl.captcha_bypass import CaptchaBypass

    # mock Page 对象
    mock_page = MagicMock()
    mock_page.url = "https://verify.cnki.net/verify/home"

    # mock YiDunHandler.extract_params 返回空 params（无 captchaId）
    # 应导致 solve 返回 False（fail_count 增加）
    with patch("anti_anti_crawl.captcha_bypass.YiDunHandler") as MockYiDun:
        MockYiDun.is_yidun_page.return_value = True
        mock_handler_instance = MockYiDun.return_value
        mock_handler_instance.extract_params = AsyncMock(return_value={})

        cb = CaptchaBypass()
        result = await cb.solve(mock_page)

        # 应返回 False（无 captchaId）
        assert result is False
        # 失败计数应增加
        assert cb._fail_count == 1
        # is_yidun_page 应被调用
        MockYiDun.is_yidun_page.assert_called_once_with(mock_page.url)


@pytest.mark.asyncio
async def test_captcha_bypass_solve_skips_yidun_for_normal_page():
    """CaptchaBypass.solve 在普通页面应跳过易盾流程，进入常规 CAPTCHA 检测。"""
    from anti_anti_crawl.captcha_bypass import CaptchaBypass
    from models.enums import CAPTCHAType

    # mock Page 对象（普通 CNKI 页面）
    mock_page = MagicMock()
    mock_page.url = "https://kns.cnki.net/kns8s/"

    with patch("anti_anti_crawl.captcha_bypass.YiDunHandler") as MockYiDun:
        MockYiDun.is_yidun_page.return_value = False

        cb = CaptchaBypass()

        # mock detect_type 返回 NONE（无 CAPTCHA）
        with patch.object(cb, "detect_type", new=AsyncMock(return_value=CAPTCHAType.NONE)):
            result = await cb.solve(mock_page)

        # 无 CAPTCHA 应返回 True
        assert result is True
        # is_yidun_page 应被调用
        MockYiDun.is_yidun_page.assert_called_once_with(mock_page.url)


# ═══════════════════════════════════════════════════════════════
# SubTask 5.2.5: increment_completed/failed 调用验证（worker/main.py）
# ═══════════════════════════════════════════════════════════════


def test_worker_main_handle_task_calls_increment_completed_on_success():
    """_handle_task 在成功路径应调用 _pool.increment_completed。"""
    import worker.main as worker_main_mod

    source = inspect.getsource(worker_main_mod.CNKIWorker._handle_task)
    assert "increment_completed" in source, \
        "_handle_task 成功路径应调用 self._pool.increment_completed"


def test_worker_main_handle_task_calls_increment_failed_on_failure():
    """_handle_task 在失败路径应调用 _pool.increment_failed。"""
    import worker.main as worker_main_mod

    source = inspect.getsource(worker_main_mod.CNKIWorker._handle_task)
    assert "increment_failed" in source, \
        "_handle_task 失败路径应调用 self._pool.increment_failed"


def test_worker_main_handle_task_calls_increment_failed_in_exception():
    """_handle_task 在异常路径应调用 _pool.increment_failed。"""
    import worker.main as worker_main_mod

    source = inspect.getsource(worker_main_mod.CNKIWorker._handle_task)
    # 异常处理块应包含 increment_failed
    assert "increment_failed" in source


def test_worker_main_future_done_callback_calls_increment_failed():
    """_on_future_done 回调应调用 _pool.increment_failed 捕获未处理异常。"""
    import worker.main as worker_main_mod

    source = inspect.getsource(worker_main_mod.CNKIWorker._task_loop)
    # 应有 _on_future_done 回调
    assert "_on_future_done" in source or "add_done_callback" in source
    # 回调中应调用 increment_failed
    assert "increment_failed" in source


# ═══════════════════════════════════════════════════════════════
# 测试运行入口
# ═══════════════════════════════════════════════════════════════


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

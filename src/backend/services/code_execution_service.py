"""
ScholarMind 代码执行沙箱服务

使用 subprocess + 临时文件方式执行 Python 代码,提供基本的隔离与超时控制。
Windows 下跳过 resource.setrlimit(仅 Linux 可用),依赖 timeout 兜底。

安全策略:
1. 代码静态预检: 扫描危险导入与模式 (os/subprocess/shutil/socket/eval/exec 等)
2. 环境变量隔离: 执行前清除敏感环境变量 (API keys, DB credentials)
3. 工作目录隔离: 在独立临时目录中执行,限制文件系统访问范围
4. 代码大小限制: 防止超大代码消耗资源
5. 超时控制: 强制终止长时间运行的进程
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
import time
from typing import Any, Optional

from ..core.logging_config import get_logger

logger = get_logger(__name__)

# ── 安全配置 ──────────────────────────────────────────────
# 危险模块黑名单: 禁止导入这些模块
DANGEROUS_IMPORTS: frozenset[str] = frozenset({
    "os", "subprocess", "shutil", "socket", "http.server",
    "ftplib", "telnetlib", "smtplib", "urllib.request",
    "http.client", "ssl", "multiprocessing", "threading",
    "signal", "ctypes", "cffi", "winreg", "msvcrt",
    "_winapi", "nt", "posix", "fcntl", "resource",
    "sysconfig", "importlib", "imp", "builtins",
})

# 危险模式正则: 检测危险函数调用与属性访问
DANGEROUS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b__import__\s*\("),
    re.compile(r"\beval\s*\("),
    re.compile(r"\bexec\s*\("),
    re.compile(r"\bcompile\s*\("),
    re.compile(r"\bgetattr\s*\(\s*[^,]*,\s*['\"]__"),
    re.compile(r"\bopen\s*\(\s*['\"](?:/|\\\\|[A-Za-z]:[\\\\/])"),  # 绝对路径访问
    re.compile(r"\bos\.system\b"),
    re.compile(r"\bsubprocess\.\w+\s*\("),
    re.compile(r"\bshutil\.\w+\s*\("),
    re.compile(r"\bsocket\.\w+\s*\("),
    re.compile(r"\bctypes\.\w+\s*\("),
    re.compile(r"\bglobals\s*\(\s*\)"),
    re.compile(r"\blocals\s*\(\s*\)"),
    re.compile(r"\bvars\s*\(\s*\)"),
    re.compile(r"\bdir\s*\(\s*\)"),
    re.compile(r"\b__\w+__\s*\("),  # 魔术方法调用
)

# 敏感环境变量前缀: 执行前清除
SENSITIVE_ENV_PREFIXES: tuple[str, ...] = (
    "DEEPSEEK_", "SEMANTIC_SCHOLAR_", "CNKI_", "JWT_", "WECHAT_",
    "ALIPAY_", "REDIS_", "CELERY_", "DATABASE_",
    "API_KEY", "SECRET", "PASSWORD", "TOKEN",
)

# 代码大小限制
MAX_CODE_SIZE: int = 100_000  # 100KB
MAX_CODE_LINES: int = 2000


class CodeSecurityError(Exception):
    """代码安全检查失败"""


def _scan_dangerous_code(code: str) -> Optional[str]:
    """静态扫描代码中的危险导入与模式

    Returns:
        命中的危险描述字符串, 无危险返回 None
    """
    if len(code) > MAX_CODE_SIZE:
        return f"代码过大({len(code)} 字节, 上限 {MAX_CODE_SIZE})"
    if code.count("\n") + 1 > MAX_CODE_LINES:
        return f"代码行数过多({code.count(chr(10)) + 1} 行, 上限 {MAX_CODE_LINES})"

    # 提取所有 import 语句中的模块名
    import_pattern = re.compile(
        r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))",
        re.MULTILINE,
    )
    for match in import_pattern.finditer(code):
        module = (match.group(1) or match.group(2) or "").split(".")[0]
        if module in DANGEROUS_IMPORTS:
            return f"禁止导入危险模块: {module}"

    # 检测危险模式
    for pattern in DANGEROUS_PATTERNS:
        match = pattern.search(code)
        if match:
            return f"检测到危险模式: {match.group(0)}"

    return None


def _build_sanitized_env() -> dict[str, str]:
    """构建清除敏感信息后的环境变量字典"""
    sanitized: dict[str, str] = {}
    for key, value in os.environ.items():
        # 跳过敏感变量
        if any(key.upper().startswith(prefix) for prefix in SENSITIVE_ENV_PREFIXES):
            continue
        # 跳过空值
        if value:
            sanitized[key] = value
    # 保留 Python 运行必需的环境变量
    sanitized.setdefault("PYTHONPATH", "")
    sanitized.setdefault("PYTHONIOENCODING", "utf-8")
    return sanitized


class CodeExecutionService:
    """代码执行沙箱服务"""

    def __init__(self) -> None:
        self._python_executable = sys.executable or "python"

    async def execute_code(self, code: str, language: str = "python", timeout: int = 30) -> dict[str, Any]:
        """执行 Python 代码

        Args:
            code: 要执行的代码内容
            language: 编程语言(目前仅支持 python)
            timeout: 超时时间(秒)

        Returns:
            dict: {success, stdout, stderr, exit_code, duration_ms}
        """
        if language.lower() != "python":
            return {
                "success": False,
                "stdout": "",
                "stderr": f"暂不支持的语言: {language}(目前仅支持 python)",
                "exit_code": -1,
                "duration_ms": 0,
                "error": "unsupported_language",
            }

        # 安全预检
        danger = _scan_dangerous_code(code)
        if danger:
            logger.warning(f"代码安全检查失败: {danger}")
            return {
                "success": False,
                "stdout": "",
                "stderr": f"代码安全检查失败: {danger}",
                "exit_code": -1,
                "duration_ms": 0,
                "error": "security_violation",
            }

        # 创建隔离工作目录
        work_dir = tempfile.mkdtemp(prefix="scholarmind_sandbox_")
        # 写入临时文件
        fd, temp_path = tempfile.mkstemp(
            suffix=".py", prefix="scholarmind_exec_", dir=work_dir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(code)

            start_time = time.time()
            logger.info(f"开始执行代码, 超时={timeout}s, 文件={temp_path}, 工作目录={work_dir}")

            # 构建清除敏感信息的环境变量
            sanitized_env = _build_sanitized_env()

            # 在线程池中执行 subprocess 以避免阻塞事件循环
            try:
                proc = await asyncio.create_subprocess_exec(
                    self._python_executable,
                    "-I",  # 隔离模式: 不读取 .pth / sitecustomize / PYTHONPATH
                    "-B",  # 不生成 .pyc
                    temp_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=work_dir,
                    env=sanitized_env,
                )
            except Exception as e:
                logger.error(f"启动子进程失败: {e}")
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"启动子进程失败: {e}",
                    "exit_code": -1,
                    "duration_ms": int((time.time() - start_time) * 1000),
                    "error": "subprocess_start_failed",
                }

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                exit_code = proc.returncode if proc.returncode is not None else -1
                duration_ms = int((time.time() - start_time) * 1000)

                stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
                stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

                # 截断过长输出
                if len(stdout) > 50000:
                    stdout = stdout[:50000] + "\n...(输出被截断)"
                if len(stderr) > 50000:
                    stderr = stderr[:50000] + "\n...(错误输出被截断)"

                logger.info(f"代码执行完成, exit_code={exit_code}, duration={duration_ms}ms")

                return {
                    "success": exit_code == 0,
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": exit_code,
                    "duration_ms": duration_ms,
                }
            except asyncio.TimeoutError:
                # 超时,终止进程
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                duration_ms = int((time.time() - start_time) * 1000)
                logger.warning("代码执行超时(%ss)", timeout)
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": f"代码执行超时(超过 {timeout} 秒)",
                    "exit_code": -1,
                    "duration_ms": duration_ms,
                    "error": "timeout",
                }
        finally:
            # 清理临时文件与工作目录
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            try:
                import shutil
                shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass

    # P0 Task 1.4: pip install 已永久禁用。路由端点已移除，此方法不再被任何代码路径调用。
    # 保留原实现供归档参考，但始终返回禁用响应。如需在受控环境安装依赖，
    # 请在 Dockerfile 构建阶段固化到 requirements.txt。
    _PIP_INSTALL_ENABLED: bool = False

    async def execute_pip_install(self, package: str) -> dict[str, Any]:
        """执行 pip install（已永久禁用）"""
        if not self._PIP_INSTALL_ENABLED:
            return {
                "success": False,
                "message": "pip install 端点已永久禁用",
                "stdout": "",
                "stderr": "pip_install_permanently_disabled",
            }
        # ----- 以下原始实现仅供存档，_PIP_INSTALL_ENABLED=False 时不可达 -----
        # 安全检查: 禁止本地路径安装
        if package.startswith(("/", "\\", ".")) or "://" in package:
            return {
                "success": False,
                "message": "禁止从本地路径或 URL 安装包",
                "stdout": "",
                "stderr": "invalid_package_source",
            }

        # 安全检查: 包名格式校验 (允许字母/数字/._- 与版本运算符)
        # 防止命令注入 (如 "requests; rm -rf /")
        package_pattern = re.compile(
            r"^[A-Za-z0-9][A-Za-z0-9._-]*"
            r"(?:[<>=!~]=?\s*[A-Za-z0-9.*+!._-]+)*$"
        )
        if not package_pattern.match(package.strip()):
            return {
                "success": False,
                "message": "包名格式非法(可能包含命令注入)",
                "stdout": "",
                "stderr": "invalid_package_name",
            }

        # 安全检查: 禁止安装已知危险包
        DANGEROUS_PACKAGES: frozenset[str] = frozenset({
            "subprocess", "pty", "shutil", "psutil",
        })
        base_name = re.split(r"[<>=!~]", package)[0].strip().lower()
        if base_name in DANGEROUS_PACKAGES:
            return {
                "success": False,
                "message": f"禁止安装危险包: {base_name}",
                "stdout": "",
                "stderr": "dangerous_package",
            }

        logger.info("执行 pip install %s", package)

        try:
            proc = await asyncio.create_subprocess_exec(
                self._python_executable,
                "-m",
                "pip",
                "install",
                "--no-warn-script-location",
                package,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_build_sanitized_env(),
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=120)
            exit_code = proc.returncode if proc.returncode is not None else -1

            stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

            if exit_code == 0:
                return {
                    "success": True,
                    "message": f"成功安装包: {package}",
                    "stdout": stdout,
                    "stderr": stderr,
                }
            else:
                return {
                    "success": False,
                    "message": f"安装失败(exit_code={exit_code})",
                    "stdout": stdout,
                    "stderr": stderr,
                }
        except asyncio.TimeoutError:
            return {
                "success": False,
                "message": "安装超时(超过 120 秒)",
                "stdout": "",
                "stderr": "timeout",
            }
        except Exception as e:
            logger.error("pip install 异常: %s", e)
            return {
                "success": False,
                "message": f"安装异常: {e}",
                "stdout": "",
                "stderr": str(e),
            }

    async def list_installed_packages(self) -> dict[str, Any]:
        """列出已安装的包

        Returns:
            dict: {success, packages, total}
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                self._python_executable,
                "-m",
                "pip",
                "list",
                "--format=json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_build_sanitized_env(),
            )
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""

            import json
            packages = json.loads(stdout) if stdout.strip() else []
            return {
                "success": True,
                "packages": packages,
                "total": len(packages),
            }
        except Exception as e:
            logger.error(f"列出已安装包失败: {e}")
            return {
                "success": False,
                "packages": [],
                "total": 0,
                "error": str(e),
            }


# 单例
_code_execution_service: Optional[CodeExecutionService] = None


def get_code_execution_service() -> CodeExecutionService:
    """获取 CodeExecutionService 单例"""
    global _code_execution_service
    if _code_execution_service is None:
        _code_execution_service = CodeExecutionService()
    return _code_execution_service

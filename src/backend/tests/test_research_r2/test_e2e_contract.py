"""R2 E2E 脚本的静态契约（T20 / AT-047·AT-048）。

浏览器验收本身需要 Playwright（当前未安装，见 ``docs/reports/R2_E2E.md``），
所以这里只锁定"脚本不许假装通过"的契约：

* 静态服务必须用 ``dist/`` 的模块化产物，不能用原型 HTML，也不能连生产库；
* 后端必须用临时 SQLite + 模型替身 + ``ENVIRONMENT=test`` 起隔离实例；
* 缺 Playwright 时必须以退出码 ``3`` 失败，而不是打印成功。

真实浏览器交互不在本套件重复：用户界面验收由 ``npm run test:research:e2e``
与 Lead 手动验收负责（AT-047/AT-053 需真实浏览器）。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "research_e2e.mjs"
PLAYWRIGHT_DIR = REPO_ROOT / "node_modules" / "playwright"


def test_script_serves_built_dist_in_isolation():
    script = SCRIPT.read_text(encoding="utf-8")

    # 用构建产物而不是原型 HTML；路径由 ROOT 推导，不写死开发者绝对路径。
    assert "const DIST = path.join(ROOT, 'dist')" in script
    assert "dist/index.html" in script

    # 后端隔离：临时 SQLite + 模型替身 + test 环境，不触碰真实库/真实模型。
    assert "DATABASE_URL: sqliteUrl" in script
    assert "RESEARCH_MODEL_STUB: 'true'" in script
    assert "ENVIRONMENT: 'test'" in script

    # 缺依赖时按契约失败：PlaywrightMissingError → exit 3，且打印安装命令。
    assert "PlaywrightMissingError" in script
    assert "npm i -D playwright && npx playwright install chromium" in script
    assert "const EXIT_PLAYWRIGHT = 3;" in script
    assert "return EXIT_PLAYWRIGHT;" in script


def test_missing_playwright_exits_three_not_success():
    if shutil.which("node") is None:
        pytest.skip("本机没有 node，无法执行 E2E 脚本")
    if PLAYWRIGHT_DIR.exists():
        pytest.skip("playwright 已安装；浏览器验收应由 E2E 实际执行，不在本套件重复")

    completed = subprocess.run(
        ["node", str(SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )

    assert completed.returncode == 3, completed.stdout + completed.stderr
    output = (completed.stdout + completed.stderr).lower()
    assert "playwright" in output
    assert "缺少浏览器驱动" in completed.stdout + completed.stderr
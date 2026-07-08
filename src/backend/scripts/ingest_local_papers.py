"""
本地论文库摄入脚本

将 C:\\Users\\13067\\.trae-cn\\数据库\\ 下的 MD 论文文件批量导入
SQLite（academic_resources 表）和 ChromaDB 向量索引，使 Agent 可通过 RAG 检索。

用法：
    cd src/backend
    python -m scripts.ingest_local_papers

    或从项目根目录：
    python -m src.backend.scripts.ingest_local_papers
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# 确保项目根在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.config import settings
from src.backend.core.logging_config import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)

# ── 外部数据库目录 ─────────────────────────────────────────
EXTERNAL_DB = Path(os.environ.get("LOCAL_PAPERS_DIR", "C:/Users/13067/.trae-cn/数据库"))
PAPERS_DIR = EXTERNAL_DB / "论文"
MD_FILES_DIR = EXTERNAL_DB / "md_files"
ANALYSIS_DIR = EXTERNAL_DB / "scholar_analysis"

SOURCE_DB_TAG = "local_md"  # source_db 标签，区分本地导入与爬虫采集


def _file_md5(filepath: Path) -> str:
    """计算文件 MD5 作为稳定 ID"""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_title_from_filename(filename: str) -> str:
    """从文件名提取标题：去掉编号前缀和年份后缀"""
    name = Path(filename).stem
    # 格式: {编号}_{标题}_{年份} 或 {编号}_{标题}
    # 去掉开头的编号 (如 001_)
    name = re.sub(r"^\d{3,4}_", "", name)
    # 去掉结尾的年份标签 (如 _2024y1q)
    name = re.sub(r"_\d{4}y\d+q.*$", "", name)
    return name.strip()


def _extract_year_from_filename(filename: str) -> str:
    """从文件名提取年份"""
    match = re.search(r"_(\d{4})y", filename)
    if match:
        return match.group(1)
    return ""


def _parse_paper_md(filepath: Path) -> dict | None:
    """解析单篇论文 MD 文件，提取元数据

    期望格式：
        # 标题
        **作者**: ... | **来源**: ... | **页数**: ...
        (正文/摘要)
        关 键 词：...
    """
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"读取文件失败: {filepath.name}: {e}")
        return None

    lines = content.split("\n")

    # ── 标题 ──
    title = ""
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
    if not title:
        title = _extract_title_from_filename(filepath.name)

    # ── 作者 / 来源 ──
    authors = ""
    source = ""
    for line in lines[1:10]:
        line = line.strip()
        # **作者**: 汪　宁　程大中 | **来源**: 《财贸经济》2024年第1期 | **页数**: 19页
        author_match = re.search(r"\*\*作者\*\*[:：]\s*(.+?)(?:\s*\||$)", line)
        if author_match:
            authors = author_match.group(1).strip()
            # 清理全角空格
            authors = re.sub(r"\s+", " ", authors.replace("　", " "))
        source_match = re.search(r"\*\*来源\*\*[:：]\s*(.+?)(?:\s*\||$)", line)
        if source_match:
            source = source_match.group(1).strip()

    # ── 关键词 ──
    keywords = ""
    kw_match = re.search(r"关\s*键\s*词\s*[：:]\s*(.+)$", content, re.MULTILINE)
    if kw_match:
        keywords = kw_match.group(1).strip()

    # ── 摘要：取正文前 500 字符 ──
    # 跳过标题行、元数据行、空行、关键词行
    body_start = 0
    for i, line in enumerate(lines):
        if i == 0 and line.startswith("# "):
            continue
        if re.match(r"^\*\*作者\*\*", line) or re.match(r"^\*\*来源\*\*", line):
            continue
        if re.match(r"^[A-Z].*Vol\.[\s\d,]+20\d{2}", line):  # 期刊英文信息行
            continue
        if not line.strip():  # 空行，跳过
            continue
        if re.match(r"内容提要", line):
            body_start = i + 1
            break
        body_start = i + 1

    # 收集摘要文本（跳过空行，取前 500 字符）
    abstract_parts = []
    for line in lines[body_start:]:
        stripped = line.strip()
        if not stripped:
            if abstract_parts:
                break  # 第一段结束
            continue
        # 跳过关键词行和作者简介行
        if re.match(r"关\s*键\s*词", stripped) or re.match(r"作者简介", stripped):
            break
        if re.match(r"中图分类号", stripped) or re.match(r"JEL", stripped):
            break
        abstract_parts.append(stripped)

    abstract = " ".join(abstract_parts)[:500] if abstract_parts else ""

    # ── 年份 ──
    year = _extract_year_from_filename(filepath.name)
    if not year and source:
        year_match = re.search(r"(\d{4})", source)
        if year_match:
            year = year_match.group(1)

    # ── 构建资源 dict ──
    file_md5 = _file_md5(filepath)
    # 标题中包含特殊字符（如书名号、全角字符），取 MD5 前 16 位作为 ID
    doc_id = f"local_{file_md5[:16]}"

    resource = {
        "id": doc_id,
        "title": title,
        "authors": authors,
        "year": year,
        "source": source,
        "source_db": SOURCE_DB_TAG,
        "abstract": abstract,
        "doi": "",
        "citations": 0,
        "is_core": False,
        "keywords": json.dumps([k.strip() for k in keywords.replace("；", ";").split(";") if k.strip()], ensure_ascii=False) if keywords else "[]",
        "url": str(filepath),
        "full_text_hash": file_md5,
        "crawled_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    return resource


def _parse_md_files_paper(filepath: Path, discipline: str, journal: str) -> dict | None:
    """解析 md_files 目录下的论文（格式可能略有不同）"""
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"读取文件失败: {filepath.name}: {e}")
        return None

    lines = content.split("\n")

    # 尝试提取标题
    title = ""
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
    if not title:
        title = _extract_title_from_filename(filepath.name)

    # 提取年份
    year = _extract_year_from_filename(filepath.name)

    # 摘要：取正文前 300 字符
    abstract_parts = []
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if len(" ".join(abstract_parts)) > 300:
            break
        abstract_parts.append(stripped)
    abstract = " ".join(abstract_parts)[:300]

    file_md5 = _file_md5(filepath)
    doc_id = f"local_{file_md5[:16]}"

    resource = {
        "id": doc_id,
        "title": title,
        "authors": "",
        "year": year,
        "source": f"{journal} ({discipline})",
        "source_db": f"{SOURCE_DB_TAG}_{discipline}",
        "abstract": abstract,
        "doi": "",
        "citations": 0,
        "is_core": False,
        "keywords": json.dumps([discipline, journal], ensure_ascii=False),
        "url": str(filepath),
        "full_text_hash": file_md5,
        "crawled_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    return resource


def _parse_scholar_analysis(filepath: Path) -> dict | None:
    """解析文风分析文件"""
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"读取文件失败: {filepath.name}: {e}")
        return None

    title = Path(filepath).stem
    # 摘要用内容前 500 字符
    abstract = content[:500].replace("\n", " ").strip()

    file_md5 = _file_md5(filepath)
    doc_id = f"local_sa_{file_md5[:16]}"

    resource = {
        "id": doc_id,
        "title": f"[文风分析] {title}",
        "authors": "",
        "year": "",
        "source": "ScholarMind Scholar Analysis",
        "source_db": "local_scholar_analysis",
        "abstract": abstract,
        "doi": "",
        "citations": 0,
        "is_core": False,
        "keywords": json.dumps(["文风分析", "学术写作"], ensure_ascii=False),
        "url": str(filepath),
        "full_text_hash": file_md5,
        "crawled_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    return resource


def main():
    """主入口：扫描所有论文并导入"""
    print("=" * 60)
    print("ScholarMind 本地论文库摄入工具")
    print(f"外部数据库: {EXTERNAL_DB}")
    print(f"SQLite 库:   {settings.DB_PATH}")
    print(f"ChromaDB:    {settings.CHROMA_DIR}")
    print("=" * 60)

    # ── 初始化服务 ──
    from src.backend.services.db_service import get_db_service
    from src.backend.services.vector_service import get_vector_service

    db = get_db_service()
    vector = get_vector_service()

    if not vector.is_ready:
        print("[WARN] ChromaDB 未就绪，仅导入 SQLite（RAG 将降级为关键词搜索）")
        print("       请确保已安装 chromadb 和 sentence-transformers")

    # ── 扫描并解析 ──
    all_resources: list[dict] = []
    stats = {"papers": 0, "md_files": 0, "analysis": 0, "skipped": 0}

    # 1. 论文/ 目录
    if PAPERS_DIR.exists():
        paper_files = sorted(PAPERS_DIR.glob("*.md"))
        print(f"\n[1/3] 扫描 {PAPERS_DIR} ...  发现 {len(paper_files)} 个文件")
        for fp in paper_files:
            resource = _parse_paper_md(fp)
            if resource:
                all_resources.append(resource)
                stats["papers"] += 1
            else:
                stats["skipped"] += 1
        print(f"       成功解析: {stats['papers']}  跳过: {stats['skipped']}")
    else:
        print(f"[1/3] 论文目录不存在: {PAPERS_DIR}")

    # 2. md_files/ 目录（按学科/期刊组织的论文）
    if MD_FILES_DIR.exists():
        print(f"\n[2/3] 扫描 {MD_FILES_DIR} ...")
        for discipline_dir in sorted(MD_FILES_DIR.iterdir()):
            if not discipline_dir.is_dir():
                continue
            discipline = discipline_dir.name
            for journal_dir in sorted(discipline_dir.iterdir()):
                if not journal_dir.is_dir():
                    continue
                journal = journal_dir.name
                for fp in sorted(journal_dir.glob("*.md")):
                    resource = _parse_md_files_paper(fp, discipline, journal)
                    if resource:
                        all_resources.append(resource)
                        stats["md_files"] += 1
                    else:
                        stats["skipped"] += 1
        print(f"       成功解析: {stats['md_files']}  跳过: {stats['skipped']}")
    else:
        print(f"[2/3] md_files 目录不存在: {MD_FILES_DIR}")

    # 3. scholar_analysis/ 目录
    if ANALYSIS_DIR.exists():
        print(f"\n[3/3] 扫描 {ANALYSIS_DIR} ...")
        for fp in sorted(ANALYSIS_DIR.glob("*.md")):
            resource = _parse_scholar_analysis(fp)
            if resource:
                all_resources.append(resource)
                stats["analysis"] += 1
            else:
                stats["skipped"] += 1
        print(f"       成功解析: {stats['analysis']}  跳过: {stats['skipped']}")
    else:
        print(f"[3/3] scholar_analysis 目录不存在: {ANALYSIS_DIR}")

    total = stats["papers"] + stats["md_files"] + stats["analysis"]
    print(f"\n总计解析: {total} 篇文档  (跳过: {stats['skipped']})")

    if total == 0:
        print("[ERROR] 未找到任何论文，请检查目录路径")
        return

    # ── 导入 SQLite ──
    print(f"\n[SQLite] 导入 {total} 条记录到 academic_resources...")
    sqlite_inserted = db.save_resources_batch(all_resources)
    print(f"         SQLite 新增: {sqlite_inserted} 条  (已存在: {total - sqlite_inserted})")

    # ── 导入 ChromaDB（通过 rebuild_from_db 全量重建，避免大批量 upsert 损坏索引）──
    if vector.is_ready:
        print(f"\n[ChromaDB] 从 SQLite 重建向量索引 ({total} 条记录)...")
        rebuilt = vector.rebuild_from_db(db)
        print(f"         ChromaDB 已重建 (文档数: {rebuilt})")
    else:
        print("\n[ChromaDB] 跳过 (未就绪)")

    # ── 统计 ──
    print("\n" + "=" * 60)
    print("导入完成!")
    db_count = db.get_resource_count()
    vector_count = vector.get_collection_stats().get("count", 0) if vector.is_ready else 0
    print(f"  SQLite 资源总数:  {db_count}")
    print(f"  ChromaDB 向量数:  {vector_count}")
    print(f"  本次新增:         {sqlite_inserted} (SQLite)")
    print("=" * 60)
    print("\n提示: 重启后端后，Agent 即可检索本地论文。")
    print("      试试在 Agent 中提问：'供应链网络对创新的影响是什么？'")


if __name__ == "__main__":
    main()

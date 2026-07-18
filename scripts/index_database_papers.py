"""数据库论文批量入库脚本（Task 6.4）

扫描 `数据库/` 目录的 .md 论文文件，按学科分类后批量入库到 ChromaDB 向量库。
入库后 RAG 服务可按 discipline 过滤检索，实现学科差异化。

用法：
    cd c:\Users\13067\Desktop\AI产品
    python -B scripts/index_database_papers.py

注意：
    - 使用 -B 参数避免 Trae 沙箱因 .pyc 写入终止进程
    - 脚本独立运行，不影响主服务
    - 默认 discipline="humanities"（数据库主要是人文社科论文）
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# 添加后端路径到 sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent / "src" / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# 设置 HuggingFace 镜像（避免中国大陆网络问题）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from src.backend.services.vector_service import get_vector_service  # noqa: E402

# ── 数据库目录 ──
DB_DIR = Path(__file__).resolve().parent.parent / "数据库"

# ── 学科分类关键词（基于文件名特征） ──
DISCIPLINE_KEYWORDS = {
    "humanities": [
        "传播", "媒介", "新闻", "舆论", "算法", "平台", "数字", "社交",
        "民族", "族际", "中华民族", "非遗", "文化",
        "法学", "法律", "司法", "民事", "刑事",
        "经济", "企业", "金融", "税收", "消费",
        "教育", "心理", "社会",
    ],
}


def classify_discipline(filename: str) -> str:
    """根据文件名关键词分类学科。

    数据库主要是人文社科论文，默认返回 humanities。
    """
    for keyword in DISCIPLINE_KEYWORDS["humanities"]:
        if keyword in filename:
            return "humanities"
    return "humanities"  # 默认人文社科


def parse_filename(filename: str) -> tuple[str, str]:
    """从文件名提取标题和作者。

    文件名格式：{标题}_{作者}.md 或 {标题}.md
    例如：ChatGPT的技术逻辑、社会影响与传播学未来_张洪忠.md
    """
    stem = Path(filename).stem
    # 处理 _作者 后缀
    if "_" in stem:
        parts = stem.rsplit("_", 1)
        title = parts[0].strip()
        author = parts[1].strip() if len(parts) > 1 else ""
    else:
        title = stem.strip()
        author = ""
    return title, author


def extract_abstract(content: str, max_length: int = 500) -> str:
    """从 Markdown 内容提取摘要。

    策略：
    1. 优先取「摘要」段落
    2. 若无，取前 max_length 字符（去除 Markdown 语法）
    """
    # 尝试匹配「摘要」「Abstract」「内容摘要」段落
    abstract_patterns = [
        r"(?:^|\n)#+\s*摘\s*要\s*\n+(.+?)(?=\n#|\Z)",
        r"(?:^|\n)#+\s*Abstract\s*\n+(.+?)(?=\n#|\Z)",
        r"(?:^|\n)#+\s*内容摘要\s*\n+(.+?)(?=\n#|\Z)",
        r"(?:^|\n)摘\s*要[:：]\s*(.+?)(?=\n\n|\n#|\Z)",
    ]
    for pattern in abstract_patterns:
        match = re.search(pattern, content, re.DOTALL)
        if match:
            abstract = match.group(1).strip()
            # 去除 Markdown 语法
            abstract = re.sub(r"[*#`_\[\]()]","", abstract)
            abstract = re.sub(r"\n+"," ", abstract)
            return abstract[:max_length]

    # 兜底：取前 max_length 字符
    plain = re.sub(r"[*#`_\[\]()]","", content)
    plain = re.sub(r"\n+"," ", plain)
    return plain[:max_length]


def extract_year(content: str) -> str:
    """从内容中提取年份（4 位数字，范围 1990-2030）。"""
    matches = re.findall(r"\b(19[9]\d|20[0-3]\d)\b", content)
    return matches[0] if matches else ""


def scan_papers(db_dir: Path) -> list[dict]:
    """扫描数据库目录，收集论文信息。

    返回 document dict 列表，每个含 id/title/abstract/source_db/year/keywords/discipline。
    """
    papers = []
    seen_titles = set()

    # 遍历 .md 文件（排除 cnki 子目录的元数据 json）
    for md_file in sorted(db_dir.glob("*.md")):
        if md_file.name == "index.md":
            continue

        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            print(f"  [SKIP] 读取失败 {md_file.name}: {e}")
            continue

        if len(content) < 100:
            continue  # 跳过过短文件

        title, author = parse_filename(md_file.name)
        if not title or title in seen_titles:
            continue
        seen_titles.add(title)

        abstract = extract_abstract(content)
        year = extract_year(content)
        discipline = classify_discipline(md_file.name)

        # 构造 document id（用文件名 stem 避免重复）
        doc_id = f"db_{md_file.stem[:50]}"

        papers.append({
            "id": doc_id,
            "title": title[:200],
            "abstract": abstract,
            "source_db": "数据库论文",
            "year": year,
            "keywords": "[]",
            "discipline": discipline,
        })

    return papers


def main():
    print("=" * 60)
    print("数据库论文批量入库脚本（Task 6.4）")
    print("=" * 60)
    print(f"数据库目录: {DB_DIR}")
    print()

    if not DB_DIR.exists():
        print(f"[ERROR] 数据库目录不存在: {DB_DIR}")
        sys.exit(1)

    # 1. 扫描论文
    print("[1/3] 扫描数据库目录...")
    papers = scan_papers(DB_DIR)
    print(f"  共发现 {len(papers)} 篇论文")

    if not papers:
        print("[WARN] 未找到任何论文，退出")
        sys.exit(0)

    # 按学科统计
    discipline_counts: dict[str, int] = {}
    for p in papers:
        d = p["discipline"]
        discipline_counts[d] = discipline_counts.get(d, 0) + 1
    print(f"  学科分布: {discipline_counts}")
    print()

    # 2. 初始化向量服务
    print("[2/3] 初始化向量服务...")
    try:
        vector = get_vector_service()
        if not vector.is_ready:
            print("  [WARN] 向量服务未就绪，等待初始化...")
            # 向量服务可能需要时间加载 embedding 模型
            import time
            for i in range(30):
                time.sleep(2)
                if vector.is_ready:
                    break
            if not vector.is_ready:
                print("  [ERROR] 向量服务 60 秒内未就绪，退出")
                sys.exit(1)
        print(f"  向量服务就绪，当前集合文档数: {vector.get_collection_stats().get('count', 0)}")
    except Exception as e:
        print(f"  [ERROR] 向量服务初始化失败: {e}")
        sys.exit(1)
    print()

    # 3. 批量入库
    print("[3/3] 批量入库...")
    try:
        vector.add_documents(papers)
        new_count = vector.get_collection_stats().get("count", 0)
        print(f"  入库完成，当前集合文档数: {new_count}")
    except Exception as e:
        print(f"  [ERROR] 入库失败: {e}")
        sys.exit(1)

    print()
    print("=" * 60)
    print(f"✅ 成功入库 {len(papers)} 篇论文")
    print(f"   学科分布: {discipline_counts}")
    print(f"   向量库总文档数: {new_count}")
    print("=" * 60)
    print()
    print("提示：RAG 服务现在可按 discipline 过滤检索，例如：")
    print("  rag_service.build_context(query, filters={'discipline': 'humanities'})")


if __name__ == "__main__":
    main()

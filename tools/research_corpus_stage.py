"""把用户提供的论文暂存到工作区临时目录（只读源目录），并生成不含正文的 manifest。

用法：
    python tools/research_corpus_stage.py
    python tools/research_corpus_stage.py --source "C:/Users/13067/Desktop/论文" --dest tmp/r2-corpus

约束：
- 源目录只读：脚本只复制、不写入、不删除。
- manifest.json 只登记相对路径、大小、sha256、语言与授权说明，**不包含论文正文**。
- 正文只存在于 --dest 指定的临时目录；评估结束后应删除该目录（见
  docs/reports/R2_CORPUS_EVAL.md「清理」一节）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

DEFAULT_SOURCE = Path.home() / "Desktop" / "论文"
DEFAULT_DEST = Path("tmp/r2-corpus")

# (sample_id, 相对源目录路径, 语言)。顺序即评估顺序，前 14 篇即 R2 T21 语料。
PAPERS: list[tuple[str, str, str]] = [
    (
        "p01-xinjiang-platform",
        "1近期论文集合/序号1+谁在定义边疆？X平台涉疆议题的阵营分化、算法提权与机器人协同的传播生态与用户认知研究.docx",
        "zh",
    ),
    (
        "p02-bot-parasitism",
        "1近期论文集合/序号2+寄生、渗透与行为激活：社交机器人的靶向策略与会话级认知渗透.docx",
        "zh",
    ),
    (
        "p03-lianghui-media",
        "1近期论文集合/序号3+转译·嵌套·公域：全国两会期间边疆民族地区媒体的议程转译与双重嵌套结构 (2).docx",
        "zh",
    ),
    (
        "p04-emotional-structure",
        "1近期论文集合/序号4+工具化自我与被压缩的情感：中国网民的情感结构与社会想象流变（1996-2026）——基于网络文学文本的计算文本分析.docx",
        "zh",
    ),
    (
        "p05-africa-media",
        "1近期论文集合/序号5+想象中国：非洲媒体对中非命运共同体的认同路径与情感传导机制.docx",
        "zh",
    ),
    (
        "p06-border-algorithm",
        "1近期论文集合/序号6+边疆的算法围困：边疆民族地区形象建构的困境与突破.docx",
        "zh",
    ),
    (
        "p07-vanishing-elderly",
        "1近期论文集合/序号7+“消失的老人”：“抖音”算法偏见下的老年群体边缘化 修改版.docx",
        "zh",
    ),
    (
        "p08-ai-imaginary-people",
        "1近期论文集合/序号8+畏惧·中立·崇拜：2021-2025年“人民网”对人工智能想象流变的批判性话语分析.docx",
        "zh",
    ),
    (
        "p09-farmers-retire",
        "老人沉迷/“Farmers Don’t Get to Retire” — Revised (JAS submission).docx",
        "en",
    ),
    ("p10-class-imagination", "AI系统性偏见/人工智能想象的阶层_NMS_主稿.docx", "zh"),
    (
        "p11-ghosts-comments",
        "社交机器人/“Ghosts” in the Comment Section Traffic Parasitism and Behavioral Activation by Social Bots.docx",
        "en",
    ),
    (
        "p12-journalism-education",
        "新闻传播教育/V7 “新闻学还能学吗？”：平台用户争议中的新闻传播教育合法性及价值重塑.docx",
        "zh",
    ),
    (
        "p13-trust-source-context",
        "用户信任/信任何以成？平台用户信任的“信源-情境匹配”假说及其路径机制.docx",
        "zh",
    ),
    ("p14-intelligent-communication", "理论文章/论智能传播_v2.docx", "zh"),
]


def stage(source: Path, dest: Path) -> int:
    """复制论文并写 manifest，返回暂存篇数。"""
    dest.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []
    for slug, rel, lang in PAPERS:
        candidate = source / rel
        if not candidate.is_file():
            raise SystemExit(f"缺少文件：{candidate}")
        data = candidate.read_bytes()
        target = dest / f"{slug}.docx"
        shutil.copyfile(candidate, target)
        manifest.append(
            {
                "sample_id": slug,
                "staged_file": target.name,
                "original_path": rel,
                "language": lang,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "license_note": "用户自有未发表稿件；仅在本机临时目录评估，正文不进入仓库。",
            }
        )
    payload = {
        "corpus_name": "user-provided-unpublished-manuscripts-2026-11",
        "source_root": str(source),
        "authorization": "用户于会话中明确提供该目录并同意用于本次评估。",
        "contains_full_text": False,
        "samples": manifest,
    }
    out = dest / "manifest.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"staged {len(manifest)} papers -> {dest}")
    return len(manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description="暂存用户提供的论文语料并生成 manifest")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="用户论文目录（只读）")
    parser.add_argument("--dest", default=str(DEFAULT_DEST), help="暂存目录（可删除）")
    args = parser.parse_args()
    stage(Path(args.source), Path(args.dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

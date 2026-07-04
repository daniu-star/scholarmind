"""A/B 测试 Pipeline CLI 入口

用法:
    python -m src.backend.ab_testing --max-iterations 3 --verbose
"""

import argparse
import asyncio
import logging

from . import run_ab_testing_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ScholarMind A/B 测试 Pipeline(Mock 演示模式)"
    )
    parser.add_argument(
        "--prototype",
        default="prototypes/interactive-prototype.html",
        help="原型 HTML 文件路径",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="最大迭代轮次(默认3)",
    )
    parser.add_argument(
        "--target-score",
        type=float,
        default=7.0,
        help="目标评分阈值(默认7.0)",
    )
    parser.add_argument(
        "--output-dir",
        default=".trae/documents/ab-testing-reports",
        help="报告输出目录",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="启用详细日志",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    result = asyncio.run(
        run_ab_testing_pipeline(
            prototype_html_path=args.prototype,
            max_iterations=args.max_iterations,
            target_score=args.target_score,
            output_dir=args.output_dir,
        )
    )

    print("\n" + "=" * 60)
    print("=== A/B 测试 Pipeline 完成 ===")
    print("=" * 60)
    print(f"迭代轮次: {result.get('iterations', 0)}")
    print(f"变体评分: {result.get('variant_scores', {})}")
    acceptance = result.get("acceptance_result")
    if acceptance:
        print(f"验收结果: {'通过' if getattr(acceptance, 'accepted', False) else '未通过'}")
        print(f"PRD 符合度: {getattr(acceptance, 'prd_compliance_score', 0):.1f}/100")
    print(f"报告路径: {result.get('report_path', 'N/A')}")
    print("=" * 60)


if __name__ == "__main__":
    main()

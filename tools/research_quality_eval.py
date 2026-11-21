#!/usr/bin/env python
"""研究质量人工盲评汇总工具（R2 / T21 / AT-050）。

本工具**只汇总真人评分**，不生成评分、不调用模型、不猜测缺失值。

用法::

    python tools/research_quality_eval.py \
        --manifest samples.json \
        --rater-a a.csv --rater-a-id rater_a \
        --rater-b b.csv --rater-b-id rater_b \
        --out out/report.json

退出码：

* 0 — 汇总完成（所有样本被两位真人完整评分）
* 2 — 输入不合法（样本 < 10、评分人 < 2、评分人 id 像模型、缺 license/source、CSV 结构错误）
* 3 — 数据不完整（评分缺失、样本覆盖不一致、维度缺失、数值维度填了分类标签）

对外输出的 ``source`` 字段固定为 ``human_raters``；任何 JSON/Markdown 都会带免责声明，
避免把人工汇总误读成模型自评。
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

MIN_SAMPLES = 10
MIN_RATERS = 2
MANIFEST_FIELDS = (
    "sample_id",
    "title",
    "license",
    "source",
    "length",
    "method",
    "reference_findings",
)
CATEGORICAL_DIMENSIONS = (
    "defect_recall",
    "false_positive",
    "evidence_support",
    "revision_conservation",
)
DIMENSIONS = CATEGORICAL_DIMENSIONS + ("time_minutes",)
CATEGORICAL_LABELS = ("pass", "partial", "fail")
# pass/partial/fail 的数值化只能用于汇总展示，不是模型评分。
LABEL_SCORE = {"pass": 1.0, "partial": 0.5, "fail": 0.0}
# 任何像"模型/自评"的评审人 id 一律拒绝：T21 要求两位真人独立评分。
MODEL_MARKERS = ("model", "ai", "self", "gpt", "llm", "bot", "agent", "auto")

DISCLAIMER = (
    "本报告仅汇总两位真人对同一批授权论文样本的独立评分，"
    "不含任何模型自评或自动生成的质量结论；缺失数据一律标记为 missing，不补零、不猜测。"
)


class EvalError(Exception):
    """输入不合法（exit code 2）。"""


class IncompleteData(EvalError):
    """数据不完整（exit code 3）。"""

    def __init__(self, message: str, missing: Sequence[str]) -> None:
        super().__init__(message)
        self.missing = list(missing)


@dataclass(frozen=True)
class Rating:
    sample_id: str
    dimension: str
    verdict: str
    notes: str


# ──────────────────────────────────────────────────────────────────────
# 读取与校验
# ──────────────────────────────────────────────────────────────────


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvalError(f"manifest 不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise EvalError(f"manifest 不是合法 JSON：{exc}") from exc


def load_manifest(path: Path) -> List[Dict[str, Any]]:
    payload = _read_json(path)
    samples = payload.get("samples") if isinstance(payload, dict) else None
    if not isinstance(samples, list):
        raise EvalError("manifest 缺少 samples 数组")
    problems: List[str] = []
    seen: set[str] = set()
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            problems.append(f"samples[{index}] 不是对象")
            continue
        sample_id = str(sample.get("sample_id") or "").strip()
        if not sample_id:
            problems.append(f"samples[{index}] 缺少 sample_id")
            continue
        if sample_id in seen:
            problems.append(f"sample_id 重复：{sample_id}")
        seen.add(sample_id)
        for field in MANIFEST_FIELDS:
            if field not in sample:
                problems.append(f"{sample_id} 缺少字段 {field}")
        if not str(sample.get("license") or "").strip():
            problems.append(f"{sample_id} 缺少授权信息 license")
        if not str(sample.get("source") or "").strip():
            problems.append(f"{sample_id} 缺少来源 source")
        findings = sample.get("reference_findings")
        if not isinstance(findings, list) or not findings:
            problems.append(f"{sample_id} 的 reference_findings 必须是非空数组（作为召回参照）")
    if len(samples) < MIN_SAMPLES:
        problems.append(f"样本数 {len(samples)} < {MIN_SAMPLES}（AT-050 要求至少 10 份授权论文）")
    if problems:
        raise EvalError("manifest 校验失败：\n- " + "\n- ".join(problems))
    return samples


def validate_reviewer_id(value: str, label: str) -> str:
    reviewer = (value or "").strip()
    if not reviewer:
        raise EvalError(f"{label} 的评审人 id 不能为空")
    lowered = reviewer.lower()
    for marker in MODEL_MARKERS:
        if marker in lowered:
            raise EvalError(
                f"{label} 的评审人 id {reviewer!r} 看起来是模型/自动评分（含 {marker!r}）；"
                "T21 要求真人评审，模型评分不能冒充真人意见"
            )
    return reviewer


def load_ratings(path: Path, reviewer: str) -> Dict[Tuple[str, str], Rating]:
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except FileNotFoundError as exc:
        raise EvalError(f"评分 CSV 不存在：{path}") from exc
    with handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise EvalError(f"评分 CSV 没有表头：{path}")
        required = {"sample_id", "dimension", "verdict"}
        missing_columns = sorted(required - {name.strip() for name in reader.fieldnames})
        if missing_columns:
            raise EvalError(f"评分 CSV {path} 缺少列：{'、'.join(missing_columns)}")
        ratings: Dict[Tuple[str, str], Rating] = {}
        for row_no, row in enumerate(reader, start=2):
            sample_id = str(row.get("sample_id") or "").strip()
            dimension = str(row.get("dimension") or "").strip()
            verdict = str(row.get("verdict") or "").strip()
            notes = str(row.get("notes") or "").strip()
            if not sample_id or not dimension:
                raise EvalError(f"{path}:{row_no} 缺少 sample_id 或 dimension")
            if dimension not in DIMENSIONS:
                raise EvalError(
                    f"{path}:{row_no} 未知维度 {dimension!r}；允许：{'、'.join(DIMENSIONS)}"
                )
            key = (sample_id, dimension)
            if key in ratings:
                raise EvalError(f"{path}:{row_no} 重复评分 {sample_id}/{dimension}")
            ratings[key] = Rating(sample_id, dimension, verdict, notes)
    return ratings


def coerce_score(rating: Rating) -> float:
    if rating.dimension == "time_minutes":
        try:
            value = float(rating.verdict)
        except ValueError as exc:
            raise IncompleteData(
                f"{rating.sample_id}/time_minutes 必须是数值分钟，实际 {rating.verdict!r}",
                [f"{rating.sample_id}/time_minutes"],
            ) from exc
        if value < 0:
            raise IncompleteData(
                f"{rating.sample_id}/time_minutes 不能为负", [f"{rating.sample_id}/time_minutes"]
            )
        return value
    label = rating.verdict.lower()
    if label not in LABEL_SCORE:
        raise IncompleteData(
            f"{rating.sample_id}/{rating.dimension} 的 verdict 必须是 pass/partial/fail，"
            f"实际 {rating.verdict!r}",
            [f"{rating.sample_id}/{rating.dimension}"],
        )
    return LABEL_SCORE[label]


# ──────────────────────────────────────────────────────────────────────
# 统计
# ──────────────────────────────────────────────────────────────────


def cohens_kappa(pairs: Iterable[Tuple[str, str]]) -> Optional[float]:
    """两评审在分类维度上的 Cohen's κ；样本不足或期望一致率为 1 时返回 None。"""

    data = list(pairs)
    if not data:
        return None
    labels = sorted({label for pair in data for label in pair} | set(CATEGORICAL_LABELS))
    total = len(data)
    observed = sum(1 for a, b in data if a == b) / total
    marginal_a = {label: sum(1 for a, _ in data if a == label) / total for label in labels}
    marginal_b = {label: sum(1 for _, b in data if b == label) / total for label in labels}
    expected = sum(marginal_a[label] * marginal_b[label] for label in labels)
    if expected >= 1.0:
        return None
    return round((observed - expected) / (1.0 - expected), 4)


def _mean(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return round(float(statistics.fmean(values)), 4)


def summarise(
    samples: Sequence[Dict[str, Any]],
    rater_a: Dict[Tuple[str, str], Rating],
    rater_b: Dict[Tuple[str, str], Rating],
    reviewer_a: str,
    reviewer_b: str,
) -> Dict[str, Any]:
    if reviewer_a == reviewer_b:
        raise EvalError("两位评审的 id 相同；T21 要求两位不同真人独立评分")

    sample_ids = [str(sample["sample_id"]) for sample in samples]
    missing: List[str] = []
    dimensions: Dict[str, Dict[str, Any]] = {}

    for dimension in DIMENSIONS:
        pairs: List[Tuple[str, str, str, str]] = []
        mismatches: List[Dict[str, Any]] = []
        scores_a: List[float] = []
        scores_b: List[float] = []
        for sample_id in sample_ids:
            key = (sample_id, dimension)
            first, second = rater_a.get(key), rater_b.get(key)
            if first is None or second is None:
                missing.append(f"{sample_id}/{dimension}")
                continue
            pairs.append((sample_id, first.verdict, second.verdict, dimension))
            scores_a.append(coerce_score(first))
            scores_b.append(coerce_score(second))
            if dimension in CATEGORICAL_DIMENSIONS and first.verdict != second.verdict:
                mismatches.append(
                    {
                        "sample_id": sample_id,
                        "rater_a": first.verdict,
                        "rater_b": second.verdict,
                        "notes_a": first.notes,
                        "notes_b": second.notes,
                    }
                )
        agreement = None
        kappa = None
        if pairs and dimension in CATEGORICAL_DIMENSIONS:
            agreement = round(sum(1 for _, a, b, _ in pairs if a == b) / len(pairs), 4)
            kappa = cohens_kappa([(a, b) for _, a, b, _ in pairs])
        dimensions[dimension] = {
            "rated_samples": len(pairs),
            "agreement": agreement,
            "cohens_kappa": kappa,
            "mean_rater_a": _mean(scores_a),
            "mean_rater_b": _mean(scores_b),
            "disagreements": mismatches,
        }

    unexpected = sorted(
        {
            f"{sample_id}/{dimension}"
            for sample_id, dimension in list(rater_a) + list(rater_b)
            if sample_id not in set(sample_ids)
        }
    )
    if unexpected:
        missing.extend(f"未知样本 {item}" for item in unexpected)

    if missing:
        raise IncompleteData("评分数据不完整（未补零、未猜测）", missing)

    reference_total = sum(len(sample.get("reference_findings") or []) for sample in samples)
    recall = _mean([dimensions["defect_recall"]["mean_rater_a"], dimensions["defect_recall"]["mean_rater_b"]])
    false_positive_score = _mean(
        [dimensions["false_positive"]["mean_rater_a"], dimensions["false_positive"]["mean_rater_b"]]
    )
    false_positive_rate = None if false_positive_score is None else round(1.0 - false_positive_score, 4)
    times = [
        value
        for value in (
            dimensions["time_minutes"]["mean_rater_a"],
            dimensions["time_minutes"]["mean_rater_b"],
        )
        if value is not None
    ]
    return {
        "source": "human_raters",
        "disclaimer": DISCLAIMER,
        "reviewers": {"rater_a": reviewer_a, "rater_b": reviewer_b},
        "reviewer_count": MIN_RATERS,
        "sample_count": len(samples),
        "reference_findings_total": reference_total,
        "dimensions": dimensions,
        "metrics": {
            # 召回与误报都是两评审均值；没有人工评分时不存在这两个数。
            "defect_recall_rate": recall,
            "false_positive_rate": false_positive_rate,
            "mean_time_minutes": _mean(times),
            "time_reduction_vs_baseline": None,  # 需要基线对照评分，缺失即 None
        },
        "status": "completed",
    }


# ──────────────────────────────────────────────────────────────────────
# 输出
# ──────────────────────────────────────────────────────────────────


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# R2 人工质量评估汇总",
        "",
        f"> {report['disclaimer']}",
        "",
        f"- 数据来源：`{report['source']}`",
        f"- 评审：`{report['reviewers']['rater_a']}` / `{report['reviewers']['rater_b']}`",
        f"- 样本数：{report['sample_count']}（参照缺陷 {report['reference_findings_total']} 条）",
        "",
        "| 维度 | 已评分样本 | 一致率 | Cohen's κ | 评审A均值 | 评审B均值 | 分歧数 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for dimension, data in report["dimensions"].items():
        kappa = "-" if data["cohens_kappa"] is None else f"{data['cohens_kappa']:.4f}"
        agreement = "-" if data["agreement"] is None else f"{data['agreement']:.4f}"
        lines.append(
            "| {dim} | {n} | {agree} | {kappa} | {a} | {b} | {d} |".format(
                dim=dimension,
                n=data["rated_samples"],
                agree=agreement,
                kappa=kappa,
                a="-" if data["mean_rater_a"] is None else data["mean_rater_a"],
                b="-" if data["mean_rater_b"] is None else data["mean_rater_b"],
                d=len(data["disagreements"]),
            )
        )
    metrics = report["metrics"]
    lines += [
        "",
        "| 指标 | 值 |",
        "| --- | --- |",
        f"| 缺陷召回率（两评审均值） | {metrics['defect_recall_rate']} |",
        f"| 误报率（两评审均值） | {metrics['false_positive_rate']} |",
        f"| 人工时间均值（分钟） | {metrics['mean_time_minutes']} |",
        f"| 相对基线的时间下降 | {metrics['time_reduction_vs_baseline']} |",
        "",
        "说明：召回与误报由人工 verdict 映射而来（pass=1 / partial=0.5 / fail=0），"
        "不是模型评分；`null` 表示未测量，绝不等于 0。",
    ]
    disagreements = [
        (dimension, item)
        for dimension, data in report["dimensions"].items()
        for item in data["disagreements"]
    ]
    if disagreements:
        lines += ["", "## 分歧清单", ""]
        for dimension, item in disagreements:
            lines.append(
                f"- `{item['sample_id']}` / {dimension}：A={item['rater_a']}，B={item['rater_b']}"
                + (f"（A: {item['notes_a']}）" if item["notes_a"] else "")
                + (f"（B: {item['notes_b']}）" if item["notes_b"] else "")
            )
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="研究质量人工盲评汇总（不生成评分）")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--rater-a", required=True, type=Path)
    parser.add_argument("--rater-b", required=True, type=Path)
    parser.add_argument("--rater-a-id", required=True)
    parser.add_argument("--rater-b-id", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        reviewer_a = validate_reviewer_id(args.rater_a_id, "--rater-a-id")
        reviewer_b = validate_reviewer_id(args.rater_b_id, "--rater-b-id")
        samples = load_manifest(args.manifest)
        ratings_a = load_ratings(args.rater_a, reviewer_a)
        ratings_b = load_ratings(args.rater_b, reviewer_b)
        report = summarise(samples, ratings_a, ratings_b, reviewer_a, reviewer_b)
    except IncompleteData as exc:
        payload = {
            "source": "human_raters",
            "disclaimer": DISCLAIMER,
            "status": "incomplete",
            "missing": exc.missing,
            "message": str(exc),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"\n数据不完整，未生成报告：{exc}", file=sys.stderr)
        return 3
    except EvalError as exc:
        print(f"输入不合法，未生成报告：{exc}", file=sys.stderr)
        print(json.dumps({"source": "human_raters", "status": "invalid", "message": str(exc)},
                         ensure_ascii=False, indent=2))
        return 2

    markdown = render_markdown(report)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n\n" + markdown,
        encoding="utf-8",
    )
    print(markdown)
    print(f"报告已写入 {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    sys.exit(main())

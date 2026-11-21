"""T21 人工盲评汇总工具（R2 / AT-050–AT-052）。

锁定三件与"诚实"直接相关的事：

1. 样本或评分人不达标、评审人 id 像模型 → 退出码 2，**不产出评分**；
2. 评分数据不完整 → 退出码 3，宁可不出报告也不补零；
3. 正常路径输出 ``source=human_raters`` 与免责声明，且分类维度才计算一致性。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
TOOL = REPO_ROOT / "tools" / "research_quality_eval.py"

DIMENSIONS = (
    "defect_recall",
    "false_positive",
    "evidence_support",
    "revision_conservation",
)


def _write_manifest(tmp_path: Path, count: int = 10) -> Path:
    manifest = []
    for index in range(count):
        manifest.append(
            {
                "sample_id": f"sample-{index:02d}",
                "title": f"样本论文 {index:02d}",
                "license": "CC-BY-4.0",
                "source": "内部授权语料",
                "length": 8000 + index,
                "method": "内容分析",
                "reference_findings": [
                    {"category": "argument", "severity": "minor", "problem": "论证跳跃"}
                ],
            }
        )
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({"samples": manifest}, ensure_ascii=False), encoding="utf-8"
    )
    return path


def _write_ratings(tmp_path: Path, name: str, *, count: int = 10, skip: str | None = None) -> Path:
    lines = ["sample_id,dimension,verdict,notes"]
    for index in range(count):
        sample = f"sample-{index:02d}"
        for dimension in DIMENSIONS:
            if skip == f"{sample}/{dimension}":
                continue
            lines.append(f"{sample},{dimension},pass,ok")
        if skip != f"{sample}/time_minutes":
            lines.append(f"{sample},time_minutes,{30 + index},分钟")
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def test_happy_path_produces_human_rater_report(tmp_path):
    manifest = _write_manifest(tmp_path)
    rater_a = _write_ratings(tmp_path, "a.csv")
    rater_b = _write_ratings(tmp_path, "b.csv")
    out = tmp_path / "out" / "report.json"

    result = _run(
        "--manifest",
        str(manifest),
        "--rater-a",
        str(rater_a),
        "--rater-a-id",
        "human_rater_a",
        "--rater-b",
        str(rater_b),
        "--rater-b-id",
        "human_rater_b",
        "--out",
        str(out),
    )
    assert result.returncode == 0, result.stderr
    report_text = (tmp_path / "out" / "report.json").read_text(encoding="utf-8")
    json_part = report_text.split(chr(10) + chr(10), 1)[0]
    payload = json.loads(json_part)
    assert payload["source"] == "human_raters"
    assert "真人" in payload["disclaimer"]
    assert payload["sample_count"] == 10
    assert payload["reviewers"] == {"rater_a": "human_rater_a", "rater_b": "human_rater_b"}
    metrics = payload["metrics"]
    assert metrics["defect_recall_rate"] is not None
    assert metrics["time_reduction_vs_baseline"] is None
    # time_minutes 是连续量，不参与 agreement/κ。
    assert payload["dimensions"]["time_minutes"]["agreement"] is None
    assert payload["dimensions"]["defect_recall"]["agreement"] is not None
    assert "人工质量评估汇总" in report_text


def test_too_few_samples_is_rejected(tmp_path):
    manifest = _write_manifest(tmp_path, count=5)
    rater_a = _write_ratings(tmp_path, "a.csv", count=5)
    rater_b = _write_ratings(tmp_path, "b.csv", count=5)

    result = _run(
        "--manifest",
        str(manifest),
        "--rater-a",
        str(rater_a),
        "--rater-a-id",
        "human_a",
        "--rater-b",
        str(rater_b),
        "--rater-b-id",
        "human_b",
        "--out",
        str(tmp_path / "out" / "report.json"),
    )
    assert result.returncode == 2
    assert not (tmp_path / "out" / "report.json").exists()


def test_model_like_rater_is_rejected(tmp_path):
    manifest = _write_manifest(tmp_path)
    rater_a = _write_ratings(tmp_path, "a.csv")
    rater_b = _write_ratings(tmp_path, "b.csv")

    result = _run(
        "--manifest",
        str(manifest),
        "--rater-a",
        str(rater_a),
        "--rater-a-id",
        "gpt-4o",
        "--rater-b",
        str(rater_b),
        "--rater-b-id",
        "human_b",
        "--out",
        str(tmp_path / "out" / "report.json"),
    )
    assert result.returncode == 2
    assert not (tmp_path / "out" / "report.json").exists()


def test_missing_rating_is_incomplete_not_zero(tmp_path):
    manifest = _write_manifest(tmp_path)
    rater_a = _write_ratings(tmp_path, "a.csv", skip="sample-03/defect_recall")
    rater_b = _write_ratings(tmp_path, "b.csv")

    result = _run(
        "--manifest",
        str(manifest),
        "--rater-a",
        str(rater_a),
        "--rater-a-id",
        "human_a",
        "--rater-b",
        str(rater_b),
        "--rater-b-id",
        "human_b",
        "--out",
        str(tmp_path / "out" / "report.json"),
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert not (tmp_path / "out" / "report.json").exists()

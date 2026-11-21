"""R2 人工质量评估 CLI 的拒绝路径（T21 / AT-050）。

``test_eval_cli.py`` 已覆盖 happy path 与"缺评分行 → 3"。这里补 CS 侧最容易
误判的三条输入错误，它们必须落在 **exit 2（输入不合法）** 而不是 3：

* 评分 CSV 缺少必需列（``verdict``）——缺列是格式错误，不是"数据不完整"；
* manifest 样本缺字段（``license``）——无法证明授权，直接拒收；
* 两名评审填了同一个 id——自评/同源评分不得冒充独立双评。

三条都断言 **不生成 --out 报告文件**：失败不得留下看起来像结论的产物。
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

TOOL = Path(__file__).resolve().parents[4] / "tools" / "research_quality_eval.py"

DIMENSIONS = (
    "defect_recall",
    "false_positive",
    "evidence_support",
    "revision_conservation",
)
SAMPLE_COUNT = 10


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _run(*args: str) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        timeout=120,
        check=False,
    )
    return subprocess.CompletedProcess(
        completed.args,
        completed.returncode,
        _decode(completed.stdout),
        _decode(completed.stderr),
    )


def _manifest(tmp_path: Path, *, drop_field: str | None = None) -> Path:
    samples = []
    for index in range(SAMPLE_COUNT):
        sample = {
            "sample_id": f"sample-{index:02d}",
            "title": f"授权论文 {index}",
            "license": "CC-BY-4.0（作者书面授权）",
            "source": "作者提供的投稿稿",
            "length": 12000 + index,
            "method": "量化问卷",
            "reference_findings": [{"locator": "p1", "problem": "样本代表性不足"}],
        }
        if drop_field and index == 0:
            sample.pop(drop_field)
        samples.append(sample)
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({"samples": samples}, ensure_ascii=False), encoding="utf-8"
    )
    return path


def _ratings(tmp_path: Path, name: str, *, drop_column: str | None = None) -> Path:
    path = tmp_path / name
    columns = ["sample_id", "dimension", "verdict"]
    if drop_column:
        columns.remove(drop_column)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for index in range(SAMPLE_COUNT):
            for dimension in DIMENSIONS:
                verdict = "pass" if (index + len(dimension)) % 3 else "partial"
                row = {
                    "sample_id": f"sample-{index:02d}",
                    "dimension": dimension,
                    "verdict": verdict,
                }
                writer.writerow({key: row[key] for key in columns})
    return path


def _args(tmp_path: Path, manifest: Path, rater_a: Path, rater_b: Path, **ids) -> list:
    out = tmp_path / "report.md"
    return [
        "--manifest",
        str(manifest),
        "--rater-a",
        str(rater_a),
        "--rater-b",
        str(rater_b),
        "--rater-a-id",
        ids.get("a", "评审-张"),
        "--rater-b-id",
        ids.get("b", "评审-李"),
        "--out",
        str(out),
    ]


def _out_path(argv: list) -> Path:
    return Path(argv[argv.index("--out") + 1])


def test_missing_csv_column_is_invalid_input_not_incomplete(tmp_path):
    manifest = _manifest(tmp_path)
    rater_a = _ratings(tmp_path, "a.csv")
    rater_b = _ratings(tmp_path, "b.csv", drop_column="verdict")
    argv = _args(tmp_path, manifest, rater_a, rater_b)

    result = _run(*argv)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "缺少列" in result.stderr and "verdict" in result.stderr
    assert not _out_path(argv).exists(), "输入不合法时不得生成报告"


def test_manifest_missing_required_field_is_rejected(tmp_path):
    manifest = _manifest(tmp_path, drop_field="license")
    rater_a = _ratings(tmp_path, "a.csv")
    rater_b = _ratings(tmp_path, "b.csv")
    argv = _args(tmp_path, manifest, rater_a, rater_b)

    result = _run(*argv)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "manifest" in result.stderr and "license" in result.stderr
    assert not _out_path(argv).exists()


def test_same_rater_id_cannot_fake_two_reviewers(tmp_path):
    manifest = _manifest(tmp_path)
    rater_a = _ratings(tmp_path, "a.csv")
    rater_b = _ratings(tmp_path, "b.csv")
    argv = _args(tmp_path, manifest, rater_a, rater_b, a="评审-张", b="评审-张")

    result = _run(*argv)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert not _out_path(argv).exists()

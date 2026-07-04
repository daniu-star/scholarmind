"""验证 pdfs 目录中所有文件是否为真正的 PDF 格式。"""
import os
from pathlib import Path

pdf_dir = Path(r"..\数据库\cnki\hybrid\pdfs")
print(f"目录: {pdf_dir.resolve()}\n")

files = sorted([f for f in os.listdir(pdf_dir) if f.endswith(".pdf")])
total_size = 0
all_valid = True

for f in files:
    path = pdf_dir / f
    with open(path, "rb") as fh:
        magic = fh.read(5)
    size = path.stat().st_size
    total_size += size
    is_pdf = magic == b"%PDF-"
    status = "✓ PDF" if is_pdf else "✗ 非 PDF!"
    print(f"  {f:35s} {status:10s} magic={magic!r} size={size:>10,} bytes")
    if not is_pdf:
        all_valid = False

print(f"\n总计: {len(files)} 个文件, {total_size:,} bytes ({total_size/1024/1024:.1f} MB)")
print(f"全部为 PDF 格式: {'是 ✓' if all_valid else '否 ✗'}")

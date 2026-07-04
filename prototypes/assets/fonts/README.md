# Self-hosted Fonts (SubTask 16.1 / 问题 77)

本目录存放从 Google Fonts CDN 迁移至本地自托管的 woff2 字体文件，用于
`prototypes/interactive-prototype.html`，解决中国大陆访问 `fonts.googleapis.com`
缓慢的问题。

## 字体清单

| 文件名                       | 字体族           | 字重 | 大小  |
|------------------------------|------------------|------|-------|
| Inter-Regular.woff2          | Inter            | 400  | ~23KB |
| Inter-Medium.woff2           | Inter            | 500  | ~24KB |
| Inter-SemiBold.woff2         | Inter            | 600  | ~24KB |
| Inter-Bold.woff2             | Inter            | 700  | ~24KB |
| SourceSerif4-Regular.woff2   | Source Serif 4   | 400  | ~20KB |
| SourceSerif4-SemiBold.woff2  | Source Serif 4   | 600  | ~21KB |
| SourceSerif4-Bold.woff2      | Source Serif 4   | 700  | ~21KB |

均为 Latin 子集（覆盖英文 UI 文本、数字、常见标点）。中文字符回退到系统字体
（`PingFang SC` / `Microsoft YaHei` / `Songti SC` / `SimSun` 等），不额外托管
中文字体以控制体积。

## 重新下载

字体来自 [Fontsource](https://github.com/fontsource) 静态 woff2（通过 jsDelivr CDN）。
如需重新下载（构建期一次性操作，运行时已完全自托管）：

```powershell
$dir = $PSScriptRoot
$base = "https://cdn.jsdelivr.net/npm"
Invoke-WebRequest "$base/@fontsource/inter/files/inter-latin-400-normal.woff2" -OutFile "$dir\Inter-Regular.woff2"
Invoke-WebRequest "$base/@fontsource/inter/files/inter-latin-500-normal.woff2" -OutFile "$dir\Inter-Medium.woff2"
Invoke-WebRequest "$base/@fontsource/inter/files/inter-latin-600-normal.woff2" -OutFile "$dir\Inter-SemiBold.woff2"
Invoke-WebRequest "$base/@fontsource/inter/files/inter-latin-700-normal.woff2" -OutFile "$dir\Inter-Bold.woff2"
Invoke-WebRequest "$base/@fontsource/source-serif-4/files/source-serif-4-latin-400-normal.woff2" -OutFile "$dir\SourceSerif4-Regular.woff2"
Invoke-WebRequest "$base/@fontsource/source-serif-4/files/source-serif-4-latin-600-normal.woff2" -OutFile "$dir\SourceSerif4-SemiBold.woff2"
Invoke-WebRequest "$base/@fontsource/source-serif-4/files/source-serif-4-latin-700-normal.woff2" -OutFile "$dir\SourceSerif4-Bold.woff2"
```

## 路径说明

HTML 位于 `prototypes/interactive-prototype.html`，由后端挂载到
`http://localhost:8000/app/interactive-prototype.html`（见 `src/backend/app.py`
中 `app.mount("/app", StaticFiles(directory=prototypes_dir))`）。因此 HTML 中
`assets/fonts/xxx.woff2` 的相对路径解析到本目录。

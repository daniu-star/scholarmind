---
name: codex-exec
description: |
  将编码任务委派给 OpenAI Codex CLI 自主执行。
  Codex 会读取代码库、搜索文件、修改代码、执行命令，完成后报告结果。
  触发词：codex执行、让codex做、用codex、codex run、调用codex、委托codex。
  适用于：重构、修 bug、写新功能、写测试、项目脚手架、代码分析等。
allowed-tools: [Bash, Read, Grep, Glob]
argument-hint: [task-description]
---

# Codex Exec — 委派任务给 Codex CLI

## 概述

[Codex CLI](https://github.com/openai/codex) 是 OpenAI 的终端编码 agent，已安装于本机 (`codex`)。通过 `codex exec` 非交互模式将任务委派给它执行。

## 模型选择

| 任务类型 | 模型 | 说明 |
|---------|------|------|
| 简单修改/快速编辑 | `o4-mini` | 默认，速度快、成本低 |
| 复杂重构/深度推理 | `o3` | 适合复杂逻辑 |
| 大范围分析/大上下文 | `gpt-4.1` | 大上下文窗口 |

## 沙箱模式

- `workspace-write`（默认）：可读写工作目录
- `read-only`：只读分析，不修改文件
- `danger-full-access`：完全访问（需用户明确要求）

## 执行步骤

### 1. 确认参数

根据用户任务确认模型和沙箱模式。如不确定模型选择，默认 `o4-mini`。

### 2. 运行 Codex

```bash
codex exec --model <model> --sandbox <sandbox> "<task-description>"
```

任务描述要清晰具体，包含文件路径、约束条件和预期结果。

**示例：**

```bash
# 快速重构
codex exec --model o4-mini --sandbox workspace-write "重构 src/utils/helper.ts 中的 parseDate 函数，提取重复逻辑到 formatDate"

# 复杂修复
codex exec --model o3 --sandbox workspace-write "在 src/api/routes.py 的 POST /users 端点添加 email 唯一性校验和对应测试"

# 只读分析
codex exec --model o4-mini --sandbox read-only "分析 src/ 目录的模块依赖，找出循环依赖和耦合问题"
```

### 3. 报告结果

执行后向用户报告：任务成功与否、文件变更列表、需要注意的问题。

## 安全

- 默认 `workspace-write` 沙箱限制外部访问
- 建议重要操作前 `git commit` 或创建分支
- **禁止使用 `--dangerously-bypass-approvals-and-sandbox`**（除非用户明确要求）

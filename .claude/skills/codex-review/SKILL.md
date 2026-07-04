---
name: codex-review
description: |
  使用 OpenAI Codex CLI 对代码进行只读审查，不修改任何文件。
  触发词：codex审查、codex review、codex检查代码。
  适用于：PR review、代码质量检查、安全审查。
allowed-tools: [Bash, Read, Grep, Glob]
argument-hint: [target]
---

# Codex Review — 代码审查

## 概述

Codex 内置审查 agent，以只读模式检查代码，不修改文件。

## 审查类型

**审查指定文件：**
```bash
codex exec review --model o4-mini "审查 src/auth/login.ts 的安全和代码质量问题"
```

**审查未提交变更：**
```bash
codex exec review --model o4-mini "审查当前工作区的未提交变更，关注安全隐患和逻辑错误"
```

**审查整个目录：**
```bash
codex exec review --model o3 "对 src/backend/ 进行全面代码审查，包括安全、性能、可维护性"
```

## 执行步骤

1. 确认审查范围和深度（快速扫描用 `o4-mini`，深度审查用 `o3`）
2. 运行 `codex exec review`
3. 整理结果：关键问题 → 改进建议 → 正面反馈

## 注意

- 只读操作，不修改任何文件
- 大型代码库应限制审查范围
- 提取关键发现呈现给用户

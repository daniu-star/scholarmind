"""
Agent 服务子包 — agent_service.py 拆分后的模块化结构

模块:
  prompt_builder  — Prompt 模板、学术特征注入、系统 Prompt 构建
  cot_processor   — Chain-of-Thought 解析、流式 CoT 状态机
  skill_router    — 技能检测、工具执行（图表、CNKI）、选项解析
  session_manager — 对话持久化、会话 CRUD、历史管理
  orchestrator    — chat()/stream_chat() 编排、greeting 模式、mock 降级
"""

# ScholarMind - 全能研究 Agent

面向高校科研人员的智能学术研究助手，基于RAG+LangGraph+6层企业架构。

## 核心功能
- 5Agent协作：研究员/审查员/架构师/综述员/润色员，覆盖选题→审查→架构→综述→润色全流程
- 8个预设技能+自定义技能扩展
- 12种Origin风格学术图表
- 6层企业架构，多级降级，熔断器保护

## 技术栈
FastAPI · LangGraph · DeepSeek · ChromaDB · RAG · Celery+Redis · SQLAlchemy · WebSocket · Matplotlib

## 使用
```bash
cd src/backend
pip install -r requirements.txt
python app.py
```

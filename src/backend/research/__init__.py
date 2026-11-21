"""ScholarMind 研究领域包（PRD v1.0 R0）。

对外只暴露稳定入口；内部模块按职责划分：

- ``contracts`` 跨层 DTO 与不变量（唯一事实来源）
- ``models``    ORM
- ``errors`` / ``ownership``  统一错误与所有权隔离
- ``project_service`` / ``document_service`` / ``document_parser``  项目与文档
- ``retrieval_service`` / ``evidence_service``  私有全文检索与证据
- ``task_repository`` / ``task_service`` / ``task_events``  任务登记与事件
- ``billing_service`` / ``outbox``  额度账本与事务外盒
- ``runtime`` / ``pipelines`` / ``review_workflow`` / ``revision_service``  执行
- ``artifact_service`` / ``export_service``  成果与导出
- ``capabilities``  能力真实性
"""

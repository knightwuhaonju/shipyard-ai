# Shipyard AI V1 Starter

这是一套给 Codex 使用的“规格驱动”启动包，用于开发中型造船厂第一阶段 AI 系统：

- Shipyard Copilot
- 企业知识库 / RAG
- LLM Wiki
- Shipyard Entity Model
- ERP / MES / PLM 只读 Tool Layer
- MCP Adapter
- Eval / Security / Audit
- Pilot Web UI

## 目标

第一阶段只解决四类可量化问题：

1. 查规范、工艺、设备手册，并给出可追溯引用。
2. 查某条船当前项目状态。
3. 查采购、到货、逾期和关键风险。
4. 查图纸、设备、BOM、物料之间的关系。

明确不做：

- 自动修改 ERP/MES/PLM
- 自动采购
- 自动修改 CAD
- 自动生产排程
- 机器人控制
- 多 Agent 编排
- LLM 自主写入 canonical Wiki
- 用向量库代替实时业务数据库

## 推荐使用方式

1. 新建空 Git 仓库。
2. 将本目录全部复制到仓库根目录。
3. 先让 Codex 阅读：
   - `AGENTS.md`
   - `docs/00-product-scope.md`
   - `docs/01-architecture.md`
   - `tasks/INDEX.md`
4. 从 `tasks/001-repository-bootstrap.md` 顺序执行。
5. 每个 Task 单独分支 / worktree。
6. 每个实现 Task 完成后，使用另一个 Codex 线程做独立 review。
7. 未通过验收标准，不进入下一个依赖 Task。

## 推荐角色

- Architect：只改 docs / ADR / interfaces，不写业务实现。
- Backend：实现 domain、API、connector。
- AI：实现 ingestion、retrieval、wiki、agent runtime。
- QA：维护 eval dataset、集成测试、安全测试。
- Reviewer：只 review，不直接改代码，输出 P0-P3 findings。

## 技术栈

- Python 3.12+
- FastAPI
- SQLAlchemy 2.x
- Pydantic 2.x
- Alembic
- PostgreSQL 16+
- pgvector
- S3-compatible object storage
- Next.js / TypeScript
- Docker Compose
- pytest
- Ruff
- mypy

V1 不要求 Kubernetes、Kafka、Flink、Neo4j、独立向量数据库或多 Agent 框架。

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

## 运行时配置与请求日志

将 `.env.example` 复制为本地环境文件并替换占位符。`DATABASE_URL` 为必填项；
应用启动时会校验配置，缺失或无效配置会使启动失败，同时错误信息不会包含环境变量值。

`LOG_LEVEL` 可选，默认值为 `INFO`。允许值为 `DEBUG`、`INFO`、`WARNING`、`ERROR`
和 `CRITICAL`（不区分大小写）。

`GET /health` 返回服务状态，并在响应头中包含 `X-Request-ID` 以便请求关联。若客户端
传入 `X-Request-ID`，仅当它由 ASCII 字母、数字、点（`.`）、下划线（`_`）或连字符（`-`）
组成，且长度为 1–128 个字符时才会被保留；否则服务生成新的 UUIDv4 请求 ID。

请求日志采用结构化格式，并只记录安全的请求元数据，例如方法、路由模板、状态码、耗时和
请求 ID。日志不记录请求或响应头、查询参数、请求体、原始 URL 路径、客户数据或异常消息。
默认容器会禁用 Uvicorn 原始访问日志；请求审计日志不受通用 `LOG_LEVEL` 抑制。请求失败时，
客户端收到通用的 `500 Internal Server Error` 响应以及 `X-Request-ID`。

## 本地开发与质量门禁

需要 Python 3.12.13 和 `make`。首次设置本地环境：

```bash
python3.12 -m venv .venv
make install-dev
```

提交前运行与 CI 完全相同的质量门禁：

```bash
make check
```

`make check` 依次检查依赖闭包并运行单元/集成测试、Ruff 和 mypy。也可以单独运行：

```bash
make test
make lint
make typecheck
make dependency-check
```

聚焦运行某个 pytest 目标：

```bash
make test PYTEST_ARGS="tests/unit/test_health.py -v"
```

CI 使用 `requirements-dev.lock` 中的精确依赖版本、固定的 Python 补丁版本
和固定提交的 GitHub Actions。更新依赖时必须显式审查并重新生成锁文件。

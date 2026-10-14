# NineClaw WebSearch

可配置的聚合搜索与网页内容提取服务，类似 Tavily Search API。支持动态添加搜索源、自定义解析器，结果去重合并后按权重排序返回。

## 架构概览

```
┌─────────────────────────────────────────────────────────┐
│                      FastAPI App                        │
│                                                         │
│  /v1/search         ─── SearchService (fan-out)         │
│  /v1/sources        ─── SourceLoader (hot-reload)       │
│  /v1/sources/fetch  ─── Authoring (调试/创建搜索源)      │
│  /v1/extract        ─── ExtractService (正文提取)        │
│  /health            ─── 健康检查                         │
└───────────────┬─────────────────────┬───────────────────┘
                │                     │
     ┌──────────▼──────────┐   ┌──────▼───────┐
     │   web_sources/      │   │  PostgreSQL  │
     │  (文件系统搜索源)    │   │  (pgvector)  │
     │  bing/config.json   │   └──────────────┘
     │  bing/extract.py    │
     │  sogou/config.json  │
     │  sogou/extract.py   │
     └─────────────────────┘
```

## 技术栈

| 层面 | 技术选型 |
|------|----------|
| Web 框架 | FastAPI + Uvicorn |
| 数据验证 | Pydantic v2 / SQLModel |
| 数据库 | PostgreSQL 17 (pgvector) |
| ORM / 迁移 | SQLAlchemy 2 + Alembic |
| HTTP 客户端 | httpx (异步) |
| HTML 解析 | parsel / lxml / html5lib / GNE |
| 日志 | loguru |
| 包管理 | uv |
| 容器化 | Docker + Docker Compose |

## 核心模块

- **SearchService** — 并发请求多个搜索源，按超时控制，结果去重合并，加权排序。
- **SourceLoader** — 从 `web_sources/` 目录热加载搜索源配置和提取脚本，无需重启。
- **ExtractService** — 给定 URL 列表，并发抓取并提取正文、标题、发布日期。
- **Authoring API** — 辅助开发搜索源：在线发起请求、保存提取脚本、测试解析效果。

## 搜索源结构

每个搜索源是 `web_sources/<source_id>/` 目录下的两个文件：

```
web_sources/bing/
├── config.json    # 请求配置：URL、参数、Headers、代理
└── extract.py     # 提取函数：extract(html) -> list[dict]
```

`config.json` 中的 `{query}` 占位符在搜索时被替换为实际查询词。

## 快速开始

```bash
# 1. 复制环境变量
cp .env.example .env

# 2. 启动服务
docker compose up -d --build

# 3. 初始化数据库
docker compose exec app uv run alembic upgrade head

# 4. 测试搜索
curl -X POST http://localhost:8000/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "hello world"}'
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/search` | 聚合搜索 |
| POST | `/v1/extract` | 网页正文提取 |
| GET | `/v1/sources` | 列出所有搜索源 |
| POST | `/v1/sources/fetch` | 调试：发起请求并保存 HTML |
| POST | `/v1/sources/save_extractor` | 保存提取脚本 |
| POST | `/v1/sources/test` | 测试提取脚本 |
| GET | `/health` | 健康检查 |

## 开发

```bash
# 安装依赖
uv sync

# 本地启动（需先启动 PostgreSQL）
python run.py

# 数据库迁移
alembic upgrade head
```

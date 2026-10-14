# Apifox 测试：知识库 API

## 服务地址

| 说明 | URL |
|------|-----|
| 基址 | `http://172.18.33.28:8000` |
| 健康检查 | `GET http://172.18.33.28:8000/health` |
| 创建知识库 | `POST http://172.18.33.28:8000/v1/knowledge` |
| 知识库列表 | `GET http://172.18.33.28:8000/v1/knowledge` |
| 知识库详情 | `GET http://172.18.33.28:8000/v1/knowledge/{id}` |
| 删除知识库 | `DELETE http://172.18.33.28:8000/v1/knowledge/{id}` |
| 下载文档 | `GET http://172.18.33.28:8000/v1/knowledge/{id}/files/{file_id}/download` |

所有业务接口在 `/v1` 下，**与 RAGFlow 无关**，数据存于服务器 `knowledge_storage/`。

## 导入 Apifox

1. Apifox → **导入** → **OpenAPI**
2. 选择 `apifox/knowledge-create.openapi.yaml`
3. 环境变量 `baseUrl` = `http://172.18.33.28:8000`（导入后已设为默认 servers）

## 创建知识库示例

```
POST http://172.18.33.28:8000/v1/knowledge
Content-Type: application/json
X-Tenant-ID: default

{
  "name": "apifox_test_kb",
  "description": "测试知识库",
  "group": "平台建设",
  "owner": "阿文",
  "embedding_model": "bge-large@local",
  "permission": "me",
  "chunk_method": "naive",
  "parser_config": {
    "chunk_token_num": 128,
    "delimiter": "\\n",
    "layout_recognize": "DeepDOC",
    "html4excel": false,
    "raptor": { "use_raptor": false },
    "graphrag": { "use_graphrag": false }
  }
}
```

成功响应：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": "apifox-test-kb",
    "name": "apifox_test_kb",
    "status": "building",
    ...
  }
}
```

## 删除知识库示例

```
DELETE http://172.18.33.28:8000/v1/knowledge/apifox-test-kb
X-Tenant-ID: default
```

成功响应：

```json
{
  "code": 0,
  "message": "success",
  "data": { "deleted": "apifox-test-kb" }
}
```

## 启动服务（在 172.18.33.28 机器上）

```bash
cd NineClaw-Manager-main
# .env 中 API_HOST=0.0.0.0  API_PORT=8000
uv run run.py
```

## WebUI 对接

WebUI 或集中部署仓库应指向本服务的 API 地址，例如 `http://172.18.33.28:8000`。

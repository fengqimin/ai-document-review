# 02 · 后端 API

> 证据基准 commit：`c91254a`。以下"观察行为"均为代码可证事实；与意图不一致处单独标注。

## 应用生命周期

`app/api/main.py`：

1. `setup_logging()`（`main.py:13`）配置控制台 + 文件 `app.log` + Application Insights 三个 handler（`app/api/middleware/logging.py:48-73`）。
2. 创建 FastAPI 实例，Swagger 启用 PKCE OAuth2（`main.py:18-24`）。
3. 挂中间件：`LoggingMiddleware`（请求耗时/异常日志，`middleware/logging.py:9-46`）+ CORS（`main.py:28-34`）。
4. 注册路由：仅 `routers/issues` 一个 router（`main.py:37`）。
5. 健康检查 `GET /api/health` 返回 204（`main.py:41-48`）。
6. `serve_static=True` 时把 `www/` 挂到 `/` 托管前端（`main.py:52-53`）。
7. 异常处理器：HTTPException → `{"error": "HTTPException", "message": detail}`（`main.py:57-63`）；兜底 Exception → 500 且 **返回 `str(exc)`**（`main.py:67-76`）。

注意：未配置优雅停机、限流、安全头（对比意图见 `docs/architecture.md` 的安全章节）。

## 配置

全部来自环境变量/`.env`，经 Pydantic Settings 加载（`app/api/config/config.py:5-30`）：`debug`、`aad_client_id`、`aad_tenant_id`、`aad_user_impersonation_scope_id`、`serve_static`、`cosmos_url`、`cosmos_key`（声明但未使用——实际用 DefaultAzureCredential）、`database_name=state`、`issues_container=issues`、`feedback_container=feedback`（**声明但未使用**）、`storage_account_url`/`storage_container_name`（API 侧未使用，前端直连）、`subscription_id`、`resource_group`、`ai_hub_project_name`、`aml_endpoint_name`、`aml_streaming_batch_size=10`、`appinsights_instrumentation_key`、`log_level`。启动时无集中校验（均为空默认值，缺失凭据会在首次调用时才失败）。

## 端点契约

### GET /api/health（`main.py:41-48`）
- 无鉴权；返回 `204` 空响应。

### GET /api/v1/review/{doc_id}/issues（`routers/issues.py:22-87`）
- 鉴权：`validate_authenticated`（`security/auth.py:16-21`，fastapi-azure-auth 单租户 Bearer，允许访客用户 `auth.py:10`）。
- 行为（观察）：
  - 先查 `issues_repository.get_issues(doc_id)`（`issues.py:49`）；**有结果 → 单条 `event: issues` + `event: complete` 后立即结束**（`issues.py:54-58`）。
  - 无结果 → `initiate_review` 发起 AML 流式审阅，逐块 `event: issues`，结束发 `event: complete`（`issues.py:60-77`）。
  - 流中异常 → 发 `event: error` + data 为原始异常字符串（`issues.py:70-73`）。
- SSE 事件格式由 `issues_event`（`issues.py:18-20`）生成：`event: issues\ndata: [Issue...]\n\n`。
- 错误映射：ValueError→400、HTTPException 原样、其他→500（`issues.py:79-87`）。

### PATCH /api/v1/review/{doc_id}/issues/{issue_id}/accept（`issues.py:90-129`）
- Body：可选 `ModifiedFieldsModel`（`suggested_fix`/`explanation`，`common/models.py:68-71`）。
- 置 `status=accepted`、`resolved_by=user.oid`、`resolved_at_UTC=now`；有修改字段则写入 `modified_fields`（`services/issues_service.py:90-104`）。返回更新后的 Issue。

### PATCH /api/v1/review/{doc_id}/issues/{issue_id}/dismiss（`issues.py:132-171`）
- Body：可选 `DismissalFeedbackModel`（`reason`，`common/models.py:73-74`）。
- 置 `status=dismissed` + resolved 字段；有反馈则同时写 `dismissal_feedback`（`issues_service.py:118-144`）。

### PATCH /api/v1/review/{doc_id}/issues/{issue_id}/feedback（`issues.py:174-209`）
- Body：必填 `DismissalFeedbackModel`。
- 仅写 `feedback` 字段（`issues_service.py:158-173`），**不改状态**。

## 服务编排（IssuesService，`services/issues_service.py`）

- `get_issues_data`（:19-36）：透传仓储查询。
- `initiate_review`（:39-75）：调 `AMLClient.call_aml_endpoint(settings.aml_endpoint_name, pdf_name)` → 每块用 `FlowOutputChunk` 校验（:57）→ 为每个 issue 生成 uuid、填 doc_id/status/review_initiated_by/时间戳（:58-67）→ 逐块 upsert（:70）→ yield。
  - 观察与意图不一致：参数签名 `time_stamp: datetime`（:39），而路由传入的是 `datetime.now(timezone.utc).isoformat()` 字符串（`routers/issues.py:62-63`），实际被直接存为字符串（与 `Issue.review_initiated_at_UTC: str` 类型一致，`common/models.py:87`）。
- `accept_issue`（:78-115）：read → `model_copy(update=...)` → upsert。
- `dismiss_issue`（:118-155）/ `add_feedback`（:158-183）：read → 字段覆盖 → upsert（`issues_repository.update_issue`，`database/issues_repository.py:56-75`）。

## 外部调用（AMLClient，`services/aml_client.py`）

- `call_aml_endpoint`（:20-82）：
  - scoring URI 拼接 `https://{endpoint}.{region}.inference.ml.azure.com/score`（:32）；
  - 用 `MLClient.online_endpoints.get_keys()` 取 Entra token（`dependencies.py:12-20` 构造 MLClient，DefaultAzureCredential）；
  - POST `{"pdf_name", "stream": True, "pagination": settings.aml_streaming_batch_size}`，`Accept: text/event-stream`（:38-47）；
  - 用 `sseclient` 解析，仅转发含 `flow_output_streaming` 键的事件，`flow_output` 事件被忽略（:55-63）；
  - HTTPError → 透传上游状态码与响应文本（:68-73）。
  - ⚠️ `:28-29` 在无 `PYTHONHTTPSVERIFY` 时**全局禁用 SSL 证书校验**（`ssl._create_default_https_context = ssl._create_unverified_context`），影响整个进程。

## 数据访问（Cosmos）

- `CosmosDBClient`（`database/db_client.py:9-78`）：`upsert_item` / `read_item(partition_key=doc_id)` / 参数化 SQL 查询（列名拼接但值参数化，:60-62）。所有方法标 `async` 但内部为同步调用（阻塞事件循环，见 P1-03）。
- `IssuesRepository`（`database/issues_repository.py:9-75`）：`get_issues`（按 `doc_id` 过滤，跨分区查询 :26）、`get_issue`（单读，找不到时 `Issue(**None)` 会 TypeError——`db_client.retrieve_item_by_id` 对 404 返回 None :43-45，而 `get_issue` 无空值保护 :39-40）、`store_issues`（逐条 upsert）、`update_issue`（读-改-写，无并发控制）。

## 错误处理语义

- 全局：HTTPException 规范化；未知异常 500 + `str(exc)` 泄漏（P1-02）。
- SSE 内：异常被降级为 `event: error` 事件，**HTTP 状态已是 200**，客户端需按事件处理（`issues.py:70-73`；前端对应 `types/api-events.ts:2`）。
- 鉴权失败由 fastapi-azure-auth 返回 401（端点 responses 声明见 `issues.py:27` 等）。

## 后台任务

无独立后台任务/队列；审阅长任务完全由 AML 端点承担，API 仅做流式代理。`feedback_container` 与 API 侧 storage 设置为未接线配置。

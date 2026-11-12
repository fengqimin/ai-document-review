> **[2026-11] 时效说明**：本系列 wiki 记录的是 Azure 架构时期的实现细节，部分章节（Blob 直连、Cosmos、Entra/MSAL、PromptFlow、AML 端点）已不再适用。当前方案见 [README](../../README.md)、[local_deployment.md](../local_deployment.md) 与 [local-deployment-plan.md](../local-deployment-plan.md)。数据契约（Issue 模型与 SSE 事件）仍保持一致，其余请以最新文档为准。

# 07 · 运维

## 前置条件

本地方案基于 Task（go-task）编排，工具链检查见 `Taskfile.yml:19-58`：`az`、`terraform`、`python3`、`node`(22)、`mkcert`、`pfazure`、`git`。自动安装脚本 `task deps-install`（:60-159，面向 apt 系 Linux/DevContainer；`.devcontainer/` 提供容器环境）。

## 运行模式

### 1. 本地开发（最小闭环）

```bash
# 后端：创建 venv 并启动 uvicorn --reload（.task/app.yml:110-120）
task api-run          # = cd app/api && .venv/bin/python3 -m uvicorn main:app --reload

# 前端：Vite dev server，/api 代理到 127.0.0.1:8000（vite.config.ts:10-14）
cd app/ui && npm install && npm start
```

本地 API 需要 `.env`（Pydantic Settings，`app/api/config/config.py:27`）以及 Entra 登录可用（DefaultAzureCredential / MSAL）。

### 2. 构建

```bash
task app-build        # = api（venv + pip install）+ ui（npm build → ../api/www）（.task/app.yml:4-39）
task app-clean        # 清理 .venv / www / node_modules（:41-75）
```

### 3. 云端部署

- **基础设施**：Terraform（`infra/`），样例变量 `infra/environments/local.tfvars.sample`。任务文件 `.task/infra.yml`（未在本次展开，入口 `Taskfile.yml:7-16`）。
- **Flow**：
  - `task flow-deploy` / `flow-deploy-agent` / `flow-deploy-eval`：`pfazure flow create` 注册到 AI Foundry（`.task/flow.yml:3-66`）。
  - `task flow-deploy-endpoint`：复制 `common/`、注册模型、sed 渲染 `deployment.yaml` 占位符（VAR_*），create-or-update 在线部署并切 100% 流量（`.task/flow.yml:68-115`）。
- **应用**：`task app-deploy`：打包 api（含拷入的 common + 构建产物 www）为 zip，`az webapp deploy` 到 App Service（`.task/app.yml:77-108`）。
- CI/CD：`.github/workflows/main.yml`（未在本文档展开）。

## 环境变量清单

### API（`app/api/config/config.py`，经 `.env` 或环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEBUG` | false | |
| `AAD_CLIENT_ID` / `AAD_TENANT_ID` / `AAD_USER_IMPERSONATION_SCOPE_ID` | 空 | Entra 鉴权（鉴权 scope id 必填否则 401 全端点） |
| `SERVE_STATIC` | true | 挂载 `www/` 静态前端 |
| `COSMOS_URL` | 空 | Cosmos 端点（凭据走 DefaultAzureCredential） |
| `DATABASE_NAME` / `ISSUES_CONTAINER` / `FEEDBACK_CONTAINER` | state / issues / feedback | feedback 容器未接线 |
| `STORAGE_ACCOUNT_URL` / `STORAGE_CONTAINER_NAME` | 空 | API 侧未使用（前端直连） |
| `SUBSCRIPTION_ID` / `RESOURCE_GROUP` / `AI_HUB_PROJECT_NAME` | 空 | MLClient 上下文 |
| `AML_ENDPOINT_NAME` | 空 | 审阅端点名 |
| `AML_STREAMING_BATCH_SIZE` | 10 | 请求体 pagination |
| `APPINSIGHTS_INSTRUMENTATION_KEY` | 空 | App Insights 连接 |
| `LOG_LEVEL` | INFO | Azure handler 级别 |

### Flow 容器（`deployment.yaml:26-36` 部署时注入）

`PRT_CONFIG_OVERRIDE`、`AZURE_CLIENT_ID`、`PROMPTFLOW_RESPONSE_INCLUDED_FIELDS='["flow_output_streaming"]'`、`DOCUMENT_INTELLIGENCE_ENDPOINT`、`STORAGE_URL_PREFIX`、`AZURE_OPENAI_ENDPOINT`（另见 `flow.dag.yaml:3-6` 的 `${aisconns.*}` 连接引用）。

### 前端（构建期 VITE_*，`authConfig.ts`、`main.tsx`）

`VITE_CLIENT_ID`、`VITE_TENANT_ID`、`VITE_API_SCOPE`、`VITE_STORAGE_ACCOUNT`、`VITE_STORAGE_DOCUMENT_CONTAINER`。

## 健康检查 / 监控

- API：`GET /api/health` → 204（`app/api/main.py:41-48`）；Flow 容器 liveness/readiness 也是 `/health`（`deployment.yaml:11-16`，由 PromptFlow serving 镜像提供）。
- 日志：控制台 + `app.log` 文件 + App Insights（`middleware/logging.py:48-73`）；请求级耗时日志由 `LoggingMiddleware` 输出。
- 无 metrics 端点、无分布式 trace 传播（未验证 App Insights 侧采样配置）。

## 故障排查表

| 现象 | 可能原因 | 排查 |
|---|---|---|
| 所有 /api/v1 401 | `AAD_*` 未配或 scope id 不符 | 检查 `.env` 与 `security/auth.py:11-13` |
| 前端 401/consent 弹窗循环 | `VITE_API_SCOPE` 与 API expose scope 不一致 | `authConfig.ts:23-25` |
| review 页白屏/控制台 TypeError | issue 无 bounding_box（包围盒计算失败链路，见 03 章） | 后端日志 `Unable to add bounding box` |
| `Unable to retrieve token for the Azure ML endpoint` | 端点未启用 Entra Auth | `aml_client.py:35-36` |
| SSE 立即 error 事件 | AML 上游 4xx/5xx，detail 透传（`aml_client.py:68-73`） | 看 `event: error` data |
| 本地 UI 打不开 PDF | Blob CORS 未对 localhost 放行 / 存储容器权限 | 浏览器 Network 面板 |
| `app.log` 不生成 | 工作目录无写权限 | `middleware/logging.py:57` |
| evaluate 流 KeyError: doc_major_version | `system_monitor` 与现行 schema 脱节 | `eval/src/system_monitor.py:83-84` |

## 备份/导入

代码库未包含数据导入导出工具；数据持久化完全依赖 Cosmos DB（Azure 侧备份策略，仓库内未配置，未验证）。

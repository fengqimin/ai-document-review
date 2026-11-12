> **[2026-11] 时效说明**：本系列 wiki 记录的是 Azure 架构时期的实现细节，部分章节（Blob 直连、Cosmos、Entra/MSAL、PromptFlow、AML 端点）已不再适用。当前方案见 [README](../../README.md)、[local_deployment.md](../local_deployment.md) 与 [local-deployment-plan.md](../local-deployment-plan.md)。数据契约（Issue 模型与 SSE 事件）仍保持一致，其余请以最新文档为准。

# 08 · 问题清单与建议

> 严重级别：P0 = 核心功能损坏/数据损坏/安全暴露；P1 = 常见路径错误行为或严重可维护性问题；P2 = 体验/性能/一致性问题。
> 除标注"未验证"外，每条均有 commit `c91254a` 的代码证据。运行时复现受本地凭据限制的条目已在证据中说明。

## P0

### P0-01 CORS 通配符 + 凭据，任意站点可携带凭据调用 API
- **证据**：`app/api/main.py:28-34` `allow_origins=["*"]` 且 `allow_credentials=True, allow_methods=["*"], allow_headers=["*"]`。Starlette 在此组合下会回显请求 Origin，等效于任意来源的凭据访问。
- **影响**：结合 MSAL 令牌由前端 JS 持有、API 含用户身份信息（`Issue.review_initiated_by` 等），恶意页面可诱导已登录用户浏览器跨站调用 API。
- **建议**：改为显式来源列表（来自环境变量），生产禁用 `*`（与 `docs/architecture.md` 的安全意图一致）。

## P1

### P1-01 全局异常处理器向客户端回显内部异常消息
- **证据**：`app/api/main.py:67-76` 返回 `{"message": str(exc)}`；SSE 路径同样把原始异常串进 `event: error`（`routers/issues.py:70-73`）。
- **影响**：泄露内部细节（连接串片段、Azure 响应体等，`aml_client.py:70-73` 还透传上游 response text）。
- **建议**：对外固定文案 + 关联 ID，详情仅入日志。

### P1-02 进程级禁用 SSL 证书校验
- **证据**：`app/api/services/aml_client.py:28-29` 在无 `PYTHONHTTPSVERIFY` 时设置 `ssl._create_default_https_context = ssl._create_unverified_context`（全局、不可逆的进程级副作用）。
- **影响**：所有 HTTPS 请求（含 Cosmos、AML）降级为不校验证书，存在中间人风险。
- **建议**：删除；确有自签需求时用受控的 ssl context。

### P1-03 async 方法内执行同步 Cosmos SDK 调用，阻塞事件循环
- **证据**：`database/db_client.py:18-78` 三个方法均为 `async def` 但直接调用同步 `upsert_item/read_item/query_items`（azure-cosmos 4.7.0 同步 SDK）。
- **影响**：每个 DB 调用期间整个事件循环停摆；SSE 流式审阅时尤为明显（每个分块多次 upsert），并发吞吐骤降。
- **建议**：换 `azure.cosmos.aio` 异步 SDK，或用 `asyncio.to_thread` 包装。

### P1-04 同一文档重复审阅无幂等保护，数据重复
- **证据**：`routers/issues.py:49-63` 先查后发起（check-then-act 无锁）；每次 `initiate_review` 生成新 uuid（`issues_service.py:61`）并 upsert，旧 issue 永不清理（04 章"删除：无"）。
- **影响**：两个标签页/两次刷新并发即翻倍入库；用户会看到成对重复问题；统计指标被污染。
- **建议**：以 `(doc_id)` 或 `(doc_id, content-hash)` 为幂等键：发起前写"审阅中"标记或用固定 id 规则 upsert；重复请求复用现有流。

### P1-05 前端排序访问 `bounding_box[1]` 可致 Review 页崩溃
- **证据**：`app/ui/src/pages/review/Review.tsx:312` `b.location.bounding_box[1]`；包围盒计算失败链路会产出空 `bounding_box`（`bounding_box.py:69-73,77-81` 失败时原样返回；`Location.bounding_box` 必填但允许空数组）；`location` 本身可空（`common/models.py:85`）。
- **影响**：任何一个问题坐标解析失败，整个问题列表渲染抛 TypeError（react-pdf 页面虽在，但列表崩溃影响核心交互）。运行时复现**未验证**（需构造失败样本）。
- **建议**：排序加保护（`a.location?.bounding_box?.[1] ?? 0`），后端失败时填充占位框。

### P1-06 `get_issue` 404 → `Issue(**None)` TypeError（500 而非 404）
- **证据**：`database/db_client.py:43-45` 404 返回 None；`issues_repository.py:39-40` 直接 `Issue(**issue)`。
- **影响**：accept/dismiss/feedback 对不存在 issue 返回 500，语义错误且日志噪音。
- **建议**：仓储层抛 `ValueError("Issue not found")`（`update_issue` 已有此模式，`issues_repository.py:74-75`），路由映射 404。

### P1-07 `eval/system_monitor` 引用不存在的字段，运行必失败
- **证据**：`eval/src/system_monitor.py:83-84` 排序引用 `doc_major_version`/`doc_minor_version`；`common/models.py:77-94` 的 `Issue` 无这两个字段（`get_issues_data` 返回的 DataFrame 也只能来自该模型）。运行时**未验证**（缺 pandas 环境），属静态确证的 schema 脱节。
- **影响**：「已审阅文档数」指标无法产出，LLM Ops 反馈闭环（README 宣传点）断裂。
- **建议**：删除排序或改为仅按 `doc_id` 去重。

## P2

### P2-01 `get_false_negatives()` 返回错集合（复制粘贴错误）
- **证据**：`eval/src/issue_associator.py:115-119` 返回 `len(self._unassociated_model_output)`，应为 `_unassociated_ground_truth`（docstring 也写错为 "true positive issues"，:109-113 同样）。
- **影响**：当前评估流经 `metric_calculator.calculate_false_negatives_per_type()`（直接取 ground truth，`metric_calculator.py:75-94`）未受影响；但该方法作为公共 API 一旦被使用即产生错误 FN。

### P2-02 `save_results_to_json` 装饰与签名矛盾
- **证据**：`eval/src/metric_calculator.py:212-217` `@staticmethod` 但首参 `self`，调用 `MetricsCalculator.save_results_to_json(results)` 会把 results 绑到 self。
- **运行时复核（2026-11-13，pytest）**：`test_write_metrics_to_promptflow_per_type` 以 `TypeError: write_metrics_to_promptflow_per_type() missing 1 required positional argument: 'metrics'` 失败——`write_metrics_to_promptflow_per_type`（`metric_calculator.py:202-210`）同样为 `@staticmethod` 但要求 `metrics` 参数，测试按无参旧签名调用。API 已偏离其调用方。

### 附：测试套件运行时状态（pytest 实测，2026-11-13）
在 Python 3.13 + promptflow 1.18.5（锁定的 1.17.1 不支持 3.13）+ pandas 环境下运行 `pytest eval/tests`：**3 通过 / 6 失败**。失败分解：

- **陈旧测试夹具（5 条，测试期望与实现/数据不符）**：`test_issue_associator` 全部 3 条——setUp 只提供 1 条可完全匹配的 issue，期望值却引用未注入的数据且期望字典缺少 `page_num`/`document_id` 键、type 拼写与实现不一致（"definitive lanugage" vs "language"）；`test_precision_recall_per_type` 断言的 `'alarmist terms'` 类型从未出现在数据中（KeyError）。
- **真实 API/行为不一致（2 条）**：上述 `write_metrics_to_promptflow_per_type` 签名 TypeError；`test_suggestion_approval_rate_no_accepted_rows` 期望无 accepted 行时返回 `0.0`，实现返回 `None`（`system_monitor.py:113-117` 显式写入 None）——语义需二选一修正。

### P2-03 非流式分块参数三处不一致
- **证据**：`process.py:45`（64）、`flow.dag.yaml:20-23`（默认 32）、`text.py:10`（16）。建议统一到配置。

### P2-04 `get_issues` 对查询错误返回 None 后 `len(None)`
- **证据**：`db_client.py:76-78` 出错返回 None；`issues_repository.py:26-27` 直接 `len(issues)` → TypeError → 500。

### P2-05 `getAccessToken` 失败路径返回 undefined
- **证据**：`app/ui/src/services/api.ts:21-30`：非交互式错误时无 return → `Bearer undefined`；调用方不检查。

### P2-06 SSE 重试无退避且可能并发多路流
- **证据**：`api.ts:125-135` `onerror` 中递归 `startStream()`（未 await、无 backoff）；`fetchEventSource` 默认重连与手工重试叠加。
- **建议**：加指数退避 + 在重试前 abort 旧连接。

### P2-07 每请求新建 MLClient/DefaultAzureCredential
- **证据**：`dependencies.py:9-20` 每个请求构造完整 MLClient（取 token 走 Entra），叠加 `get_keys()` 每次 review 一次（`aml_client.py:33`）。建议缓存凭据/端点密钥（带 TTL）。

### P2-08 MSAL 令牌缓存置于 localStorage
- **证据**：`app/ui/src/authConfig.ts:10-13`。XSS 下令牌可被读取；建议 `sessionStorage` 或内存 + B2C/SPA 最佳实践权衡。

### P2-09 配置项漂移：`cosmos_key`、`feedback_container`、`storage_account_url` 声明未用
- **证据**：`config/config.py:12-18`；`CosmosDBConfig` 只用 URL+DefaultAzureCredential（`database/config.py:14`）；feedback 写在 issue 文档内（04 章）。误导运维配置。

### P2-10 `marshmallow`、前端 `@azure/identity` 等疑似无用依赖
- **证据**：`app/api/requirements.txt:7`、`app/ui/package.json:8-9`；仓库内无 import（Grep 全库未命中使用点）。建议清理缩小攻击面。

### P2-11 `handleUpdateIssue` 直接变异 state 数组元素
- **证据**：`Review.tsx:131-139` `issues[index] = updatedIssue` 后浅拷贝。功能可用但违反不可变更新约定，易在并发更新（流式追加 + PATCH 返回）时丢更新。

### P2-12 `Issue` 时间字段为字符串而非 datetime
- **证据**：`common/models.py:87-89`；路由传 isoformat 字符串（`issues.py:62-63`）与 `initiate_review` 的 `time_stamp: datetime` 注解不符（`issues_service.py:39`）。排序/统计需字符串解析。

## 路线图建议（按收益排序）

1. **安全加固批次**：P0-01、P1-01、P1-02（改动小、风险高）。
2. **正确性批次**：P1-03（aio SDK）、P1-04（幂等）、P1-06（404 语义）、P1-05（前端防护）。
3. **反馈闭环修复**：P1-07、P2-01、P2-02（评估链路）。
4. **卫生批次**：P2-03/09/10/11/12 + 清理无用依赖；为 `app/api` 补 pytest（当前仅 eval 有测试 `eval/tests/`），覆盖仓储错误路径与 SSE 事件格式。

# 09 · 代码参考（符号索引）

> 按模块分组的 symbol → file:line 映射（基准 commit `c91254a`）。kind：函数 fn / 类 cls / 方法 m / 常量 const / 路由 rt / 组件 cmp。

## app/api — FastAPI 后端

| 符号 | kind | 位置 | 用途 |
|---|---|---|---|
| `app` | const | app/api/main.py:18 | FastAPI 实例（PKCE Swagger 配置） |
| `health_check` | rt | app/api/main.py:46 | GET /api/health → 204 |
| `http_exception_handler` | fn | app/api/main.py:58 | HTTPException 规范化 |
| `general_exception_handler` | fn | app/api/main.py:68 | 兜底 500（回显 str(exc)） |
| `Settings` | cls | app/api/config/config.py:5 | 环境变量配置模型 |
| `settings` | const | app/api/config/config.py:30 | 全局配置单例 |
| `CosmosDBConfig` | cls | app/api/database/config.py:6 | Cosmos 连接构造（DefaultAzureCredential） |
| `CosmosDBClient` | cls | app/api/database/db_client.py:9 | 通用容器客户端 |
| `CosmosDBClient.store_item` | m | app/api/database/db_client.py:18 | upsert |
| `CosmosDBClient.retrieve_item_by_id` | m | app/api/database/db_client.py:32 | 单读（404→None） |
| `CosmosDBClient.retrieve_items_by_values` | m | app/api/database/db_client.py:51 | 参数化条件查询 |
| `IssuesRepository` | cls | app/api/database/issues_repository.py:9 | Issue 仓储 |
| `IssuesRepository.get_issues` | m | app/api/database/issues_repository.py:15 | 按 doc_id 查全部 |
| `IssuesRepository.get_issue` | m | app/api/database/issues_repository.py:31 | 单读（无空值保护） |
| `IssuesRepository.store_issues` | m | app/api/database/issues_repository.py:43 | 批量 upsert |
| `IssuesRepository.update_issue` | m | app/api/database/issues_repository.py:56 | 读-改-写 |
| `azure_scheme` | const | app/api/security/auth.py:7 | fastapi-azure-auth 单租户 Bearer |
| `validate_authenticated` | fn | app/api/security/auth.py:16 | 鉴权依赖 |
| `LoggingMiddleware` | cls | app/api/middleware/logging.py:9 | 请求耗时/异常日志 |
| `setup_logging` | fn | app/api/middleware/logging.py:48 | 控制台+文件+App Insights |
| `router` | const | app/api/routers/issues.py:14 | 问题路由集 |
| `issues_event` | fn | app/api/routers/issues.py:18 | SSE `issues` 事件序列化 |
| `get_pdf_issues` | rt | app/api/routers/issues.py:31 | GET .../issues（SSE 流式审阅） |
| `accept_issue` | rt | app/api/routers/issues.py:102 | PATCH .../accept |
| `dismiss_issue` | rt | app/api/routers/issues.py:144 | PATCH .../dismiss |
| `provide_feedback` | rt | app/api/routers/issues.py:186 | PATCH .../feedback |
| `IssuesService` | cls | app/api/services/issues_service.py:13 | 审阅编排服务 |
| `IssuesService.get_issues_data` | m | app/api/services/issues_service.py:19 | 查询已有问题 |
| `IssuesService.initiate_review` | m | app/api/services/issues_service.py:39 | 发起 AML 审阅，分块入库 |
| `IssuesService.accept_issue` | m | app/api/services/issues_service.py:78 | 置 accepted + modified_fields |
| `IssuesService.dismiss_issue` | m | app/api/services/issues_service.py:118 | 置 dismissed + dismissal_feedback |
| `IssuesService.add_feedback` | m | app/api/services/issues_service.py:158 | 写 feedback 字段 |
| `AMLClient` | cls | app/api/services/aml_client.py:15 | AML 端点 SSE 消费者 |
| `AMLClient.call_aml_endpoint` | m | app/api/services/aml_client.py:20 | POST /score 并解析 SSE |
| `get_issues_service` | fn | app/api/dependencies.py:9 | 组合根：Service(Repository, AMLClient) |
| `get_aml_client` | fn | app/api/dependencies.py:12 | 构造 MLClient + AMLClient |

## common — 共享模型与日志

| 符号 | kind | 位置 | 用途 |
|---|---|---|---|
| `Location` | cls | common/models.py:6 | source_sentence/page_num/bounding_box/para_index |
| `IssueType` | cls | common/models.py:13 | Grammar & Spelling / Definitive Language |
| `SingleShotIssue` | cls | common/models.py:18 | agent 原始输出条目（含 comment_id） |
| `ConsolidatorIssue` | cls | common/models.py:27 | 整合者评分条目 |
| `CombinedIssue` | cls | common/models.py:34 | 两者合并 |
| `AllSingleShotIssues` | cls | common/models.py:38 | 条目集合 |
| `AllConsolidatorIssues` | cls | common/models.py:42 | 条目集合 |
| `AllCombinedIssues` | cls | common/models.py:46 | 合并集合（Flow 最终输出） |
| `BaseIssue` | cls | common/models.py:50 | 端点侧精简条目 |
| `FlowOutputChunk` | cls | common/models.py:58 | AML 分块载荷 |
| `IssueStatusEnum` | cls | common/models.py:62 | not_reviewed/accepted/dismissed |
| `ModifiedFieldsModel` | cls | common/models.py:68 | accept 时的用户改写 |
| `DismissalFeedbackModel` | cls | common/models.py:73 | 驳回反馈 |
| `Issue` | cls | common/models.py:77 | Cosmos 落库/响应模型 |
| `get_logger` | fn | common/logger.py:4 | 标准库 logger 取用 |

## flows/ai_doc_review — 审阅流水线

| 符号 | kind | 位置 | 用途 |
|---|---|---|---|
| `AGENT_PROMPTS` | const | flows/ai_doc_review/flows.py:15 | 类型→提示词文件映射 |
| `create_flow` | fn | flows/ai_doc_review/flows.py:29 | 加载模板并覆盖提示词/连接 |
| `setup_flows` | fn | flows/ai_doc_review/flows.py:47 | 构造 Entra 连接 + 全部 flow |
| `run_flow` | fn | flows/ai_doc_review/process.py:14 | 单 flow 执行适配 |
| `get_issues_from_text_chunks` | fn | flows/ai_doc_review/process.py:19 | 抽取→分块→并发 agent→包围盒→yield |
| `process`（非流式） | fn | flows/ai_doc_review/process.py:43 | pagination=64 全量收集 |
| `process`（流式） | fn | flows/ai_doc_review/process_streaming.py:13 | 按块 yield JSON |
| `analyze_document` | fn | flows/ai_doc_review/text.py:15 | DI prebuilt-document 抽取 |
| `get_text_chunks` | fn | flows/ai_doc_review/text.py:30 | 段落分块 + [i] 前缀 |
| `create_bounding_box` | fn | flows/ai_doc_review/bounding_box.py:8 | 词多边形→quadpoints |
| `add_bounding_box` | fn | flows/ai_doc_review/bounding_box.py:50 | 定位词序并回填坐标 |
| `merge_singleshot_fields_with_consolidator` | fn | flows/ai_doc_review/agent_template/merge.py:9 | comment_id 拼接，滤 REMOVE |
| `aggregate_single_shots` | fn | flows/ai_doc_review/agent_template/aggregate.py:13 | 5-shot 去重 + comment_id |

## flows/ai_doc_review_eval 与 eval/src — 评估

| 符号 | kind | 位置 | 用途 |
|---|---|---|---|
| `evaluate_issues` | fn | flows/ai_doc_review_eval/evaluation.py:6 | 关联+指标入口（阈值 0.8） |
| `aggregate` | fn | flows/ai_doc_review_eval/aggregate.py:7 | 多 run 聚合 |
| `log_metrics` | fn | flows/ai_doc_review_eval/log_metrics.py:7 | promptflow.log_metric 打点 |
| `IssueAssociator` | cls | eval/src/issue_associator.py:3 | 相似度（SequenceMatcher）关联 |
| `IssueAssociator.similarity_ratio` | m | eval/src/issue_associator.py:21 | 文本相似度 |
| `IssueAssociator.associate_issues` | m | eval/src/issue_associator.py:34 | 贪心最佳匹配 |
| `IssueAssociator.get_false_negatives` | m | eval/src/issue_associator.py:115 | ⚠ 返回错集合（见 08 章 P2-01） |
| `MetricsCalculator` | cls | eval/src/metric_calculator.py:5 | TP/FP/FN/Precision/Recall |
| `MetricsCalculator.calculate_precision_per_type` | m | eval/src/metric_calculator.py:96 | 除零保护 |
| `MetricsCalculator.calculate_metrics_from_multiple_results` | m | eval/src/metric_calculator.py:220 | 跨 run 聚合 |
| `Metric` | cls | eval/src/system_monitor.py:5 | 指标值容器 |
| `SystemMonitor` | cls | eval/src/system_monitor.py:25 | 配置驱动指标计算 |
| `SystemMonitor._calculate_amount_of_unique_document_reviewed` | m | eval/src/system_monitor.py:79 | ⚠ 引用不存在字段（P1-07） |

## app/ui — React 前端

| 符号 | kind | 位置 | 用途 |
|---|---|---|---|
| `MsalAzureCredential` | cls | app/ui/src/main.tsx:10 | Blob SDK 的 MSAL 凭据适配器 |
| `msalInstance` | const | app/ui/src/main.tsx:25 | MSAL 公共客户端 |
| `storageClient` | const | app/ui/src/main.tsx:27 | BlobServiceClient（VITE_STORAGE_ACCOUNT） |
| `containerClient` | const | app/ui/src/main.tsx:29 | documents 容器客户端 |
| `App` | cmp | app/ui/src/App.tsx:35 | 布局 + MsalProvider + 路由 |
| `Pages` | cmp | app/ui/src/App.tsx:65 | / 与 /review 路由 |
| `msalConfig` | const | app/ui/src/authConfig.ts:3 | clientId/authority/cache |
| `loginRequest` | const | app/ui/src/authConfig.ts:17 | 登录 scopes |
| `accessTokenRequest` | const | app/ui/src/authConfig.ts:23 | VITE_API_SCOPE |
| `Files` | cmp | app/ui/src/pages/files/Files.tsx:55 | 文档列表/上传 |
| `handleUploadFile` | fn | app/ui/src/pages/files/Files.tsx:84 | 上传后跳转 review |
| `Review` | cmp | app/ui/src/pages/review/Review.tsx:44 | 审阅工作台 |
| `handleSelectIssue` | fn | app/ui/src/pages/review/Review.tsx:97 | 选中问题→翻页+红框标注 |
| `handleUpdateIssue` | fn | app/ui/src/pages/review/Review.tsx:131 | PATCH 结果回填 |
| `runCheck` | fn | app/ui/src/pages/review/Review.tsx:163 | SSE 消费（issues/error/complete） |
| `IssueCard` | cmp | app/ui/src/components/IssueCard.tsx:31 | 单条问题卡 |
| `handleAccept` | fn | app/ui/src/components/IssueCard.tsx:58 | PATCH accept |
| `handleDismiss` | fn | app/ui/src/components/IssueCard.tsx:95 | PATCH dismiss |
| `handleSubmitFeedback` | fn | app/ui/src/components/IssueCard.tsx:118 | PATCH feedback |
| `getAccessToken` | fn | app/ui/src/services/api.ts:12 | MSAL 静默/弹窗取 token |
| `getErrorMessage` | fn | app/ui/src/services/api.ts:33 | 错误响应→可读文案 |
| `callApi` | fn | app/ui/src/services/api.ts:62 | 普通 REST 调用 |
| `streamApi` | fn | app/ui/src/services/api.ts:86 | fetchEventSource + 重试 |
| `initAnnotations` | fn | app/ui/src/services/annotations.ts:10 | 初始化标注层 |
| `addAnnotation` | fn | app/ui/src/services/annotations.ts:24 | 高亮 quadpoints |
| `deleteAnnotation` | fn | app/ui/src/services/annotations.ts:43 | 删除标注 |
| `getBlob` | fn | app/ui/src/services/storage.ts:4 | 下载 PDF |
| `listBlobs` | fn | app/ui/src/services/storage.ts:14 | 列表 |
| `uploadBlob` | fn | app/ui/src/services/storage.ts:23 | 上传 |
| `Issue` / `IssueStatus` | type/enum | app/ui/src/types/issue.ts:1,22 | 前端数据契约 |
| `APIEvent` | enum | app/ui/src/types/api-events.ts:1 | issues/error/complete |
| `RetriableError` / `FatalError` | cls | app/ui/src/types/error.ts:1-2 | 重试语义标记 |

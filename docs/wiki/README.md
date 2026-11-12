# AI Document Review — 代码 Wiki

> 本 Wiki 基于仓库 `ai-document-review` 在 commit `c91254a`（HEAD -> main，2025 年前后代码状态）生成，所有行号引用均以该 commit 为准。

## 一页概览

**AI Document Review** 是一个 Azure 解决方案加速器（源自 Azure-Samples）：用户上传 PDF 文档，系统通过 Document Intelligence 抽取文本，再由一组可定制的 LLM「审阅智能体」（PromptFlow 编排）识别文档中的问题（如语法拼写、确定性表述），并将结果以 SSE 流式推送到 Web UI，用户可接受/驳回问题并提交反馈，反馈数据用于评估与持续改进提示词。

核心组件：

| 组件 | 技术栈 | 位置 | 职责 |
|---|---|---|---|
| Web UI | React 18 + Fluent UI v9 + MSAL + Vite | `app/ui/` | 文档上传（直连 Blob）、PDF 阅读与高亮标注、问题审阅与反馈 |
| API | FastAPI（Python 3） | `app/api/` | 鉴权、问题存取（Cosmos DB）、SSE 流式转发 AML 端点结果、托管静态前端 |
| 共享模型 | Pydantic | `common/` | Issue 等数据模型与日志工具，被 API 与 Flow 两侧共享 |
| 审阅流水线 | PromptFlow + Azure OpenAI (gpt-4o) + Document Intelligence | `flows/ai_doc_review/` | 多智能体审阅：抽取文本 → 多 shot 检出 → 合并去重 → 整合评分 → 计算包围盒 |
| 评估流水线 | PromptFlow 评估流 + pytest | `flows/ai_doc_review_eval/`、`eval/` | 检出结果与标注数据对齐（相似度匹配），计算 Precision/Recall，聚合打点 |
| 基础设施 | Terraform (azurerm/azapi) | `infra/` | 资源组、NSP 网络边界、Cosmos DB、App Service、AI Foundry Hub、Entra 身份 |

## 按角色的阅读路径

- **新成员上手**：[README](README.md) → [01-架构](01-architecture.md) → [07-运维](07-operations.md)（跑起来）→ [09-代码索引](09-code-reference.md)（当字典查）
- **后端开发**：[02-后端 API](02-backend-api.md) → [04-数据模型](04-data-model.md) → [08-问题清单](08-issues-and-recommendations.md)
- **AI/提示词工程**：[03-审阅流水线](03-review-flow.md) → [06-依赖](06-dependencies.md)
- **前端开发**：[05-前端](05-frontend.md) → [08-问题清单](08-issues-and-recommendations.md)
- **运维/DevOps**：[07-运维](07-operations.md) → [01-架构](01-architecture.md)

## 章节索引

| 章节 | 内容 |
|---|---|
| [01-architecture.md](01-architecture.md) | 系统定位、运行时/分层架构图、核心数据流、技术选型与架构风险 |
| [02-backend-api.md](02-backend-api.md) | FastAPI 生命周期、全部端点契约、服务编排、错误处理、SSE 语义 |
| [03-review-flow.md](03-review-flow.md) | 核心审阅流水线：多智能体 Flow、文本分块、包围盒计算、提示词体系 |
| [04-data-model.md](04-data-model.md) | Cosmos DB 容器与 Issue 模式、字段表、数据生命周期、数据质量风险 |
| [05-frontend.md](05-frontend.md) | 前端栈、路由、组件树、API 客户端、状态流、已知 UI 问题 |
| [06-dependencies.md](06-dependencies.md) | 运行时/开发依赖及使用位置、模块依赖图、共享代码策略 |
| [07-operations.md](07-operations.md) | 前置条件、安装、运行模式、环境变量、部署、故障排查 |
| [08-issues-and-recommendations.md](08-issues-and-recommendations.md) | 问题登记簿（P0/P1/P2）、证据、根因、修复建议、路线图 |
| [09-code-reference.md](09-code-reference.md) | 按模块分组的符号索引（symbol → file:line） |

## 快速开始（本地最小路径）

```bash
# 1. 后端（需已配置 .env，见 07-operations.md）
cd app/api
python3 -m venv .venv && .venv/bin/pip3 install -r requirements.txt
.venv/bin/python3 -m uvicorn main:app --reload

# 2. 前端（Vite 代理 /api → localhost:8000，见 app/ui/vite.config.ts:10-14）
cd app/ui
npm install && npm start
```

或使用 Task（`task api-run` / `task app-build`，见 `Taskfile.yml:7-16` 与 `.task/app.yml`）。

## 文档元数据

- **commit**: `c91254a`
- **生成日期**: 2026-11-13
- **覆盖范围**: 全栈（app/api + app/ui + common + flows + eval + infra）
- **验证状态**: 全部 Python 模块通过 `compileall` 语法编译；依赖安装、pytest、`npm run build` 及 Azure 服务连通性在文档生成环境中**未验证**（本地缺依赖/凭据），正文中均已标注。

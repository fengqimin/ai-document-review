# AI Document Review (local deployment)

AI Document Review 是一个可本地部署的文档审阅加速器：用户通过 Web UI 上传 PDF，由多个基于大模型的审阅 Agent 依据可定制的 guideline 提示词检出语法、绝对化用语等问题，流式返回带页码与包围盒定位的结果，支持接受/驳回与反馈回流。适用于法律、监管、技术等对内容合规与准确性要求较高的场景。

**当前版本为本地优先（local-first）架构**：应用、UI、PDF 原件、审阅结果与账号数据全部留在本地；唯一的外部依赖是一个 OpenAI 兼容协议的大模型端点（`LLM_BASE_URL` + `LLM_API_KEY` + `LLM_MODEL`，可指向 OpenAI、DeepSeek、通义、Moonshot 或内网 vLLM 等）。原 Azure 版本（Blob Storage、Cosmos DB、Document Intelligence、Azure OpenAI、Entra ID、Application Insights、AML 部署）已整体退役，相关资产移入 [`legacy/`](./legacy/README.md)。

![UI](./docs/images/ui_review_issues.png)

## 工作流程

1. **上传 PDF**：经文档 API 上传（本地文件存储，不再直连 Blob）。
2. **文本抽取**：PyMuPDF 抽取段落/词级文本与坐标，构造与 Document Intelligence 同形的数据结构；扫描件可选启用 Tesseract OCR。
3. **多 Agent 审阅**：按 chunk 并发发起多轮（默认 5-shot）检出 → 去重 → consolidator 整合 → 合并过滤，LLM 通过 OpenAI 兼容协议调用，结构化输出（`json_schema`，不支持时自动降级）。
4. **流式结果**：SSE 推送 issue 事件，前端 PDF 高亮定位。
5. **人工复核**：接受/驳回 issue 并提交反馈。

## 快速开始

```bash
cp .env.example .env       # 填入 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
docker compose up -d --build
# 打开 http://localhost:8000 ，默认账号 admin / admin123（首次登录后请修改）
```

不使用 Docker 时：

```bash
task api-install           # 或手动 python -m venv .venv && pip install -r requirements.txt
task ui-install && task ui-build
cd app/api && ../../.venv/bin/python -m uvicorn main:app --port 8000
```

详见 [docs/local_deployment.md](./docs/local_deployment.md)（配置项、厂商切换、OCR、数据迁移与故障排查）。

## 文档索引

- [架构说明](./docs/architecture.md) — 组件、数据流、API 契约
- [本地部署指南](./docs/local_deployment.md) — 一键部署、环境变量、模型端点配置
- [迁移设计方案](./docs/local-deployment-plan.md) — Azure → 本地方案的完整设计稿（组件对照、兼容性桥、风险）
- [开发指南](./docs/getting_started.md) — 本地开发环境、测试、目录结构
- [docs/wiki/](./docs/wiki/README.md) — 历史架构时期的实现细节 wiki（Azure 时期，仅供历史参考）
- [legacy/](./legacy/README.md) — 已退役的 Azure 部署资产（Terraform、PromptFlow、CI 等）

## 定制审阅 Agent

审阅规则完全由提示词驱动：在 `flows/ai_doc_review/prompts/` 下为每个 issue 类型维护 `guidelines.jinja2`（审阅准则）、`agent.jinja2`（检出提示）与 `consolidator.jinja2`（整合提示）。新增审阅维度只需新增一组提示词与 Pydantic 模型，无需改动引擎。

## Contributing

见 [CONTRIBUTING.md](./CONTRIBUTING.md) 与 [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)。

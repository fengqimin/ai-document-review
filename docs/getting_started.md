# 开发指南（Getting Started）

本指南面向本地开发环境。一键部署见 [local_deployment.md](./local_deployment.md)。

## 环境要求

- Python 3.12+（或 Docker）
- Node.js 22（仅前端构建/开发需要）
- [Task](https://taskfile.dev)（可选，也可手动执行等价命令）

## 开发环境搭建

```bash
# 1. 安装依赖（venv + npm）
task install
# 等价手动方式：
#   python3 -m venv .venv
#   .venv/bin/python -m pip install -r requirements.txt pytest
#   cd app/ui && npm install

# 2. 配置环境变量
cp .env.example .env      # 本地开发至少填入 LLM_* 三项，或留空用 degraded 模式调 API

# 3. 同时启动后端与前端 dev server
task dev
#   - 后端: http://localhost:8000 (uvicorn --reload)
#   - 前端: http://localhost:5173 (vite dev, 代理 /api)
#   未配置 LLM 时 /api/health 返回 degraded，审阅端点返回明确 error 事件，其余功能可用
```

默认账号 `admin / admin123`（首次建库自动引导；`AUTH_DISABLED=true` 时免登录）。

## 构建

```bash
task ui-build    # vite 构建产物输出到 app/api/www，由 API 静态托管
```

## 测试

```bash
task check-code  # compileall 编译检查
task test        # pytest：流水线 21 例 + 后端 12 例
# 单独运行：
.venv/bin/python -m pytest flows/ai_doc_review/tests app/api/tests -q
```

流水线测试使用 mock 的 OpenAI 兼容服务（本地 HTTP server），不消耗真实 token。

## 项目结构

```
app/api/         FastAPI 后端
  routers/       auth / documents / issues
  security/      本地账号（PBKDF2）+ JWT
  database/      SQLite 客户端与 issues 仓储
  services/      review_client（流水线包装）、issues_service
  tests/         后端回归测试
app/ui/          React 前端（Fluent UI + react-pdf）
  services/      api.ts（SSE/REST）、storage.ts（文档 API）、auth.ts
common/          Issue 数据模型与日志
flows/ai_doc_review/
  text.py        PyMuPDF 抽取（DI 同形结构）
  ocr.py         可选 Tesseract OCR
  llm.py         OpenAI 兼容客户端（schema 降级/退避/usage）
  pipeline.py    5-shot 检出 → 去重 → consolidator → REMOVE 过滤
  engine.py      stream_review() 同步生成器入口
  prompts/       jinja2 提示词（审阅规则的唯一来源）
  tests/         流水线测试
eval/            指标评估（读本地 SQLite）
legacy/          已退役 Azure 资产，勿改动
```

## 常见任务

- **新增审阅维度**：在 `flows/ai_doc_review/prompts/<type>/` 下加 `guidelines/agent/consolidator` 三份 jinja2，并在 `common/models.py` 的 `IssueType` 与 `pipeline.AGENT_PROMPTS` 注册。
- **切换 LLM 厂商**：改 `.env` 的 `LLM_BASE_URL/LLM_API_KEY/LLM_MODEL`，代码不动。
- **查看运行数据**：`data/review.db`（SQLite）与 `data/documents/`（PDF 原件），直接备份或拷贝即可。

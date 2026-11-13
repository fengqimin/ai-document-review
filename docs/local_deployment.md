# 本地部署指南

应用完全本地运行：UI、API、审阅引擎在同一个容器里，数据（SQLite、PDF、日志）落在 `./data/`，唯一的外部依赖是一个 OpenAI 兼容协议的大模型端点。

## 一键部署（Docker）

```bash
cp .env.example .env
# 编辑 .env：填入 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
docker compose up -d --build
```

打开 <http://localhost:8000>，默认账号 `admin / admin123`。**首次登录后请立即在 `.env` 中修改 `ADMIN_PASSWORD` 与 `JWT_SECRET` 并重启**。

数据备份：直接拷贝 `./data/` 目录即可（含 `review.db`、`documents/`、`logs/`）。

镜像为多阶段构建（node 阶段只产出 `www/` 静态文件，不进最终镜像），构建后约 **834MB**；`uv` 与 `npm` 的下载缓存使用 BuildKit 缓存挂载，不写入镜像层。compose 显式把 `DATA_DIR` 指到挂载点 `/app/data`——相对路径会按仓库根解析，不随工作目录漂移。

```bash
docker compose down   # 停止，data/ 保留
task logs             # 跟踪日志
```

## 不用 Docker 运行

需要 **Python 3.14+** 与 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync                                                  # 按 uv.lock 建 .venv 并装依赖
cd app/ui && npm install && npm run build && cd ../..    # UI 构建到 app/api/www
cd app/api && uv run --project ../.. uvicorn main:app --port 8000
```

## 配置 LLM 端点（厂商中立）

`LLM_BASE_URL` + `LLM_API_KEY` + `LLM_MODEL` 三项必填。任何实现 OpenAI Chat Completions 协议的服务均可：

| 厂商 | LLM_BASE_URL | 模型示例 |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 通义千问（兼容模式） | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-max` |
| Moonshot | `https://api.moonshot.cn/v1` | `moonshot-v1-128k` |
| 内网 vLLM / SGLang | `http://<host>:8000/v1` | 服务端 `--served-model-name` |

切换厂商只改 `.env` 三行，代码与提示词不动。

### 输出格式兼容性

不同厂商对结构化输出的实现差异很大，客户端做了三层兜底，实测能覆盖常见情况：

1. **`json_schema` 优先**：端点拒绝该字段时自动降级为 `json_object` + 在提示里注入 JSON Schema，只降级一次，后续调用沿用。
2. **信封容错**：不少端点（含部分 DeepSeek 兼容网关）无视请求的 `{"issues": [...]}` 结构，直接返回裸数组 `[{...}]`，或用 `items` / `data` 之类的键名，或在 JSON 外包一层 ```json 围栏。这些都自动纠正，不消耗重试次数。
3. **机械字段容错**：`page_num` / `bounding_box` / `comment_id` 由流水线自己计算（包围盒与去重阶段），模型漏填或填 `null` 时自动补默认值，不会因为一个占位字段丢掉整条有效发现。

真正缺语义字段（`text` / `explanation` / `suggested_fix` / `location.para_index`）时仍会重试并报错，不会静默吞掉。

### 数据出域与合规

- 审阅时**抽取出的文本分块**会发往上述端点——这是唯一出域点。
- PDF 原件、审阅结果、账号、日志全部留在本地。
- 涉敏文档要求数据不出内网时：用内网 GPU 通过 [vLLM](https://github.com/vllm-project/vllm) 或 SGLang 部署大参数开源模型（如 Qwen2.5-72B-Instruct），`LLM_BASE_URL` 指向内网地址即可，应用侧零改动。
- 日志只记录 token 用量与错误码，不记录 prompt 正文；API Key 仅保存在 `.env`（不入镜像、不入 git）。

## 关键配置项

| 变量 | 默认 | 说明 |
|---|---|---|
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | 空 | 必填；不配置时服务以 degraded 状态启动，审阅返回明确错误 |
| `LLM_STRICT_JSON` | `true` | 优先 `json_schema` 结构化输出，端点不支持时自动降级 `json_object` |
| `LLM_SHOTS` | `5` | 每 chunk 并发检出轮数（越高召回越好，token 消耗线性增加） |
| `LLM_MAX_WORKERS` | `8` | 单次审阅的全局并发请求上限（所有维度、所有在跑分块共用），注意厂商限流 |
| `CHUNK_MAX_WORKERS` | `2` | 同时在跑的分块数（有界预取，输出顺序不变） |
| `LLM_TRANSIENT_RETRIES` / `LLM_MAX_RETRIES` | `5` / `2` | 429/5xx 退避重试 / JSON 校验重试（分开计数） |
| `LLM_MAX_TOKENS` | `8192` | 单次输出上限；过小会把 JSON 截断（日志会提示 `finish_reason=length`） |
| `CONSOLIDATOR_BATCH_SIZE` | `10` | 每次 consolidator 处理的 issue 数，条数越多输出越长，越容易截断 |
| `PARAGRAPHS_PER_CHUNK` | `16` | 每个审阅块的段落数 |
| `AUTH_DISABLED` | `false` | `true` 时免登录（仅限单机可信环境） |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / `admin123` | 仅首次建库生效 |
| `JWT_SECRET` / `JWT_EXPIRE_MINUTES` | 占位值 / `480` | 暴露服务前必须修改 |
| `OCR_ENABLED` / `OCR_LANGUAGES` | `false` / `eng` | 扫描件 OCR（需镜像内含 tesseract） |
| `MAX_UPLOAD_MB` | `50` | 上传大小上限 |

完整列表见 `.env.example`。

> 写 `.env` 时注释必须独占一行。`docker run --env-file` 不剥离行内注释，`LLM_MAX_WORKERS=8  # 说明` 会被当作字符串 `8  # 说明` 传给进程，整数配置解析失败、容器直接启动不起来。

## 扫描件 OCR（可选）

默认镜像不含 Tesseract。需要处理扫描版 PDF 时，基于根 `Dockerfile` 追加：

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-chi-sim && rm -rf /var/lib/apt/lists/*
RUN uv pip install --system pytesseract Pillow
```

并在 `.env` 设 `OCR_ENABLED=true`、`OCR_LANGUAGES=eng+chi_sim`。纯文本 PDF 不受影响。

## 从旧版 Azure 部署迁移

- **issues 数据**：从 Cosmos DB 导出 JSON 后按 `common/models.py` 结构整理，批量插入 `data/review.db` 的 `issues` 表（payload 为 JSON 列）。
- **PDF 原件**：从 Blob 下载后放入 `data/documents/`（文件名即 doc_id）。
- **用户**：无迁移——本地账号首次建库自动引导，旧 Entra 账号需重建。
- 原 Terraform/部署资产保留在 [`legacy/`](../legacy/README.md)（含销毁旧资源的入口）。

## 故障排查

| 现象 | 处理 |
|---|---|
| `/api/health` 一直 `degraded` | `.env` 的 LLM 三项未配齐；容器内 `docker compose exec app env \| grep LLM_` 确认 |
| 审阅 SSE 返回 error：LLM not configured | 同上 |
| 429 / rate limit | 调低 `LLM_MAX_WORKERS`、`LLM_SHOTS`，或确认厂商配额 |
| JSON 解析失败频繁 | 厂商对 `json_schema` 支持差时设 `LLM_STRICT_JSON=false`（自动走 `json_object` + schema 注入） |
| 某个维度（如 Definitive Language）一条结果都没有 | 查日志 `Agent shot failed for <维度>`：该维度的所有 shot 都没通过校验。日志里会打印具体缺失字段 |
| 审阅很慢（3 段文档数分钟） | 流水线已把两个维度与 5 个 shot 全部并行（受 `LLM_MAX_WORKERS` 封顶），剩余耗时基本等于厂商单次推理耗时 × 波数。调低 `LLM_SHOTS` 可线性减少请求数，或确认端点并发配额后提高 `LLM_MAX_WORKERS` |
| 高亮缺失但 issue 正常 | 段落切分与原 Document Intelligence 存在差异属预期行为，审阅不中断 |
| 登录后立即 401 | `JWT_SECRET` 与签发时不一致（改过未重启）；清 sessionStorage 重新登录 |
| 容器起不来 | `docker compose logs app`；确认 8000 端口未被占用 |

## 端到端自检

不消耗真实 token 的自检方式：

```bash
uv run pytest -q
# 33 例覆盖：抽取/包围盒、去重/REMOVE 过滤、mock OpenAI 服务的请求体与
# schema 降级/退避、端到端分块流、认证/上传/下载/路径穿越防御
```

更多背景：[架构说明](./architecture.md) · [迁移设计方案](./local-deployment-plan.md)

# Local deployment configuration (copy to .env and adjust)

# --- Data layout -----------------------------------------------------------
# All state lives under DATA_DIR: review.db + documents/
DATA_DIR="data"

# --- Authentication ---------------------------------------------------------
# Set AUTH_DISABLED=true only for trusted single-host demos (no login required)
AUTH_DISABLED="false"
# MUST be changed before exposing this service
JWT_SECRET="change-me-before-exposing-this-service"
JWT_EXPIRE_MINUTES=480
# Bootstrap account, written only on first startup (empty users table)
ADMIN_USERNAME="admin"
ADMIN_PASSWORD="admin123"

# --- LLM endpoint (OpenAI-compatible; REQUIRED for review) ------------------
# Works with any vendor exposing /v1/chat/completions, e.g.:
#   OpenAI:          https://api.openai.com/v1        + gpt-4o
#   DeepSeek:        https://api.deepseek.com/v1      + deepseek-chat
#   Qwen (compat):   https://dashscope.aliyuncs.com/compatible-mode/v1 + qwen-max
#   Moonshot:        https://api.moonshot.cn/v1       + moonshot-v1-128k
#   Intranet vLLM:   http://<gpu-host>:8000/v1        + <served-model-name>
# NOTE: review sends extracted document text to this endpoint (data egress).
LLM_BASE_URL=""
LLM_API_KEY=""
LLM_MODEL=""

# Tuning: costs / rate limits / structured output
LLM_STRICT_JSON="true"
LLM_SHOTS=5
LLM_MAX_WORKERS=2
LLM_MAX_RETRIES=2
LLM_TIMEOUT_SECONDS=300
LLM_MAX_TOKENS=4096
PARAGRAPHS_PER_CHUNK=16

# --- OCR (scanned PDFs, default off) ----------------------------------------
OCR_ENABLED="false"
OCR_LANGUAGES="eng"

# --- Upload limits -----------------------------------------------------------
MAX_UPLOAD_MB=50

# --- CORS (explicit whitelist; never "*" with credentials) -------------------
CORS_ORIGINS="http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000"

# --- Static UI ----------------------------------------------------------------
SERVE_STATIC="true"
STATIC_DIR="www"

# --- Logging -------------------------------------------------------------------
# "DEBUG", "INFO", "WARNING" or "ERROR"; never logs prompts or API keys
LOG_LEVEL="INFO"
DEBUG="false"

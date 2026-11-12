import logging
import time

from config.config import settings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class LoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.logger = logging.getLogger(__name__)

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        # Log incoming request details
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        self.logger.info(f"Received {request.method} for {request.url} from {client_ip} using {user_agent}")

        try:
            # Proceed with request processing
            response = await call_next(request)
        except Exception as exc:
            # Log exception if it occurs
            process_time = time.time() - start_time
            self.logger.error(
                f"Exception during {request.method} {request.url} after {process_time:.2f}s: {exc}",
                exc_info=True,
            )
            raise

        # Log the response details
        process_time = time.time() - start_time
        self.logger.info(
            f"{request.method} {request.url} completed in {process_time:.2f}s with status {response.status_code}"
        )

        return response


def setup_logging():
    """Local logging: console + file under DATA_DIR/logs. No cloud export,
    no request/response bodies (tokens, prompts and API keys never logged)."""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    level = getattr(logging, str(settings.log_level).upper(), logging.INFO)

    handlers: list[logging.Handler] = [logging.StreamHandler()]

    try:
        settings.log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(settings.log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(log_format))
        handlers.append(file_handler)
    except OSError as e:
        logging.warning(f"File logging disabled (cannot write {settings.log_file}): {e}")

    logging.basicConfig(level=level, format=log_format, handlers=handlers, force=True)

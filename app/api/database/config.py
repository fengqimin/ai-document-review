import sqlite3

from config.config import settings

# Tables that SQLiteDBClient is allowed to map "containers" onto.
ALLOWED_TABLES = {"issues"}


class SQLiteDBConfig:
    """SQLite connection factory (replaces CosmosDBConfig).

    Single file under DATA_DIR/review.db; WAL mode for safe concurrent reads
    on a single-process deployment.
    """

    def __init__(self) -> None:
        self.db_path = settings.database_path

    def connect(self) -> sqlite3.Connection:
        """Open a new connection with sane single-host pragmas applied."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def init_db(self) -> None:
        """Create tables and indexes if missing (idempotent)."""
        settings.documents_dir.mkdir(parents=True, exist_ok=True)
        settings.log_file.parent.mkdir(parents=True, exist_ok=True)

        conn = self.connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS issues (
                    id      TEXT NOT NULL,
                    doc_id  TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (id, doc_id)
                );
                CREATE INDEX IF NOT EXISTS idx_issues_doc_id ON issues (doc_id);

                CREATE TABLE IF NOT EXISTS users (
                    username      TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    display_name  TEXT NOT NULL DEFAULT '',
                    oid           TEXT NOT NULL
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

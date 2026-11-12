import json
from typing import Any, Dict, List, Optional

from common.logger import get_logger
from database.config import ALLOWED_TABLES, SQLiteDBConfig

logging = get_logger(__name__)


class SQLiteDBClient:
    """SQLite-backed document store with the same method surface as the old
    CosmosDBClient, so callers (issues_repository) keep working unchanged.

    Items are stored as a JSON ``payload`` column keyed by (id, doc_id).
    All methods are synchronous; callers wrap them with asyncio.to_thread.
    """

    # Filter columns allowed in retrieve/delete queries (whitelist, prevents
    # SQL injection via dynamic column names).
    _FILTER_COLUMNS = {"doc_id"}

    def __init__(self, container_name: str) -> None:
        if container_name not in ALLOWED_TABLES:
            raise ValueError(f"Unknown container/table: {container_name}")
        self.table = container_name
        self.config = SQLiteDBConfig()

    # ------------------------------------------------------------------ write
    def store_item(self, item: Dict[str, Any]) -> None:
        """Upsert an item. Must contain 'id'; 'doc_id' is the partition key."""
        item_id = item.get("id")
        doc_id = item.get("doc_id")
        if item_id is None or doc_id is None:
            raise ValueError("Item must contain 'id' and 'doc_id' fields.")
        conn = self.config.connect()
        try:
            conn.execute(
                f"INSERT INTO {self.table} (id, doc_id, payload) VALUES (?, ?, ?) "
                f"ON CONFLICT (id, doc_id) DO UPDATE SET payload = excluded.payload",
                (item_id, doc_id, json.dumps(item, ensure_ascii=False)),
            )
            conn.commit()
            logging.debug(f"Item {item_id} stored in {self.table}.")
        except Exception as e:
            logging.error(f"An error occurred while storing the item: {e}")
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------ read
    def retrieve_item_by_id(self, item_id: str, partition_key: str) -> Optional[Dict[str, Any]]:
        conn = self.config.connect()
        try:
            row = conn.execute(
                f"SELECT payload FROM {self.table} WHERE id = ? AND doc_id = ?",
                (item_id, partition_key),
            ).fetchone()
            return json.loads(row["payload"]) if row else None
        except Exception as e:
            logging.error(f"An error occurred while retrieving the item: {e}")
            return None
        finally:
            conn.close()

    def retrieve_items_by_values(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        unknown = set(filters) - self._FILTER_COLUMNS
        if unknown:
            raise ValueError(f"Filter columns not allowed: {sorted(unknown)}")
        clauses = " AND ".join(f"json_extract(payload, '$.{col}') = ?" for col in filters)
        params = [filters[col] for col in filters]
        conn = self.config.connect()
        try:
            rows = conn.execute(
                f"SELECT payload FROM {self.table}"
                + (f" WHERE {clauses}" if clauses else ""),
                params,
            ).fetchall()
            return [json.loads(row["payload"]) for row in rows]
        except Exception as e:
            logging.error(f"An error occurred while retrieving items: {e}")
            return []
        finally:
            conn.close()

    # ---------------------------------------------------------------- delete
    def delete_items_by_values(self, filters: Dict[str, Any]) -> int:
        """Delete items matching whitelisted filters; returns row count."""
        unknown = set(filters) - self._FILTER_COLUMNS
        if unknown:
            raise ValueError(f"Filter columns not allowed: {sorted(unknown)}")
        clauses = " AND ".join(f"json_extract(payload, '$.{col}') = ?" for col in filters)
        params = [filters[col] for col in filters]
        conn = self.config.connect()
        try:
            cursor = conn.execute(
                f"DELETE FROM {self.table}" + (f" WHERE {clauses}" if clauses else ""),
                params,
            )
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            logging.error(f"An error occurred while deleting items: {e}")
            raise
        finally:
            conn.close()

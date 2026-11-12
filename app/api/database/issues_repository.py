import asyncio
from typing import Any, Dict, List

from common.logger import get_logger
from common.models import Issue
from config.config import settings
from database.db_client import SQLiteDBClient

logging = get_logger(__name__)


class IssuesRepository:
    def __init__(self) -> None:
        """Initialize the IssuesRepository with a SQLiteDBClient."""
        self.db_client = SQLiteDBClient(settings.issues_container)

    async def get_issues(self, doc_id: str) -> List[Issue]:
        """Retrieve all issues for a given document id."""
        logging.info(f"Retrieving issues for document {doc_id}.")
        issues = await asyncio.to_thread(
            self.db_client.retrieve_items_by_values, {"doc_id": doc_id}
        )
        logging.info(f"Retrieved {len(issues)} issues for document {doc_id}.")
        return [Issue(**issue) for issue in issues]

    async def get_issue(self, doc_id: str, issue_id: str) -> Issue:
        """Retrieve a single issue; raises ValueError when not found."""
        issue = await asyncio.to_thread(
            self.db_client.retrieve_item_by_id, issue_id, doc_id
        )
        if issue is None:
            raise ValueError(f"Issue {issue_id} not found.")
        return Issue(**issue)

    async def store_issues(self, issues: List[Issue]) -> None:
        logging.info(f"Storing {len(issues)} issues in the database.")
        for issue in issues:
            await asyncio.to_thread(self.db_client.store_item, issue.model_dump())
        logging.info("Issues stored successfully.")

    async def update_issue(self, doc_id: str, issue_id: str, fields: Dict[str, Any]) -> Issue:
        """Update fields of an issue; raises ValueError when not found."""
        issue = await asyncio.to_thread(
            self.db_client.retrieve_item_by_id, issue_id, doc_id
        )
        if issue is None:
            raise ValueError(f"Issue {issue_id} not found.")
        for field, value in fields.items():
            issue[field] = value
        await asyncio.to_thread(self.db_client.store_item, issue)
        logging.info(f"Issue {issue_id} updated.")
        return Issue(**issue)

    async def delete_issues_by_doc(self, doc_id: str) -> int:
        """Remove all issues belonging to a document (used on overwrite/delete)."""
        logging.info(f"Deleting all issues for document {doc_id}.")
        return await asyncio.to_thread(
            self.db_client.delete_items_by_values, {"doc_id": doc_id}
        )

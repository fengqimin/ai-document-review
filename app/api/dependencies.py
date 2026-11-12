from functools import lru_cache

from database.issues_repository import IssuesRepository
from services.issues_service import IssuesService
from services.review_client import ReviewClient


@lru_cache(maxsize=1)
def get_issues_service() -> IssuesService:
    """Build the service graph once (replaces per-request MLClient creation)."""
    return IssuesService(IssuesRepository(), ReviewClient())

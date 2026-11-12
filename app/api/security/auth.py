from datetime import datetime, timedelta, timezone

import jwt
from common.logger import get_logger
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from security import users
from config.config import settings

logging = get_logger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

ALGORITHM = "HS256"


class User(BaseModel):
    """Local authenticated user (replaces fastapi_azure_auth User).

    Keeps the `oid` attribute so `review_initiated_by=user.oid` semantics are
    unchanged.
    """

    oid: str
    name: str
    username: str


def create_access_token(user: dict) -> str:
    """user: dict as returned by users.get_user()."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": user["username"], "oid": user["oid"], "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def _synthetic_user() -> User:
    return User(
        oid=users.derive_oid("local"),
        name="Local User",
        username="local",
    )


async def validate_authenticated(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> User:
    """Validate a Bearer JWT and return the local user.

    With AUTH_DISABLED=true a synthetic user is returned (trusted single-host
    demo mode, no token required).
    """
    if settings.auth_disabled:
        return _synthetic_user()

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = users.get_user(payload.get("sub", ""))
    if user is None:
        raise HTTPException(status_code=401, detail="Unknown user")
    return User(oid=user["oid"], name=user["display_name"], username=user["username"])

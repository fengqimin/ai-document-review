from common.logger import get_logger
from config.config import settings
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from security import users
from security.auth import User, create_access_token, validate_authenticated

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logging = get_logger(__name__)


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post(
    "/login",
    summary="Log in with a local account and get a JWT",
    responses={200: {"description": "Authenticated"}, 401: {"description": "Bad credentials"}},
)
async def login(body: LoginRequest) -> dict:
    if settings.auth_disabled:
        raise HTTPException(status_code=400, detail="Authentication is disabled (AUTH_DISABLED=true)")

    user = users.get_user(body.username)
    if user is None or not users.verify_password(body.password, user["password_hash"]):
        # Same message for unknown user and wrong password: no account enumeration.
        logging.warning(f"Failed login attempt for username '{body.username}'.")
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_access_token(user)
    expires_in = settings.jwt_expire_minutes * 60
    logging.info(f"User '{body.username}' logged in.")
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": User(oid=user["oid"], name=user["display_name"], username=user["username"]).model_dump(),
    }


@router.get("/me", summary="Current authenticated user")
async def me(user: User = Depends(validate_authenticated)) -> User:
    return user


@router.get("/config", summary="Auth configuration for the frontend")
async def auth_config() -> dict:
    return {"auth_disabled": settings.auth_disabled}


@router.post("/logout", summary="Log out (stateless JWT: client discards the token)")
async def logout(user: User = Depends(validate_authenticated)) -> Response:
    # JWT is stateless; the client discards it. Hook for future token revocation.
    logging.info(f"User '{user.username}' logged out.")
    return Response(status_code=204)

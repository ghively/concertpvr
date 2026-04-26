"""Login / logout / me / set-password endpoints + AuthMiddleware."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from concertpvr.auth import hash_password, verify_password
from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import Settings
from concertpvr.session import create_token, generate_secret, verify_token

SESSION_COOKIE = "cpvr_session"
SESSION_MAX_AGE_S = 60 * 60 * 24 * 30  # 30 days

router = APIRouter()


class LoginPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str


class SetPasswordPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_password: str
    current_password: str | None = None


def _read_settings(db: Database) -> tuple[str | None, str | None]:
    with db.session() as s:
        row = s.get(Settings, 1)
        if row is None:
            return None, None
        return row.password_hash, row.session_secret


@router.post("/auth/login", status_code=status.HTTP_204_NO_CONTENT)
def login(
    payload: LoginPayload,
    response: Response,
    db: Database = Depends(get_db),  # noqa: B008
) -> Response:
    pw_hash, secret = _read_settings(db)
    if pw_hash is None or secret is None:
        raise HTTPException(status_code=400, detail="password not set")
    if not verify_password(payload.password, pw_hash):
        raise HTTPException(status_code=401, detail="invalid password")

    token = create_token({"v": 1}, secret)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE_S,
        httponly=True,
        samesite="lax",
        path="/",
    )
    response.status_code = 204
    return response


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> Response:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/auth/me")
def me(
    request: Request,
    db: Database = Depends(get_db),  # noqa: B008
) -> dict[str, object]:
    pw_hash, secret = _read_settings(db)
    password_set = pw_hash is not None
    if not password_set:
        return {"authenticated": True, "password_set": False}

    token = request.cookies.get(SESSION_COOKIE, "")
    payload = verify_token(token, secret or "", SESSION_MAX_AGE_S) if secret else None
    return {"authenticated": payload is not None, "password_set": True}


@router.post("/auth/set-password", status_code=status.HTTP_204_NO_CONTENT)
def set_password(
    payload: SetPasswordPayload,
    response: Response,
    db: Database = Depends(get_db),  # noqa: B008
) -> Response:
    with db.session() as s:
        row = s.get(Settings, 1)
        if row is None:
            row = Settings(id=1)
            s.add(row)
            s.flush()

        if row.password_hash is not None and (
            not payload.current_password
            or not verify_password(payload.current_password, row.password_hash)
        ):
            raise HTTPException(status_code=401, detail="current password invalid")

        row.password_hash = hash_password(payload.new_password)
        if row.session_secret is None:
            row.session_secret = generate_secret()

        secret = row.session_secret

    token = create_token({"v": 1}, secret)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE_S,
        httponly=True,
        samesite="lax",
        path="/",
    )
    response.status_code = 204
    return response


# ── Middleware ────────────────────────────────────────────────────────────


def _path_is_open(path: str) -> bool:
    return path.startswith("/api/auth/") or path == "/api/healthz" or not path.startswith("/api/")


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if _path_is_open(request.url.path):
            return await call_next(request)

        db = request.app.state.db
        pw_hash, secret = _read_settings(db)
        if pw_hash is None or secret is None:
            return await call_next(request)

        token = request.cookies.get(SESSION_COOKIE, "")
        payload = verify_token(token, secret, SESSION_MAX_AGE_S)
        if payload is None:
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "not authenticated"}, status_code=401)

        return await call_next(request)

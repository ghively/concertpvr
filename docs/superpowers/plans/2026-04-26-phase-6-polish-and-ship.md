# concertpvr — Phase 6: Polish & Ship Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock the operational story — single-password auth, complete the Settings page, replace `confirm()` with a real dialog, configure logging, update the README, and write the release smoke-test checklist. Result: ready to deploy on a Synology and trust on a LAN.

**Architecture:** Auth is opt-in. Until the user sets a password, the app is open (LAN trust assumed for first-run setup). Once a password is set, all `/api/*` endpoints (except auth + healthz) require a session cookie issued by `/api/auth/login`. Cookie value is an `itsdangerous` URLSafeTimedSerializer token signed with `Settings.session_secret`. Argon2 hashing on the password (already pinned). Frontend stores no password — relies on the cookie; surfaces a login screen when `/api/auth/me` returns 401.

**Tech Stack:** Adds `itsdangerous` to backend deps. Reuses already-pinned `argon2-cffi`. No new frontend deps.

**Spec reference:** `docs/superpowers/specs/2026-04-24-concertpvr-design.md` — §3 lifecycle/auth, §11 Deployment, §7.8 Settings.

**Phase 5 baseline (already on `main`):** 157 backend tests, full feature set. All 6 tabs functional. Pending only auth + UX polish + docs.

---

## File structure (additions in this phase)

```
src/concertpvr/
├── auth.py                # NEW: argon2 password hashing helpers
├── session.py             # NEW: itsdangerous session cookie middleware + helpers
└── api/
    └── auth.py            # NEW: /api/auth/login, /api/auth/logout, /api/auth/me

alembic/versions/
└── 0006_auth.py

tests/
├── test_auth.py           # password hashing + session token round-trip
└── test_auth_api.py       # /api/auth endpoints + middleware behavior

frontend/src/
├── lib/
│   ├── api.ts             # APPEND: authApi (login/logout/me)
│   ├── query.ts           # APPEND: useSession hook
│   └── api.ts             # MODIFY existing request(): on 401, set window.location='/login'
├── components/
│   └── ui/
│       └── confirm.tsx    # NEW: ConfirmDialog primitive
├── pages/
│   ├── Login.tsx          # NEW: login screen
│   └── Settings.tsx       # MODIFY: change-password section + missing fields
└── components/Layout.tsx  # MODIFY: show user/logout in top-right

docs/
├── release-checklist.md   # NEW
└── README.md              # MODIFY: full feature list + auth notes
```

---

## Module interfaces

**`auth.hash_password(plain) -> str`** — argon2-encoded hash, includes salt + parameters in the output string.
**`auth.verify_password(plain, hashed) -> bool`** — constant-time compare via argon2's `verify`.

**`session.create_token(payload, secret) -> str`** — wraps `itsdangerous.URLSafeTimedSerializer`.
**`session.verify_token(token, secret, max_age_s) -> dict | None`** — returns payload or None on expiry/tamper.
**`session.AuthMiddleware`** — Starlette middleware. On request:
- If path starts with `/api/auth/` or `/api/healthz` or doesn't start with `/api/` → pass through.
- Else: read `cpvr_session` cookie; if password is unset OR cookie verifies → pass; else 401.

**API endpoints:**
- `POST /api/auth/login {password}` → 204 + `Set-Cookie: cpvr_session=...; HttpOnly; Path=/; SameSite=Lax`
- `POST /api/auth/logout` → 204 + `Set-Cookie: cpvr_session=; Max-Age=0`
- `GET /api/auth/me` → `{authenticated: bool, password_set: bool}` — used by frontend to decide whether to show login screen

---

## Task 1: Migration 0006 + auth columns + dependency

**Files:**
- Modify: `pyproject.toml` (add `itsdangerous>=2.2.0` to deps)
- Modify: `src/concertpvr/models.py` (add `password_hash` + `session_secret` to `Settings`)
- Create: `alembic/versions/0006_auth.py`
- Modify: `tests/test_db.py` (append round-trip)

- [ ] **Step 1: Add dep to `pyproject.toml`**

In the `dependencies` array, alphabetically insert:
```
"itsdangerous>=2.2.0",
```

Install:
```bash
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
./.venv/Scripts/python.exe -c "import itsdangerous; print('ok')"
```

- [ ] **Step 2: Append columns to `Settings` in `src/concertpvr/models.py`**

Inside the existing `Settings` class, alongside `yt_dlp_cookies_path`:

```python
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    session_secret: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 3: Migration `alembic/versions/0006_auth.py`**

```python
"""auth columns on settings

Revision ID: 0006_auth
Revises: 0005_channel_watchers
Create Date: 2026-04-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_auth"
down_revision: str | None = "0005_channel_watchers"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("password_hash", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("session_secret", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("settings", "session_secret")
    op.drop_column("settings", "password_hash")
```

- [ ] **Step 4: Append round-trip test to `tests/test_db.py`**

```python
def test_settings_auth_columns_default_to_null(tmp_db):
    Base.metadata.create_all(tmp_db.engine)
    with tmp_db.session() as s:
        s.add(Settings(id=1))
    with tmp_db.session() as s:
        row = s.get(Settings, 1)
        assert row is not None
        assert row.password_hash is None
        assert row.session_secret is None
```

- [ ] **Step 5: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest -q
```
Expected: 158 (157 + 1).

```bash
git add pyproject.toml src/concertpvr/models.py alembic/versions/0006_auth.py tests/test_db.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(auth): password_hash + session_secret columns + itsdangerous dep"
```

---

## Task 2: `auth` + `session` modules

**Files:**
- Create: `src/concertpvr/auth.py`
- Create: `src/concertpvr/session.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Failing tests `tests/test_auth.py`**

```python
import pytest

from concertpvr.auth import hash_password, verify_password
from concertpvr.session import create_token, verify_token


def test_hash_round_trip():
    h = hash_password("hunter2")
    assert isinstance(h, str)
    assert h.startswith("$argon2")
    assert verify_password("hunter2", h) is True
    assert verify_password("wrong", h) is False


def test_hash_is_unique_per_call():
    """Argon2 includes a random salt — same password hashes differently each time."""
    a = hash_password("same")
    b = hash_password("same")
    assert a != b
    assert verify_password("same", a)
    assert verify_password("same", b)


def test_verify_handles_invalid_hash_gracefully():
    assert verify_password("anything", "not-a-real-hash") is False
    assert verify_password("anything", "") is False


def test_create_and_verify_token():
    secret = "test-secret-32-bytes-long-enough"
    token = create_token({"user": "admin"}, secret)
    assert isinstance(token, str)
    payload = verify_token(token, secret, max_age_s=3600)
    assert payload == {"user": "admin"}


def test_verify_token_rejects_wrong_secret():
    secret = "real-secret"
    token = create_token({"user": "admin"}, secret)
    assert verify_token(token, "different-secret", max_age_s=3600) is None


def test_verify_token_rejects_expired():
    import time
    secret = "test-secret"
    token = create_token({"user": "admin"}, secret)
    # max_age_s=0 means already expired
    time.sleep(1)
    assert verify_token(token, secret, max_age_s=0) is None


def test_verify_token_rejects_garbage():
    assert verify_token("garbage", "secret", max_age_s=3600) is None
    assert verify_token("", "secret", max_age_s=3600) is None
```

- [ ] **Step 2: Implement `src/concertpvr/auth.py`**

```python
"""Argon2 password hashing helpers."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
```

- [ ] **Step 3: Implement `src/concertpvr/session.py`**

```python
"""Cookie-token serialization for session auth."""

from __future__ import annotations

import secrets
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_SALT = "concertpvr-session-v1"


def generate_secret() -> str:
    """Generate a fresh 32-byte URL-safe secret. Called once when the user sets a password."""
    return secrets.token_urlsafe(32)


def create_token(payload: dict[str, Any], secret: str) -> str:
    s = URLSafeTimedSerializer(secret, salt=_SALT)
    return s.dumps(payload)


def verify_token(token: str, secret: str, max_age_s: int) -> dict[str, Any] | None:
    if not token:
        return None
    s = URLSafeTimedSerializer(secret, salt=_SALT)
    try:
        return s.loads(token, max_age=max_age_s)
    except (BadSignature, SignatureExpired):
        return None
```

- [ ] **Step 4: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_auth.py -v
```
Expected: 7 pass.

```bash
git add src/concertpvr/auth.py src/concertpvr/session.py tests/test_auth.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(auth): argon2 password hashing + itsdangerous session tokens"
```

---

## Task 3: Auth middleware + auth API

**Files:**
- Create: `src/concertpvr/api/auth.py`
- Modify: `src/concertpvr/main.py` (register router; mount middleware)
- Create: `tests/test_auth_api.py`

The middleware:
- Lets `/api/auth/*` and `/api/healthz` through unconditionally (so login + health-check work without auth).
- Lets non-`/api/` requests through (so static SPA + WebSocket paths work).
- For `/api/*`: if `password_hash` is unset (first-run), passes through. If set, requires a valid session cookie.

WebSocket auth: out of scope for Phase 6. The `/ws/streams/{id}/progress` endpoint will be reachable without auth on a LAN-only setup. (Frontend cookies are sent automatically on same-origin WS upgrades, so adding WS auth later is just one extra check inside the handler.)

- [ ] **Step 1: Failing tests `tests/test_auth_api.py`**

```python
import pytest
from fastapi.testclient import TestClient

from concertpvr.auth import hash_password
from concertpvr.main import create_app
from concertpvr.models import Settings
from concertpvr.session import generate_secret


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        yield c


def _set_password(client, password: str) -> None:
    db = client.app.state.db
    with db.session() as s:
        row = s.get(Settings, 1)
        if row is None:
            row = Settings(id=1)
            s.add(row)
        row.password_hash = hash_password(password)
        if row.session_secret is None:
            row.session_secret = generate_secret()


def test_me_reports_unconfigured_first(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["password_set"] is False
    assert body["authenticated"] is True  # unconfigured → no auth required → effectively authed


def test_open_when_password_unset(client):
    """Without a password, /api/streams should be reachable without a cookie."""
    r = client.get("/api/streams")
    assert r.status_code == 200


def test_login_succeeds_with_correct_password(client):
    _set_password(client, "hunter2")
    r = client.post("/api/auth/login", json={"password": "hunter2"})
    assert r.status_code == 204
    assert "cpvr_session" in r.cookies


def test_login_fails_with_wrong_password(client):
    _set_password(client, "hunter2")
    r = client.post("/api/auth/login", json={"password": "wrong"})
    assert r.status_code == 401


def test_protected_endpoint_requires_login_when_password_set(client):
    _set_password(client, "hunter2")
    r = client.get("/api/streams")
    assert r.status_code == 401


def test_protected_endpoint_works_after_login(client):
    _set_password(client, "hunter2")
    client.post("/api/auth/login", json={"password": "hunter2"})
    r = client.get("/api/streams")
    assert r.status_code == 200


def test_logout_clears_cookie(client):
    _set_password(client, "hunter2")
    client.post("/api/auth/login", json={"password": "hunter2"})
    r = client.post("/api/auth/logout")
    assert r.status_code == 204
    # After logout the cookie should be cleared and subsequent requests unauth'd
    r2 = client.get("/api/streams")
    assert r2.status_code == 401


def test_healthz_always_open(client):
    _set_password(client, "hunter2")
    r = client.get("/api/healthz")
    assert r.status_code == 200


def test_me_after_login_reports_authenticated(client):
    _set_password(client, "hunter2")
    client.post("/api/auth/login", json={"password": "hunter2"})
    r = client.get("/api/auth/me")
    body = r.json()
    assert body["authenticated"] is True
    assert body["password_set"] is True
```

- [ ] **Step 2: Implement `src/concertpvr/api/auth.py`**

```python
"""Login / logout / me endpoints + AuthMiddleware."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from concertpvr.auth import verify_password
from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import Settings
from concertpvr.session import create_token, verify_token

SESSION_COOKIE = "cpvr_session"
SESSION_MAX_AGE_S = 60 * 60 * 24 * 30  # 30 days

router = APIRouter()


class LoginPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str


def _read_settings(db: Database) -> tuple[str | None, str | None]:
    """Returns (password_hash, session_secret)."""
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
) -> dict:
    pw_hash, secret = _read_settings(db)
    password_set = pw_hash is not None
    if not password_set:
        return {"authenticated": True, "password_set": False}

    token = request.cookies.get(SESSION_COOKIE, "")
    payload = verify_token(token, secret or "", SESSION_MAX_AGE_S) if secret else None
    return {"authenticated": payload is not None, "password_set": True}


# ── Middleware ────────────────────────────────────────────────────────────


def _path_is_open(path: str) -> bool:
    return (
        path.startswith("/api/auth/")
        or path == "/api/healthz"
        or not path.startswith("/api/")
    )


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
```

- [ ] **Step 3: Wire into `src/concertpvr/main.py`**

In `create_app()`, after the lifespan is set on `FastAPI(...)`, add the middleware (before any routers are included — middleware order doesn't matter for this case, but keep it tidy):

```python
    from concertpvr.api.auth import AuthMiddleware
    app.add_middleware(AuthMiddleware)
```

In `create_app()`, register the router (after the existing routers):

```python
    from concertpvr.api.auth import router as auth_router
    app.include_router(auth_router, prefix="/api")
```

Also: `Settings.session_secret` should be auto-set when a password is first created. Update the existing `patch_settings` in `src/concertpvr/api/settings.py` — after the row is saved, if `password_hash` was just set and `session_secret` is None, generate one:

```python
    # ... after `s.expunge(row)` etc., before the EmbyClient rebuild ...
    if row.password_hash and row.session_secret is None:
        from concertpvr.session import generate_secret
        with db.session() as s:
            row2 = s.get(Settings, 1)
            if row2 is not None and row2.session_secret is None:
                row2.session_secret = generate_secret()
```

But that's clunky — the password isn't set via `PATCH /api/settings`; we add a dedicated endpoint in the next step. So leave `patch_settings` alone for now.

Add to `api/auth.py` a `set-password` endpoint:

```python
class SetPasswordPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_password: str
    current_password: str | None = None


@router.post("/auth/set-password", status_code=status.HTTP_204_NO_CONTENT)
def set_password(
    payload: SetPasswordPayload,
    response: Response,
    db: Database = Depends(get_db),  # noqa: B008
) -> Response:
    """Set or change the password.

    First-time set: current_password must be None and password must be unset.
    Change: current_password must verify against the existing hash.
    """
    from concertpvr.auth import hash_password
    from concertpvr.session import generate_secret

    with db.session() as s:
        row = s.get(Settings, 1)
        if row is None:
            row = Settings(id=1)
            s.add(row)
            s.flush()

        if row.password_hash is not None:
            if not payload.current_password or not verify_password(
                payload.current_password, row.password_hash
            ):
                raise HTTPException(status_code=401, detail="current password invalid")

        row.password_hash = hash_password(payload.new_password)
        if row.session_secret is None:
            row.session_secret = generate_secret()

        secret = row.session_secret

    # Issue a fresh session cookie so the user stays logged in
    token = create_token({"v": 1}, secret)
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_MAX_AGE_S,
        httponly=True, samesite="lax", path="/",
    )
    response.status_code = 204
    return response
```

Add the corresponding test in `tests/test_auth_api.py`:

```python
def test_set_password_first_time(client):
    r = client.post("/api/auth/set-password", json={"new_password": "hunter2"})
    assert r.status_code == 204
    # Subsequent request authenticated via cookie
    r2 = client.get("/api/streams")
    assert r2.status_code == 200


def test_set_password_change_requires_current(client):
    client.post("/api/auth/set-password", json={"new_password": "old"})
    # Without current_password, can't change
    r = client.post("/api/auth/set-password", json={"new_password": "new"})
    assert r.status_code == 401
    # With wrong current_password
    r = client.post("/api/auth/set-password",
                    json={"new_password": "new", "current_password": "wrong"})
    assert r.status_code == 401
    # With correct current_password
    r = client.post("/api/auth/set-password",
                    json={"new_password": "new", "current_password": "old"})
    assert r.status_code == 204
```

- [ ] **Step 4: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_auth_api.py -v
./.venv/Scripts/python.exe -m pytest -q
```
Expected: 11 new pass; full suite ~169.

```bash
git add src/concertpvr/api/auth.py src/concertpvr/main.py tests/test_auth_api.py
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(api): /api/auth login/logout/me/set-password + AuthMiddleware"
```

---

## Task 4: Frontend login screen + 401 handling

**Files:**
- Modify: `frontend/src/lib/api.ts` (append authApi + 401 redirect)
- Modify: `frontend/src/lib/query.ts` (append useSession)
- Create: `frontend/src/pages/Login.tsx`
- Modify: `frontend/src/App.tsx` (add `/login` route + AuthGate component)
- Modify: `frontend/src/components/Layout.tsx` (logout button when authenticated)

- [ ] **Step 1: Append to `frontend/src/lib/api.ts`**

```typescript
// ── Auth ────────────────────────────────────────────────────────────────────

export type SessionState = {
  authenticated: boolean;
  password_set: boolean;
};

export const authApi = {
  me: () => api.get<SessionState>("/api/auth/me"),
  login: async (password: string) => {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ password }),
      credentials: "include",
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(res.status, body);
    }
  },
  logout: async () => {
    await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
  },
  setPassword: async (newPassword: string, currentPassword?: string) => {
    const res = await fetch("/api/auth/set-password", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        new_password: newPassword,
        current_password: currentPassword ?? null,
      }),
      credentials: "include",
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(res.status, body);
    }
  },
};
```

Also modify the existing `request` function to redirect to `/login` on 401 (except when calling auth endpoints themselves):

```typescript
async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body ? { "content-type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
    credentials: "include",
  });
  const text = await res.text();
  const json = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : null;
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/api/auth/")) {
      // Redirect once so the login screen can take over
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    throw new ApiError(res.status, json);
  }
  return json as T;
}
```

- [ ] **Step 2: Append `useSession` to `frontend/src/lib/query.ts`**

```typescript
import { type SessionState, authApi } from "./api";

export function useSession() {
  return useQuery<SessionState>({
    queryKey: ["auth", "me"],
    queryFn: () => authApi.me(),
    retry: false,
    staleTime: 30_000,
  });
}
```

- [ ] **Step 3: Create `frontend/src/pages/Login.tsx`**

```typescript
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { authApi, type ApiError } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nav = useNavigate();
  const qc = useQueryClient();

  const submit = async () => {
    if (!password) return;
    setSubmitting(true);
    setError(null);
    try {
      await authApi.login(password);
      qc.invalidateQueries({ queryKey: ["auth", "me"] });
      nav("/", { replace: true });
    } catch (e) {
      const err = e as ApiError;
      setError(err.status === 401 ? "Invalid password." : err.message);
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-0 p-4">
      <Card className="w-full max-w-sm space-y-4">
        <div>
          <h1 className="text-xl font-semibold">
            <span className="text-terracotta">◉</span> concertpvr
          </h1>
          <CardLabel className="mt-2">Sign in</CardLabel>
        </div>
        <Input
          autoFocus
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
        />
        {error && <p className="text-xs text-red-400">{error}</p>}
        <Button variant="primary" onClick={submit} disabled={submitting} className="w-full justify-center">
          {submitting ? "Signing in…" : "Sign in"}
        </Button>
      </Card>
    </div>
  );
}
```

- [ ] **Step 4: Modify `frontend/src/App.tsx`**

```typescript
import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import Streams from "@/pages/Streams";
import Schedule from "@/pages/Schedule";
import Library from "@/pages/Library";
import Watchers from "@/pages/Watchers";
import Settings from "@/pages/Settings";
import Recordings from "@/pages/Recordings";
import TimelineEditor from "@/pages/TimelineEditor";
import Login from "@/pages/Login";
import { useSession } from "@/lib/query";

function AuthGate({ children }: { children: React.ReactNode }) {
  const { data, isLoading } = useSession();
  if (isLoading) {
    return <div className="text-ink-dim text-xs p-8">Loading…</div>;
  }
  if (data && data.password_set && !data.authenticated) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<AuthGate><Layout /></AuthGate>}>
        <Route index element={<Dashboard />} />
        <Route path="streams" element={<Streams />} />
        <Route path="schedule" element={<Schedule />} />
        <Route path="recordings" element={<Recordings />} />
        <Route path="timeline/:id" element={<TimelineEditor />} />
        <Route path="library" element={<Library />} />
        <Route path="watchers" element={<Watchers />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
```

- [ ] **Step 5: Add logout to Layout — `frontend/src/components/Layout.tsx`**

Add a logout link to the right of the Settings link in the header. Append to imports:

```typescript
import { useNavigate } from "react-router-dom";
import { authApi } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";
import { useSession } from "@/lib/query";
```

Inside `Layout()`, before the `return`:

```typescript
  const nav = useNavigate();
  const qc = useQueryClient();
  const { data: session } = useSession();
  const showLogout = session?.password_set ?? false;
```

In the JSX, after the existing settings NavLink:

```typescript
        {showLogout && (
          <button
            onClick={async () => {
              await authApi.logout();
              qc.invalidateQueries({ queryKey: ["auth", "me"] });
              nav("/login", { replace: true });
            }}
            className="ml-3 text-xs text-ink-dim hover:text-ink"
          >
            Log out
          </button>
        )}
```

- [ ] **Step 6: Typecheck + build + commit**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
git add frontend/src/lib/api.ts frontend/src/lib/query.ts frontend/src/pages/Login.tsx frontend/src/App.tsx frontend/src/components/Layout.tsx
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): login screen + AuthGate + 401 redirect + logout"
```

---

## Task 5: Settings page completion (change-password + missing fields)

**File:** Modify `frontend/src/pages/Settings.tsx`

The current page exposes most settings but is missing:
- `auto_prune_when_full` (bool toggle)
- `yt_dlp_cookies_path`
- A change-password section (separate from the rest of the form)

- [ ] **Step 1: Replace contents of `frontend/src/pages/Settings.tsx`**

```typescript
import { useEffect, useState } from "react";
import { useSettings, useUpdateSettings, useSession } from "@/lib/query";
import { Button } from "@/components/ui/button";
import { Card, CardLabel } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { authApi, type ApiError, type SettingsPatch } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function SettingsPage() {
  const { data, isLoading, error } = useSettings();
  const update = useUpdateSettings();
  const { data: session, refetch: refetchSession } = useSession();

  const [form, setForm] = useState<SettingsPatch>({});
  useEffect(() => {
    if (data) setForm({});
  }, [data]);

  // Password section state
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [pwSubmitting, setPwSubmitting] = useState(false);
  const [pwMessage, setPwMessage] = useState<
    { kind: "ok"; text: string } | { kind: "err"; text: string } | null
  >(null);

  if (isLoading) return <div className="text-ink-dim text-xs">Loading…</div>;
  if (error || !data) return <div className="text-terracotta text-xs">Failed to load settings.</div>;

  const field = <K extends keyof SettingsPatch>(k: K) => (v: SettingsPatch[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  const merged = { ...data, ...form };

  const save = () => {
    const dirty: SettingsPatch = {};
    for (const k of Object.keys(form) as (keyof SettingsPatch)[]) {
      if (form[k] !== data[k]) (dirty as Record<string, unknown>)[k as string] = form[k];
    }
    if (Object.keys(dirty).length > 0) update.mutate(dirty);
  };

  const submitPassword = async () => {
    setPwMessage(null);
    if (!newPw) return;
    setPwSubmitting(true);
    try {
      await authApi.setPassword(newPw, session?.password_set ? currentPw : undefined);
      setCurrentPw(""); setNewPw("");
      setPwMessage({ kind: "ok", text: "Password updated." });
      refetchSession();
    } catch (e) {
      const err = e as ApiError;
      setPwMessage({
        kind: "err",
        text: err.status === 401 ? "Current password is incorrect." : err.message,
      });
    } finally {
      setPwSubmitting(false);
    }
  };

  return (
    <div className="max-w-2xl">
      <h2 className="text-lg font-semibold mb-4">Settings</h2>

      {/* Emby Integration */}
      <Card className="mb-4 space-y-3">
        <CardLabel>Emby Integration</CardLabel>
        <Labeled label="Emby server URL" help="Used to trigger library refresh after publish">
          <Input
            className="font-mono"
            value={merged.emby_url ?? ""}
            onChange={(e) => field("emby_url")(e.target.value || null)}
            placeholder="http://192.168.1.10:8096"
          />
        </Labeled>
        <Labeled label="API key">
          <Input
            type="password"
            className="font-mono"
            value={merged.emby_api_key ?? ""}
            onChange={(e) => field("emby_api_key")(e.target.value || null)}
          />
        </Labeled>
        <Labeled label="Movies library path (Emby's view)">
          <Input
            className="font-mono"
            value={merged.emby_library_path ?? ""}
            onChange={(e) => field("emby_library_path")(e.target.value || null)}
            placeholder="/media/concerts"
          />
        </Labeled>
      </Card>

      {/* Naming */}
      <Card className="mb-4 space-y-3">
        <CardLabel>Naming</CardLabel>
        <Labeled
          label="Folder pattern"
          help="Tokens: {artist} {festival} {venue} {year} {date} {title}"
        >
          <Input
            className="font-mono"
            value={merged.folder_pattern}
            onChange={(e) => field("folder_pattern")(e.target.value)}
          />
        </Labeled>
      </Card>

      {/* Recording defaults */}
      <Card className="mb-4 space-y-3">
        <CardLabel>Recording defaults</CardLabel>
        <Labeled label="Default quality (yt-dlp format selector)">
          <Input
            className="font-mono"
            value={merged.default_quality}
            onChange={(e) => field("default_quality")(e.target.value)}
          />
        </Labeled>
        <Labeled label="Default retention (days)">
          <Input
            type="number"
            className="font-mono"
            value={merged.default_retention_days}
            onChange={(e) => field("default_retention_days")(Number(e.target.value))}
          />
        </Labeled>
        <Labeled label="Max concurrent recordings">
          <Input
            type="number"
            className="font-mono"
            value={merged.max_concurrent_recordings}
            onChange={(e) => field("max_concurrent_recordings")(Number(e.target.value))}
          />
        </Labeled>
        <Labeled label="Auto-prune buffer when disk full">
          <button
            onClick={() => field("auto_prune_when_full")(!merged.auto_prune_when_full)}
            className={cn(
              "w-9 h-5 rounded-full relative transition-colors",
              merged.auto_prune_when_full ? "bg-sage/30" : "bg-surface-3",
            )}
          >
            <span
              className={cn(
                "absolute top-0.5 w-4 h-4 rounded-full transition-all",
                merged.auto_prune_when_full ? "left-[18px] bg-sage" : "left-0.5 bg-ink-dim",
              )}
            />
          </button>
        </Labeled>
      </Card>

      {/* yt-dlp */}
      <Card className="mb-4 space-y-3">
        <CardLabel>yt-dlp</CardLabel>
        <Labeled
          label="Cookies file path"
          help="Optional. Export your YouTube cookies and place the file in /data/. Required for member-only or age-gated streams."
        >
          <Input
            className="font-mono"
            value={merged.yt_dlp_cookies_path ?? ""}
            onChange={(e) => field("yt_dlp_cookies_path")(e.target.value || null)}
            placeholder="/data/cookies.txt"
          />
        </Labeled>
      </Card>

      <div className="flex gap-2 mb-8">
        <Button variant="primary" onClick={save} disabled={update.isPending}>
          {update.isPending ? "Saving…" : "Save"}
        </Button>
        {update.isSuccess && <span className="text-sage text-xs self-center">Saved ✓</span>}
        {update.isError && (
          <span className="text-terracotta text-xs self-center">Error: {update.error.message}</span>
        )}
      </div>

      {/* Password */}
      <Card className="space-y-3">
        <CardLabel>Password</CardLabel>
        <p className="text-xs text-ink-dim">
          {session?.password_set
            ? "Change your password. You'll stay signed in on this device."
            : "Set a password to require sign-in for the web UI. Until you do, anyone on the LAN can access the app."}
        </p>
        {session?.password_set && (
          <Labeled label="Current password">
            <Input
              type="password"
              value={currentPw}
              onChange={(e) => setCurrentPw(e.target.value)}
            />
          </Labeled>
        )}
        <Labeled label="New password">
          <Input
            type="password"
            value={newPw}
            onChange={(e) => setNewPw(e.target.value)}
          />
        </Labeled>
        {pwMessage && (
          <p className={cn(
            "text-xs",
            pwMessage.kind === "ok" ? "text-sage" : "text-red-400",
          )}>
            {pwMessage.text}
          </p>
        )}
        <Button variant="primary" onClick={submitPassword} disabled={pwSubmitting || !newPw}>
          {pwSubmitting ? "Updating…" : session?.password_set ? "Change password" : "Set password"}
        </Button>
      </Card>
    </div>
  );
}

function Labeled({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-[11px] text-ink-dim mb-1">{label}</label>
      {children}
      {help && <div className="text-[10px] text-ink-faint mt-1">{help}</div>}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck + commit**

```bash
cd frontend && npm run typecheck && cd ..
git add frontend/src/pages/Settings.tsx
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): settings page completed with password + auto-prune + cookies fields"
```

---

## Task 6: ConfirmDialog primitive + replace browser confirms

**Files:**
- Create: `frontend/src/components/ui/confirm.tsx`
- Modify: `frontend/src/pages/Streams.tsx` (replace confirm)
- Modify: `frontend/src/pages/Schedule.tsx` (replace confirm)
- Modify: `frontend/src/pages/Watchers.tsx` (replace confirm)
- Modify: `frontend/src/components/SegmentSidebar.tsx` (replace confirm)

The browser `confirm()` is jarring on a polished UI. Build a small confirm dialog primitive that returns a Promise<boolean>.

- [ ] **Step 1: `frontend/src/components/ui/confirm.tsx`**

```typescript
import { useState, createContext, useContext, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogFooter, DialogHeader } from "@/components/ui/dialog";

type ConfirmFn = (opts: {
  title?: string;
  message: string;
  confirmLabel?: string;
  destructive?: boolean;
}) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<{
    open: boolean;
    title?: string;
    message: string;
    confirmLabel?: string;
    destructive?: boolean;
  } | null>(null);
  const resolverRef = useRef<((v: boolean) => void) | null>(null);

  const confirm: ConfirmFn = (opts) =>
    new Promise<boolean>((resolve) => {
      resolverRef.current = resolve;
      setState({ open: true, ...opts });
    });

  const close = (result: boolean) => {
    resolverRef.current?.(result);
    resolverRef.current = null;
    setState((s) => (s ? { ...s, open: false } : null));
  };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {state && (
        <Dialog open={state.open} onOpenChange={(o) => { if (!o) close(false); }}>
          {state.title && <DialogHeader>{state.title}</DialogHeader>}
          <DialogBody>
            <p className="text-sm text-ink">{state.message}</p>
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" onClick={() => close(false)}>Cancel</Button>
            <Button
              variant={state.destructive ? "primary" : "primary"}
              onClick={() => close(true)}
            >
              {state.confirmLabel ?? "Confirm"}
            </Button>
          </DialogFooter>
        </Dialog>
      )}
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): ConfirmFn {
  const c = useContext(ConfirmContext);
  if (!c) throw new Error("useConfirm must be used inside ConfirmProvider");
  return c;
}
```

- [ ] **Step 2: Wrap App with `ConfirmProvider` in `frontend/src/main.tsx`**

```typescript
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { ConfirmProvider } from "@/components/ui/confirm";
import "./styles/globals.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { refetchOnWindowFocus: false, retry: 1 },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <ConfirmProvider>
          <App />
        </ConfirmProvider>
      </QueryClientProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
```

- [ ] **Step 3: Replace `confirm(...)` calls across pages**

In `frontend/src/pages/Streams.tsx`, in the StreamRow component, change the delete handler:

```typescript
import { useConfirm } from "@/components/ui/confirm";

function StreamRow({ stream }: { stream: Stream }) {
  const { data: sub } = useWatchSubscription(stream.id);
  const toggle = useToggleWatch(stream.id);
  const del = useDeleteStream();
  const confirm = useConfirm();
  const enabled = sub?.enabled ?? false;
  // ... existing JSX, but replace the confirm in the delete button:
  <Button
    variant="ghost"
    onClick={async () => {
      const ok = await confirm({
        title: "Delete stream",
        message: `Delete "${stream.title}"? This will also remove its recordings.`,
        confirmLabel: "Delete",
        destructive: true,
      });
      if (ok) del.mutate(stream.id);
    }}
  >
    ✕
  </Button>
```

(Show only the changed parts here — the rest of the file is unchanged. Apply the same pattern in Schedule, Watchers, and SegmentSidebar by importing `useConfirm` and awaiting `confirm({ ... })` instead of calling browser `confirm()`.)

For each file, the pattern is:
1. Add `import { useConfirm } from "@/components/ui/confirm";`
2. Inside the component, `const confirm = useConfirm();`
3. Replace `if (confirm("...")) doIt();` with:
   ```typescript
   const ok = await confirm({ message: "...", confirmLabel: "Delete", destructive: true });
   if (ok) doIt();
   ```
   And make the click handler `async`.

Apply in:
- `frontend/src/pages/Schedule.tsx` → "Delete this schedule?"
- `frontend/src/pages/Watchers.tsx` → "Stop watching..."
- `frontend/src/components/SegmentSidebar.tsx` → "Delete segment..."
- `frontend/src/pages/Streams.tsx` → "Delete stream..."

- [ ] **Step 4: Typecheck + build + commit**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
git add frontend/src/components/ui/confirm.tsx frontend/src/main.tsx frontend/src/pages/Streams.tsx frontend/src/pages/Schedule.tsx frontend/src/pages/Watchers.tsx frontend/src/components/SegmentSidebar.tsx
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "feat(frontend): ConfirmDialog primitive replaces browser confirm()"
```

---

## Task 7: Logging configuration + README + release checklist

**Files:**
- Create: `src/concertpvr/logging_config.py`
- Modify: `src/concertpvr/__main__.py` (call `configure_logging()`)
- Modify: `README.md` (full rewrite)
- Create: `docs/release-checklist.md`

- [ ] **Step 1: `src/concertpvr/logging_config.py`**

```python
"""Logging configuration — rotating file in CPVR_DATA_DIR/logs/ + console."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


def configure_logging(logs_dir: Path, level: str = "INFO") -> None:
    """Configure root logger.

    - INFO+ to stdout (so it shows up in `docker logs`).
    - INFO+ to a rotating file in `logs_dir/concertpvr.log` (5 MiB × 5 backups).
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "concertpvr.log"

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    # Idempotent — clear any prior handlers when called twice (tests do this).
    for h in list(root.handlers):
        root.removeHandler(h)

    root.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Quiet noisy libraries
    logging.getLogger("apscheduler.executors").setLevel("WARNING")
    logging.getLogger("apscheduler.scheduler").setLevel("WARNING")
```

- [ ] **Step 2: Wire into `src/concertpvr/__main__.py`**

```python
"""Entry point: `python -m concertpvr`."""

import uvicorn

from concertpvr.config import Config
from concertpvr.logging_config import configure_logging

if __name__ == "__main__":
    cfg = Config()
    configure_logging(cfg.logs_dir)
    uvicorn.run(
        "concertpvr.main:create_app",
        factory=True,
        host=cfg.host,
        port=cfg.port,
        reload=False,
    )
```

- [ ] **Step 3: Test that logging config works**

Append to `tests/test_config.py` (or create `tests/test_logging.py` — do whichever fits the existing test structure):

```python
def test_configure_logging_creates_log_file(tmp_path):
    import logging
    from concertpvr.logging_config import configure_logging

    configure_logging(tmp_path / "logs")
    logging.getLogger("concertpvr.test").info("hello")

    log_file = tmp_path / "logs" / "concertpvr.log"
    assert log_file.exists()
    assert "hello" in log_file.read_text()

    # Cleanup the global logging state so other tests aren't affected
    logging.getLogger().handlers = []
```

- [ ] **Step 4: Replace `README.md` with full feature list**

```markdown
# concertpvr

YouTube concert & livestream PVR with Emby integration. Runs on Synology NAS via Docker.

## Features

- **Buffer YouTube live streams** with configurable retention; scrub back through any captured fragment via the Timeline editor.
- **Schedule recordings** in advance (URL + start/end + optional artist tag).
- **Channel watchers** auto-record any matching live broadcast every 60 seconds.
- **Per-artist segmentation** from yt-dlp chapters, pasted setlists, or manual timeline marking.
- **Publish to Emby** — ffmpeg cuts the segment, generates `movie.nfo` + `poster.jpg` + `fanart.jpg`, drops it in your movies library, triggers a scan.
- **Single-password auth** for LAN deployments (optional — the app is open until you set a password from Settings).

## Status

All planned phases shipped. See `docs/superpowers/specs/2026-04-24-concertpvr-design.md` for the design spec and `docs/superpowers/plans/` for the per-phase implementation plans.

## Deployment (Synology, Docker)

```bash
docker compose up -d --build
```

The compose file expects two bind mounts:
- `/volume1/concertpvr` → app data (DB, buffer, staging, logs).
- `/volume1/media/concerts` → Emby movies library target.

Adjust paths to your Synology layout. The container runs `alembic upgrade head` on each start, so schema migrations apply automatically.

After first start, browse to `http://<your-nas-ip>:8787` and:
1. Open **Settings** → set a password (one-time; until you do, the app is open on your LAN).
2. Configure Emby URL + API key in **Settings** if you want library refreshes.
3. **Streams** → add a YouTube URL → start buffer; or **Schedule** → new schedule; or **Watchers** → add a channel.

## Local development

### Backend (one shell)

```bash
python -m venv .venv
source .venv/bin/activate    # or .venv/Scripts/activate on Windows
pip install -e ".[dev]"

export CPVR_DATA_DIR=/tmp/cpvr-dev
alembic upgrade head
python -m concertpvr
```

Backend at http://localhost:8787.

### Frontend (another shell)

```bash
cd frontend
npm install
npm run dev
```

Frontend at http://localhost:5173, proxying `/api/*` to the backend.

## Tests

```bash
pytest                       # backend, ~169 tests
cd frontend && npm test      # frontend (vitest scaffolding)
```

## Manual smoke test before release

See `docs/release-checklist.md`.

## License

TBD.
```

- [ ] **Step 5: Create `docs/release-checklist.md`**

```markdown
# Release smoke test checklist

Run through this before tagging a new version. Everything must pass.

## Boot

- [ ] `docker compose up -d --build` starts cleanly
- [ ] `curl http://localhost:8787/api/healthz` returns `{"status":"ok"}`
- [ ] `docker compose logs concertpvr` shows alembic running upgrades to head, scheduler started
- [ ] Browse http://localhost:8787 — the SPA loads, navigation works

## Auth

- [ ] Settings page → set a password
- [ ] Click Log out — redirected to /login
- [ ] Wrong password → 401, error message shown
- [ ] Correct password → redirected to dashboard
- [ ] All `/api/*` endpoints (except healthz + auth) require the cookie

## Stream buffer

- [ ] Streams → Add stream → paste a real YouTube live URL
- [ ] App probes via yt-dlp and shows title/channel
- [ ] Click Start buffer
- [ ] yt-dlp spawns; LiveProgressBar shows bytes/bitrate/duration updating in real time
- [ ] Click Stop buffer — recorder terminates cleanly
- [ ] After 5 minutes, retention pruner runs (check logs for "buffer_retention_prune")

## Scheduled recording

- [ ] Schedule → New schedule → URL + start time ~2 minutes from now + 1-minute window
- [ ] Schedule appears in calendar and Dashboard "Up Next" rail
- [ ] At fire time, schedule status flips pending → running → complete
- [ ] A new Recording row appears in the Recordings tab
- [ ] The .mkv file is in the staging directory

## Channel watcher

- [ ] Watchers → Add a channel — paste any active YouTube channel URL
- [ ] Channel name + avatar populate from probe
- [ ] Toggle one off and on
- [ ] Polling job fires every 60s (check `docker compose logs` for "channel_poller")
- [ ] If a watched channel goes live, a new buffer recording starts automatically

## Segment & publish

- [ ] Recordings → click a finished recording → Timeline editor opens
- [ ] Vidstack player loads the recording (range request seeking works)
- [ ] If the recording has yt-dlp chapters → segments auto-derived
- [ ] Drag empty timeline → new segment created
- [ ] Drag region edges → start/end persist (debounced PATCH)
- [ ] Click Publish → segment status flips publishing → published
- [ ] Library tab → poster card appears for the published segment
- [ ] Configured Emby movies path — verify the folder + movie.nfo + poster.jpg + fanart.jpg landed
- [ ] If Emby is configured — Emby reports the new movie within ~30s of publish

## UI polish

- [ ] Confirm dialogs replace browser native confirms for delete actions
- [ ] Setlist paste modal accepts unicode em-dashes and ASCII hyphens

## Logs

- [ ] `docker compose exec concertpvr ls /data/logs/` shows `concertpvr.log` rotating
- [ ] No errors at INFO level on a clean boot

## Tear down

- [ ] `docker compose down`
- [ ] Restart with `docker compose up -d` — schedules persist (rehydrated on startup), buffer fragments persist, segments + setlists persist
```

- [ ] **Step 6: Run + commit**

```bash
./.venv/Scripts/python.exe -m pytest -q
```
Expected: 170 (169 + 1).

```bash
git add src/concertpvr/logging_config.py src/concertpvr/__main__.py tests/test_config.py README.md docs/release-checklist.md
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "chore: rotating log config + full README + release smoke-test checklist"
```

---

## Task 8: Phase 6 wrap-up + ship

- [ ] **Step 1: Backend sweep**

```bash
./.venv/Scripts/python.exe -m ruff check src/ tests/
./.venv/Scripts/python.exe -m ruff format --check src/ tests/
./.venv/Scripts/python.exe -m mypy src/
./.venv/Scripts/python.exe -m pytest -q
```

If anything fails, fix INLINE per the now-standard guardrails — never weaken `Field(...)` defaults; never change tests to assert different from the spec; never relax mypy strictness. Allowed: `ruff format`, `# noqa: B008`, `# type: ignore[import-untyped]`.

- [ ] **Step 2: Frontend sweep**

```bash
cd frontend && npm run typecheck && npm run build && cd ..
```

- [ ] **Step 3: Commit fixes if any, then tag**

```bash
git status
git add -A
git -c gpg.format=openpgp -c commit.gpgsign=false commit -m "chore: phase 6 wrap-up — lint/type/test sweep" || echo "(nothing to commit)"

git tag -a phase-6-polish-and-ship -m "Phase 6 complete: auth, settings, UX polish, docs"
git tag -a v0.1.0 -m "concertpvr v0.1.0 — first release"
git log --oneline phase-5-channel-watchers..HEAD | head -25
```

- [ ] **Step 4: Manual smoke test**

Run through `docs/release-checklist.md`. Note any items that don't pass — those are bugs to fix before declaring v0.1.0 actually shipped.

---

## Phase 6 done

At tag `v0.1.0`:
- Argon2 password hashing + itsdangerous-signed session cookies + AuthMiddleware
- `/api/auth/login`, `/api/auth/logout`, `/api/auth/me`, `/api/auth/set-password`
- Login screen with password input
- Frontend AuthGate wraps all routes; 401 → automatic redirect to /login
- Logout button in nav (only when password is set)
- Settings page completed: change-password section + auto-prune toggle + cookies path field
- ConfirmDialog primitive replaces browser `confirm()` across all destructive actions
- Rotating log file in `/data/logs/concertpvr.log` (5 MiB × 5 backups)
- README rewritten with full feature list + deployment story
- `docs/release-checklist.md` covers boot → auth → buffer → schedule → watcher → publish → tear-down

**Tests added:** ~12 (1 settings columns, 7 auth helpers, 11 auth API endpoints, 1 logging).

The product is ready to ship.

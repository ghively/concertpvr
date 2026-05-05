"""WebSocket progress fan-out — live recordings + VOD downloads.

When auth is enabled (settings.password_hash is set), connections must carry a
valid `cpvr_session` cookie. Without one, the server closes with policy code
1008 immediately after accept, before any data flows. The HTTP middleware
won't intercept WebSocket upgrade requests, so the auth check has to live
here directly.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from concertpvr.api.auth import SESSION_COOKIE, SESSION_MAX_AGE_S
from concertpvr.db import Database
from concertpvr.models import Settings
from concertpvr.session import verify_token

router = APIRouter()


def _is_authenticated(ws: WebSocket) -> bool:
    """Apply the same gate as AuthMiddleware: open if no password set, else verify cookie."""
    db: Database = ws.app.state.db
    with db.session() as s:
        row = s.get(Settings, 1)
        pw_hash = row.password_hash if row else None
        secret = row.session_secret if row else None
    if pw_hash is None or secret is None:
        return True
    token = ws.cookies.get(SESSION_COOKIE, "")
    if not token:
        return False
    return verify_token(token, secret, SESSION_MAX_AGE_S) is not None


@router.websocket("/ws/streams/{stream_id}/progress")
async def ws_progress(ws: WebSocket, stream_id: int) -> None:
    if not _is_authenticated(ws):
        await ws.close(code=1008, reason="not authenticated")
        return
    bc = ws.app.state.broadcaster
    topic = f"streams.{stream_id}.progress"
    await ws.accept()
    try:
        async for msg in bc.subscribe(topic):
            await ws.send_json(msg)
    except WebSocketDisconnect:
        return


@router.websocket("/ws/recordings/{recording_id}/progress")
async def ws_vod_progress(ws: WebSocket, recording_id: int) -> None:
    """Subscribes to recordings.{id}.progress events from the VOD download
    handler. Each event carries pct/bytes_total/bitrate_bps/eta_s."""
    if not _is_authenticated(ws):
        await ws.close(code=1008, reason="not authenticated")
        return
    bc = ws.app.state.broadcaster
    topic = f"recordings.{recording_id}.progress"
    await ws.accept()
    try:
        async for msg in bc.subscribe(topic):
            await ws.send_json(msg)
    except WebSocketDisconnect:
        return

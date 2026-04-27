"""WebSocket progress fan-out — live recordings + VOD downloads."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/streams/{stream_id}/progress")
async def ws_progress(ws: WebSocket, stream_id: int) -> None:
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
    bc = ws.app.state.broadcaster
    topic = f"recordings.{recording_id}.progress"
    await ws.accept()
    try:
        async for msg in bc.subscribe(topic):
            await ws.send_json(msg)
    except WebSocketDisconnect:
        return

"""WebSocket progress fan-out for live recordings."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/streams/{stream_id}/progress")
async def ws_progress(ws: WebSocket, stream_id: int) -> None:
    bc = ws.app.state.broadcaster  # access broadcaster directly from app state
    topic = f"streams.{stream_id}.progress"
    await ws.accept()
    try:
        async for msg in bc.subscribe(topic):
            await ws.send_json(msg)
    except WebSocketDisconnect:
        return

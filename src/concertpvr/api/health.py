"""Liveness probe."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from concertpvr.db import Database
from concertpvr.deps import get_db

router = APIRouter()


@router.get("/healthz")
def healthz(deep: bool = Query(False), db: Database = Depends(get_db)) -> dict[str, str]:  # noqa: B008
    body = {"status": "ok"}
    if deep:
        with db.session() as s:
            s.execute(text("SELECT 1"))
        body["db"] = "reachable"
    return body

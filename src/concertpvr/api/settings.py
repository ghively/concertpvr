"""Settings singleton CRUD."""
from fastapi import APIRouter, Depends

from concertpvr.db import Database
from concertpvr.deps import get_db
from concertpvr.models import Settings
from concertpvr.schemas import SettingsPatch, SettingsRead

router = APIRouter()


def _get_or_create(db: Database) -> Settings:
    with db.session() as s:
        row = s.get(Settings, 1)
        if row is None:
            row = Settings(id=1)
            s.add(row)
            s.flush()
        s.expunge(row)
    return row


@router.get("/settings", response_model=SettingsRead)
def read_settings(db: Database = Depends(get_db)) -> Settings:
    return _get_or_create(db)


@router.patch("/settings", response_model=SettingsRead)
def patch_settings(patch: SettingsPatch, db: Database = Depends(get_db)) -> Settings:
    updates = patch.model_dump(exclude_unset=True)
    with db.session() as s:
        row = s.get(Settings, 1)
        if row is None:
            row = Settings(id=1)
            s.add(row)
            s.flush()
        for k, v in updates.items():
            setattr(row, k, v)
        s.flush()
        s.refresh(row)
        s.expunge(row)
    return row

"""Minimal Emby client — just enough to trigger a library refresh."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class EmbyClient:
    def __init__(self, base_url: str | None, api_key: str | None) -> None:
        self._base_url = (base_url or "").rstrip("/") or None
        self._api_key = api_key

    @property
    def configured(self) -> bool:
        return self._base_url is not None and self._api_key is not None

    async def trigger_path_scan(self, library_path: str) -> None:
        if not self.configured:
            return
        url = f"{self._base_url}/Library/Media/Updated"
        payload = {"Updates": [{"Path": library_path, "UpdateType": "Created"}]}
        headers = {"X-Emby-Token": self._api_key or ""}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    logger.warning(
                        "emby scan trigger failed: %s %s", resp.status_code, resp.text[:200]
                    )
        except httpx.HTTPError as e:
            logger.warning("emby scan trigger network error: %s", e)

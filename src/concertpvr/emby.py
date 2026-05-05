"""Minimal Emby client — just enough to trigger a library refresh.

Path translation: when concertpvr writes to a path that Emby sees at a
different mount, callers can construct EmbyClient with `local_prefix` and
`emby_prefix`. The translation is a literal string-replace on `local_prefix`
→ `emby_prefix`. Both null = pass-through.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class EmbyClient:
    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        *,
        local_prefix: str | None = None,
        emby_prefix: str | None = None,
    ) -> None:
        self._base_url = (base_url or "").rstrip("/") or None
        self._api_key = api_key
        self._local_prefix = local_prefix or None
        self._emby_prefix = emby_prefix or None

    @property
    def configured(self) -> bool:
        return self._base_url is not None and self._api_key is not None

    def translate_path(self, local_path: str) -> str:
        """Map a concertpvr-write path to the path Emby sees, if a mapping is set.

        Returns the input unchanged if either prefix is unset, or if the input
        doesn't start with `local_prefix`. Caller-friendly: never raises; this
        is best-effort by design (a wrong mapping just means Emby's scan
        trigger is a no-op, which is what users see today without any mapping).
        """
        if self._local_prefix is None or self._emby_prefix is None:
            return local_path
        if local_path.startswith(self._local_prefix):
            return self._emby_prefix + local_path[len(self._local_prefix) :]
        return local_path

    async def trigger_path_scan(self, library_path: str) -> None:
        if not self.configured:
            return
        translated = self.translate_path(library_path)
        url = f"{self._base_url}/Library/Media/Updated"
        payload = {"Updates": [{"Path": translated, "UpdateType": "Created"}]}
        headers = {"X-Emby-Token": self._api_key or ""}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    logger.warning(
                        "emby scan trigger failed: %s %s",
                        resp.status_code,
                        resp.text[:200],
                    )
        except httpx.HTTPError as e:
            logger.warning("emby scan trigger network error: %s", e)

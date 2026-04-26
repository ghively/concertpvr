import pytest

from concertpvr.emby import EmbyClient


@pytest.mark.asyncio
async def test_unconfigured_client_silently_no_ops():
    client = EmbyClient(base_url=None, api_key=None)
    assert client.configured is False
    await client.trigger_path_scan("/media/concerts/foo")


@pytest.mark.asyncio
async def test_configured_client_posts_to_emby(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://emby:8096/Library/Media/Updated",
        status_code=204,
    )
    client = EmbyClient(base_url="http://emby:8096", api_key="abc")
    assert client.configured is True
    await client.trigger_path_scan("/media/concerts/Phoebe")
    request = httpx_mock.get_request()
    assert request.headers.get("X-Emby-Token") == "abc" or "api_key=abc" in str(request.url)


@pytest.mark.asyncio
async def test_configured_client_swallows_4xx_5xx(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://emby:8096/Library/Media/Updated",
        status_code=500,
    )
    client = EmbyClient(base_url="http://emby:8096", api_key="abc")
    await client.trigger_path_scan("/media/concerts/foo")

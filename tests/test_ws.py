import asyncio

import pytest

from concertpvr.ws import Broadcaster


@pytest.mark.asyncio
async def test_subscriber_receives_published_message():
    bc = Broadcaster()
    received: list[dict] = []

    async def reader():
        async for msg in bc.subscribe("topic.a"):
            received.append(msg)
            if len(received) == 2:
                return

    task = asyncio.create_task(reader())
    await asyncio.sleep(0.01)
    await bc.publish("topic.a", {"n": 1})
    await bc.publish("topic.a", {"n": 2})
    await task

    assert received == [{"n": 1}, {"n": 2}]


@pytest.mark.asyncio
async def test_two_subscribers_each_get_messages():
    bc = Broadcaster()
    a: list[dict] = []
    b: list[dict] = []

    async def reader(out: list[dict]):
        async for msg in bc.subscribe("t"):
            out.append(msg)
            if out == [{"n": 1}]:
                return

    t1 = asyncio.create_task(reader(a))
    t2 = asyncio.create_task(reader(b))
    await asyncio.sleep(0.01)
    await bc.publish("t", {"n": 1})
    await asyncio.gather(t1, t2)

    assert a == [{"n": 1}]
    assert b == [{"n": 1}]


@pytest.mark.asyncio
async def test_no_subscribers_publish_is_a_noop():
    bc = Broadcaster()
    await bc.publish("nobody.here", {"n": 1})
    assert bc.subscriber_count("nobody.here") == 0


@pytest.mark.asyncio
async def test_subscriber_count_tracks_active():
    bc = Broadcaster()

    async def reader():
        async for _ in bc.subscribe("t"):
            return

    task = asyncio.create_task(reader())
    await asyncio.sleep(0.01)
    assert bc.subscriber_count("t") == 1
    await bc.publish("t", {"x": 1})
    await task
    assert bc.subscriber_count("t") == 0


@pytest.mark.asyncio
async def test_topics_are_isolated():
    bc = Broadcaster()
    received_a: list[dict] = []

    async def reader():
        async for msg in bc.subscribe("topic.a"):
            received_a.append(msg)
            return

    task = asyncio.create_task(reader())
    await asyncio.sleep(0.01)
    await bc.publish("topic.b", {"n": 99})
    await bc.publish("topic.a", {"n": 1})
    await task
    assert received_a == [{"n": 1}]

import inspect
from collections.abc import Iterator
from typing import Final, TypedDict

import pytest

from app.infra.pubsub import SubscriberEntry
from app.services.event import (
    Topic,
    Unsubscribe,
    drain,
    publish,
    subscribe,
    subscriber,
)


class Pinged(TypedDict):
    ping_id: str


# Test-local, so no product subscriber is registered on it.
PINGED: Final = Topic[Pinged]("test.pinged")


@pytest.fixture
def cleanups() -> Iterator[list[Unsubscribe]]:
    """The unsubscribe functions of a test, called at its end so no handler leaks to the next."""
    registered: list[Unsubscribe] = []
    yield registered
    for cleanup in registered:
        cleanup()


class TestEvent:
    async def test_delivers_the_typed_payload_to_a_subscriber(
        self, cleanups: list[Unsubscribe]
    ) -> None:
        seen: list[str] = []

        def on_pinged(payload: Pinged) -> None:
            seen.append(payload["ping_id"])

        cleanups.append(subscribe(PINGED, on_pinged))

        await publish(PINGED, {"ping_id": "m1"})
        await drain()

        assert seen == ["m1"]

    async def test_does_not_let_a_raising_subscriber_block_another(
        self, cleanups: list[Unsubscribe]
    ) -> None:
        ran = False

        def raises(_: Pinged) -> None:
            raise RuntimeError("boom")

        def survives(_: Pinged) -> None:
            nonlocal ran
            ran = True

        cleanups.append(subscribe(PINGED, raises))
        cleanups.append(subscribe(PINGED, survives))

        await publish(PINGED, {"ping_id": "m2"})
        await drain()

        assert ran is True

    async def test_stops_delivering_after_unsubscribe(self) -> None:
        calls = 0

        def count(_: Pinged) -> None:
            nonlocal calls
            calls += 1

        unsubscribe = subscribe(PINGED, count)

        unsubscribe()
        await publish(PINGED, {"ping_id": "m3"})
        await drain()

        assert calls == 0

    async def test_subscribes_an_async_handler(self, cleanups: list[Unsubscribe]) -> None:
        seen: list[str] = []

        async def on_pinged(payload: Pinged) -> None:
            seen.append(payload["ping_id"])

        cleanups.append(subscribe(PINGED, on_pinged))

        await publish(PINGED, {"ping_id": "m4"})
        await drain()

        assert seen == ["m4"]


class TestSubscriberEntry:
    async def test_makes_a_typed_entry_for_the_bus_to_register_on_connect(self) -> None:
        seen: list[str] = []

        async def on_pinged(payload: Pinged) -> None:
            seen.append(payload["ping_id"])

        entry = subscriber(PINGED, on_pinged)

        assert isinstance(entry, SubscriberEntry)
        assert entry.topic == "test.pinged"
        result = entry.handle({"ping_id": "m5"})
        assert inspect.isawaitable(result)
        await result
        assert seen == ["m5"]

"""Typed access to the event bus. Add an event by adding a `Topic` constant with its payload type;
publish from a controller after its write (`api/user/` and `api/conversation/` are the examples);
a reaction is a file in `infra/subscribers/` listed in `infra/pubsub.py`. `publish` returns once
the handlers are scheduled, not finished: a reaction is detached from the publisher by
construction, and a failing or slow one never reaches it. A test (or shutdown) that needs the
reaction's effect awaits `drain()`.
"""

from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from typing import Final, TypedDict, cast

from app.infra.pubsub import SubscriberEntry, Unsubscribe, pubsub

__all__ = [
    "RUN_CREATED",
    "USER_REGISTERED",
    "RunCreated",
    "Topic",
    "Unsubscribe",
    "UserRegistered",
    "detach",
    "drain",
    "publish",
    "subscribe",
    "subscriber",
]


@dataclass(frozen=True)
class Topic[P]:
    """A topic name that carries its payload type, so a publisher and a subscriber cannot
    disagree about it."""

    name: str


class UserRegistered(TypedDict):
    user_id: str


USER_REGISTERED: Final = Topic[UserRegistered]("user.registered")


class RunCreated(TypedDict):
    run_id: str


# Published by the conversation controller after a send; the agent executes the run.
RUN_CREATED: Final = Topic[RunCreated]("run.created")


async def publish[P](topic: Topic[P], payload: P) -> None:
    await pubsub.publish(topic.name, payload)


def subscribe[P](topic: Topic[P], handler: Callable[[P], Awaitable[None] | None]) -> Unsubscribe:
    return pubsub.subscribe(topic.name, _untyped(handler))


def subscriber[P](
    topic: Topic[P], handle: Callable[[P], Awaitable[None] | None]
) -> SubscriberEntry:
    """An entry for `infra/pubsub.py`'s list, registered when the bus connects."""
    return SubscriberEntry(topic.name, _untyped(handle))


def _untyped[P](
    handler: Callable[[P], Awaitable[None] | None],
) -> Callable[[object], Awaitable[None] | None]:
    # The bus is untyped; the `Topic` is the contract between publishers and subscribers.
    def handle(payload: object) -> Awaitable[None] | None:
        return handler(cast(P, payload))

    return handle


def detach(work: Coroutine[object, object, None]) -> None:
    """Runs `work` beside the request, tracked by the bus: `drain()` waits for it and a shutdown
    gives it the bus's deadline before cancelling it."""
    pubsub.detach(work)


async def drain() -> None:
    """Resolves once every scheduled handler has settled."""
    await pubsub.drain()

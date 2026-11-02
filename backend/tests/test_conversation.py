import httpx
import pytest
from pydantic import ValidationError

from app.api.conversation import service as conversation_service
from app.api.conversation.schema import SendMessageBody
from app.api.run.controller import finish_run
from app.config.constants import RATE_LIMITS
from app.models.conversation.interface import MessageRecord
from app.models.run.enums import RunStatus
from app.services.db import Executor
from tests.agent_support import bearer, send, start_conversation
from tests.store import reset_store, store_backed
from tests.support import error_of


class TestSendMessageBody:
    """The request rules of `POST /api/conversation/{id}/message`."""

    def test_accepts_one_character_and_the_limit(self) -> None:
        assert SendMessageBody.model_validate({"content": "a"}).content == "a"
        assert len(SendMessageBody.model_validate({"content": "a" * 32000}).content) == 32000

    def test_counts_code_points_not_utf16_units(self) -> None:
        assert SendMessageBody.model_validate({"content": "\U0001f600" * 32000})

    def test_rejects_an_empty_content(self) -> None:
        with pytest.raises(ValidationError) as failure:
            SendMessageBody.model_validate({"content": ""})

        assert failure.value.errors()[0]["loc"] == ("content",)

    def test_rejects_a_content_over_the_limit(self) -> None:
        with pytest.raises(ValidationError) as failure:
            SendMessageBody.model_validate({"content": "a" * 32001})

        assert failure.value.errors()[0]["loc"] == ("content",)

    def test_rejects_a_missing_or_non_string_content(self) -> None:
        for body in ({}, {"content": 5}, {"content": None}):
            with pytest.raises(ValidationError):
                SendMessageBody.model_validate(body)


class StoreBacked:
    @pytest.fixture(autouse=True)
    async def empty_store(self) -> None:
        await reset_store()


@store_backed
class TestConversation(StoreBacked):
    async def test_starts_lists_and_opens_a_conversation(self, client: httpx.AsyncClient) -> None:
        headers = bearer()
        first = await start_conversation(client, headers)
        second = await start_conversation(client, headers)

        listed = await client.get("/api/conversation", headers=headers)
        opened = await client.get(f"/api/conversation/{first}", headers=headers)

        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["items"]] == [second, first]
        assert listed.json()["nextCursor"] is None
        assert opened.status_code == 200
        assert opened.json()["id"] == first
        assert opened.json()["title"] is None
        assert opened.json()["latestRun"] is None

    async def test_pages_by_cursor_latest_activity_first(self, client: httpx.AsyncClient) -> None:
        headers = bearer()
        ids = [await start_conversation(client, headers) for _ in range(3)]

        page = await client.get("/api/conversation?limit=2", headers=headers)
        rest = await client.get(
            f"/api/conversation?limit=2&cursor={page.json()['nextCursor']}", headers=headers
        )

        assert [item["id"] for item in page.json()["items"]] == [ids[2], ids[1]]
        assert [item["id"] for item in rest.json()["items"]] == [ids[0]]
        assert rest.json()["nextCursor"] is None

    async def test_a_sent_message_names_the_conversation_and_moves_it_to_the_top(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = bearer()
        older = await start_conversation(client, headers)
        newer = await start_conversation(client, headers)

        run_id = await send(client, headers, older, "  How do I\n write a test?  ")

        listed = await client.get("/api/conversation", headers=headers)
        opened = await client.get(f"/api/conversation/{older}", headers=headers)
        assert [item["id"] for item in listed.json()["items"]] == [older, newer]
        assert opened.json()["title"] == "How do I write a test?"
        assert opened.json()["latestRun"]["id"] == run_id
        assert opened.json()["latestRun"]["status"] == "queued"

    async def test_a_bad_cursor_is_a_validation_failure(self, client: httpx.AsyncClient) -> None:
        res = await client.get("/api/conversation?cursor=nope!", headers=bearer())

        assert res.status_code == 400
        assert error_of(res).code == "validation_failed"
        assert res.json()["requestId"]


@store_backed
class TestMessage(StoreBacked):
    async def test_sending_stores_the_message_and_claims_a_run(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = bearer()
        conversation = await start_conversation(client, headers)

        res = await client.post(
            f"/api/conversation/{conversation}/message",
            headers=headers,
            json={"content": "hello"},
        )

        assert res.status_code == 201
        body = res.json()
        assert body["message"]["role"] == "user"
        assert body["message"]["text"] == "hello"
        assert body["message"]["runId"] == body["run"]["id"]
        assert body["run"]["status"] == "queued"
        assert body["run"]["errorCode"] is None

    async def test_lists_messages_newest_first_with_a_cursor(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = bearer()
        conversation = await start_conversation(client, headers)
        await send(client, headers, conversation, "one")
        # A second send needs the first run finished; end it the way the agent does.
        await _finish_active_run(client, headers, conversation)
        await send(client, headers, conversation, "two")

        page = await client.get(
            f"/api/conversation/{conversation}/message?limit=1", headers=headers
        )
        rest = await client.get(
            f"/api/conversation/{conversation}/message?cursor={page.json()['nextCursor']}",
            headers=headers,
        )

        assert [m["text"] for m in page.json()["items"]] == ["two"]
        assert [m["text"] for m in rest.json()["items"]] == ["one"]
        assert rest.json()["nextCursor"] is None

    async def test_a_message_over_the_limit_is_a_validation_failure(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = bearer()
        conversation = await start_conversation(client, headers)

        res = await client.post(
            f"/api/conversation/{conversation}/message",
            headers=headers,
            json={"content": "a" * 32001},
        )

        assert res.status_code == 400
        assert error_of(res).code == "validation_failed"
        assert error_of(res).details[0].path == "content"
        assert res.json()["requestId"]

    async def test_a_failed_insert_releases_the_claim_so_the_next_send_succeeds(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        headers = bearer()
        conversation = await start_conversation(client, headers)
        real_insert = conversation_service.insert_message
        calls: list[int] = []

        async def fail_once(record: MessageRecord, *, db: Executor | None = None) -> MessageRecord:
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("the insert failed")
            return await real_insert(record, db=db)

        monkeypatch.setattr("app.api.conversation.service.insert_message", fail_once)

        failed = await client.post(
            f"/api/conversation/{conversation}/message", headers=headers, json={"content": "one"}
        )
        retried = await client.post(
            f"/api/conversation/{conversation}/message", headers=headers, json={"content": "two"}
        )

        assert failed.status_code == 500
        assert error_of(failed).code == "internal"
        assert failed.json()["requestId"]
        assert retried.status_code == 201
        opened = await client.get(f"/api/conversation/{conversation}", headers=headers)
        assert opened.json()["latestRun"]["id"] == retried.json()["run"]["id"]

    async def test_a_second_send_during_an_active_run_is_a_conflict(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = bearer()
        conversation = await start_conversation(client, headers)
        await send(client, headers, conversation, "one")

        res = await client.post(
            f"/api/conversation/{conversation}/message", headers=headers, json={"content": "two"}
        )

        assert res.status_code == 409
        assert error_of(res).code == "conflict"
        assert res.json()["requestId"]
        listed = await client.get(f"/api/conversation/{conversation}/message", headers=headers)
        assert [m["text"] for m in listed.json()["items"]] == ["one"]


@store_backed
class TestAccess(StoreBacked):
    async def test_every_endpoint_answers_401_without_a_token(
        self, client: httpx.AsyncClient
    ) -> None:
        calls = [
            await client.post("/api/conversation"),
            await client.get("/api/conversation"),
            await client.get("/api/conversation/x"),
            await client.get("/api/conversation/x/message"),
            await client.post("/api/conversation/x/message", json={"content": "a"}),
        ]

        for res in calls:
            assert res.status_code == 401
            assert error_of(res).code == "unauthenticated"
            assert res.json()["requestId"]

    async def test_another_users_conversation_is_not_found(self, client: httpx.AsyncClient) -> None:
        owner, other = bearer(), bearer()
        conversation = await start_conversation(client, owner)

        responses = [
            await client.get(f"/api/conversation/{conversation}", headers=other),
            await client.get(f"/api/conversation/{conversation}/message", headers=other),
            await client.post(
                f"/api/conversation/{conversation}/message",
                headers=other,
                json={"content": "hi"},
            ),
        ]

        for res in responses:
            assert res.status_code == 404
            assert error_of(res).code == "not_found"
            assert res.json()["requestId"]
        listed = await client.get("/api/conversation", headers=other)
        assert listed.json()["items"] == []

    async def test_a_missing_conversation_is_not_found(self, client: httpx.AsyncClient) -> None:
        res = await client.get("/api/conversation/does-not-exist", headers=bearer())

        assert res.status_code == 404
        assert error_of(res).code == "not_found"

    async def test_sends_over_the_per_user_limit_are_rate_limited(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = bearer()
        for _ in range(RATE_LIMITS.message_per_user.limit):
            conversation = await start_conversation(client, headers)
            await send(client, headers, conversation, "hello")
        conversation = await start_conversation(client, headers)

        res = await client.post(
            f"/api/conversation/{conversation}/message", headers=headers, json={"content": "hi"}
        )
        other = bearer()
        someone_else = await client.post(
            f"/api/conversation/{await start_conversation(client, other)}/message",
            headers=other,
            json={"content": "hi"},
        )

        assert res.status_code == 429
        assert error_of(res).code == "rate_limited"
        assert int(res.headers["retry-after"]) > 0
        assert res.json()["requestId"]
        assert someone_else.status_code == 201  # the limit is per user


async def _finish_active_run(
    client: httpx.AsyncClient, headers: dict[str, str], conversation_id: str
) -> None:
    opened = await client.get(f"/api/conversation/{conversation_id}", headers=headers)
    await finish_run(opened.json()["latestRun"]["id"], RunStatus.completed, None)

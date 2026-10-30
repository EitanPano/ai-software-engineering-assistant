"""QA's adversarial pass over the conversation and run endpoints: boundary sizes, malformed input,
another tenant's ids and content that must stay inert."""

import httpx
import pytest

from tests.agent_support import bearer, start_conversation
from tests.store import reset_store, store_backed
from tests.support import error_of


class StoreBacked:
    @pytest.fixture(autouse=True)
    async def empty_store(self) -> None:
        await reset_store()


@store_backed
class TestPagingBoundaries(StoreBacked):
    @pytest.mark.parametrize("limit", ["0", "-1", "abc", "1.5", ""])
    async def test_a_bad_limit_is_a_validation_failure_never_a_500(
        self, client: httpx.AsyncClient, limit: str
    ) -> None:
        headers = bearer()
        conversation = await start_conversation(client, headers)

        for path in ("/api/conversation", f"/api/conversation/{conversation}/message"):
            res = await client.get(f"{path}?limit={limit}", headers=headers)
            assert res.status_code == 400, (path, limit, res.text)
            assert error_of(res).code == "validation_failed"
            assert res.json()["requestId"]

    async def test_an_enormous_limit_never_errors(self, client: httpx.AsyncClient) -> None:
        headers = bearer()
        res = await client.get("/api/conversation?limit=100000000", headers=headers)

        assert res.status_code in (200, 400)

    async def test_an_empty_list_has_no_cursor(self, client: httpx.AsyncClient) -> None:
        headers = bearer()
        conversation = await start_conversation(client, headers)

        listed = await client.get("/api/conversation", headers=bearer())
        messages = await client.get(f"/api/conversation/{conversation}/message", headers=headers)

        assert listed.json() == {"items": [], "nextCursor": None}
        assert messages.json() == {"items": [], "nextCursor": None}


@store_backed
class TestSendMalformed(StoreBacked):
    async def _send(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        conversation: str,
        **kwargs: object,
    ) -> httpx.Response:
        return await client.post(
            f"/api/conversation/{conversation}/message",
            headers=headers,
            **kwargs,  # type: ignore[arg-type]
        )

    async def test_a_missing_or_non_json_body_is_a_validation_failure(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = bearer()
        conversation = await start_conversation(client, headers)

        no_body = await self._send(client, headers, conversation)
        not_json = await self._send(
            client,
            {**headers, "Content-Type": "application/json"},
            conversation,
            content=b"{nope",
        )
        wrong_type = await self._send(client, headers, conversation, json={"content": ["a"]})
        over = await self._send(client, headers, conversation, json={"content": "a" * 32001})

        for res in (no_body, not_json, wrong_type, over):
            assert res.status_code == 400, res.text
            assert error_of(res).code == "validation_failed"
            assert res.json()["requestId"]
        listed = await client.get(f"/api/conversation/{conversation}/message", headers=headers)
        assert listed.json()["items"] == []

    async def test_the_limit_itself_is_accepted_and_html_is_returned_as_plain_text(
        self, client: httpx.AsyncClient
    ) -> None:
        headers = bearer()
        conversation = await start_conversation(client, headers)
        payload = "<script>alert(1)</script>" + "a" * (32000 - len("<script>alert(1)</script>"))

        res = await self._send(client, headers, conversation, json={"content": payload})

        assert res.status_code == 201, res.text
        assert res.json()["message"]["text"] == payload
        assert res.headers["content-type"].startswith("application/json")

    async def test_a_second_user_cannot_read_the_stream_of_a_run_they_do_not_own(
        self, client: httpx.AsyncClient
    ) -> None:
        owner, other = bearer(), bearer()
        conversation = await start_conversation(client, owner)
        sent = await self._send(client, owner, conversation, json={"content": "secret words"})
        run_id = sent.json()["run"]["id"]

        res = await client.get(f"/api/run/{run_id}/event", headers=other)

        assert res.status_code == 404
        assert "secret words" not in res.text
        assert error_of(res).code == "not_found"

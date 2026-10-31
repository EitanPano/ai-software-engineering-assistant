"""The Voyage client, against the scripted fake: the request it builds, its batches, its bounded
retries, and that nothing it raises carries the key (V07)."""

from collections.abc import AsyncIterator, Callable

import httpx2
import pytest

from app.config.constants import EMBEDDING
from app.config.env import env
from app.services import voyage
from app.services.voyage import ATTEMPTS, EmbeddingUnavailable, embed_documents
from tests import fake_voyage


@pytest.fixture
async def fake(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[list[float]]:
    fake_voyage.reset()
    pauses: list[float] = []

    async def record_pause(seconds: float) -> None:
        pauses.append(seconds)

    monkeypatch.setattr("app.services.voyage.pause", record_pause)
    client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=fake_voyage.app), base_url="http://fake-voyage"
    )
    voyage.use_client(client)
    try:
        yield pauses
    finally:
        voyage.use_client(None)
        await client.aclose()


def use_handler(handler: Callable[[httpx2.Request], httpx2.Response]) -> httpx2.AsyncClient:
    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler), base_url="http://fake-voyage"
    )
    voyage.use_client(client)
    return client


@pytest.mark.usefixtures("fake")
class TestRequest:
    async def test_embeds_documents_with_the_model_and_no_truncation(self) -> None:
        vectors = await embed_documents(["alpha", "beta"])

        assert [len(v) for v in vectors] == [EMBEDDING.dimension] * 2
        assert vectors[0] == fake_voyage.vector_of("alpha")
        assert vectors[1] == fake_voyage.vector_of("beta")
        body = fake_voyage.state.requests[0]
        assert body["input"] == ["alpha", "beta"]
        assert body["model"] == "voyage-code-4"
        assert body["input_type"] == "document"
        assert body["truncation"] is False
        assert body["output_dimension"] == 1024

    async def test_authenticates_with_the_key_and_sends_it_nowhere_else(self) -> None:
        await embed_documents(["alpha"])

        assert fake_voyage.state.authorizations == [f"Bearer {env.voyage_api_key}"]
        assert env.voyage_api_key not in str(fake_voyage.state.requests)

    async def test_sends_nothing_for_no_texts(self) -> None:
        assert await embed_documents([]) == []
        assert fake_voyage.state.requests == []

    async def test_splits_by_the_number_of_texts_a_request_may_hold(self) -> None:
        texts = [f"t{n}" for n in range(EMBEDDING.batch_texts * 2 + 1)]

        vectors = await embed_documents(texts)

        assert len(vectors) == len(texts)
        sizes = [len(body["input"]) for body in fake_voyage.state.requests]  # type: ignore[arg-type]
        assert sizes == [EMBEDDING.batch_texts, EMBEDDING.batch_texts, 1]
        assert vectors[-1] == fake_voyage.vector_of(texts[-1])

    async def test_splits_by_the_tokens_a_request_may_hold(self) -> None:
        texts = [f"{n:04d}" + "x" * 6000 for n in range(70)]

        vectors = await embed_documents(texts)

        assert len(vectors) == 70
        assert len(fake_voyage.state.requests) > 2
        assert vectors[40] == fake_voyage.vector_of(texts[40])


class TestRetries:
    async def test_retries_a_throttle_then_succeeds(self, fake: list[float]) -> None:
        answers = iter([429, 500])

        def handler(request: httpx2.Request) -> httpx2.Response:
            status = next(answers, 200)
            if status != 200:
                return httpx2.Response(status, json={"detail": "later"})
            return httpx2.Response(
                200, json={"data": [{"index": 0, "embedding": [0.0] * EMBEDDING.dimension}]}
            )

        client = use_handler(handler)

        assert len(await embed_documents(["alpha"])) == 1
        assert len(fake) == 2
        assert fake == sorted(fake)
        await client.aclose()

    @pytest.mark.usefixtures("fake")
    async def test_gives_up_after_the_attempts_and_reports_unavailable(self) -> None:
        with pytest.raises(EmbeddingUnavailable):
            await embed_documents(["text [[fail:never]] text"])

        assert len(fake_voyage.state.requests) == ATTEMPTS

    async def test_does_not_retry_a_request_voyage_rejects(self, fake: list[float]) -> None:
        calls: list[int] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            calls.append(1)
            return httpx2.Response(400, json={"detail": "bad input"})

        client = use_handler(handler)

        with pytest.raises(EmbeddingUnavailable):
            await embed_documents(["alpha"])
        assert calls == [1]
        assert fake == []
        await client.aclose()

    async def test_retries_a_transport_failure_then_reports_unavailable(
        self, fake: list[float]
    ) -> None:
        calls: list[int] = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            calls.append(1)
            raise httpx2.ConnectError("no route", request=request)

        client = use_handler(handler)

        with pytest.raises(EmbeddingUnavailable):
            await embed_documents(["alpha"])
        assert len(calls) == ATTEMPTS
        assert len(fake) == ATTEMPTS - 1
        await client.aclose()

    @pytest.mark.usefixtures("fake")
    async def test_a_released_failure_succeeds_on_the_next_call(self) -> None:
        with pytest.raises(EmbeddingUnavailable):
            await embed_documents(["x [[fail:later]] x"])
        fake_voyage.state.released.add("later")

        assert len(await embed_documents(["x [[fail:later]] x"])) == 1


@pytest.mark.usefixtures("fake")
class TestAnswersItDoesNotTrust:
    async def test_a_vector_of_the_wrong_length_is_unavailable(self) -> None:
        with pytest.raises(EmbeddingUnavailable):
            await embed_documents(["[[bad]]"])

    async def test_a_wrong_number_of_vectors_is_unavailable(self) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, json={"data": []})

        client = use_handler(handler)

        with pytest.raises(EmbeddingUnavailable):
            await embed_documents(["alpha"])
        await client.aclose()

    async def test_an_answer_that_is_not_json_is_unavailable(self) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, content=b"<html>proxy</html>")

        client = use_handler(handler)

        with pytest.raises(EmbeddingUnavailable):
            await embed_documents(["alpha"])
        await client.aclose()

    async def test_the_error_never_carries_the_key_or_the_text(self) -> None:
        with pytest.raises(EmbeddingUnavailable) as raised:
            await embed_documents(["secret text [[fail:never]]"])

        assert env.voyage_api_key not in str(raised.value)
        assert "secret text" not in str(raised.value)
